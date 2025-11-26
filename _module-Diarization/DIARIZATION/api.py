#!/usr/bin/env python3
"""
Simple API for integration with the transcription suite.

This module provides a simple interface for the transcription suite to call
the diarization functionality without dealing with the complexity of the
internal modules.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union

from config_manager import ConfigManager
from diarize_audio import diarize_and_combine


class DiarizationAPI:
    """
    Simple API wrapper for diarization functionality.

    This class provides an easy-to-use interface for the transcription suite.
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

    def process(
        self,
        audio_file: Union[str, Path],
        transcription_json: Optional[Union[str, Dict]] = None,
        output_file: Optional[Union[str, Path]] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
        use_word_timestamps: bool = False,
        output_format: str = "json",
    ) -> Dict[str, Any]:
        """
        Process an audio file for diarization and optionally combine with transcription.

        Args:
            audio_file: Path to the audio file
            transcription_json: Path to transcription JSON file or the data itself
            output_file: Optional path to save results
            min_speakers: Minimum number of speakers
            max_speakers: Maximum number of speakers
            use_word_timestamps: Use word-level timestamps if available
            output_format: Output format (json, srt, text)

        Returns:
            Dictionary containing the results
        """
        # Convert paths to strings
        audio_file = str(audio_file)
        if output_file:
            output_file = str(output_file)

        # Handle transcription input
        transcription_data = None
        transcription_file = None

        if transcription_json:
            if isinstance(transcription_json, dict):
                transcription_data = transcription_json
            elif isinstance(transcription_json, (str, Path)):
                transcription_file = str(transcription_json)

        # Call the main diarization function
        try:
            result = diarize_and_combine(
                audio_file=audio_file,
                transcription_data=transcription_data,
                transcription_file=transcription_file,
                config_path=self.config_path,
                output_file=output_file,
                output_format=output_format,
                use_word_timestamps=use_word_timestamps,
            )

            return result

        except Exception as e:
            logging.error(f"Diarization failed: {e}", exc_info=True)
            raise


def quick_diarize(
    audio_file: str,
    hf_token: str,
    transcription_json: Optional[Union[str, Dict]] = None,
    output_file: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Quick function for one-shot diarization.

    This is the simplest way to use the diarization module from external code.

    Args:
        audio_file: Path to the audio file
        hf_token: HuggingFace token for PyAnnote access
        transcription_json: Optional transcription data or file path
        output_file: Optional path to save results

    Returns:
        Dictionary containing the diarization results

    Example:
        from DIARIZATION.api import quick_diarize

        result = quick_diarize(
            "audio.wav",
            "hf_YOUR_TOKEN_HERE",
            transcription_json="transcript.json",
            output_file="output.json"
        )
    """
    api = DiarizationAPI(hf_token=hf_token)
    return api.process(
        audio_file=audio_file,
        transcription_json=transcription_json,
        output_file=output_file,
    )
