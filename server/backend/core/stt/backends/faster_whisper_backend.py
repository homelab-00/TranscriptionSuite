"""Lightweight faster-whisper backend (no WhisperX dependency).

Used on bare-metal Metal (Apple Silicon) environments where the full WhisperX
stack is not installed.  Provides the same STTBackend interface for Live Mode
transcription using ``faster_whisper.WhisperModel`` directly.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    STTBackend,
)

SAMPLE_RATE = 16000

logger = logging.getLogger(__name__)


class FasterWhisperBackend(STTBackend):
    """Thin wrapper around ``faster_whisper.WhisperModel``."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._model_name: str | None = None
        self._device: str = "cpu"

    # ------------------------------------------------------------------
    # STTBackend interface
    # ------------------------------------------------------------------

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        from faster_whisper import WhisperModel

        compute_type: str = kwargs.get("compute_type", "default")
        download_root: str | None = kwargs.get("download_root")

        logger.info(f"Loading faster-whisper model: {model_name} (device={device})")
        self._model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=download_root,
        )
        self._model_name = model_name
        self._device = device
        logger.info("faster-whisper model loaded")

    def unload(self) -> None:
        self._model = None
        self._model_name = None

    def is_loaded(self) -> bool:
        return self._model is not None

    def warmup(self, **_kwargs: Any) -> None:
        if self._model is None:
            return

        warmup_path = Path(__file__).parent.parent / "warmup_audio.wav"
        if warmup_path.exists():
            warmup_audio, _ = sf.read(str(warmup_path), dtype="float32")
        else:
            warmup_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)

        try:
            t0 = time.perf_counter()
            segments, _info = self._model.transcribe(warmup_audio, beam_size=1, language="en")
            # Consume the generator to force execution
            for _ in segments:
                pass
            logger.info("Warmup transcribe complete (%.2fs)", time.perf_counter() - t0)
        except Exception as e:
            logger.warning(f"Warmup transcribe failed (non-critical): {e}")

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        audio_sample_rate: int = SAMPLE_RATE,
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = 5,
        initial_prompt: str | None = None,
        suppress_tokens: list[int] | None = None,
        vad_filter: bool = True,
        word_timestamps: bool = True,
        translation_target_language: str | None = None,
        progress_callback: Any | None = None,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        del audio_sample_rate, progress_callback
        if self._model is None:
            raise RuntimeError("faster-whisper model is not loaded")

        kwargs: dict[str, Any] = {
            "beam_size": beam_size,
            "task": task,
            "vad_filter": vad_filter,
            "word_timestamps": word_timestamps,
        }
        if language:
            kwargs["language"] = language
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt
        if suppress_tokens is not None:
            kwargs["suppress_tokens"] = suppress_tokens

        # Merge extra decode options (e.g. no_speech_threshold,
        # compression_ratio_threshold) from configure_decode_options().
        # Explicit args above take precedence over _decode_options.
        for key, value in self._decode_options.items():
            if key not in kwargs:
                kwargs[key] = value

        t0 = time.perf_counter()
        segments_gen, info = self._model.transcribe(audio, **kwargs)

        result_segments: list[BackendSegment] = []
        for seg in segments_gen:
            words: list[dict[str, Any]] = []
            if word_timestamps and seg.words:
                words = [
                    {
                        "word": w.word,
                        "start": w.start,
                        "end": w.end,
                        "probability": w.probability,
                    }
                    for w in seg.words
                ]
            result_segments.append(
                BackendSegment(
                    text=seg.text,
                    start=seg.start,
                    end=seg.end,
                    words=words,
                )
            )

        logger.info("faster-whisper transcribe took %.2fs", time.perf_counter() - t0)

        return result_segments, BackendTranscriptionInfo(
            language=info.language,
            language_probability=info.language_probability,
        )

    def supports_translation(self) -> bool:
        return True

    @property
    def backend_name(self) -> str:
        return "faster_whisper"
