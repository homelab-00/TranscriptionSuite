#!/usr/bin/env python3
"""
Diarization manager using PyAnnote.

This module handles the core diarization functionality using PyAnnote models.
It provides a clean interface for speaker diarization on audio files.

Integrated directly into the main application (Python 3.11).
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf
import torch
from scipy import signal

from .utils import (
    DiarizationSegment,
    merge_consecutive_segments,
    safe_print,
    validate_audio_file,
)

# Get project root for config
_PROJECT_ROOT = Path(__file__).parent.parent


class DiarizationManager:
    """Manages speaker diarization using PyAnnote models."""

    # Default configuration
    DEFAULT_CONFIG = {
        "model": "pyannote/speaker-diarization-3.1",
        "device": "cuda",
        "min_speakers": None,
        "max_speakers": None,
        "min_duration_on": 0.0,
        "min_duration_off": 0.0,
        "merge_gap_threshold": 0.5,
        "sample_rate": 16000,
        "temp_dir": "/tmp/transcription-suite",
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the diarization manager.

        Args:
            config: Configuration dictionary. If None, uses defaults and
                   attempts to load from project config.yaml.
        """
        self.config = self._load_config(config)
        self.pipeline = None
        self.device = None
        self.temp_dir: str = ""
        self._initialize()

    def _load_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Load configuration, merging with defaults."""
        result = self.DEFAULT_CONFIG.copy()

        # Try to load from project config.yaml
        config_file = _PROJECT_ROOT / "config.yaml"
        if config_file.exists():
            try:
                import yaml

                with open(config_file) as f:
                    file_config = yaml.safe_load(f) or {}

                # Extract diarization-related settings
                if "diarization" in file_config:
                    for key, value in file_config["diarization"].items():
                        if key in result:
                            result[key] = value

                # Also check pyannote section for backwards compatibility
                if "pyannote" in file_config:
                    for key, value in file_config["pyannote"].items():
                        if key in result:
                            result[key] = value

                logging.debug(f"Loaded config from {config_file}")
            except Exception as e:
                logging.warning(f"Could not load config from {config_file}: {e}")

        # Override with provided config
        if config:
            for key, value in config.items():
                if key in result:
                    result[key] = value

        return result

    def _initialize(self) -> None:
        """Initialize the PyAnnote pipeline and set up the environment."""
        # Set up device
        device_str = self.config.get("device", "cuda")
        if device_str == "cuda" and torch.cuda.is_available():
            self.device = torch.device("cuda")
            logging.info("Using CUDA for diarization")
        else:
            self.device = torch.device("cpu")
            if device_str == "cuda":
                logging.warning("CUDA requested but not available, using CPU")
            else:
                logging.info("Using CPU for diarization")

        # Set up temporary directory
        temp_dir_path = self.config.get("temp_dir", "/tmp/transcription-suite")
        os.makedirs(temp_dir_path, exist_ok=True)
        self.temp_dir = temp_dir_path
        logging.debug(f"Using temporary directory: {self.temp_dir}")

    def _get_hf_token(self) -> Optional[str]:
        """Get HuggingFace token from environment or cached login."""
        # 1. Check HF_TOKEN environment variable
        env_token = os.environ.get("HF_TOKEN")
        if env_token:
            return env_token

        # 2. Try to get cached token from huggingface-cli login
        try:
            from huggingface_hub import get_token

            token = get_token()
            if token:
                return token
        except Exception:
            pass

        return None

    def load_pipeline(self) -> None:
        """
        Load the PyAnnote diarization pipeline.

        This is separated from initialization to allow lazy loading.
        """
        if self.pipeline is not None:
            logging.info("Pipeline already loaded")
            return

        safe_print("Loading PyAnnote diarization pipeline...", "info")

        try:
            from pyannote.audio import Pipeline

            hf_token = self._get_hf_token()
            model_name = self.config.get("model", "pyannote/speaker-diarization-3.1")

            # Load the pipeline from HuggingFace
            kwargs = {}
            if hf_token:
                kwargs["use_auth_token"] = hf_token
            self.pipeline = Pipeline.from_pretrained(model_name, **kwargs)

            # Move pipeline to device if available
            if self.pipeline is not None and self.device is not None:
                self.pipeline.to(self.device)

            safe_print(f"Successfully loaded {model_name}", "success")
            logging.info(f"Pipeline loaded: {model_name} on {self.device}")

        except ImportError:
            raise ImportError(
                "pyannote.audio is not installed. "
                "Please install it with: uv pip install pyannote-audio"
            )
        except Exception as e:
            logging.error(f"Failed to load PyAnnote pipeline: {e}")
            raise RuntimeError(f"Could not load diarization pipeline: {e}")

    def unload_pipeline(self) -> None:
        """Unload the pipeline to free memory."""
        if self.pipeline is not None:
            del self.pipeline
            self.pipeline = None

            # Clear CUDA cache if using GPU
            if self.device is not None and self.device.type == "cuda":
                torch.cuda.empty_cache()

            logging.info("Pipeline unloaded and memory cleared")
            safe_print("Diarization pipeline unloaded", "info")

    def _prepare_audio(self, audio_file: str) -> Tuple[str, float]:
        """
        Prepare audio file for diarization (convert to correct format if needed).

        Args:
            audio_file: Path to the input audio file

        Returns:
            Tuple of (processed_audio_path, duration_seconds)
        """
        # Read the audio file
        data, sample_rate = sf.read(audio_file, dtype="float32")
        audio_data = np.asarray(data, dtype="float32")

        # Calculate duration
        if len(audio_data.shape) > 1:
            duration = len(audio_data) / sample_rate
        else:
            duration = len(audio_data) / sample_rate

        # Check if we need to resample
        target_sample_rate = self.config.get("sample_rate", 16000)

        if sample_rate != target_sample_rate:
            logging.info(
                f"Resampling audio from {sample_rate}Hz to {target_sample_rate}Hz"
            )
            num_samples = int(len(audio_data) * target_sample_rate / sample_rate)
            audio_data = signal.resample(audio_data, num_samples)
            if isinstance(audio_data, tuple):
                audio_data = audio_data[0]
            sample_rate = target_sample_rate

        # Convert to mono if stereo
        if len(audio_data.shape) > 1 and audio_data.shape[1] > 1:
            logging.info("Converting stereo to mono")
            audio_data = np.mean(audio_data, axis=1)

        # Save to temporary file
        temp_audio_path = os.path.join(self.temp_dir, "prepared_audio.wav")
        sf.write(temp_audio_path, audio_data, sample_rate)

        logging.info(f"Audio prepared: {duration:.2f}s duration at {sample_rate}Hz")

        return temp_audio_path, duration

    def diarize(
        self,
        audio_file: str,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
    ) -> List[DiarizationSegment]:
        """
        Perform speaker diarization on an audio file.

        Args:
            audio_file: Path to the audio file
            min_speakers: Minimum number of speakers (overrides config)
            max_speakers: Maximum number of speakers (overrides config)

        Returns:
            List of DiarizationSegment objects
        """
        # Validate input
        if not validate_audio_file(audio_file):
            raise ValueError(f"Invalid audio file: {audio_file}")

        # Load pipeline if not already loaded
        if self.pipeline is None:
            self.load_pipeline()

        safe_print(f"Processing: {audio_file}", "info")

        try:
            # Prepare audio
            prepared_audio, duration = self._prepare_audio(audio_file)

            # Get diarization parameters
            min_spk = min_speakers or self.config.get("min_speakers")
            max_spk = max_speakers or self.config.get("max_speakers")

            # Build parameters dict
            params = {}
            if min_spk is not None:
                params["min_speakers"] = min_spk
            if max_spk is not None:
                params["max_speakers"] = max_spk

            # Additional parameters from config
            min_duration_on = self.config.get("min_duration_on", 0.0)
            min_duration_off = self.config.get("min_duration_off", 0.0)

            if min_duration_on > 0:
                params["min_duration_on"] = min_duration_on
            if min_duration_off > 0:
                params["min_duration_off"] = min_duration_off

            # Run diarization
            safe_print("Running speaker diarization...", "info")
            logging.info(f"Diarization parameters: {params}")

            assert self.pipeline is not None

            if params:
                diarization_result = self.pipeline(prepared_audio, **params)
            else:
                diarization_result = self.pipeline(prepared_audio)

            # Convert PyAnnote output to our segment format
            segments = self._convert_to_segments(diarization_result)

            # Merge consecutive segments if configured
            merge_gap = self.config.get("merge_gap_threshold", 0.5)
            if merge_gap > 0:
                segments = merge_consecutive_segments(segments, merge_gap)
                logging.info(f"Merged segments with gap threshold {merge_gap}s")

            # Sort segments by start time
            segments.sort(key=lambda s: s.start)

            # Log summary
            num_speakers = len(set(seg.speaker for seg in segments))
            safe_print(
                f"Diarization complete: {len(segments)} segments, "
                f"{num_speakers} speakers, {duration:.1f}s total",
                "success",
            )

            return segments

        except Exception as e:
            logging.error(f"Diarization failed: {e}", exc_info=True)
            raise RuntimeError(f"Diarization failed: {e}")

        finally:
            # Clean up temporary files
            self._cleanup_temp_files()

    def _convert_to_segments(self, diarization_result) -> List[DiarizationSegment]:
        """
        Convert PyAnnote diarization output to our segment format.

        Args:
            diarization_result: PyAnnote output

        Returns:
            List of DiarizationSegment objects
        """
        segments = []

        # Handle pyannote.audio 4.x DiarizeOutput dataclass
        # which wraps the annotation in a speaker_diarization attribute
        if hasattr(diarization_result, "speaker_diarization"):
            annotation = diarization_result.speaker_diarization
        else:
            # Older versions return the annotation directly
            annotation = diarization_result

        for turn, _, speaker in annotation.itertracks(yield_label=True):
            # Create a segment for each speaker turn
            segment = DiarizationSegment(
                start=turn.start,
                end=turn.end,
                speaker=speaker,
                confidence=None,
            )
            segments.append(segment)

        return segments

    def _cleanup_temp_files(self) -> None:
        """Clean up temporary files created during processing."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                temp_audio = os.path.join(self.temp_dir, "prepared_audio.wav")
                if os.path.exists(temp_audio):
                    os.remove(temp_audio)
                    logging.debug(f"Removed temporary file: {temp_audio}")
            except Exception as e:
                logging.warning(f"Could not clean up temporary files: {e}")

    def __del__(self):
        """Cleanup when the manager is destroyed."""
        try:
            self.unload_pipeline()
        except Exception:
            pass
