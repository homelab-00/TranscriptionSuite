"""Tests for GGML model capabilities — translation support validation."""

from __future__ import annotations

import pytest
from server.core.stt.capabilities import (
    supports_english_translation,
    validate_translation_request,
)

# ---------------------------------------------------------------------------
# GGML models fall through to default Whisper path
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GGML models: which support translation and which don't.
#
# The previous version of this file used a parametrized class with an
# ``if ".en" not in model_name and "turbo" not in model_name:`` guard inside
# the test body — for .en / turbo cases the test asserted *nothing*, which
# silently passed any mutation affecting those models. Explicit positive and
# negative cases below close that gap.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_name",
    [
        "ggml-large-v3.bin",
        "large-v3.gguf",
        "/models/ggml-medium.bin",
    ],
)
def test_ggml_multilingual_supports_translation(model_name: str):
    assert supports_english_translation(model_name) is True


@pytest.mark.parametrize(
    "model_name",
    [
        "ggml-base.en.bin",  # English-only variant
        "ggml-large-v3-turbo.bin",  # turbo variant
        "ggml-large-v3-turbo-q8_0.bin",  # turbo quantised
        "ggml-tiny.en.bin",
    ],
)
def test_ggml_en_or_turbo_does_not_support_translation(model_name: str):
    assert supports_english_translation(model_name) is False


@pytest.mark.parametrize(
    "model_name",
    [
        "ggml-large-v3.bin",
        "large-v3.gguf",
        "/models/ggml-medium.bin",
    ],
)
def test_validate_allows_english_target_for_multilingual(model_name: str):
    result = validate_translation_request(
        model_name=model_name,
        task="translate",
        translation_target_language="en",
    )
    assert result == "en"


# ---------------------------------------------------------------------------
# GGML models reject non-English translation targets
# ---------------------------------------------------------------------------


def test_ggml_rejects_non_english_target():
    with pytest.raises(ValueError, match="must be 'en'"):
        validate_translation_request(
            model_name="ggml-large-v3.bin",
            task="translate",
            translation_target_language="fr",
        )


# ---------------------------------------------------------------------------
# Existing backends are not affected
# ---------------------------------------------------------------------------


def test_nvidia_parakeet_still_no_translation():
    assert supports_english_translation("nvidia/parakeet-ctc-1.1b") is False


def test_nvidia_canary_still_translates():
    assert supports_english_translation("nvidia/canary-1b") is True
