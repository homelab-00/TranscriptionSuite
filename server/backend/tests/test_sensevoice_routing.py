"""Routing + capability tests for the SenseVoice (FunASR) backend."""

from __future__ import annotations

import pytest

# --- capabilities.py -------------------------------------------------------


class TestSenseVoiceCapabilities:
    def test_sensevoice_has_no_translation(self) -> None:
        from server.core.stt.capabilities import supports_english_translation

        assert supports_english_translation("iic/SenseVoiceSmall") is False
        assert supports_english_translation("FunAudioLLM/SenseVoiceSmall") is False
        # Regression guard: the new pattern must not affect non-SenseVoice ids.
        assert supports_english_translation("Systran/faster-whisper-large-v3") is True

    def test_sensevoice_supports_auto_detect(self) -> None:
        from server.core.stt.capabilities import supports_auto_detect

        assert supports_auto_detect("iic/SenseVoiceSmall") is True

    def test_sensevoice_translate_request_rejected(self) -> None:
        from server.core.stt.capabilities import validate_translation_request

        with pytest.raises(ValueError, match="does not support translation"):
            validate_translation_request(
                model_name="iic/SenseVoiceSmall",
                task="translate",
                translation_target_language="en",
            )
