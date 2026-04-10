"""whisper.cpp sidecar backend — HTTP client to whisper-server."""

from __future__ import annotations

import io
import logging
import os
import struct
from collections.abc import Callable
from typing import Any

import httpx
import numpy as np
from httpx import HTTPStatusError as HttpxHTTPStatusError
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    STTBackend,
)

logger = logging.getLogger(__name__)

_DEFAULT_SERVER_URL = "http://whisper-server:8080"
_INFERENCE_TIMEOUT = 300  # seconds — long audio can take a while
_LOAD_TIMEOUT = 60

_SIDECAR_UNREACHABLE_MSG = (
    "whisper.cpp sidecar is not reachable at {url}. "
    "This usually means the Vulkan runtime profile is not selected or the "
    "sidecar container failed to start. GGML models (whisper.cpp) require "
    'the Vulkan runtime profile — switch to "Vulkan" in Settings and restart '
    "the container, or choose a non-GGML model for CPU mode."
)

_SIDECAR_LOAD_TIMEOUT_MSG = (
    "whisper.cpp sidecar at {url} is reachable but the model load timed out "
    "after {timeout}s. The sidecar may still be downloading or initialising "
    "the model. Wait a moment and retry, or check the sidecar container logs."
)

_SIDECAR_INFERENCE_TIMEOUT_MSG = (
    "whisper.cpp sidecar at {url} accepted the request but transcription "
    "timed out after {timeout}s. This usually means the audio is too long for "
    "the current timeout, or the Vulkan device is under heavy load. Try "
    "shorter audio or check the sidecar container logs."
)


def _resolve_server_url() -> str:
    """Resolve whisper-server URL from env → config → default."""
    url = os.environ.get("WHISPERCPP_SERVER_URL", "").strip()
    if url:
        return url.rstrip("/")

    try:
        from server.config import get_config

        cfg = get_config()
        url = (cfg.get("whisper_cpp", "server_url") or "").strip()
        if url:
            return url.rstrip("/")
    except Exception as _exc:
        logger.debug("Could not read whisper_cpp server_url from config: %s", repr(_exc))

    return _DEFAULT_SERVER_URL


def _audio_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """Encode a float32 mono ndarray as a WAV byte buffer."""
    pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    raw = pcm.tobytes()
    buf = io.BytesIO()
    # WAV header
    num_samples = len(pcm)
    data_size = num_samples * 2  # 16-bit = 2 bytes per sample
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))  # chunk size
    buf.write(struct.pack("<H", 1))  # PCM
    buf.write(struct.pack("<H", 1))  # mono
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", sample_rate * 2))  # byte rate
    buf.write(struct.pack("<H", 2))  # block align
    buf.write(struct.pack("<H", 16))  # bits per sample
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(raw)
    return buf.getvalue()


class WhisperCppBackend(STTBackend):
    """STTBackend that delegates to a whisper.cpp whisper-server via HTTP."""

    def __init__(self) -> None:
        self._server_url: str = ""
        self._model_name: str | None = None
        self._loaded: bool = False
        self._client: httpx.Client | None = None

    def _ensure_client(self) -> httpx.Client:
        """Return (or create) a persistent httpx.Client."""
        if self._client is None:
            self._client = httpx.Client(timeout=_INFERENCE_TIMEOUT)
        return self._client

    # ------------------------------------------------------------------
    # STTBackend interface
    # ------------------------------------------------------------------

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        self._server_url = _resolve_server_url()
        self._model_name = model_name
        logger.info(
            "WhisperCppBackend: loading model %s via %s",
            model_name,
            self._server_url,
        )

        client = self._ensure_client()
        try:
            resp = client.post(
                f"{self._server_url}/load",
                json={"model": model_name},
                timeout=_LOAD_TIMEOUT,
            )
            resp.raise_for_status()
        except (httpx.NetworkError, OSError) as exc:
            raise RuntimeError(_SIDECAR_UNREACHABLE_MSG.format(url=self._server_url)) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                _SIDECAR_LOAD_TIMEOUT_MSG.format(url=self._server_url, timeout=_LOAD_TIMEOUT)
            ) from exc
        except HttpxHTTPStatusError:
            logger.warning(
                "WhisperCppBackend: /load returned an error status (server may "
                "pre-load the model); continuing anyway",
            )

        self._loaded = True
        logger.info("WhisperCppBackend: model ready")

    def unload(self) -> None:
        self._model_name = None
        self._loaded = False
        if self._client is not None:
            try:
                self._client.close()
            except Exception as _exc:
                logger.debug("Failed to close HTTP client cleanly: %s", repr(_exc))
            self._client = None

    def is_loaded(self) -> bool:
        return self._loaded

    def warmup(self) -> None:
        if not self._loaded:
            return
        logger.info("WhisperCppBackend: warmup — sending silent audio")
        silence = np.zeros(16000, dtype=np.float32)  # 1 second
        try:
            self.transcribe(silence)
        except Exception:
            logger.warning("WhisperCppBackend: warmup inference failed (non-fatal)")

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        audio_sample_rate: int = 16000,
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = 5,
        initial_prompt: str | None = None,
        suppress_tokens: list[int] | None = None,
        vad_filter: bool = True,
        word_timestamps: bool = True,
        translation_target_language: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        if not self._loaded:
            raise RuntimeError("WhisperCppBackend: model is not loaded")

        wav_bytes = _audio_to_wav_bytes(audio, audio_sample_rate)

        data: dict[str, Any] = {
            "response_format": "verbose_json",
        }
        if language:
            data["language"] = language
        if task == "translate":
            data["translate"] = "true"
        if initial_prompt:
            data["prompt"] = initial_prompt
        if beam_size != 5:
            data["beam_size"] = str(beam_size)

        client = self._ensure_client()
        try:
            resp = client.post(
                f"{self._server_url}/inference",
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data=data,
                timeout=_INFERENCE_TIMEOUT,
            )
            resp.raise_for_status()
        except (httpx.NetworkError, OSError) as exc:
            raise RuntimeError(_SIDECAR_UNREACHABLE_MSG.format(url=self._server_url)) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                _SIDECAR_INFERENCE_TIMEOUT_MSG.format(
                    url=self._server_url, timeout=_INFERENCE_TIMEOUT
                )
            ) from exc
        except HttpxHTTPStatusError as exc:
            raise RuntimeError(
                f"whisper.cpp sidecar at {self._server_url} returned HTTP "
                f"{exc.response.status_code} for /inference"
            ) from exc

        result = resp.json()
        return self._parse_response(result)

    def supports_translation(self) -> bool:
        return True

    @property
    def backend_name(self) -> str:
        return "whispercpp"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(
        result: dict[str, Any],
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        """Convert whisper-server JSON into BackendSegment list + info."""
        segments: list[BackendSegment] = []
        raw_segments = result.get("segments", [])

        for seg in raw_segments:
            words: list[dict[str, Any]] = []
            for tok in seg.get("tokens", []):
                t_start = tok.get("t0")
                t_end = tok.get("t1")
                text = tok.get("text", "").strip()
                if t_start is not None and t_end is not None and text:
                    words.append(
                        {
                            "word": text,
                            "start": t_start / 100.0,
                            "end": t_end / 100.0,
                            "probability": tok.get("p", 0.0),
                        }
                    )

            segments.append(
                BackendSegment(
                    text=seg.get("text", "").strip(),
                    start=seg.get("t0", seg.get("from", 0.0)),
                    end=seg.get("t1", seg.get("to", 0.0)),
                    words=words,
                )
            )

        detected_lang = result.get("language", None)
        info = BackendTranscriptionInfo(
            language=detected_lang,
            language_probability=0.0,
        )
        return segments, info
