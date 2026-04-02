"""Tests for STT backend factory detection."""

import sys

from server.core.stt.backends.factory import (
    detect_backend_type,
    is_canary_model,
    is_mlx_model,
    is_nemo_model,
    is_parakeet_model,
    is_vibevoice_asr_model,
)


def test_detects_vibevoice_asr_backend() -> None:
    assert detect_backend_type("microsoft/VibeVoice-ASR") == "vibevoice_asr"
    assert is_vibevoice_asr_model("microsoft/VibeVoice-ASR")
    assert detect_backend_type("scerz/VibeVoice-ASR-4bit") == "vibevoice_asr"
    assert is_vibevoice_asr_model("scerz/VibeVoice-ASR-4bit")


def test_existing_backend_detection_unchanged() -> None:
    assert detect_backend_type("Systran/faster-whisper-large-v3") == "whisper"
    assert detect_backend_type("nvidia/parakeet-tdt-0.6b-v3") == "parakeet"
    assert detect_backend_type("nvidia/canary-1b-v2") == "canary"
    assert is_parakeet_model("nvidia/parakeet-tdt-0.6b-v3")
    assert is_canary_model("nvidia/canary-1b-v2")
    assert is_nemo_model("nvidia/parakeet-tdt-0.6b-v3")
    assert is_nemo_model("nvidia/canary-1b-v2")


# ---------------------------------------------------------------------------
# New mlx-audio Whisper model IDs (asr-fp16 naming scheme)
# ---------------------------------------------------------------------------


def test_detects_mlx_whisper_turbo_asr_fp16() -> None:
    """New mlx-audio Whisper Turbo model IDs route to mlx_whisper backend."""
    assert detect_backend_type("mlx-community/whisper-large-v3-turbo-asr-fp16") == "mlx_whisper"
    assert detect_backend_type("mlx-community/whisper-large-v3-turbo-asr-8bit") == "mlx_whisper"
    assert detect_backend_type("mlx-community/whisper-large-v3-turbo-asr-4bit") == "mlx_whisper"


def test_detects_mlx_whisper_large_v3_asr_fp16() -> None:
    assert detect_backend_type("mlx-community/whisper-large-v3-asr-fp16") == "mlx_whisper"
    assert detect_backend_type("mlx-community/whisper-large-v3-asr-8bit") == "mlx_whisper"
    assert detect_backend_type("mlx-community/whisper-large-v3-asr-4bit") == "mlx_whisper"


def test_detects_mlx_whisper_small_and_tiny_asr() -> None:
    assert detect_backend_type("mlx-community/whisper-small-asr-fp16") == "mlx_whisper"
    assert detect_backend_type("mlx-community/whisper-tiny-asr-fp16") == "mlx_whisper"


def test_is_mlx_model_includes_new_whisper_ids() -> None:
    assert is_mlx_model("mlx-community/whisper-large-v3-turbo-asr-fp16")
    assert is_mlx_model("mlx-community/whisper-small-asr-fp16")
    assert is_mlx_model("mlx-community/whisper-tiny-asr-fp16")


def test_is_mlx_model_includes_vibevoice() -> None:
    assert is_mlx_model("mlx-community/VibeVoice-ASR-bf16")
    assert is_mlx_model("mlx-community/VibeVoice-ASR-4bit")
    assert is_mlx_model("mlx-community/VibeVoice-ASR-8bit")


def test_is_mlx_model_excludes_non_mlx() -> None:
    assert not is_mlx_model("Systran/faster-whisper-large-v3")
    assert not is_mlx_model("microsoft/VibeVoice-ASR")
    assert not is_mlx_model("nvidia/parakeet-tdt-0.6b-v3")


# ---------------------------------------------------------------------------
# Factory whisperx fallback → FasterWhisperBackend
# ---------------------------------------------------------------------------


def test_create_backend_falls_back_to_faster_whisper_when_whisperx_absent() -> None:
    """When whisperx is not importable, create_backend() returns FasterWhisperBackend."""
    from server.core.stt.backends.factory import create_backend
    from server.core.stt.backends.faster_whisper_backend import FasterWhisperBackend

    saved = sys.modules.get("whisperx", ...)
    sys.modules["whisperx"] = None  # type: ignore[assignment]
    try:
        backend = create_backend("Systran/faster-whisper-large-v3")
        assert isinstance(backend, FasterWhisperBackend)
    finally:
        if saved is ...:
            sys.modules.pop("whisperx", None)
        else:
            sys.modules["whisperx"] = saved  # type: ignore[assignment]
