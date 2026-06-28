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


# --- factory.py ------------------------------------------------------------


class TestSenseVoiceFactory:
    @pytest.mark.parametrize(
        "model_name",
        [
            "iic/SenseVoiceSmall",
            "FunAudioLLM/SenseVoiceSmall",
            "iic/SenseVoice-extra",
            "IIC/SENSEVOICESMALL",  # case-insensitive
        ],
    )
    def test_sensevoice_models_detected(self, model_name: str) -> None:
        from server.core.stt.backends.factory import detect_backend_type, is_sensevoice_model

        assert detect_backend_type(model_name) == "sensevoice"
        assert is_sensevoice_model(model_name) is True

    def test_non_sensevoice_unaffected(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type, is_sensevoice_model

        assert detect_backend_type("Systran/faster-whisper-large-v3") == "whisper"
        assert detect_backend_type("nvidia/parakeet-tdt-0.6b-v3") == "parakeet"
        # Bilateral coverage: the public helper agrees on the negative case too.
        assert is_sensevoice_model("Systran/faster-whisper-large-v3") is False


# --- bootstrap model-name helpers -----------------------------------------


class TestBootstrapSelection:
    def _bootstrap(self):
        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "docker" / "bootstrap_runtime.py"
        spec = importlib.util.spec_from_file_location("bootstrap_runtime_under_test", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_sensevoice_recognised_and_not_whisper(self) -> None:
        bootstrap = self._bootstrap()
        assert bootstrap.is_sensevoice_model_name("iic/SenseVoiceSmall") is True
        # Must NOT be misclassified as a whisper model (else funasr never installs).
        assert bootstrap.is_whisper_model_name("iic/SenseVoiceSmall") is False
        # Real whisper ids still classify as whisper.
        assert bootstrap.is_whisper_model_name("Systran/faster-whisper-large-v3") is True
        assert bootstrap.is_sensevoice_model_name("nvidia/parakeet-tdt-0.6b-v3") is False


# --- model_manager feature status -----------------------------------------


class TestSenseVoiceFeatureStatus:
    def test_reads_sensevoice_from_bootstrap_status(self, tmp_path, monkeypatch) -> None:
        import json

        status = {"features": {"sensevoice": {"available": True, "reason": "ready"}}}
        status_file = tmp_path / "bootstrap-status.json"
        status_file.write_text(json.dumps(status), encoding="utf-8")
        monkeypatch.setenv("BOOTSTRAP_STATUS_FILE", str(status_file))

        from server.core.model_manager import ModelManager

        mgr = object.__new__(ModelManager)
        mgr._sensevoice_feature_available = False
        mgr._sensevoice_feature_reason = "not_requested"
        mgr._initialize_sensevoice_feature_status()

        assert mgr.get_sensevoice_feature_status() == {"available": True, "reason": "ready"}
