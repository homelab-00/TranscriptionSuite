"""Sortformer diarization engine for Apple Silicon (Metal).

Wraps the ``mlx-audio`` Sortformer model for token-free, Metal-native speaker
diarization.  Supports up to 4 speakers without requiring a HuggingFace token.

The default model is NVIDIA's Streaming Sortformer v2.1: its Arrival-Order
Speaker Cache (AOSC) carries speaker identities across streaming chunks, which
keeps labels consistent over multi-hour recordings. The older offline v1 model
only has basic chunk-to-chunk context and tends to swap or split speakers on
long audio. Override with ``sortformer.model`` in config.yaml.

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
from server.core.stt.backends.mlx_thread_pin import MLXThreadAffinityMixin, mlx_pinned

logger = logging.getLogger(__name__)

try:
    from mlx_audio.vad import load as _load_sortformer

    HAS_MLX_AUDIO = True
except Exception:  # ImportError or transitive failures
    _load_sortformer = None  # type: ignore[assignment]
    HAS_MLX_AUDIO = False

# Default model hosted on mlx-community (open weights, no auth needed).
DEFAULT_SORTFORMER_MODEL = "mlx-community/diar_streaming_sortformer_4spk-v2.1-fp32"
_DEFAULT_MODEL = DEFAULT_SORTFORMER_MODEL

# Duration of one Sortformer output frame (hop 160 samples x subsampling 8 at 16 kHz).
_DIAR_FRAME_S = 0.08

# Minimum speech probability to accept a diarization frame.
_DEFAULT_THRESHOLD = 0.5


def sortformer_available() -> bool:
    """Return True when mlx-audio Sortformer can be used."""
    return HAS_MLX_AUDIO


class SortformerEngine(MLXThreadAffinityMixin):
    """Metal-native speaker diarization via mlx-audio Sortformer.

    The interface mirrors :class:`DiarizationEngine` so it can be used as a
    drop-in replacement on Apple Silicon.

    GH #124 — Sortformer is a second Metal-native MLX consumer (the #134 thread
    pin only covered the four MLX STT backends). The server dispatches diarization
    on ``asyncio.to_thread`` workers while the engine is materialized elsewhere, so
    the same cross-thread "no stream (gpu,0)" hazard applies. This engine therefore
    mixes in :class:`MLXThreadAffinityMixin` and decorates every GPU-touching method
    with :func:`mlx_pinned`, funnelling all MLX work onto one owning thread.
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

        # Names the dedicated MLX owning thread (mlx-sortformer-*) for the mixin.
        self.backend_name = "sortformer"
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

    @mlx_pinned
    def load(self) -> None:
        """Download (if needed) and load the Sortformer model."""
        if self._loaded:
            return

        logger.info("Loading Sortformer model: %s", self.model_name)
        self._model = _load_sortformer(self.model_name)
        self._loaded = True
        logger.info("Sortformer model loaded")

    @mlx_pinned
    def unload(self) -> None:
        """Release model memory.

        Runs on the owning MLX thread; the executor itself is torn down separately
        via :meth:`shutdown_mlx_thread` (called by the model manager) to avoid a
        worker shutting itself down.
        """
        if not self._loaded:
            return
        del self._model
        self._model = None
        self._loaded = False
        try:
            import mlx.core as mx

            mx.clear_cache()
        except Exception:
            logger.debug("mlx cache clear failed (non-critical)", exc_info=True)
        gc.collect()
        logger.info("Sortformer model unloaded")

    def is_loaded(self) -> bool:
        return self._loaded

    # -- inference ---------------------------------------------------------

    @mlx_pinned
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

        # Read configurable streaming chunk duration (default 15.0 s).
        cfg = get_config()
        sortformer_cfg = cfg.get("sortformer", default={}) or {}
        chunk_duration_s = float(sortformer_cfg.get("chunk_duration_s", 15.0))
        modules_cfg = getattr(getattr(self._model, "config", None), "modules_config", None)
        use_aosc = bool(getattr(modules_cfg, "use_aosc", False))
        if chunk_duration_s > 0 and use_aosc:
            # mlx-audio moves at most spkcache_update_period frames from the FIFO
            # into the speaker cache per chunk. A longer chunk grows the FIFO
            # without bound, so every step attends over more frames and a
            # multi-hour file slows down quadratically.
            max_chunk_s = modules_cfg.spkcache_update_period * _DIAR_FRAME_S
            if chunk_duration_s > max_chunk_s:
                logger.info(
                    "Sortformer: chunk_duration_s %.1f exceeds the AOSC update period; using %.2fs",
                    chunk_duration_s,
                    max_chunk_s,
                )
                chunk_duration_s = max_chunk_s
        # Post-processing: drop blips and bridge short pauses within one turn.
        # Passed only when set, so mlx-audio releases without these kwargs work.
        post_kwargs: dict[str, float] = {}
        min_duration = float(sortformer_cfg.get("min_segment_duration_s", 0.0))
        merge_gap = float(sortformer_cfg.get("merge_gap_s", 0.0))
        if min_duration > 0:
            post_kwargs["min_duration"] = min_duration
        if merge_gap > 0:
            post_kwargs["merge_gap"] = merge_gap

        if chunk_duration_s > 0 and use_aosc:
            all_segments_raw = self._diarize_fed_chunks(
                audio_data, sample_rate, chunk_duration_s, post_kwargs
            )
            return self._to_result(all_segments_raw)

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
                    **post_kwargs,
                ):
                    all_segments_raw.extend(result.segments)
            else:
                # Offline inference: process entire file at once (high memory).
                logger.info("Sortformer: offline diarization (streaming disabled)")
                result = self._model.generate(tmp_path, threshold=self.threshold, **post_kwargs)
                all_segments_raw = list(result.segments)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
            # Release intermediate Metal buffers.
            try:
                import mlx.core as mx

                mx.clear_cache()
            except Exception:
                logger.debug("mlx cache clear failed (non-critical)", exc_info=True)

        return self._to_result(all_segments_raw)

    def _diarize_fed_chunks(
        self,
        audio_data: np.ndarray,
        sample_rate: int,
        chunk_duration_s: float,
        post_kwargs: dict[str, float],
    ) -> list[DiarizationSegment]:
        """Stream the audio through ``feed()`` one chunk at a time (AOSC models).

        mlx-audio's file mode pre-encodes the whole recording in one Metal
        buffer (~12 GB per hour of audio), which fails on multi-hour files;
        feeding chunks keeps memory flat. Chunk times are re-anchored on the
        real sample offset: ``feed()`` advances its clock by whole output
        frames, which drifts ~40 ms per 15 s chunk (~30 s over three hours).
        """
        import mlx.core as mx

        audio = np.asarray(audio_data, dtype=np.float32).squeeze()
        total_s = len(audio) / sample_rate
        chunk_samples = max(1, int(round(chunk_duration_s * sample_rate)))
        logger.info(
            "Sortformer: streaming diarization (%.2fs chunks, %.0fs audio)",
            chunk_duration_s,
            total_s,
        )

        state = self._model.init_streaming_state()
        segments: list[DiarizationSegment] = []
        try:
            for i, start in enumerate(range(0, len(audio), chunk_samples)):
                chunk = audio[start : start + chunk_samples]
                chunk_start_s = start / sample_rate
                chunk_end_s = min(chunk_start_s + len(chunk) / sample_rate, total_s)
                if len(chunk) < sample_rate:
                    # Too short for the feature front-end: pad the tail with silence.
                    chunk = np.pad(chunk, (0, sample_rate - len(chunk)))
                model_offset_s = state.frames_processed * _DIAR_FRAME_S
                result, state = self._model.feed(
                    chunk,
                    state,
                    sample_rate=sample_rate,
                    threshold=self.threshold,
                    **post_kwargs,
                )
                shift = chunk_start_s - model_offset_s
                for seg in result.segments:
                    start_s = float(seg.start) + shift
                    end_s = min(float(seg.end) + shift, chunk_end_s)
                    if end_s > start_s:
                        segments.append(
                            DiarizationSegment(start=start_s, end=end_s, speaker=str(seg.speaker))
                        )
                if i % 64 == 63:
                    mx.clear_cache()
        finally:
            try:
                mx.clear_cache()
            except Exception:
                logger.debug("mlx cache clear failed (non-critical)", exc_info=True)
        return segments

    @staticmethod
    def _to_result(all_segments_raw: list[Any]) -> DiarizationResult:
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
