"""
Speech-to-text (STT) engine module for real-time transcription.

This package provides real-time audio-to-text transcription capabilities
ported from the MAIN folder's sophisticated STT engine, adapted for
server-side use without local microphone dependencies.

Key components:
- AudioToTextRecorder: Core transcription engine with VAD
- VAD utilities: Silero and WebRTC voice activity detection
- TranscriptionWorker: Subprocess-based model isolation
"""

from server.core.stt.constants import (
    SAMPLE_RATE,
    BUFFER_SIZE,
    DEFAULT_MODEL,
    DEFAULT_PREVIEW_MODEL,
    DEFAULT_SILERO_SENSITIVITY,
    DEFAULT_WEBRTC_SENSITIVITY,
    DEFAULT_POST_SPEECH_SILENCE_DURATION,
    DEFAULT_MIN_LENGTH_OF_RECORDING,
    DEFAULT_PRE_RECORDING_BUFFER_DURATION,
    MAX_SILENCE_DURATION,
    INT16_MAX_ABS_VALUE,
)

__all__ = [
    "SAMPLE_RATE",
    "BUFFER_SIZE",
    "DEFAULT_MODEL",
    "DEFAULT_PREVIEW_MODEL",
    "DEFAULT_SILERO_SENSITIVITY",
    "DEFAULT_WEBRTC_SENSITIVITY",
    "DEFAULT_POST_SPEECH_SILENCE_DURATION",
    "DEFAULT_MIN_LENGTH_OF_RECORDING",
    "DEFAULT_PRE_RECORDING_BUFFER_DURATION",
    "MAX_SILENCE_DURATION",
    "INT16_MAX_ABS_VALUE",
]
