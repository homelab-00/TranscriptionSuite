"""Backend detection and factory for STT backends."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.core.stt.backends.base import STTBackend

_PARAKEET_PATTERN = re.compile(r"^nvidia/(parakeet|nemotron-speech)", re.IGNORECASE)
_CANARY_PATTERN = re.compile(r"^nvidia/canary", re.IGNORECASE)
_VIBEVOICE_ASR_PATTERN = re.compile(r"^[^/]+/vibevoice-asr(?:-[^/]+)?$", re.IGNORECASE)
_MLX_PATTERN = re.compile(r"^mlx-community/", re.IGNORECASE)


def detect_backend_type(model_name: str) -> str:
    """Return backend type based on the model name."""
    name = model_name.strip()
    if _PARAKEET_PATTERN.match(name):
        return "parakeet"
    if _CANARY_PATTERN.match(name):
        return "canary"
    if _VIBEVOICE_ASR_PATTERN.match(name):
        return "vibevoice_asr"
    if _MLX_PATTERN.match(name):
        return "mlx_whisper"
    return "whisper"


def is_parakeet_model(model_name: str) -> bool:
    """Return True if *model_name* is an NVIDIA Parakeet / NeMo ASR-only model."""
    return detect_backend_type(model_name) == "parakeet"


def is_canary_model(model_name: str) -> bool:
    """Return True if *model_name* is an NVIDIA Canary multitask model."""
    return detect_backend_type(model_name) == "canary"


def is_nemo_model(model_name: str) -> bool:
    """Return True if *model_name* is any NVIDIA NeMo model (Parakeet or Canary)."""
    return detect_backend_type(model_name) in ("parakeet", "canary")


def is_vibevoice_asr_model(model_name: str) -> bool:
    """Return True if *model_name* selects a VibeVoice-ASR backend variant."""
    return detect_backend_type(model_name) == "vibevoice_asr"


def create_backend(model_name: str) -> STTBackend:
    """Instantiate the appropriate STTBackend for *model_name*."""
    backend_type = detect_backend_type(model_name)
    if backend_type == "parakeet":
        from server.core.stt.backends.parakeet_backend import ParakeetBackend

        return ParakeetBackend()

    if backend_type == "canary":
        from server.core.stt.backends.canary_backend import CanaryBackend

        return CanaryBackend()

    if backend_type == "vibevoice_asr":
        from server.core.stt.backends.vibevoice_asr_backend import VibeVoiceASRBackend

        return VibeVoiceASRBackend()

    if backend_type == "mlx_whisper":
        from server.core.stt.backends.mlx_whisper_backend import MLXWhisperBackend

        return MLXWhisperBackend()

    from server.core.stt.backends.whisperx_backend import WhisperXBackend

    return WhisperXBackend()
