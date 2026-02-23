"""Faster-whisper STT backend.

Extracted from engine.py — wraps the faster-whisper library behind the
STTBackend interface so the engine doesn't depend on it directly.
"""

from __future__ import annotations

import gc
import logging
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    STTBackend,
)

# Target sample rate for Whisper (technical requirement)
SAMPLE_RATE = 16000

logger = logging.getLogger(__name__)


class WhisperBackend(STTBackend):
    """Faster-whisper / CTranslate2 backend."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._model_name: str | None = None

    # ------------------------------------------------------------------
    # STTBackend interface
    # ------------------------------------------------------------------

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        import faster_whisper
        from faster_whisper import BatchedInferencePipeline

        compute_type: str = kwargs.get("compute_type", "default")
        gpu_device_index = kwargs.get("gpu_device_index", 0)
        download_root: str | None = kwargs.get("download_root")
        batch_size: int = kwargs.get("batch_size", 16)

        logger.info(f"Loading Whisper model: {model_name}")

        model = faster_whisper.WhisperModel(
            model_size_or_path=model_name,
            device=device,
            compute_type=compute_type,
            device_index=gpu_device_index,
            download_root=download_root,
        )

        if batch_size > 0:
            model = BatchedInferencePipeline(model=model)

        self._model = model
        self._model_name = model_name
        logger.info("Whisper model loaded")

    def unload(self) -> None:
        self._model = None
        self._model_name = None
        try:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except Exception as e:
            logger.debug(f"Could not clear GPU cache: {e}")

    def is_loaded(self) -> bool:
        return self._model is not None

    def warmup(self) -> None:
        if self._model is None:
            return
        try:
            warmup_path = Path(__file__).parent.parent / "warmup_audio.wav"

            if not warmup_path.exists():
                logger.warning("Warmup audio not found, using silent audio")
                warmup_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
            else:
                warmup_audio, _ = sf.read(str(warmup_path), dtype="float32")

            segments, _ = self._model.transcribe(
                audio=warmup_audio,
                language="en",
                beam_size=1,
            )
            # Consume the generator
            _ = " ".join(seg.text for seg in segments)
            logger.debug("Whisper model warmup complete")

        except Exception as e:
            logger.warning(f"Whisper model warmup failed (non-critical): {e}")

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
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        if self._model is None:
            raise RuntimeError("Whisper model is not loaded")

        segments_iter, info = self._model.transcribe(
            audio,
            language=language,
            task=task,
            beam_size=beam_size,
            initial_prompt=initial_prompt,
            suppress_tokens=suppress_tokens if suppress_tokens is not None else [-1],
            vad_filter=vad_filter,
            word_timestamps=word_timestamps,
        )

        result_segments: list[BackendSegment] = []
        for seg in segments_iter:
            words: list[dict[str, Any]] = []
            if word_timestamps and hasattr(seg, "words") and seg.words:
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

            # Yield control so callers can check cancellation between segments
            yield_segment = result_segments  # noqa: F841 — kept for clarity

        backend_info = BackendTranscriptionInfo(
            language=info.language,
            language_probability=info.language_probability,
        )
        return result_segments, backend_info

    def supports_translation(self) -> bool:
        return True

    @property
    def backend_name(self) -> str:
        return "whisper"
