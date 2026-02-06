"""Tests for translation capability guards."""

import pytest

from server.core.stt.capabilities import (
    supports_english_translation,
    validate_translation_request,
)


def test_supports_translation_for_multilingual_model() -> None:
    assert supports_english_translation("Systran/faster-whisper-large-v3")


@pytest.mark.parametrize(
    "model_name",
    [
        "openai/whisper-small.en",
        "openai/whisper-large-v3-turbo",
        "distil-whisper/distil-large-v3",
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
            model_name="openai/whisper-small.en",
            task="translate",
            translation_target_language="en",
        )


def test_non_translate_task_is_noop_validation() -> None:
    assert (
        validate_translation_request(
            model_name="openai/whisper-small.en",
            task="transcribe",
            translation_target_language="el",
        )
        == "en"
    )
