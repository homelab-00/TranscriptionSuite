#!/usr/bin/env python3
"""
Main entry point for the diarization module.

This module performs speaker diarization ONLY. Combining with transcription
is handled by the calling code in _core.

Usage:
    python diarize_audio.py <audio_file> [options]

    Or from Python:
    from diarize_audio import diarize_audio
    result = diarize_audio(audio_file)
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from config_manager import ConfigManager
from diarization_manager import DiarizationManager
from logging_setup import setup_logging
from utils import (
    DiarizationSegment,
    safe_print,
    segments_to_json,
    segments_to_rttm,
    validate_audio_file,
)

# Add parent directory to path for imports when called directly
sys.path.insert(0, str(Path(__file__).parent))


def diarize_audio(
    audio_file: str,
    config_path: Optional[str] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
    output_format: str = "json",
) -> Dict[str, Any]:
    """
    Perform speaker diarization on an audio file.

    This function ONLY performs diarization. Combining with transcription
    is handled by the calling code in _core.

    Args:
        audio_file: Path to the audio file
        config_path: Optional path to configuration file
        min_speakers: Minimum number of speakers
        max_speakers: Maximum number of speakers
        output_format: Output format (json, rttm, segments)

    Returns:
        Dictionary containing diarization results with structure:
        {
            "segments": [...],  # List of segment dicts
            "total_duration": float,
            "num_speakers": int
        }
    """
    # Load configuration
    config = ConfigManager(config_path)
    setup_logging(config.config)

    # Initialize diarization manager
    manager = DiarizationManager(config)

    try:
        # Perform diarization
        segments = manager.diarize(audio_file, min_speakers, max_speakers)

        # Format output based on requested format
        if output_format == "json":
            return json.loads(segments_to_json(segments))
        elif output_format == "rttm":
            return {"rttm": segments_to_rttm(segments)}
        elif output_format == "segments":
            return {"segments": [seg.to_dict() for seg in segments]}
        else:
            return {"segments": [seg.to_dict() for seg in segments]}

    finally:
        # Optionally unload pipeline to free memory
        manager.unload_pipeline()


def get_diarization_segments(
    audio_file: str,
    config_path: Optional[str] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
) -> List[DiarizationSegment]:
    """
    Perform diarization and return raw DiarizationSegment objects.

    This is the recommended function for programmatic use from _core,
    as it returns the actual segment objects rather than dictionaries.

    Args:
        audio_file: Path to the audio file
        config_path: Optional path to configuration file
        min_speakers: Minimum number of speakers
        max_speakers: Maximum number of speakers

    Returns:
        List of DiarizationSegment objects
    """
    # Load configuration
    config = ConfigManager(config_path)
    setup_logging(config.config)

    # Validate audio file
    if not validate_audio_file(audio_file):
        raise ValueError(f"Invalid audio file: {audio_file}")

    # Initialize diarization manager
    manager = DiarizationManager(config)

    try:
        # Perform diarization and return raw segments
        safe_print("Performing speaker diarization...", "info")
        segments = manager.diarize(audio_file, min_speakers, max_speakers)
        safe_print(
            f"Diarization complete: {len(segments)} segments, "
            f"{len(set(s.speaker for s in segments))} speakers",
            "success",
        )
        return segments

    finally:
        # Unload pipeline to free memory
        manager.unload_pipeline()


def main():
    """Main entry point for command-line usage."""
    parser = argparse.ArgumentParser(
        description="Speaker diarization module for audio files (diarization ONLY)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Diarize an audio file
  %(prog)s audio.wav

  # Diarize with specific number of speakers
  %(prog)s audio.wav --min-speakers 2 --max-speakers 4

  # Save results to file
  %(prog)s audio.wav --output diarization.json

  # Export as RTTM format
  %(prog)s audio.wav --output diarization.rttm --format rttm

Note: This module only performs diarization. Combining with transcription
is handled by the _core transcription suite.
        """,
    )

    parser.add_argument("audio_file", help="Path to the audio file to diarize")

    parser.add_argument(
        "--config",
        help="Path to configuration file (default: config.yaml in script directory)",
    )

    parser.add_argument("--min-speakers", type=int, help="Minimum number of speakers")

    parser.add_argument("--max-speakers", type=int, help="Maximum number of speakers")

    parser.add_argument("--output", help="Path to save results")

    parser.add_argument(
        "--format",
        choices=["json", "rttm", "segments"],
        default="json",
        help="Output format (default: json)",
    )

    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # Set up logging
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    try:
        # Perform diarization only
        result = diarize_audio(
            audio_file=args.audio_file,
            config_path=args.config,
            min_speakers=args.min_speakers,
            max_speakers=args.max_speakers,
            output_format=args.format,
        )

        # Save results if output specified
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            if args.format == "rttm":
                with open(output_path, "w") as f:
                    f.write(result.get("rttm", ""))
            else:
                with open(output_path, "w") as f:
                    json.dump(result, f, indent=2)

            safe_print(f"Results saved to: {output_path}", "success")

        # Print results to console if no output file specified
        if not args.output:
            print(json.dumps(result, indent=2))

    except Exception as e:
        safe_print(f"Error: {e}", "error")
        logging.error("Fatal error", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
