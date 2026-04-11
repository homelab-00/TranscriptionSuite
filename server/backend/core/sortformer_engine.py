"""Sortformer diarization engine for Apple Silicon (Metal).

Wraps the ``mlx-audio`` Sortformer model for token-free, Metal-native speaker
diarization.  Supports up to 4 speakers without requiring a HuggingFace token.

Requires: ``mlx-audio>=0.4.1`` (included in the ``mlx`` optional-dependencies
group).
"""

from __future__ import annotations

import gc
import logging
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from server.config import get_config
from server.core.diarization_engine import DiarizationResult, DiarizationSegment

logger = logging.getLogger(__name__)

try:
    from mlx_audio.vad import load as _load_sortformer

    HAS_MLX_AUDIO = True
except Exception:  # ImportError or transitive failures
    _load_sortformer = None  # type: ignore[assignment]
    HAS_MLX_AUDIO = False

# Default model hosted on mlx-community (open weights, no auth needed).
_DEFAULT_MODEL = "mlx-community/diar_sortformer_4spk-v1-fp32"

# Minimum speech probability to accept a diarization frame.
_DEFAULT_THRESHOLD = 0.5


def sortformer_available() -> bool:
    """Return True when mlx-audio Sortformer can be used."""
    return HAS_MLX_AUDIO


class SortformerEngine:
    """Metal-native speaker diarization via mlx-audio Sortformer.

    The interface mirrors :class:`DiarizationEngine` so it can be used as a
    drop-in replacement on Apple Silicon.
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        threshold: float = _DEFAULT_THRESHOLD,
        *,
        num_speakers: int | None = None,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> None:
        if not HAS_MLX_AUDIO:
            raise ImportError(
                "mlx-audio is required for Sortformer diarization. "
                "Install with: uv sync --extra mlx"
            )

        self.model_name = model
        self.threshold = threshold
        self.num_speakers = num_speakers
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers or 4  # Sortformer supports up to 4

        self._model: Any | None = None
        self._loaded = False

        logger.info(
            "SortformerEngine initialized: model=%s, threshold=%.2f",
            model,
            threshold,
        )

    # -- lifecycle ---------------------------------------------------------

    def load(self) -> None:
        """Download (if needed) and load the Sortformer model."""
        if self._loaded:
            return

        logger.info("Loading Sortformer model: %s", self.model_name)
        self._model = _load_sortformer(self.model_name)
        self._loaded = True
        logger.info("Sortformer model loaded")

    def unload(self) -> None:
        """Release model memory."""
        if not self._loaded:
            return
        del self._model
        self._model = None
        self._loaded = False
        try:
            import mlx.core as mx

            mx.clear_cache()
        except Exception:
            pass
        gc.collect()
        logger.info("Sortformer model unloaded")

    def is_loaded(self) -> bool:
        return self._loaded

    # -- inference ---------------------------------------------------------

    def diarize_audio(
        self,
        audio_data: np.ndarray,
        sample_rate: int = 16000,
        num_speakers: int | None = None,
    ) -> DiarizationResult:
        """Run Sortformer diarization on in-memory audio.

        Uses streaming inference (``generate_stream``) by default to keep
        memory bounded — attention memory scales quadratically with chunk
        duration, so small streaming chunks (5-10 s) are dramatically cheaper
        than processing the full file at once.  The streaming state carries
        speaker context across chunks so accuracy is maintained.

        Args:
            audio_data: Mono float32 audio samples.
            sample_rate: Sample rate in Hz.
            num_speakers: Hint (currently unused — Sortformer auto-detects).

        Returns:
            :class:`DiarizationResult` with speaker-attributed segments.
        """
        if not self._loaded:
            self.load()

        if self._model is None:
            raise RuntimeError("Sortformer model not available")

        try:
            import soundfile as sf
        except ImportError as exc:
            raise RuntimeError("soundfile is required for Sortformer") from exc

        # Read configurable streaming chunk duration (default 5.0 s).
        cfg = get_config()
        sortformer_cfg = cfg.get("sortformer", default={}) or {}
        chunk_duration_s = float(sortformer_cfg.get("chunk_duration_s", 5.0))

        # Sortformer expects a file path — write a temporary WAV.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, audio_data, sample_rate)
            tmp_path = tmp.name

        try:
            if chunk_duration_s > 0:
                # Streaming inference: process in small chunks for bounded memory.
                logger.info(
                    "Sortformer: streaming diarization (%.1fs chunks)",
                    chunk_duration_s,
                )
                all_segments_raw: list[Any] = []
                for result in self._model.generate_stream(
                    tmp_path,
                    chunk_duration=chunk_duration_s,
                    threshold=self.threshold,
                ):
                    all_segments_raw.extend(result.segments)
            else:
                # Offline inference: process entire file at once (high memory).
                logger.info("Sortformer: offline diarization (streaming disabled)")
                result = self._model.generate(tmp_path, threshold=self.threshold)
                all_segments_raw = list(result.segments)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
            # Release intermediate Metal buffers.
            try:
                import mlx.core as mx

                mx.clear_cache()
            except Exception:
                pass

        segments: list[DiarizationSegment] = []
        speakers: set[str] = set()

        for seg in all_segments_raw:
            speaker = str(getattr(seg, "speaker", "UNKNOWN"))
            start = float(getattr(seg, "start", 0.0))
            end = float(getattr(seg, "end", 0.0))
            segments.append(DiarizationSegment(start=start, end=end, speaker=speaker))
            speakers.add(speaker)

        num_found = len(speakers)
        logger.info("Sortformer diarization complete: %d speakers found", num_found)
        return DiarizationResult(segments=segments, num_speakers=num_found)

    def diarize_file(
        self,
        file_path: str,
        num_speakers: int | None = None,
    ) -> DiarizationResult:
        """Diarize an audio file on disk."""
        from server.core.audio_utils import load_audio

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        audio_data, sr = load_audio(str(path), target_sample_rate=16000)
        return self.diarize_audio(audio_data, sr, num_speakers)
