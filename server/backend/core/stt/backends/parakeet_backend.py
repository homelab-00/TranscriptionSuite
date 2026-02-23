"""NVIDIA Parakeet (NeMo) STT backend.

Wraps NeMo's ASRModel behind the STTBackend interface. NeMo is a large
optional dependency — imports are lazy so the module can be imported even
when ``nemo_toolkit`` is not installed.
"""

from __future__ import annotations

import gc
import logging
import math
from typing import Any

import numpy as np
import torch
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    STTBackend,
)

# Target sample rate for Parakeet (same as Whisper)
SAMPLE_RATE = 16000

# Maximum audio duration (seconds) NeMo handles well in one pass.
# Longer files are chunked at this boundary to avoid OOM / quality issues.
MAX_CHUNK_DURATION = 20 * 60  # 20 minutes

logger = logging.getLogger(__name__)


def _patch_sampler_for_python313() -> None:
    """Fix lhotse compatibility with Python 3.13+.

    Python 3.13 made ``object.__init__()`` strict about rejecting keyword
    arguments.  lhotse's ``CutSampler`` calls
    ``super().__init__(data_source=None)`` which reaches ``object.__init__``
    when PyTorch's ``Sampler`` does not override ``__init__``, causing a
    ``TypeError``.  This patch adds a thin ``__init__`` that accepts and
    ignores the deprecated ``data_source`` parameter.
    """
    try:
        from torch.utils.data import Sampler

        if Sampler.__init__ is object.__init__:

            def _sampler_init(self, data_source=None):  # noqa: ARG001
                pass

            Sampler.__init__ = _sampler_init  # type: ignore[assignment]
    except (ImportError, AttributeError):
        pass


def _import_nemo_asr() -> Any:
    """Lazy-import ``nemo.collections.asr`` with a clear error message."""
    try:
        import nemo.collections.asr as nemo_asr  # type: ignore[import-untyped]

        _patch_sampler_for_python313()
        return nemo_asr
    except ImportError as exc:
        raise ImportError(
            "NeMo toolkit is required for NVIDIA Parakeet models but is not installed. "
            "Set INSTALL_NEMO=true in your Docker environment to enable it."
        ) from exc


class ParakeetBackend(STTBackend):
    """NVIDIA Parakeet / NeMo ASR backend."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._model_name: str | None = None

    # ------------------------------------------------------------------
    # STTBackend interface
    # ------------------------------------------------------------------

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        nemo_asr = _import_nemo_asr()

        logger.info(f"Loading Parakeet model: {model_name}")

        model = nemo_asr.models.ASRModel.from_pretrained(model_name=model_name)
        model = model.to(device)
        model.eval()

        self._model = model
        self._model_name = model_name
        logger.info("Parakeet model loaded")

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
            silent_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
            self._transcribe_array(silent_audio, timestamps=False)
            logger.debug("Parakeet model warmup complete")
        except Exception as e:
            logger.warning(f"Parakeet model warmup failed (non-critical): {e}")

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
            raise RuntimeError("Parakeet model is not loaded")

        if task == "translate":
            raise ValueError(
                "NVIDIA Parakeet models do not support translation. "
                "Use a multilingual Whisper model for the translate task."
            )

        # Whisper-specific params (beam_size, suppress_tokens, vad_filter,
        # initial_prompt) are silently ignored — they have no Parakeet equivalent.

        total_samples = len(audio)
        total_duration = total_samples / SAMPLE_RATE

        if total_duration > MAX_CHUNK_DURATION:
            return self._transcribe_long(audio, word_timestamps=word_timestamps)

        return self._transcribe_short(audio, word_timestamps=word_timestamps, language=language)

    def supports_translation(self) -> bool:
        return False

    @property
    def backend_name(self) -> str:
        return "parakeet"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transcribe_array(
        self,
        audio: np.ndarray,
        *,
        timestamps: bool = True,
    ) -> Any:
        """Run NeMo transcribe on a single numpy array."""
        import tempfile

        import soundfile as sf

        # NeMo's transcribe() expects file paths or torch tensors.
        # We write a temporary WAV for simplicity and compatibility.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE, subtype="FLOAT")
            output = self._model.transcribe(
                [tmp.name],
                timestamps=timestamps,
            )
        return output

    def _transcribe_short(
        self,
        audio: np.ndarray,
        *,
        word_timestamps: bool = True,
        language: str | None = None,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        """Transcribe a single chunk that fits within MAX_CHUNK_DURATION."""
        output = self._transcribe_array(audio, timestamps=word_timestamps)

        segments = self._parse_output(output, word_timestamps=word_timestamps)

        # Language detection: Parakeet v3 auto-detects but NeMo doesn't
        # expose the detected language consistently. Default to user-specified
        # or "en".
        detected_language = language or "en"

        info = BackendTranscriptionInfo(
            language=detected_language,
            language_probability=1.0,
        )
        return segments, info

    def _transcribe_long(
        self,
        audio: np.ndarray,
        *,
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

            output = self._transcribe_array(chunk, timestamps=word_timestamps)
            chunk_segments = self._parse_output(output, word_timestamps=word_timestamps)

            # Offset timestamps
            for seg in chunk_segments:
                seg.start += time_offset
                seg.end += time_offset
                for w in seg.words:
                    w["start"] = w["start"] + time_offset
                    w["end"] = w["end"] + time_offset

            all_segments.extend(chunk_segments)
            time_offset += len(chunk) / SAMPLE_RATE

        info = BackendTranscriptionInfo(
            language="en",
            language_probability=1.0,
        )
        return all_segments, info

    def _parse_output(
        self,
        output: Any,
        *,
        word_timestamps: bool = True,
    ) -> list[BackendSegment]:
        """Convert NeMo transcription output to BackendSegment list."""
        segments: list[BackendSegment] = []

        # NeMo output structure varies by model version. The common pattern
        # for models with timestamps is:
        #   output[0]  — list of Hypothesis objects (one per input file)
        #   hypothesis.timestamp['segment'] — list of segment dicts
        #   hypothesis.timestamp['word'] — list of word dicts
        #
        # For models without timestamps or when timestamps=False, output is
        # a list of plain text strings.

        if not output:
            return segments

        # Handle plain text output (no timestamps requested or model doesn't support them)
        first = output[0]
        if isinstance(first, str):
            if first.strip():
                segments.append(BackendSegment(text=first.strip(), start=0.0, end=0.0))
            return segments

        # Handle list-of-lists (batch output where first element is list of strings)
        if isinstance(first, list):
            for item in first:
                if isinstance(item, str) and item.strip():
                    segments.append(BackendSegment(text=item.strip(), start=0.0, end=0.0))
            return segments

        # Handle Hypothesis object with timestamps
        hypothesis = first
        ts = getattr(hypothesis, "timestamp", None) or getattr(hypothesis, "timestamps", None)

        if ts is None:
            # Fall back to text-only
            text = getattr(hypothesis, "text", str(hypothesis))
            if text and text.strip():
                segments.append(BackendSegment(text=text.strip(), start=0.0, end=0.0))
            return segments

        seg_timestamps = ts.get("segment", []) if isinstance(ts, dict) else []
        word_timestamps_data = ts.get("word", []) if isinstance(ts, dict) else []

        if seg_timestamps:
            for seg_ts in seg_timestamps:
                text = seg_ts.get("text", seg_ts.get("label", "")).strip()
                start = float(seg_ts.get("start", 0.0))
                end = float(seg_ts.get("end", 0.0))

                words: list[dict[str, Any]] = []
                if word_timestamps and word_timestamps_data:
                    # Attach words that fall within this segment's time range
                    for w in word_timestamps_data:
                        w_start = float(w.get("start", 0.0))
                        w_end = float(w.get("end", 0.0))
                        if w_start >= start - 0.01 and w_end <= end + 0.01:
                            words.append(
                                {
                                    "word": w.get("text", w.get("label", "")),
                                    "start": w_start,
                                    "end": w_end,
                                    "probability": float(w.get("confidence", 1.0)),
                                }
                            )

                if text:
                    segments.append(BackendSegment(text=text, start=start, end=end, words=words))
        else:
            # No segment timestamps — try to build from text
            text = getattr(hypothesis, "text", "")
            if text and text.strip():
                segments.append(BackendSegment(text=text.strip(), start=0.0, end=0.0))

        return segments
