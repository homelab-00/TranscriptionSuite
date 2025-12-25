"""
Core transcription and AI components.

This module contains:
- transcription_engine: Unified Whisper transcription (file-based)
- diarization_engine: PyAnnote speaker diarization
- model_manager: AI model lifecycle management
- realtime_engine: Real-time transcription with VAD
- preview_engine: Preview transcription for standalone clients
- client_detector: Client type detection (standalone vs web)
- audio_utils: Audio processing utilities
- stt: Server-side speech-to-text engine
"""


# Lazy imports to avoid circular dependencies
def __getattr__(name: str):
    if name == "TranscriptionEngine":
        from server.core.transcription_engine import TranscriptionEngine

        return TranscriptionEngine
    elif name == "ModelManager":
        from server.core.model_manager import ModelManager

        return ModelManager
    elif name == "DiarizationEngine":
        from server.core.diarization_engine import DiarizationEngine

        return DiarizationEngine
    elif name == "RealtimeTranscriptionEngine":
        from server.core.realtime_engine import RealtimeTranscriptionEngine

        return RealtimeTranscriptionEngine
    elif name == "PreviewTranscriptionEngine":
        from server.core.preview_engine import PreviewTranscriptionEngine

        return PreviewTranscriptionEngine
    elif name == "ClientType":
        from server.core.client_detector import ClientType

        return ClientType
    elif name == "ClientDetector":
        from server.core.client_detector import ClientDetector

        return ClientDetector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "TranscriptionEngine",
    "ModelManager",
    "DiarizationEngine",
    "RealtimeTranscriptionEngine",
    "PreviewTranscriptionEngine",
    "ClientType",
    "ClientDetector",
]
