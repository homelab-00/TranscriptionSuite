"""STT backend abstraction layer.

Provides a unified interface for different speech-to-text engines
(e.g. faster-whisper, NVIDIA Parakeet/NeMo).
"""

from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    STTBackend,
)
from server.core.stt.backends.factory import (
    create_backend,
    detect_backend_type,
    is_parakeet_model,
)

__all__ = [
    "BackendSegment",
    "BackendTranscriptionInfo",
    "STTBackend",
    "create_backend",
    "detect_backend_type",
    "is_parakeet_model",
]
