"""Tests for translation capability guards."""

import pytest
from server.core.stt.capabilities import (
    supports_auto_detect,
    supports_english_translation,
    validate_translation_request,
)


def test_supports_translation_for_multilingual_model() -> None:
    assert supports_english_translation("Systran/faster-whisper-large-v3")


@pytest.mark.parametrize(
    "model_name",
    [
        "Systran/faster-whisper-small.en",
        "Systran/faster-whisper-medium.en",
        "deepdml/faster-whisper-large-v3-turbo-ct2",
        "microsoft/VibeVoice-ASR",
        "scerz/VibeVoice-ASR-4bit",
    ],
)
def test_rejects_known_unsupported_models(model_name: str) -> None:
    assert not supports_english_translation(model_name)


def test_validate_translation_rejects_non_english_target() -> None:
    with pytest.raises(ValueError, match="must be 'en'"):
        validate_translation_request(
            model_name="Systran/faster-whisper-large-v3",
            task="translate",
            translation_target_language="el",
        )


def test_validate_translation_rejects_unsupported_model() -> None:
    with pytest.raises(ValueError, match="does not support translation"):
        validate_translation_request(
            model_name="Systran/faster-whisper-small.en",
            task="translate",
            translation_target_language="en",
        )


def test_non_translate_task_is_noop_validation() -> None:
    assert (
        validate_translation_request(
            model_name="Systran/faster-whisper-small.en",
            task="transcribe",
            translation_target_language="el",
        )
        == "en"
    )


@pytest.mark.parametrize(
    "model_name",
    [
        "Systran/faster-whisper-large-v3",
        "nvidia/parakeet-tdt-0.6b-v3",
        "mlx-community/parakeet-tdt-0.6b-v3",
        "microsoft/VibeVoice-ASR",
        "Systran/faster-whisper-small.en",
        None,
        "",
    ],
)
def test_auto_detect_supported(model_name: str | None) -> None:
    """Whisper, Parakeet (NVIDIA + MLX), VibeVoice, and unknown models auto-detect."""
    assert supports_auto_detect(model_name)


@pytest.mark.parametrize(
    "model_name",
    [
        "nvidia/canary-1b-v2",
        "nvidia/canary-180m-flash",
        "eelcor/canary-1b-v2-mlx",
        "Mediform/canary-1b-v2-mlx-q8",
    ],
)
def test_auto_detect_unsupported_for_canary(model_name: str) -> None:
    """Canary (NVIDIA + MLX ports) requires an explicit source language."""
    assert not supports_auto_detect(model_name)


def test_canary_backend_rejects_missing_language() -> None:
    """Regression for gh-81: Canary must not silently default language to 'en'."""
    import numpy as np
    from server.core.stt.backends.canary_backend import CanaryBackend

    backend = CanaryBackend.__new__(CanaryBackend)
    # Bypass heavy __init__; set only what transcribe() touches before raising.
    backend._model = object()  # type: ignore[attr-defined]

    with pytest.raises(ValueError, match="explicit source language"):
        backend.transcribe(
            np.zeros(16000, dtype=np.float32),
            language=None,
            task="transcribe",
        )
