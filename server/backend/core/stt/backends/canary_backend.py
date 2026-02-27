"""NVIDIA Canary (NeMo) multitask ASR + translation backend.

Extends the Parakeet backend with ``source_lang`` / ``target_lang``
support required by Canary encoder-decoder models.  Canary supports
ASR in 25 European languages and bidirectional translation between
English and the other 24 languages.

Like Parakeet, NeMo is a large optional dependency — imports are lazy.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any

import numpy as np
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
)
from server.core.stt.backends.parakeet_backend import (
    MAX_CHUNK_DURATION,
    SAMPLE_RATE,
    ParakeetBackend,
)

logger = logging.getLogger(__name__)


class CanaryBackend(ParakeetBackend):
    """NVIDIA Canary / NeMo multitask ASR + translation backend."""

    # ------------------------------------------------------------------
    # STTBackend interface overrides
    # ------------------------------------------------------------------

    def _do_warmup(self) -> None:
        """Internal method to perform actual Canary warmup."""
        try:
            warmup_start = time.perf_counter()
            logger.info("Starting Canary warmup...")
            silent_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
            self._transcribe_array_canary(
                silent_audio, source_lang="en", target_lang="en", timestamps=False
            )
            warmup_time = time.perf_counter() - warmup_start
            logger.info(f"[TIMING] Canary warmup complete ({warmup_time:.2f}s)")
            self._warmup_complete = True
        except Exception as e:
            logger.warning(f"Canary model warmup failed (non-critical): {e}")
            self._warmup_complete = True

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
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        del audio_sample_rate
        if self._model is None:
            raise RuntimeError("Canary model is not loaded")

        # Canary requires an explicit source language code.
        source_lang = language if language else "en"

        if task == "translate":
            # Use caller-specified target, defaulting to English.
            target_lang = (translation_target_language or "en").strip().lower()
            if word_timestamps:
                logger.info(
                    "Canary translation (AST) only provides segment-level timestamps; "
                    "word-level timestamps may be unavailable. Diarization speaker "
                    "attribution will fall back to segment-level alignment."
                )
        else:
            # Same source and target = pure transcription.
            target_lang = source_lang

        total_duration = len(audio) / SAMPLE_RATE

        if total_duration > MAX_CHUNK_DURATION:
            canary_fn = functools.partial(
                self._transcribe_array_canary,
                source_lang=source_lang,
                target_lang=target_lang,
            )
            return self._transcribe_long(
                audio,
                word_timestamps=word_timestamps,
                transcribe_fn=canary_fn,
                language=source_lang,
            )

        return self._transcribe_short_canary(
            audio,
            source_lang=source_lang,
            target_lang=target_lang,
            word_timestamps=word_timestamps,
        )

    def supports_translation(self) -> bool:
        return True

    @property
    def backend_name(self) -> str:
        return "canary"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transcribe_array_canary(
        self,
        audio: np.ndarray,
        *,
        source_lang: str = "en",
        target_lang: str = "en",
        timestamps: bool = True,
    ) -> Any:
        """Run NeMo transcribe with Canary-specific language parameters."""
        import tempfile

        import soundfile as sf

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE, subtype="FLOAT")
            output = self._model.transcribe(
                [tmp.name],
                source_lang=source_lang,
                target_lang=target_lang,
                timestamps=timestamps,
            )
        return output

    def _transcribe_short_canary(
        self,
        audio: np.ndarray,
        *,
        source_lang: str = "en",
        target_lang: str = "en",
        word_timestamps: bool = True,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        """Transcribe a single chunk within MAX_CHUNK_DURATION."""
        output = self._transcribe_array_canary(
            audio,
            source_lang=source_lang,
            target_lang=target_lang,
            timestamps=word_timestamps,
        )

        segments = self._parse_output(output, word_timestamps=word_timestamps)

        info = BackendTranscriptionInfo(
            language=source_lang,
            language_probability=1.0,
        )
        return segments, info
