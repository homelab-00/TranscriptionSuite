"""Tests for GGML model name routing to WhisperCppBackend."""

from __future__ import annotations

import pytest
from server.core.stt.backends.factory import (
    detect_backend_type,
    is_whispercpp_model,
)

# ---------------------------------------------------------------------------
# GGML models → "whispercpp"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_name",
    [
        "ggml-large-v3.bin",
        "ggml-base.en.bin",
        "ggml-medium.bin",
        "ggml-tiny.bin",
        "large-v3-turbo.gguf",
        "whisper-large-v3.gguf",
        "/models/ggml-small.bin",
        "GGML-LARGE-V3.BIN",  # case insensitive
    ],
)
def test_ggml_models_route_to_whispercpp(model_name: str):
    assert detect_backend_type(model_name) == "whispercpp"
    assert is_whispercpp_model(model_name) is True


# ---------------------------------------------------------------------------
# Non-GGML models are unaffected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_name,expected_type",
    [
        ("openai/whisper-large-v3", "whisper"),
        ("Systran/faster-whisper-large-v3", "whisper"),
        ("distil-whisper/distil-large-v3", "whisper"),
        ("nvidia/parakeet-ctc-1.1b", "parakeet"),
        ("nvidia/canary-1b", "canary"),
        ("nvidia/nemotron-speech-1b", "parakeet"),
        ("myorg/vibevoice-asr-large", "vibevoice_asr"),
    ],
)
def test_non_ggml_models_unaffected(model_name: str, expected_type: str):
    assert detect_backend_type(model_name) == expected_type
    assert is_whispercpp_model(model_name) is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_string_falls_through_to_whisper():
    assert detect_backend_type("") == "whisper"


def test_whitespace_only_falls_through_to_whisper():
    assert detect_backend_type("   ") == "whisper"
