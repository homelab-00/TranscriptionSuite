"""SenseVoice (FunAudioLLM) STT backend.

Adapted from FunAudioLLM/SenseVoice (https://github.com/FunAudioLLM/SenseVoice)
and modelscope/FunASR (https://github.com/modelscope/FunASR) — wraps the
``funasr.AutoModel`` pipeline (SenseVoiceSmall + fsmn-vad) behind the project's
STTBackend interface.

Phase 1 scope: transcriber-only, CUDA/Linux. SenseVoice is non-autoregressive
and produces NO word-level timestamps; segments carry empty ``words`` lists and,
when funasr returns no per-sentence info, a single segment spanning the clip.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from server.core.audio_utils import clear_gpu_cache
from server.core.stt.backends.base import (
    BackendDependencyError,
    BackendSegment,
    BackendTranscriptionInfo,
    STTBackend,
)

SAMPLE_RATE = 16000

# SenseVoiceSmall's first-class language codes (the only values its API accepts).
_SENSEVOICE_LANGUAGES = frozenset({"zh", "en", "yue", "ja", "ko"})
_LANG_TOKEN_RE = re.compile(r"<\|(zh|en|yue|ja|ko)\|>", re.IGNORECASE)

logger = logging.getLogger(__name__)


def _compose_device(device: str, gpu_device_index: int) -> str:
    """Map the engine's ("cuda", index) convention to funasr's "cuda:N" string."""
    if device == "cuda":
        return f"cuda:{int(gpu_device_index)}"
    return device


def _extract_language(raw_text: str | None) -> str | None:
    """Return the SenseVoice language code embedded in *raw_text*, if any."""
    match = _LANG_TOKEN_RE.search(raw_text or "")
    return match.group(1).lower() if match else None


def _write_temp_wav(audio: np.ndarray, sample_rate: int) -> str:
    """Write float32 mono audio to a temp 16-bit WAV and return its path."""
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="sensevoice_")
    try:
        os.close(fd)
        sf.write(path, audio, sample_rate, subtype="PCM_16")
    except Exception:
        with contextlib.suppress(OSError):
            os.remove(path)
        raise
    return path


def _import_funasr_automodel() -> Any:
    """Lazy-import ``funasr.AutoModel`` with a clear, actionable error message."""
    try:
        from funasr import AutoModel

        return AutoModel
    except ImportError as exc:
        raise BackendDependencyError(
            "FunASR is required for SenseVoice models but is not installed. "
            "Set INSTALL_FUNASR=true in your Docker environment to enable it.",
            backend_type="funasr",
            remedy="Set INSTALL_FUNASR=true in your Docker environment and restart.",
        ) from exc


class SenseVoiceBackend(STTBackend):
    """FunASR-backed SenseVoice transcription backend (Phase 1, CUDA/Linux)."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._model_name: str | None = None
        self._device: str | None = None

    # -- lifecycle ----------------------------------------------------------

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        AutoModel = _import_funasr_automodel()

        gpu_device_index = kwargs.get("gpu_device_index", 0)
        funasr_device = _compose_device(device, gpu_device_index)

        logger.info(f"Loading SenseVoice model: {model_name} on {funasr_device}")
        # hub="hf": pull weights from HuggingFace, not the CN-hosted ModelScope.
        # disable_update=True: skip the ModelScope version ping (offline-friendly).
        self._model = AutoModel(
            model=model_name,
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": 30000},
            device=funasr_device,
            hub="hf",
            disable_update=True,
        )
        self._model_name = model_name
        self._device = funasr_device
        logger.info("SenseVoice model loaded")

    def unload(self) -> None:
        self._model = None
        self._model_name = None
        self._device = None
        clear_gpu_cache()

    def is_loaded(self) -> bool:
        return self._model is not None

    def warmup(self) -> None:
        if self._model is None:
            return
        try:
            warmup_path = Path(__file__).parent.parent / "warmup_audio.wav"
            if warmup_path.exists():
                self._model.generate(input=str(warmup_path), cache={}, language="en", use_itn=True)
                logger.debug("SenseVoice warmup complete")
            else:
                logger.debug("SenseVoice warmup skipped (no warmup_audio.wav)")
        except Exception as e:  # noqa: BLE001 — warmup is best-effort
            logger.warning(f"SenseVoice warmup failed (non-critical): {e}")

    # -- transcription ------------------------------------------------------

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
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        # SenseVoice has no translate task and no word timestamps — ignore the
        # Whisper-shaped knobs the engine passes through.
        del task, beam_size, initial_prompt, suppress_tokens
        del vad_filter, word_timestamps, translation_target_language, progress_callback

        if self._model is None:
            raise RuntimeError("SenseVoice model is not loaded")

        lang = self._resolve_language(language)
        wav_path = _write_temp_wav(audio, audio_sample_rate)
        try:
            result = self._model.generate(
                input=wav_path,
                cache={},
                language=lang,
                use_itn=True,
                batch_size_s=300,
                merge_vad=True,
                merge_length_s=15,
            )
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

        duration_s = float(len(audio)) / float(audio_sample_rate) if audio_sample_rate else 0.0
        return self._parse_result(result, duration_s, forced_language=lang)

    def supports_translation(self) -> bool:
        return False

    @property
    def backend_name(self) -> str:
        return "sensevoice"

    # -- helpers ------------------------------------------------------------

    def _resolve_language(self, language: str | None) -> str:
        if not language:
            return "auto"
        code = language.strip().lower()
        if code in _SENSEVOICE_LANGUAGES:
            return code
        logger.warning(
            f"SenseVoice does not support language '{language}'; falling back to auto-detect"
        )
        return "auto"

    def _parse_result(
        self,
        result: list[dict[str, Any]],
        duration_s: float,
        *,
        forced_language: str,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        if not result:
            return [], BackendTranscriptionInfo(language=None, language_probability=0.0)

        first = result[0]
        raw_text = str(first.get("text", ""))
        detected = _extract_language(raw_text)
        if detected is None and forced_language != "auto":
            detected = forced_language
        info = BackendTranscriptionInfo(language=detected, language_probability=0.0)

        # Preferred shape: per-sentence segments (VAD-chunk boundaries in ms).
        sentence_info = first.get("sentence_info")
        if isinstance(sentence_info, list) and sentence_info:
            segments: list[BackendSegment] = []
            for sentence in sentence_info:
                text = rich_transcription_postprocess(str(sentence.get("text", "")))
                start = float(sentence.get("start", 0.0)) / 1000.0
                end = float(sentence.get("end", 0.0)) / 1000.0
                segments.append(BackendSegment(text=text, start=start, end=end, words=[]))
            return segments, info

        # Fallback: one segment spanning the whole clip (no timestamps available).
        text = rich_transcription_postprocess(raw_text)
        return [BackendSegment(text=text, start=0.0, end=duration_s, words=[])], info
