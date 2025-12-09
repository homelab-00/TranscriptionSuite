"""
Canary transcription service for the transcription suite.

This module provides a bridge to the persistent NeMo Canary server
(which runs in its own venv with Python 3.11 due to NeMo requirements).

The server keeps the Canary model loaded in memory for fast transcription.
Communication is via TCP socket on localhost.

Usage:
    from CANARY_SERVICE import CanaryService, transcribe_audio

    # Simple function call
    result = transcribe_audio("audio.wav", language="el")

    # Or use the service class for more control
    service = CanaryService()
    service.ensure_server_running()
    result = service.transcribe("audio.wav", language="el")
"""

from .service import (
    CanaryService,
    CanaryTranscriptionResult,
    transcribe_audio,
    get_server_status,
    shutdown_server,
)

__all__ = [
    "CanaryService",
    "CanaryTranscriptionResult",
    "transcribe_audio",
    "get_server_status",
    "shutdown_server",
]
