"""
Diarization module for speaker identification in audio files.

This module provides speaker diarization using PyAnnote and can be
integrated with transcription systems for speaker-labeled transcripts.
"""

from .diarization_manager import DiarizationManager
from .diarize_audio import diarize_and_combine, diarize_audio
from .transcription_combiner import (
    SpeakerTranscriptionSegment,
    TranscriptionCombiner,
    TranscriptionSegment,
)
from .utils import DiarizationSegment

__version__ = "1.0.0"

__all__ = [
    "diarize_audio",
    "diarize_and_combine",
    "DiarizationManager",
    "TranscriptionCombiner",
    "TranscriptionSegment",
    "SpeakerTranscriptionSegment",
    "DiarizationSegment",
]
