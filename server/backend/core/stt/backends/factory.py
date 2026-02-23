"""Backend detection and factory for STT backends."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.core.stt.backends.base import STTBackend

_PARAKEET_PATTERN = re.compile(r"^nvidia/(parakeet|nemotron-speech)", re.IGNORECASE)


def detect_backend_type(model_name: str) -> str:
    """Return ``"parakeet"`` or ``"whisper"`` based on the model name."""
    if _PARAKEET_PATTERN.match(model_name.strip()):
        return "parakeet"
    return "whisper"


def is_parakeet_model(model_name: str) -> bool:
    """Return True if *model_name* is an NVIDIA Parakeet / NeMo model."""
    return detect_backend_type(model_name) == "parakeet"


def create_backend(model_name: str) -> STTBackend:
    """Instantiate the appropriate STTBackend for *model_name*."""
    backend_type = detect_backend_type(model_name)
    if backend_type == "parakeet":
        from server.core.stt.backends.parakeet_backend import ParakeetBackend

        return ParakeetBackend()

    from server.core.stt.backends.whisper_backend import WhisperBackend

    return WhisperBackend()
