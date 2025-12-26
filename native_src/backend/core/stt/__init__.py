"""
Speech-to-text (STT) engine module for real-time transcription.

This package provides real-time audio-to-text transcription capabilities
ported from the MAIN folder's sophisticated STT engine, adapted for
server-side use without local microphone dependencies.

Key components:
- AudioToTextRecorder: Core transcription engine with VAD
- VAD utilities: Silero and WebRTC voice activity detection

Configuration for the STT engine is loaded from config.yaml via
the server.config module. See the 'stt', 'main_transcriber', and
'preview_transcriber' sections in config.yaml.
"""

# Mathematical constant for 16-bit audio normalization (not configurable)
INT16_MAX_ABS_VALUE = 32768.0

# Target sample rate for Whisper/Silero (technical requirement, not configurable)
SAMPLE_RATE = 16000

__all__ = [
    "INT16_MAX_ABS_VALUE",
    "SAMPLE_RATE",
]
