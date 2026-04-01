"""MLX Whisper STT backend (Apple Silicon / Metal acceleration).

Uses ``mlx-audio`` to run Whisper models via Apple's MLX framework, giving
Metal GPU acceleration on Apple Silicon Macs.

Model names are HuggingFace repo IDs in the ``mlx-community`` namespace
with the ``-asr-`` naming scheme that includes HuggingFace processor files:
    mlx-community/whisper-tiny-asr-fp16
    mlx-community/whisper-small-asr-fp16
    mlx-community/whisper-large-v3-asr-fp16
    mlx-community/whisper-large-v3-turbo-asr-fp16

Note: Older ``whisper-*-mlx`` model IDs lack the HuggingFace processor
required by ``mlx-audio`` and are no longer supported by this backend.

Word-level timestamps are supported via a monkey-patch for a bug in
mlx-audio v0.4.x where ``set_alignment_heads()`` stores data as
``_alignment_heads`` but ``timing.py`` reads ``alignment_heads``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    STTBackend,
)

SAMPLE_RATE = 16000

logger = logging.getLogger(__name__)


class MLXWhisperBackend(STTBackend):
    """Apple MLX / Metal-accelerated Whisper backend via mlx-audio.

    Uses ``mlx-audio`` (https://github.com/ml-explore/mlx-audio) for Whisper
    inference with word-level timestamps on Apple Silicon.
    """

    def __init__(self) -> None:
        self._model: Any | None = None
        self._model_name: str = ""

    # ------------------------------------------------------------------
    # STTBackend interface
    # ------------------------------------------------------------------

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        del device  # MLX always uses Metal
        try:
            from mlx_audio.stt import load as mlx_stt_load
        except ImportError as exc:
            raise RuntimeError(
                "mlx-audio is not installed. "
                "Run: uv sync --extra mlx  (requires macOS + Apple Silicon)"
            ) from exc

        logger.info("Loading MLX Whisper model via mlx-audio: %s", model_name)
        self._model = mlx_stt_load(model_name)

        # Monkey-patch: mlx-audio v0.4.x bug — set_alignment_heads() stores
        # data as _alignment_heads but timing.py reads alignment_heads.
        if hasattr(self._model, "_alignment_heads") and not hasattr(
            self._model, "alignment_heads"
        ):
            self._model.alignment_heads = self._model._alignment_heads
            logger.debug("Applied alignment_heads monkey-patch for word timestamps")

        self._model_name = model_name
        logger.info("MLX Whisper model loaded: %s", model_name)

    def unload(self) -> None:
        if self._model is not None:
            import gc

            import mlx.core as mx

            del self._model
            self._model = None
            self._model_name = ""
            mx.clear_cache()
            gc.collect()
            logger.info("MLX Whisper model unloaded")

    def is_loaded(self) -> bool:
        return self._model is not None

    def warmup(self) -> None:
        if self._model is None:
            return
        silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
        try:
            self._model.generate(silence, language="en")
        except Exception as exc:
            logger.debug("MLX Whisper warmup (non-fatal): %s", exc)

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
        del suppress_tokens, vad_filter, progress_callback, beam_size

        if self._model is None:
            raise RuntimeError("MLX Whisper model is not loaded")

        # Resample if needed — mlx-audio expects 16 kHz float32.
        if audio_sample_rate != SAMPLE_RATE:
            from scipy.signal import resample as sp_resample

            target_length = int(len(audio) * SAMPLE_RATE / audio_sample_rate)
            audio = sp_resample(audio, target_length).astype(np.float32)

        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim > 1:
            audio = audio.squeeze()

        effective_task = task
        if translation_target_language and translation_target_language != "en":
            logger.warning(
                "MLX Whisper only supports translation to English; "
                "ignoring target language '%s'",
                translation_target_language,
            )

        # Check if alignment_heads are available for word timestamps.
        use_word_timestamps = word_timestamps and hasattr(
            self._model, "alignment_heads"
        )
        if word_timestamps and not use_word_timestamps:
            logger.debug(
                "Word timestamps requested but alignment_heads not available; "
                "falling back to segment-level timestamps"
            )

        result = self._model.generate(
            audio,
            language=language,
            task=effective_task,
            initial_prompt=initial_prompt,
            word_timestamps=use_word_timestamps,
        )

        # mlx-audio generate() returns STTOutput with .segments list of dicts:
        #   {"id", "seek", "start", "end", "text", "tokens", "temperature",
        #    "avg_logprob", "compression_ratio", "no_speech_prob",
        #    "words": [{"word", "start", "end", "probability"}]}
        result_segments: list[BackendSegment] = []
        for seg in result.segments or []:
            text = str(seg.get("text", "")).strip()
            if not text:
                continue

            words: list[dict[str, Any]] = []
            if use_word_timestamps:
                for w in seg.get("words", []):
                    words.append(
                        {
                            "word": w.get("word", ""),
                            "start": float(w.get("start", 0.0)),
                            "end": float(w.get("end", 0.0)),
                            "probability": float(w.get("probability", 0.0)),
                        }
                    )
            result_segments.append(
                BackendSegment(
                    text=text,
                    start=float(seg.get("start", 0.0)),
                    end=float(seg.get("end", 0.0)),
                    words=words,
                )
            )

        detected_language: str | None = getattr(result, "language", None)
        info = BackendTranscriptionInfo(
            language=detected_language,
            language_probability=1.0,
        )
        return result_segments, info

    def supports_translation(self) -> bool:
        return True

    @property
    def preferred_input_sample_rate_hz(self) -> int:
        return SAMPLE_RATE

    @property
    def backend_name(self) -> str:
        return "mlx_whisper"
