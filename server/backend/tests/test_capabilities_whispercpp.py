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


@pytest.mark.parametrize(
    "model_name",
    [
        "ggml-large-v3.bin",
        "ggml-base.en.bin",
        "large-v3.gguf",
        "/models/ggml-medium.bin",
    ],
)
class TestGgmlTranslationSupport:
    def test_supports_translation(self, model_name: str):
        # GGML names without ".en" or "turbo" in them should support translation
        if ".en" not in model_name and "turbo" not in model_name:
            assert supports_english_translation(model_name) is True

    def test_validate_allows_english_target(self, model_name: str):
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
# GGML turbo model — no translation (matches "turbo" guard)
# ---------------------------------------------------------------------------


def test_ggml_turbo_no_translation():
    assert supports_english_translation("ggml-large-v3-turbo.bin") is False


# ---------------------------------------------------------------------------
# Existing backends are not affected
# ---------------------------------------------------------------------------


def test_nvidia_parakeet_still_no_translation():
    assert supports_english_translation("nvidia/parakeet-ctc-1.1b") is False


def test_nvidia_canary_still_translates():
    assert supports_english_translation("nvidia/canary-1b") is True
