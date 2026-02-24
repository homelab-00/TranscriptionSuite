"""NVIDIA Canary (NeMo) multitask ASR + translation backend.

Extends the Parakeet backend with ``source_lang`` / ``target_lang``
support required by Canary encoder-decoder models.  Canary supports
ASR in 25 European languages and bidirectional translation between
English and the other 24 languages.

Like Parakeet, NeMo is a large optional dependency — imports are lazy.
"""

from __future__ import annotations

import logging
import math
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

    def warmup(self, background: bool = False) -> None:
        """Run warmup inference.

        Args:
            background: If True, run warmup in a background thread (Fix 4)
        """
        if self._model is None:
            return

        if background:
            # Start warmup in background thread
            import threading
            import time

            def _warmup_worker():
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

            self._warmup_thread = threading.Thread(target=_warmup_worker, daemon=True)
            self._warmup_thread.start()
            logger.info("Started background warmup thread")
        else:
            # Blocking warmup
            try:
                import time

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
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = 5,
        initial_prompt: str | None = None,
        suppress_tokens: list[int] | None = None,
        vad_filter: bool = True,
        word_timestamps: bool = True,
        translation_target_language: str | None = None,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        if self._model is None:
            raise RuntimeError("Canary model is not loaded")

        # Canary requires an explicit source language code.
        source_lang = language if language else "en"

        if task == "translate":
            # Use caller-specified target, defaulting to English.
            target_lang = (translation_target_language or "en").strip().lower()
        else:
            # Same source and target = pure transcription.
            target_lang = source_lang

        total_duration = len(audio) / SAMPLE_RATE

        if total_duration > MAX_CHUNK_DURATION:
            return self._transcribe_long_canary(
                audio,
                source_lang=source_lang,
                target_lang=target_lang,
                word_timestamps=word_timestamps,
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

    def _transcribe_long_canary(
        self,
        audio: np.ndarray,
        *,
        source_lang: str = "en",
        target_lang: str = "en",
        word_timestamps: bool = True,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        """Chunk long audio at ~20 min boundaries and concatenate results."""
        chunk_samples = int(MAX_CHUNK_DURATION * SAMPLE_RATE)
        total_samples = len(audio)
        num_chunks = math.ceil(total_samples / chunk_samples)

        all_segments: list[BackendSegment] = []
        time_offset = 0.0

        for i in range(num_chunks):
            start = i * chunk_samples
            end = min(start + chunk_samples, total_samples)
            chunk = audio[start:end]

            logger.info(
                f"Transcribing chunk {i + 1}/{num_chunks} "
                f"({time_offset:.0f}s - {time_offset + len(chunk) / SAMPLE_RATE:.0f}s)"
            )

            output = self._transcribe_array_canary(
                chunk,
                source_lang=source_lang,
                target_lang=target_lang,
                timestamps=word_timestamps,
            )
            chunk_segments = self._parse_output(output, word_timestamps=word_timestamps)

            for seg in chunk_segments:
                seg.start += time_offset
                seg.end += time_offset
                for w in seg.words:
                    w["start"] = w["start"] + time_offset
                    w["end"] = w["end"] + time_offset

            all_segments.extend(chunk_segments)
            time_offset += len(chunk) / SAMPLE_RATE

        info = BackendTranscriptionInfo(
            language=source_lang,
            language_probability=1.0,
        )
        return all_segments, info
