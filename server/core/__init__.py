"""
Core transcription and AI components.

This module contains:
- transcription_engine: Unified Whisper transcription
- diarization_engine: PyAnnote speaker diarization
- model_manager: AI model lifecycle management
- audio_utils: Audio processing utilities
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
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["TranscriptionEngine", "ModelManager", "DiarizationEngine"]
