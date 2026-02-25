"""STT backend abstraction layer.

Provides a unified interface for different speech-to-text engines
(e.g. faster-whisper, NVIDIA Parakeet/NeMo, NVIDIA Canary/NeMo).
"""

from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    DiarizedTranscriptionResult,
    STTBackend,
)
from server.core.stt.backends.factory import (
    create_backend,
    detect_backend_type,
    is_canary_model,
    is_nemo_model,
    is_parakeet_model,
)

__all__ = [
    "BackendSegment",
    "BackendTranscriptionInfo",
    "DiarizedTranscriptionResult",
    "STTBackend",
    "create_backend",
    "detect_backend_type",
    "is_canary_model",
    "is_nemo_model",
    "is_parakeet_model",
]
