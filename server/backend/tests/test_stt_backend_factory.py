"""Tests for STT backend factory detection."""

from server.core.stt.backends.factory import (
    detect_backend_type,
    is_canary_model,
    is_nemo_model,
    is_parakeet_model,
    is_vibevoice_asr_model,
)


def test_detects_vibevoice_asr_backend() -> None:
    assert detect_backend_type("microsoft/VibeVoice-ASR") == "vibevoice_asr"
    assert is_vibevoice_asr_model("microsoft/VibeVoice-ASR")


def test_existing_backend_detection_unchanged() -> None:
    assert detect_backend_type("Systran/faster-whisper-large-v3") == "whisper"
    assert detect_backend_type("nvidia/parakeet-tdt-0.6b-v3") == "parakeet"
    assert detect_backend_type("nvidia/canary-1b-v2") == "canary"
    assert is_parakeet_model("nvidia/parakeet-tdt-0.6b-v3")
    assert is_canary_model("nvidia/canary-1b-v2")
    assert is_nemo_model("nvidia/parakeet-tdt-0.6b-v3")
    assert is_nemo_model("nvidia/canary-1b-v2")
