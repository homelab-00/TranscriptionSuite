"""
Diarization module for speaker identification in audio files.

This module provides speaker diarization using PyAnnote. It performs
DIARIZATION ONLY - combining with transcription is handled by the
calling code in _core.

Usage from _core:
    # Option 1: Via subprocess (separate venv)
    result = subprocess.run([
        "_module-diarization/.venv/bin/python",
        "-m", "DIARIZATION.diarize_audio",
        "audio.wav", "--format", "json"
    ], capture_output=True, text=True)
    diarization = json.loads(result.stdout)

    # Option 2: Via the diarization_service module in _core
    from diarization_service import get_diarization
    segments = get_diarization("audio.wav")
"""

from .api import DiarizationAPI, quick_diarize
from .diarization_manager import DiarizationManager
from .diarize_audio import diarize_audio, get_diarization_segments
from .utils import DiarizationSegment

__version__ = "1.0.0"

__all__ = [
    "diarize_audio",
    "get_diarization_segments",
    "quick_diarize",
    "DiarizationAPI",
    "DiarizationManager",
    "DiarizationSegment",
]
