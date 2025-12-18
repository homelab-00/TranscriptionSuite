"""
Speaker diarization engine for TranscriptionSuite server.

Wraps PyAnnote speaker diarization pipeline for integration
with the unified transcription engine.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from server.core.audio_utils import clear_gpu_cache

logger = logging.getLogger(__name__)

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


class DiarizationSegment:
    """A segment with speaker assignment."""

    def __init__(self, start: float, end: float, speaker: str):
        self.start = start
        self.end = end
        self.speaker = speaker

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "speaker": self.speaker,
            "duration": round(self.duration, 3),
        }


class DiarizationResult:
    """Complete diarization result."""

    def __init__(self, segments: List[DiarizationSegment], num_speakers: int):
        self.segments = segments
        self.num_speakers = num_speakers

    def get_speaker_at(self, time: float) -> Optional[str]:
        """Get the speaker at a specific time."""
        for seg in self.segments:
            if seg.start <= time <= seg.end:
                return seg.speaker
        return None

    def to_dict(self) -> Dict[str, Any]:
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
        hf_token: Optional[str] = None,
        device: str = "cuda",
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
    ):
        """
        Initialize the diarization engine.

        Args:
            hf_token: HuggingFace token for accessing PyAnnote models
            device: Device to run on ("cuda" or "cpu")
            num_speakers: Known number of speakers (if known)
            min_speakers: Minimum number of speakers
            max_speakers: Maximum number of speakers
        """
        if not HAS_PYANNOTE:
            raise ImportError(
                "pyannote.audio is required for diarization. "
                "Install with: pip install pyannote.audio"
            )

        self.hf_token = hf_token or os.environ.get("HF_TOKEN")
        self.device = device
        self.num_speakers = num_speakers
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers

        self._pipeline: Optional[Any] = None
        self._loaded = False

        logger.info(f"DiarizationEngine initialized: device={device}")

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

        logger.info("Loading PyAnnote diarization pipeline...")

        try:
            self._pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=self.hf_token,
            )

            # Move to device
            if HAS_TORCH and torch is not None:
                if self.device == "cuda" and torch.cuda.is_available():
                    self._pipeline = self._pipeline.to(torch.device("cuda"))
                else:
                    self._pipeline = self._pipeline.to(torch.device("cpu"))

            self._loaded = True
            logger.info("Diarization pipeline loaded successfully")

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
        num_speakers: Optional[int] = None,
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

            diarization = self._pipeline(
                audio_input,
                num_speakers=n_speakers,
                min_speakers=self.min_speakers,
                max_speakers=self.max_speakers,
            )

            # Convert to segments
            segments: List[DiarizationSegment] = []
            speakers = set()

            for turn, _, speaker in diarization.itertracks(yield_label=True):
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
        num_speakers: Optional[int] = None,
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


def create_diarization_engine(config: Dict[str, Any]) -> DiarizationEngine:
    """
    Create a DiarizationEngine from configuration.

    Args:
        config: Configuration with diarization settings

    Returns:
        Configured DiarizationEngine instance
    """
    diar_config = config.get("transcription", {}).get("diarization", {})
    trans_config = config.get("transcription", config.get("main_transcriber", {}))

    return DiarizationEngine(
        hf_token=diar_config.get("hf_token") or os.environ.get("HF_TOKEN"),
        device=trans_config.get("device", "cuda"),
        num_speakers=diar_config.get("num_speakers"),
        min_speakers=diar_config.get("min_speakers"),
        max_speakers=diar_config.get("max_speakers"),
    )
