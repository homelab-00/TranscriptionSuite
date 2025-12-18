"""
Diarization module for speaker identification in audio files.

This module provides speaker diarization using PyAnnote, plus utilities
for combining diarization with transcription results.

Usage:
    from DIARIZATION import DiarizationManager, quick_diarize

    # Quick diarization
    result = quick_diarize("audio.wav")

    # Or use the manager for more control
    manager = DiarizationManager()
    segments = manager.diarize("audio.wav")

    # Use the service for more features
    from DIARIZATION import DiarizationService
    service = DiarizationService()
    segments = service.diarize("audio.wav")

    # Combine transcription with diarization
    from DIARIZATION import TranscriptionCombiner
    combiner = TranscriptionCombiner()
    result = combiner.combine(transcription, segments)
"""

from .diarization_manager import DiarizationManager
from .utils import (
    DiarizationSegment,
    format_timestamp,
    merge_consecutive_segments,
    safe_print,
    segments_to_json,
    segments_to_rttm,
    segments_to_text,
    validate_audio_file,
)
from .service import DiarizationService, get_diarization
from .combiner import (
    TranscriptionCombiner,
    TranscriptionSegment,
    SpeakerTranscriptionSegment,
    export_to_json,
    export_to_srt,
    export_to_text,
)

__version__ = "2.0.0"


def quick_diarize(
    audio_file: str,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> dict:
    """
    Quick diarization function for simple use cases.

    Args:
        audio_file: Path to the audio file
        min_speakers: Minimum number of speakers
        max_speakers: Maximum number of speakers

    Returns:
        Dictionary with segments, total_duration, and num_speakers
    """
    manager = DiarizationManager()
    try:
        segments = manager.diarize(audio_file, min_speakers, max_speakers)
        return {
            "segments": [seg.to_dict() for seg in segments],
            "total_duration": max([seg.end for seg in segments]) if segments else 0,
            "num_speakers": len(set(seg.speaker for seg in segments)) if segments else 0,
        }
    finally:
        manager.unload_pipeline()


__all__ = [
    # Core diarization
    "DiarizationManager",
    "DiarizationSegment",
    "quick_diarize",
    # Service
    "DiarizationService",
    "get_diarization",
    # Combiner
    "TranscriptionCombiner",
    "TranscriptionSegment",
    "SpeakerTranscriptionSegment",
    "export_to_json",
    "export_to_srt",
    "export_to_text",
    # Utilities
    "format_timestamp",
    "merge_consecutive_segments",
    "safe_print",
    "segments_to_json",
    "segments_to_rttm",
    "segments_to_text",
    "validate_audio_file",
]
