"""
Core transcription and AI components.

This module contains:
- stt: Unified transcription engine (AudioToTextRecorder) for streaming and file-based
- diarization_engine: PyAnnote speaker diarization
- model_manager: AI model lifecycle management
- realtime_engine: Real-time transcription with VAD
- client_detector: Client type detection (standalone vs web)
- audio_utils: Audio processing utilities
"""


# Lazy imports to avoid circular dependencies
def __getattr__(name: str):
    if name == "AudioToTextRecorder":
        from server.core.stt.engine import AudioToTextRecorder

        return AudioToTextRecorder
    elif name == "TranscriptionResult":
        from server.core.stt.engine import TranscriptionResult

        return TranscriptionResult
    elif name == "ModelManager":
        from server.core.model_manager import ModelManager

        return ModelManager
    elif name == "DiarizationEngine":
        from server.core.diarization_engine import DiarizationEngine

        return DiarizationEngine
    elif name == "RealtimeTranscriptionEngine":
        from server.core.realtime_engine import RealtimeTranscriptionEngine

        return RealtimeTranscriptionEngine
    elif name == "ClientType":
        from server.core.client_detector import ClientType

        return ClientType
    elif name == "ClientDetector":
        from server.core.client_detector import ClientDetector

        return ClientDetector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AudioToTextRecorder",
    "TranscriptionResult",  # lgtm [py/undefined-export]
    "ModelManager",  # lgtm [py/undefined-export]
    "DiarizationEngine",  # lgtm [py/undefined-export]
    "RealtimeTranscriptionEngine",  # lgtm [py/undefined-export]
    "ClientType",
    "ClientDetector",
]
