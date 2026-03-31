"""MLX VibeVoice-ASR backend (Apple Silicon / Metal acceleration).

Uses ``mlx-audio`` to run the MLX-community port of Microsoft's VibeVoice-ASR
model natively on Apple Silicon via Metal.  The model produces structured JSON
output with timestamps and speaker IDs — providing native diarization without
requiring a separate diarization pipeline.

Supported model IDs:
    mlx-community/VibeVoice-ASR-bf16   (~18 GB, bf16)

Key characteristics:
- 51 languages with native speaker diarization and timestamps
- Structured JSON output parsed into segments with start/end/speaker_id/text
- No translation support (ASR + diarization only)
- Maximum ~59 minutes per call (handled internally by mlx-audio)
- The model expects 24 kHz audio; resampling from 16 kHz is handled internally
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    DiarizedTranscriptionResult,
    STTBackend,
)

INPUT_SAMPLE_RATE = 16000

logger = logging.getLogger(__name__)


class MLXVibeVoiceBackend(STTBackend):
    """STT backend for VibeVoice-ASR via mlx-audio on Apple Silicon."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._model_name: str = ""

    # ── STTBackend interface ──────────────────────────────────────────

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        del device  # MLX always uses Metal
        from mlx_audio.stt import load as mlx_stt_load

        logger.info("Loading MLX VibeVoice model: %s", model_name)
        self._model = mlx_stt_load(model_name)
        self._model_name = model_name
        logger.info("MLX VibeVoice model loaded: %s", model_name)

    def unload(self) -> None:
        if self._model is not None:
            import gc

            import mlx.core as mx

            del self._model
            self._model = None
            self._model_name = ""
            mx.clear_cache()
            gc.collect()
            logger.info("MLX VibeVoice model unloaded")

    def is_loaded(self) -> bool:
        return self._model is not None

    def warmup(self) -> None:
        if self._model is None:
            return
        # Feed 1 second of silence to trigger JIT compilation.
        silence = np.zeros(INPUT_SAMPLE_RATE, dtype=np.float32)
        try:
            self._model.generate(silence, sampling_rate=INPUT_SAMPLE_RATE)
        except Exception as exc:
            logger.debug("MLX VibeVoice warmup (non-fatal): %s", exc)

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        audio_sample_rate: int = INPUT_SAMPLE_RATE,
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
        """Transcribe audio without diarization (segments only)."""
        if self._model is None:
            raise RuntimeError("MLX VibeVoice model not loaded")

        result = self._run_generate(audio, audio_sample_rate)

        segments: list[BackendSegment] = []
        for seg in result.segments or []:
            text = str(seg.get("text", "")).strip()
            if not text:
                continue
            segments.append(
                BackendSegment(
                    text=text,
                    start=float(seg.get("start", 0.0) or 0.0),
                    end=float(seg.get("end", 0.0) or 0.0),
                    words=[],
                )
            )

        if not segments and result.text.strip():
            audio_duration = len(audio) / max(audio_sample_rate, 1)
            segments.append(
                BackendSegment(
                    text=result.text.strip(),
                    start=0.0,
                    end=audio_duration,
                    words=[],
                )
            )

        info = BackendTranscriptionInfo(language=language, language_probability=0.0)
        return segments, info

    def transcribe_with_diarization(
        self,
        audio: np.ndarray,
        *,
        audio_sample_rate: int = INPUT_SAMPLE_RATE,
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = 5,
        num_speakers: int | None = None,
        hf_token: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> DiarizedTranscriptionResult | None:
        """Transcribe with native VibeVoice speaker diarization."""
        del num_speakers, hf_token  # Model determines speakers internally
        if self._model is None:
            raise RuntimeError("MLX VibeVoice model not loaded")

        result = self._run_generate(audio, audio_sample_rate)
        raw_segments = result.segments or []

        segments: list[dict[str, Any]] = []
        speakers: set[str] = set()

        for seg in raw_segments:
            text = str(seg.get("text", "")).strip()
            if not text:
                continue
            speaker = str(seg.get("speaker_id", "") or seg.get("speaker", "") or "").strip()
            if speaker:
                speakers.add(speaker)
            segments.append(
                {
                    "text": text,
                    "start": float(seg.get("start", 0.0) or 0.0),
                    "end": float(seg.get("end", 0.0) or 0.0),
                    "speaker": speaker or None,
                }
            )

        if not segments and result.text.strip():
            audio_duration = len(audio) / max(audio_sample_rate, 1)
            segments.append(
                {
                    "text": result.text.strip(),
                    "start": 0.0,
                    "end": audio_duration,
                    "speaker": None,
                }
            )

        return DiarizedTranscriptionResult(
            segments=segments,
            words=[],
            num_speakers=len(speakers),
            language=language,
            language_probability=0.0,
        )

    def supports_translation(self) -> bool:
        return False

    @property
    def preferred_input_sample_rate_hz(self) -> int:
        return INPUT_SAMPLE_RATE

    @property
    def backend_name(self) -> str:
        return "mlx_vibevoice"

    # ── Internal helpers ──────────────────────────────────────────────

    def _run_generate(self, audio: np.ndarray, audio_sample_rate: int) -> Any:
        """Run model.generate() and return the STTOutput."""
        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim > 1:
            audio = audio.squeeze()
        return self._model.generate(audio, sampling_rate=audio_sample_rate)
