"""Backend detection and factory for STT backends."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.core.stt.backends.base import STTBackend

_PARAKEET_PATTERN = re.compile(r"^nvidia/(parakeet|nemotron-speech)", re.IGNORECASE)
_CANARY_PATTERN = re.compile(r"^nvidia/canary", re.IGNORECASE)
_VIBEVOICE_ASR_PATTERN = re.compile(r"^[^/]+/vibevoice-asr(?:-[^/]+)?$", re.IGNORECASE)
# whisper.cpp / GGML models: match only the BASENAME so a crafted
# ``../ggml-evil.bin`` or ``models/subdir/ggml-fake.bin`` cannot force
# whisper.cpp routing via ``re.search``. The old ``search()`` pattern
# allowed any substring match, which silently re-routed whisper-family
# repos whose path happened to contain ``/ggml-*.bin`` or ``.gguf``.
_WHISPERCPP_BASENAME_RE = re.compile(r"^ggml-[^/]+\.bin$|^[^/]+\.gguf$", re.IGNORECASE)
# MLX Parakeet and MLX Canary must be checked before the general mlx-community prefix.
_MLX_PARAKEET_PATTERN = re.compile(r"^mlx-community/parakeet", re.IGNORECASE)
# Matches community Canary MLX ports: eelcor/canary-1b-v2-mlx, Mediform/canary-1b-v2-mlx-q8, qfuxa/canary-mlx, etc.
_MLX_CANARY_PATTERN = re.compile(r"^[^/]+/canary[^/]*-mlx", re.IGNORECASE)
# MLX VibeVoice must be checked before the generic VibeVoice pattern.
_MLX_VIBEVOICE_PATTERN = re.compile(r"^mlx-community/vibevoice-asr", re.IGNORECASE)
_MLX_PATTERN = re.compile(r"^mlx-community/", re.IGNORECASE)


def _looks_like_whispercpp(name: str) -> bool:
    """Return True iff *name* resolves to a GGML file safe to route to the sidecar.

    Normalises separator (``\\`` → ``/``), rejects traversal segments, and
    only matches the final path component against the GGML basename regex.
    """
    # Normalise Windows-style path separators so a Windows-hosted cache path
    # like ``models\\ggml-tiny.bin`` routes the same as its POSIX twin.
    normalised = name.replace("\\", "/")
    parts = normalised.split("/")
    # Path traversal: ``..`` segments anywhere in the name are suspicious —
    # the sidecar's ``/models/`` root is read-only but a traversal still
    # lets a malicious caller reference unintended files inside the container.
    if any(p == ".." for p in parts):
        return False
    basename = parts[-1] if parts else normalised
    return bool(_WHISPERCPP_BASENAME_RE.match(basename))


def detect_backend_type(model_name: str) -> str:
    """Return backend type based on the model name."""
    name = model_name.strip()
    if _PARAKEET_PATTERN.match(name):
        return "parakeet"
    if _CANARY_PATTERN.match(name):
        return "canary"
    # MLX VibeVoice must be checked before the generic VibeVoice pattern.
    if _MLX_VIBEVOICE_PATTERN.match(name):
        return "mlx_vibevoice"
    if _VIBEVOICE_ASR_PATTERN.match(name):
        return "vibevoice_asr"
    if _looks_like_whispercpp(name):
        return "whispercpp"
    if _MLX_PARAKEET_PATTERN.match(name):
        return "mlx_parakeet"
    if _MLX_CANARY_PATTERN.match(name):
        return "mlx_canary"
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


def is_whispercpp_model(model_name: str) -> bool:
    """Return True if *model_name* is a GGML model for the whisper.cpp sidecar."""
    return detect_backend_type(model_name) == "whispercpp"


def is_mlx_model(model_name: str) -> bool:
    """Return True if *model_name* is an MLX Community model (Apple Silicon)."""
    return detect_backend_type(model_name) in (
        "mlx_whisper",
        "mlx_parakeet",
        "mlx_canary",
        "mlx_vibevoice",
    )


def is_mlx_parakeet_model(model_name: str) -> bool:
    """Return True if *model_name* is an MLX-accelerated Parakeet model."""
    return detect_backend_type(model_name) == "mlx_parakeet"


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

    if backend_type == "whispercpp":
        from server.core.stt.backends.whispercpp_backend import WhisperCppBackend

        return WhisperCppBackend()

    if backend_type == "mlx_parakeet":
        from server.core.stt.backends.mlx_parakeet_backend import MLXParakeetBackend

        return MLXParakeetBackend()

    if backend_type == "mlx_canary":
        from server.core.stt.backends.mlx_canary_backend import MLXCanaryBackend

        return MLXCanaryBackend()

    if backend_type == "mlx_vibevoice":
        from server.core.stt.backends.mlx_vibevoice_backend import MLXVibeVoiceBackend

        return MLXVibeVoiceBackend()

    if backend_type == "mlx_whisper":
        from server.core.stt.backends.mlx_whisper_backend import MLXWhisperBackend

        return MLXWhisperBackend()

    # Default: faster-whisper / WhisperX backend.
    # Prefer WhisperX (alignment + diarization support) when available;
    # fall back to lightweight FasterWhisperBackend when it isn't (e.g. MLX
    # bare-metal environments where the whisper extra is not installed).
    try:
        import importlib

        importlib.import_module("whisperx")
    except ImportError:
        from server.core.stt.backends.faster_whisper_backend import FasterWhisperBackend

        return FasterWhisperBackend()

    from server.core.stt.backends.whisperx_backend import WhisperXBackend

    return WhisperXBackend()
