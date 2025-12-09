"""
Canary transcription module using NeMo Canary-1B-v2.

This module provides high-quality multilingual transcription using NVIDIA's
NeMo Canary model. Now integrated directly (Python 3.11)!

Usage:
    from CANARY import CanaryTranscriber, transcribe_file

    # Quick transcription
    result = transcribe_file("audio.wav", language="el")

    # Or use the transcriber for more control
    transcriber = CanaryTranscriber()
    transcriber.load_model()
    result = transcriber.transcribe("audio.wav", language="el")

    # Or use the service for persistent model loading
    from CANARY import CanaryService, transcribe_audio
    result = transcribe_audio("audio.wav", language="el")
"""

from .canary_transcriber import (
    CanaryTranscriber,
    TranscriptionResult,
    WordTimestamp,
    get_transcriber,
)
from .service import (
    CanaryService,
    CanaryTranscriptionResult,
    transcribe_audio,
    get_server_status,
    shutdown_server,
    get_service,
)

__version__ = "2.0.0"


def transcribe_file(
    audio_path: str,
    language: str = "en",
    pnc: bool = True,
) -> TranscriptionResult:
    """
    Quick transcription function for simple use cases.

    Args:
        audio_path: Path to the audio file
        language: Language code (e.g., "el" for Greek, "en" for English)
        pnc: Include punctuation and capitalization

    Returns:
        TranscriptionResult with text and word timestamps
    """
    transcriber = get_transcriber()
    if not transcriber.is_loaded:
        transcriber.load_model()
    return transcriber.transcribe(audio_path, language=language, pnc=pnc)


__all__ = [
    # Core transcriber
    "CanaryTranscriber",
    "TranscriptionResult",
    "WordTimestamp",
    "get_transcriber",
    "transcribe_file",
    # Service (persistent model)
    "CanaryService",
    "CanaryTranscriptionResult",
    "transcribe_audio",
    "get_server_status",
    "shutdown_server",
    "get_service",
]
