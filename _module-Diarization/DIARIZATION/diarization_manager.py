#!/usr/bin/env python3
"""
Diarization manager using PyAnnote.

This module handles the core diarization functionality using PyAnnote models.
It provides a clean interface for speaker diarization on audio files.
"""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf
import torch
from config_manager import ConfigManager
from utils import (
    DiarizationSegment,
    merge_consecutive_segments,
    safe_print,
    validate_audio_file,
)


class DiarizationManager:
    """Manages speaker diarization using PyAnnote models."""

    def __init__(self, config: Optional[ConfigManager] = None):
        """
        Initialize the diarization manager.

        Args:
            config: Configuration manager instance. If None, uses default configuration.
        """
        self.config = config or ConfigManager()
        self.pipeline = None
        self.device = None
        self.temp_dir: str = ""
        self._initialize()

    def _initialize(self) -> None:
        """Initialize the PyAnnote pipeline and set up the environment."""
        # Validate configuration
        if not self.config.validate():
            raise ValueError("Invalid configuration. Please check your config.yaml file.")

        # Set up device
        device_str = self.config.get("pyannote", "device")
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
        temp_dir_path = self.config.get("processing", "temp_dir")
        os.makedirs(temp_dir_path, exist_ok=True)
        self.temp_dir = temp_dir_path
        logging.info(f"Using temporary directory: {self.temp_dir}")

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

            hf_token = self.config.get("pyannote", "hf_token")
            model_name = self.config.get("pyannote", "model")

            # Load the pipeline from HuggingFace
            kwargs = {}
            if hf_token:
                kwargs["token"] = hf_token
            self.pipeline = Pipeline.from_pretrained(model_name, **kwargs)

            # Move pipeline to device if available
            if self.pipeline is not None and self.device is not None:
                self.pipeline.to(self.device)

            safe_print(f"Successfully loaded {model_name}", "success")
            logging.info(f"Pipeline loaded: {model_name} on {self.device}")

        except ImportError:
            raise ImportError(
                "pyannote.audio is not installed. "
                "Please install it with: pip install pyannote.audio"
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
        duration = len(audio_data) / sample_rate

        # Check if we need to resample
        target_sample_rate = self.config.get("processing", "sample_rate")

        if sample_rate != target_sample_rate:
            logging.info(
                f"Resampling audio from {sample_rate}Hz to {target_sample_rate}Hz"
            )

            # Resample using scipy
            from scipy import signal

            num_samples = int(len(audio_data) * target_sample_rate / sample_rate)
            audio_data = signal.resample(audio_data, num_samples)[0]
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
            min_spk = min_speakers or self.config.get("pyannote", "min_speakers")
            max_spk = max_speakers or self.config.get("pyannote", "max_speakers")

            # Build parameters dict
            params = {}
            if min_spk is not None:
                params["min_speakers"] = min_spk
            if max_spk is not None:
                params["max_speakers"] = max_spk

            # Additional parameters from config
            min_duration_on = self.config.get("pyannote", "min_duration_on")
            min_duration_off = self.config.get("pyannote", "min_duration_off")

            if min_duration_on > 0:
                params["min_duration_on"] = min_duration_on
            if min_duration_off > 0:
                params["min_duration_off"] = min_duration_off

            # Run diarization
            safe_print("Running speaker diarization...", "info")
            logging.info(f"Diarization parameters: {params}")

            assert self.pipeline is not None
            pipeline = self.pipeline

            if params:
                diarization_result = pipeline(prepared_audio, **params)
            else:
                diarization_result = pipeline(prepared_audio)

            # Convert PyAnnote output to our segment format
            segments = self._convert_to_segments(diarization_result)

            # Merge consecutive segments if configured
            merge_gap = self.config.get("output", "merge_gap_threshold")
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
            # Clean up temporary files unless configured to keep them
            if not self.config.get("processing", "keep_temp_files"):
                self._cleanup_temp_files()

    def _convert_to_segments(self, diarization_result) -> List[DiarizationSegment]:
        """
        Convert PyAnnote diarization output to our segment format.

        Args:
            diarization_result: PyAnnote output (DiarizeOutput in v4.x or
                Annotation in older versions)

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
                # PyAnnote doesn't provide confidence in standard output
                confidence=None,
            )
            segments.append(segment)

        return segments

    def _cleanup_temp_files(self) -> None:
        """Clean up temporary files created during processing."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                # Only remove files we created, not the entire directory
                temp_audio = os.path.join(self.temp_dir, "prepared_audio.wav")
                if os.path.exists(temp_audio):
                    os.remove(temp_audio)
                    logging.debug(f"Removed temporary file: {temp_audio}")
            except Exception as e:
                logging.warning(f"Could not clean up temporary files: {e}")

    def process_batch(
        self, audio_files: List[str], output_dir: Optional[str] = None
    ) -> Dict[str, List[DiarizationSegment]]:
        """
        Process multiple audio files in batch.

        Args:
            audio_files: List of paths to audio files
            output_dir: Optional directory to save results

        Returns:
            Dictionary mapping file paths to their diarization segments
        """
        results = {}

        # Create output directory if specified
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        total = len(audio_files)
        for idx, audio_file in enumerate(audio_files, 1):
            safe_print(f"Processing {idx}/{total}: {Path(audio_file).name}", "info")

            try:
                segments = self.diarize(audio_file)
                results[audio_file] = segments

                # Save results if output directory specified
                if output_dir:
                    self._save_results(audio_file, segments, output_dir)

            except Exception as e:
                logging.error(f"Failed to process {audio_file}: {e}")
                safe_print(f"Failed: {audio_file} - {e}", "error")
                results[audio_file] = []

        return results

    def _save_results(
        self, audio_file: str, segments: List[DiarizationSegment], output_dir: str
    ) -> None:
        """
        Save diarization results to file.

        Args:
            audio_file: Original audio file path
            segments: List of diarization segments
            output_dir: Directory to save results
        """
        from utils import segments_to_json, segments_to_rttm, segments_to_text

        # Get base name without extension
        base_name = Path(audio_file).stem

        # Get output format from config
        output_format = self.config.get("output", "format")

        if output_format == "json":
            output_file = os.path.join(output_dir, f"{base_name}.json")
            with open(output_file, "w") as f:
                f.write(segments_to_json(segments))

        elif output_format == "rttm":
            output_file = os.path.join(output_dir, f"{base_name}.rttm")
            with open(output_file, "w") as f:
                f.write(segments_to_rttm(segments, file_id=base_name))

        elif output_format == "segments":
            output_file = os.path.join(output_dir, f"{base_name}.txt")
            with open(output_file, "w") as f:
                f.write(segments_to_text(segments))

        else:
            logging.warning(f"Unknown output format: {output_format}")
            return

        logging.info(f"Results saved to: {output_file}")

    def __del__(self):
        """Cleanup when the manager is destroyed."""
        self.unload_pipeline()
