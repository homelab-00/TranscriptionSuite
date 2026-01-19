"""
Speech-to-text (STT) engine module for transcription.

This package provides the unified transcription engine for TranscriptionSuite,
supporting both real-time streaming (with VAD) and file-based transcription.

Key components:
- AudioToTextRecorder: Unified transcription engine with VAD and file support
- TranscriptionResult: Standard result format for all transcription operations
- VAD utilities: Silero and WebRTC voice activity detection

Configuration for the STT engine is loaded from config.yaml via
the server.config module. See the 'stt', 'main_transcriber', and
'live_transcriber' sections in config.yaml.
"""

from server.core.stt.engine import AudioToTextRecorder, TranscriptionResult

# Mathematical constant for 16-bit audio normalization (not configurable)
INT16_MAX_ABS_VALUE = 32768.0

# Target sample rate for Whisper/Silero (technical requirement, not configurable)
SAMPLE_RATE = 16000

__all__ = [
    "AudioToTextRecorder",
    "TranscriptionResult",
    "INT16_MAX_ABS_VALUE",
    "SAMPLE_RATE",
]
