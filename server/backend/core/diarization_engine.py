"""
Speaker diarization engine for TranscriptionSuite server.

Wraps PyAnnote speaker diarization pipeline for integration
with the unified transcription engine.
"""

import logging
import os
import warnings
from pathlib import Path
from typing import Any

import numpy as np
from server.config import get_config
from server.core.audio_utils import clear_gpu_cache

logger = logging.getLogger(__name__)

_PYANNOTE_TORCHCODEC_WARNING_RE = (
    r"torchcodec is not installed correctly so built-in audio decoding will fail\..*"
)
warnings.filterwarnings(
    "ignore",
    message=_PYANNOTE_TORCHCODEC_WARNING_RE,
    category=UserWarning,
)

# Optional imports
try:
    from pyannote.audio import Pipeline

    HAS_PYANNOTE = True
except ImportError:
    Pipeline = None  # type: ignore
    HAS_PYANNOTE = False

try:
    import torch

    HAS_TORCH = True
except ImportError:
    torch = None  # type: ignore
    HAS_TORCH = False


def _resolve_device(requested: str) -> str:
    """Return the best available torch device for the requested preference.

    Mapping:
      - ``"cuda"``  → ``"cuda"`` if CUDA available, else ``"mps"`` if MPS available, else ``"cpu"``
      - ``"mps"``   → ``"mps"``  if MPS  available, else ``"cpu"``
      - ``"auto"``  → best of cuda → mps → cpu
      - anything else (e.g. ``"cpu"``) → returned as-is
    """
    if not HAS_TORCH or torch is None:
        return "cpu"
    if requested in ("cuda", "auto"):
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    if requested == "mps":
        return "mps" if torch.backends.mps.is_available() else "cpu"
    return requested


class DiarizationSegment:
    """A segment with speaker assignment."""

    def __init__(self, start: float, end: float, speaker: str):
        self.start = start
        self.end = end
        self.speaker = speaker

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "speaker": self.speaker,
            "duration": round(self.duration, 3),
        }


class DiarizationResult:
    """Complete diarization result."""

    def __init__(self, segments: list[DiarizationSegment], num_speakers: int):
        self.segments = segments
        self.num_speakers = num_speakers

    def get_speaker_at(self, time: float) -> str | None:
        """Get the speaker at a specific time."""
        for seg in self.segments:
            if seg.start <= time <= seg.end:
                return seg.speaker
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "segments": [s.to_dict() for s in self.segments],
            "num_speakers": self.num_speakers,
        }


class DiarizationEngine:
    """
    Speaker diarization engine using PyAnnote.

    Identifies different speakers in audio and provides
    time-aligned speaker labels.
    """

    def __init__(
        self,
        model: str | None = None,
        hf_token: str | None = None,
        device: str | None = None,
        num_speakers: int | None = None,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
        min_duration_on: float | None = None,
        min_duration_off: float | None = None,
    ):
        """
        Initialize the diarization engine.

        All parameters default to values from config.yaml's 'diarization' section.

        Args:
            model: PyAnnote model identifier. If None, uses config default.
            hf_token: HuggingFace token. If None, uses config or HF_TOKEN env var.
            device: Device to run on ("cuda" or "cpu"). If None, uses config default.
            num_speakers: Known number of speakers (if known)
            min_speakers: Minimum number of speakers
            max_speakers: Maximum number of speakers
            min_duration_on: Minimum duration (seconds) of speech segments
            min_duration_off: Minimum duration (seconds) of silence between segments
        """
        if not HAS_PYANNOTE:
            raise ImportError(
                "pyannote.audio is required for diarization. "
                "Install with: pip install pyannote.audio"
            )

        # Load defaults from config
        cfg = get_config()
        diar_cfg = cfg.config.get("diarization", {})

        self.model = model or diar_cfg.get("model", "pyannote/speaker-diarization-community-1")
        self.hf_token = hf_token or diar_cfg.get("hf_token") or os.environ.get("HF_TOKEN")
        self.device = _resolve_device(device or diar_cfg.get("device", "cuda"))
        self.num_speakers = (
            num_speakers if num_speakers is not None else diar_cfg.get("num_speakers")
        )
        self.min_speakers = (
            min_speakers if min_speakers is not None else diar_cfg.get("min_speakers")
        )
        self.max_speakers = (
            max_speakers if max_speakers is not None else diar_cfg.get("max_speakers")
        )
        self.min_duration_on = (
            min_duration_on if min_duration_on is not None else diar_cfg.get("min_duration_on", 0.0)
        )
        self.min_duration_off = (
            min_duration_off
            if min_duration_off is not None
            else diar_cfg.get("min_duration_off", 0.0)
        )

        self._pipeline: Any | None = None
        self._loaded = False

        logger.info(f"DiarizationEngine initialized: model={model}, device={device}")

    def load(self) -> None:
        """Load the diarization pipeline."""
        if self._loaded:
            logger.debug("Diarization pipeline already loaded")
            return

        if not self.hf_token:
            raise ValueError(
                "HuggingFace token required for PyAnnote. "
                "Set HF_TOKEN environment variable or pass hf_token parameter."
            )

        logger.info(f"Loading PyAnnote diarization pipeline: {self.model}")

        try:
            self._pipeline = Pipeline.from_pretrained(
                self.model,
                token=self.hf_token,
            )

            # Move to device
            if HAS_TORCH and torch is not None:
                self._pipeline = self._pipeline.to(torch.device(self.device))
                logger.info("Diarization pipeline moved to device: %s", self.device)

                # Re-enable TF32 for inference performance (~10-15% GPU uplift).
                # pyannote disables it globally for training reproducibility,
                # but inference-only workloads benefit from the faster math.
                if torch.cuda.is_available():
                    torch.backends.cuda.matmul.allow_tf32 = True
                    torch.backends.cudnn.allow_tf32 = True

            # Apply embedding batch size from config
            cfg = get_config()
            diar_cfg = cfg.config.get("diarization", {})
            batch_size = diar_cfg.get("embedding_batch_size", 32)
            if hasattr(self._pipeline, "embedding_batch_size"):
                self._pipeline.embedding_batch_size = batch_size
                logger.info("Set embedding_batch_size=%s on diarization pipeline", batch_size)

            self._loaded = True
            logger.info(f"Diarization pipeline loaded successfully: {self.model}")

        except Exception as e:
            logger.error(f"Failed to load diarization pipeline: {e}")
            raise

    def unload(self) -> None:
        """Unload the pipeline to free memory."""
        if not self._loaded:
            return

        logger.info("Unloading diarization pipeline")
        del self._pipeline
        self._pipeline = None
        self._loaded = False
        clear_gpu_cache()
        logger.info("Diarization pipeline unloaded")

    def is_loaded(self) -> bool:
        """Check if pipeline is loaded."""
        return self._loaded

    def diarize_audio(
        self,
        audio_data: np.ndarray,
        sample_rate: int = 16000,
        num_speakers: int | None = None,
    ) -> DiarizationResult:
        """
        Perform speaker diarization on audio data.

        Args:
            audio_data: Audio samples as float32 numpy array
            sample_rate: Sample rate of the audio
            num_speakers: Override number of speakers

        Returns:
            DiarizationResult with speaker segments
        """
        if not self._loaded:
            self.load()

        if self._pipeline is None:
            raise RuntimeError("Diarization pipeline not available")

        logger.info(f"Diarizing {len(audio_data) / sample_rate:.2f}s of audio")

        # Prepare audio for PyAnnote
        if HAS_TORCH and torch is not None:
            waveform = torch.from_numpy(audio_data).float().unsqueeze(0)
            audio_input = {"waveform": waveform, "sample_rate": sample_rate}
        else:
            raise RuntimeError("PyTorch required for diarization")

        # Run diarization
        try:
            n_speakers = num_speakers or self.num_speakers

            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r"std\(\): degrees of freedom is <= 0\..*",
                    category=UserWarning,
                )

                warnings.filterwarnings(
                    "ignore",
                    message=r"TensorFloat-32 \(TF32\) has been disabled.*",
                    category=UserWarning,
                )

                diarization = self._pipeline(
                    audio_input,
                    num_speakers=n_speakers,
                    min_speakers=self.min_speakers,
                    max_speakers=self.max_speakers,
                )

            # Convert to segments
            segments: list[DiarizationSegment] = []
            speakers = set()

            annotation = diarization
            if hasattr(diarization, "speaker_diarization"):
                annotation = diarization.speaker_diarization

            if not hasattr(annotation, "itertracks"):
                raise RuntimeError(f"Unexpected diarization output type: {type(diarization)!r}")

            for turn, _, speaker in annotation.itertracks(yield_label=True):
                segments.append(
                    DiarizationSegment(
                        start=turn.start,
                        end=turn.end,
                        speaker=speaker,
                    )
                )
                speakers.add(speaker)

            result = DiarizationResult(
                segments=segments,
                num_speakers=len(speakers),
            )

            logger.info(f"Diarization complete: {len(speakers)} speakers found")
            return result

        except Exception as e:
            logger.error(f"Diarization failed: {e}")
            raise

    def diarize_file(
        self,
        file_path: str,
        num_speakers: int | None = None,
    ) -> DiarizationResult:
        """
        Perform speaker diarization on an audio file.

        Args:
            file_path: Path to the audio file
            num_speakers: Override number of speakers

        Returns:
            DiarizationResult with speaker segments
        """
        from server.core.audio_utils import load_audio

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info(f"Diarizing file: {file_path}")

        audio_data, sample_rate = load_audio(str(path), target_sample_rate=16000)
        return self.diarize_audio(audio_data, sample_rate, num_speakers)


def create_diarization_engine(config: dict[str, Any]) -> DiarizationEngine:
    """
    Create a DiarizationEngine from configuration.

    Args:
        config: Configuration with diarization settings.
                Expects 'diarization' key at top level of config dict.

    Returns:
        Configured DiarizationEngine instance
    """
    # Read from top-level 'diarization' section (matches config.yaml structure)
    diar_config = config.get("diarization", {})

    return DiarizationEngine(
        model=diar_config.get("model", "pyannote/speaker-diarization-community-1"),
        hf_token=diar_config.get("hf_token") or os.environ.get("HF_TOKEN"),
        device=_resolve_device(diar_config.get("device", "cuda")),
        num_speakers=diar_config.get("num_speakers"),
        min_speakers=diar_config.get("min_speakers"),
        max_speakers=diar_config.get("max_speakers"),
        min_duration_on=diar_config.get("min_duration_on", 0.0),
        min_duration_off=diar_config.get("min_duration_off", 0.0),
    )
