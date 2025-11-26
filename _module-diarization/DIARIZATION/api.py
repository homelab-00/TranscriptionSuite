#!/usr/bin/env python3
"""
Simple API for integration with the transcription suite.

This module provides a simple interface for the transcription suite to call
the diarization functionality. It performs DIARIZATION ONLY - combining with
transcription is handled by the calling code in _core.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from config_manager import ConfigManager
from diarize_audio import diarize_audio, get_diarization_segments
from utils import DiarizationSegment


class DiarizationAPI:
    """
    Simple API wrapper for diarization functionality.

    This class provides an easy-to-use interface for the transcription suite.
    It performs DIARIZATION ONLY - no transcription combining.
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        hf_token: Optional[str] = None,
    ):
        """
        Initialize the diarization API.

        Args:
            config_path: Optional path to configuration file
            hf_token: Optional HuggingFace token (overrides config)
        """
        self.config_path = config_path
        self.hf_token = hf_token

        # If HF token provided, update config
        if hf_token:
            config = ConfigManager(config_path)
            config.config["pyannote"]["hf_token"] = hf_token
            # Save the updated config
            import yaml

            with open(config.config_path, "w") as f:
                yaml.dump(config.config, f, default_flow_style=False)

    def diarize(
        self,
        audio_file: Union[str, Path],
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
        output_format: str = "json",
    ) -> Dict[str, Any]:
        """
        Perform diarization on an audio file.

        Args:
            audio_file: Path to the audio file
            min_speakers: Minimum number of speakers
            max_speakers: Maximum number of speakers
            output_format: Output format (json, rttm, segments)

        Returns:
            Dictionary containing diarization results
        """
        return diarize_audio(
            audio_file=str(audio_file),
            config_path=self.config_path,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            output_format=output_format,
        )

    def get_segments(
        self,
        audio_file: Union[str, Path],
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
    ) -> List[DiarizationSegment]:
        """
        Perform diarization and return raw DiarizationSegment objects.

        This is the recommended method for programmatic use, as it returns
        the actual segment objects rather than dictionaries.

        Args:
            audio_file: Path to the audio file
            min_speakers: Minimum number of speakers
            max_speakers: Maximum number of speakers

        Returns:
            List of DiarizationSegment objects
        """
        return get_diarization_segments(
            audio_file=str(audio_file),
            config_path=self.config_path,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
        )


def quick_diarize(
    audio_file: str,
    hf_token: Optional[str] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Quick function for one-shot diarization.

    This is the simplest way to use the diarization module from external code.

    Args:
        audio_file: Path to the audio file
        hf_token: Optional HuggingFace token for PyAnnote access
        min_speakers: Optional minimum number of speakers
        max_speakers: Optional maximum number of speakers

    Returns:
        Dictionary containing the diarization results

    Example:
        from DIARIZATION.api import quick_diarize

        result = quick_diarize("audio.wav", hf_token="hf_YOUR_TOKEN_HERE")
        for segment in result["segments"]:
            print(f"{segment['speaker']}: {segment['start']:.2f}s - {segment['end']:.2f}s")
    """
    api = DiarizationAPI(hf_token=hf_token)
    return api.diarize(
        audio_file=audio_file,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
    )
