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

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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


def __getattr__(name: str) -> Any:
    """Lazily resolve heavy STT engine exports to avoid startup import cost."""
    if name in {"AudioToTextRecorder", "TranscriptionResult"}:
        from server.core.stt.engine import AudioToTextRecorder, TranscriptionResult

        exports = {
            "AudioToTextRecorder": AudioToTextRecorder,
            "TranscriptionResult": TranscriptionResult,
        }
        return exports[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
