#!/usr/bin/env python3
"""
Main entry point for the diarization module.

This script can be called from the transcription suite to perform
speaker diarization on audio files and optionally combine with transcription.

Usage:
    python diarize_audio.py <audio_file> [options]

    Or from Python:
    from diarize_audio import diarize_and_transcribe
    result = diarize_and_transcribe(audio_file, transcription_data)
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from config_manager import ConfigManager
from diarization_manager import DiarizationManager
from logging_setup import setup_logging
from transcription_combiner import (
    TranscriptionCombiner,
    export_to_json,
    export_to_srt,
    export_to_text,
)
from utils import (
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

    Args:
        audio_file: Path to the audio file
        config_path: Optional path to configuration file
        min_speakers: Minimum number of speakers
        max_speakers: Maximum number of speakers
        output_format: Output format (json, rttm, segments)

    Returns:
        Dictionary containing diarization results
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


def diarize_and_combine(
    audio_file: str,
    transcription_data: Optional[Dict[str, Any]] = None,
    transcription_file: Optional[str] = None,
    config_path: Optional[str] = None,
    output_file: Optional[str] = None,
    output_format: str = "json",
    use_word_timestamps: bool = False,
) -> Dict[str, Any]:
    """
    Perform diarization and optionally combine with transcription.

    Args:
        audio_file: Path to the audio file
        transcription_data: Transcription data dictionary (Whisper format)
        transcription_file: Path to transcription JSON file (alternative to
            transcription_data)
        config_path: Optional path to configuration file
        output_file: Optional path to save results
        output_format: Output format (json, srt, text)
        use_word_timestamps: Use word-level timestamps if available

    Returns:
        Dictionary containing combined results
    """
    # Load configuration
    config = ConfigManager(config_path)
    setup_logging(config.config)

    # Validate audio file
    if not validate_audio_file(audio_file):
        raise ValueError(f"Invalid audio file: {audio_file}")

    # Load transcription if file provided
    if transcription_file and not transcription_data:
        with open(transcription_file, "r", encoding="utf-8") as f:
            transcription_data = json.load(f)

    # Initialize managers
    diarization_manager = DiarizationManager(config)
    combiner = TranscriptionCombiner()

    try:
        # Perform diarization
        safe_print("Performing speaker diarization...", "info")
        diarization_segments = diarization_manager.diarize(audio_file)

        # If no transcription provided, return just diarization
        if not transcription_data:
            result = {
                "diarization": [seg.to_dict() for seg in diarization_segments],
                "transcription": None,
                "combined": None,
            }
        else:
            # Parse transcription
            if use_word_timestamps:
                transcription_segments = combiner.parse_word_timestamps(
                    transcription_data
                )
                safe_print(f"Parsed {len(transcription_segments)} word segments", "info")
            else:
                transcription_segments = combiner.parse_whisper_output(transcription_data)
                safe_print(
                    f"Parsed {len(transcription_segments)} transcription segments", "info"
                )

            # Combine transcription with diarization
            safe_print("Combining transcription with speaker diarization...", "info")

            if use_word_timestamps:
                combined_segments = combiner.combine_with_words(
                    transcription_segments, diarization_segments
                )
            else:
                combined_segments = combiner.combine(
                    transcription_segments, diarization_segments, merge_sentences=True
                )

            safe_print(
                f"Created {len(combined_segments)} speaker-labeled segments", "success"
            )

            # Prepare result
            result = {
                "diarization": [seg.to_dict() for seg in diarization_segments],
                "transcription": transcription_data,
                "combined": [seg.to_dict() for seg in combined_segments],
            }

            # Save to file if requested
            if output_file:
                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)

                if output_format == "srt":
                    export_to_srt(combined_segments, str(output_path))
                elif output_format == "text":
                    export_to_text(combined_segments, str(output_path))
                else:  # json
                    export_to_json(
                        combined_segments,
                        str(output_path),
                        metadata={
                            "audio_file": str(audio_file),
                            "num_diarization_segments": len(diarization_segments),
                            "num_transcription_segments": len(transcription_segments),
                        },
                    )

                safe_print(f"Results saved to: {output_path}", "success")

        return result

    finally:
        # Unload pipeline to free memory
        diarization_manager.unload_pipeline()


def main():
    """Main entry point for command-line usage."""
    parser = argparse.ArgumentParser(
        description="Speaker diarization module for audio files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Diarize only
  %(prog)s audio.wav

  # Diarize with specific number of speakers
  %(prog)s audio.wav --min-speakers 2 --max-speakers 4

  # Combine with transcription
  %(prog)s audio.wav --transcription transcript.json --output result.json

  # Export as SRT subtitles
  %(prog)s audio.wav --transcription transcript.json --output subtitles.srt --format srt
        """,
    )

    parser.add_argument("audio_file", help="Path to the audio file to diarize")

    parser.add_argument(
        "--config",
        help="Path to configuration file (default: config.yaml in script directory)",
    )

    parser.add_argument("--min-speakers", type=int, help="Minimum number of speakers")

    parser.add_argument("--max-speakers", type=int, help="Maximum number of speakers")

    parser.add_argument(
        "--transcription", help="Path to transcription JSON file (Whisper format)"
    )

    parser.add_argument("--output", help="Path to save results")

    parser.add_argument(
        "--format",
        choices=["json", "srt", "text", "rttm"],
        default="json",
        help="Output format (default: json)",
    )

    parser.add_argument(
        "--use-word-timestamps",
        action="store_true",
        help="Use word-level timestamps from transcription if available",
    )

    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # Set up logging
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    try:
        if args.transcription:
            # Diarize and combine with transcription
            result = diarize_and_combine(
                audio_file=args.audio_file,
                transcription_file=args.transcription,
                config_path=args.config,
                output_file=args.output,
                output_format=args.format,
                use_word_timestamps=args.use_word_timestamps,
            )
        else:
            # Diarize only
            result = diarize_audio(
                audio_file=args.audio_file,
                config_path=args.config,
                min_speakers=args.min_speakers,
                max_speakers=args.max_speakers,
                output_format=args.format if args.format != "srt" else "json",
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
