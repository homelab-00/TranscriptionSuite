"""
Diarization service for the transcription suite.

This module provides a bridge to call the separate diarization module
(which runs in its own venv due to dependency conflicts) and handles
the combining of transcription + diarization results.
"""

from .service import DiarizationService, get_diarization
from .combiner import (
    TranscriptionCombiner,
    TranscriptionSegment,
    SpeakerTranscriptionSegment,
    export_to_json,
    export_to_srt,
    export_to_text,
)

__all__ = [
    "DiarizationService",
    "get_diarization",
    "TranscriptionCombiner",
    "TranscriptionSegment",
    "SpeakerTranscriptionSegment",
    "export_to_json",
    "export_to_srt",
    "export_to_text",
]
