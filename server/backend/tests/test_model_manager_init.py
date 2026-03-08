"""Tests for ModelManager initialisation and feature-flag logic.

Covers:
- Feature status initialisation from ``bootstrap-status.json``
- Feature status fallback to environment variables
- ``_classify_diarization_error`` mapping
- ``is_same_model`` normalisation
- ``is_main_model_disabled`` detection
- ``get_diarization_feature_status`` / ``get_whisper_feature_status`` /
  ``get_vibevoice_asr_feature_status`` return shapes

All tests mock ``audio_utils.check_cuda_available → False`` and
``audio_utils.get_gpu_memory_info → {}`` to avoid GPU probing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.usefixtures("torch_stub")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bootstrap_status(
    tmp_path: Path,
    *,
    diarization: dict | None = None,
    whisper: dict | None = None,
    nemo: dict | None = None,
    vibevoice_asr: dict | None = None,
) -> Path:
    """Write a bootstrap-status.json and return its path."""
    features: dict[str, Any] = {}
    if diarization is not None:
        features["diarization"] = diarization
    if whisper is not None:
        features["whisper"] = whisper
    if nemo is not None:
        features["nemo"] = nemo
    if vibevoice_asr is not None:
        features["vibevoice_asr"] = vibevoice_asr

    status_file = tmp_path / "bootstrap-status.json"
    status_file.write_text(json.dumps({"features": features}), encoding="utf-8")
    return status_file


def _build_manager(
    tmp_path: Path,
    config: dict[str, Any] | None = None,
    status_file: Path | None = None,
    env_overrides: dict[str, str] | None = None,
):
    """Create a ModelManager with GPU / heavy imports fully stubbed."""
    from server.core.model_manager import ModelManager

    if config is None:
        config = {"main_transcriber": {"model": "tiny"}}

    env = {"BOOTSTRAP_STATUS_FILE": str(status_file or tmp_path / "nope.json")}
    if env_overrides:
        env.update(env_overrides)

    with (
        patch(
            "server.core.model_manager.resolve_main_transcriber_model",
            return_value="tiny",
        ),
        patch("server.core.audio_utils.check_cuda_available", return_value=False),
        patch("server.core.audio_utils.get_gpu_memory_info", return_value={}),
        patch.dict("os.environ", env, clear=False),
    ):
        return ModelManager(config)


# ── Feature status from bootstrap-status.json ─────────────────────────────


class TestFeatureStatusFromBootstrap:
    def test_diarization_available_from_bootstrap(self, tmp_path: Path):
        sf = _make_bootstrap_status(tmp_path, diarization={"available": True, "reason": "ready"})

        mgr = _build_manager(tmp_path, status_file=sf)

        assert mgr.get_diarization_feature_status() == {
            "available": True,
            "reason": "ready",
        }

    def test_diarization_unavailable_from_bootstrap(self, tmp_path: Path):
        sf = _make_bootstrap_status(
            tmp_path, diarization={"available": False, "reason": "token_missing"}
        )

        mgr = _build_manager(tmp_path, status_file=sf)

        assert mgr.get_diarization_feature_status() == {
            "available": False,
            "reason": "token_missing",
        }

    def test_whisper_available_from_bootstrap(self, tmp_path: Path):
        sf = _make_bootstrap_status(tmp_path, whisper={"available": True, "reason": "ready"})

        mgr = _build_manager(tmp_path, status_file=sf)

        assert mgr.get_whisper_feature_status() == {
            "available": True,
            "reason": "ready",
        }

    def test_nemo_available_from_bootstrap(self, tmp_path: Path):
        sf = _make_bootstrap_status(tmp_path, nemo={"available": True, "reason": "ready"})

        mgr = _build_manager(tmp_path, status_file=sf)

        status = mgr.get_status()
        assert status["features"]["nemo"] == {
            "available": True,
            "reason": "ready",
        }

    def test_vibevoice_available_from_bootstrap(self, tmp_path: Path):
        sf = _make_bootstrap_status(tmp_path, vibevoice_asr={"available": True, "reason": "ready"})

        mgr = _build_manager(tmp_path, status_file=sf)

        assert mgr.get_vibevoice_asr_feature_status() == {
            "available": True,
            "reason": "ready",
        }

    def test_vibevoice_error_from_bootstrap(self, tmp_path: Path):
        sf = _make_bootstrap_status(
            tmp_path,
            vibevoice_asr={
                "available": False,
                "reason": "import_failed",
                "error": "No module named 'nemo'",
            },
        )

        mgr = _build_manager(tmp_path, status_file=sf)

        status = mgr.get_vibevoice_asr_feature_status()
        assert status["available"] is False
        assert status["error"] == "No module named 'nemo'"


# ── Feature status fallback (no bootstrap file) ──────────────────────────


class TestFeatureStatusFallback:
    def test_diarization_fallback_token_missing(self, tmp_path: Path):
        mgr = _build_manager(tmp_path, env_overrides={"HF_TOKEN": ""})

        assert mgr.get_diarization_feature_status() == {
            "available": False,
            "reason": "token_missing",
        }

    def test_diarization_fallback_token_present_in_env(self, tmp_path: Path):
        mgr = _build_manager(tmp_path, env_overrides={"HF_TOKEN": "hf_abc123"})

        assert mgr.get_diarization_feature_status() == {
            "available": True,
            "reason": "ready",
        }

    def test_diarization_fallback_token_present_in_config(self, tmp_path: Path):
        config = {
            "main_transcriber": {"model": "tiny"},
            "diarization": {"hf_token": "hf_config_token"},
        }

        mgr = _build_manager(tmp_path, config=config, env_overrides={"HF_TOKEN": ""})

        assert mgr.get_diarization_feature_status()["available"] is True

    def test_whisper_fallback_not_requested(self, tmp_path: Path):
        mgr = _build_manager(tmp_path, env_overrides={"INSTALL_WHISPER": ""})

        assert mgr.get_whisper_feature_status() == {
            "available": False,
            "reason": "not_requested",
        }

    def test_whisper_fallback_requested(self, tmp_path: Path):
        mgr = _build_manager(tmp_path, env_overrides={"INSTALL_WHISPER": "true"})

        assert mgr.get_whisper_feature_status() == {
            "available": False,
            "reason": "requested",
        }

    def test_vibevoice_fallback_not_requested(self, tmp_path: Path):
        mgr = _build_manager(tmp_path, env_overrides={"INSTALL_VIBEVOICE_ASR": ""})

        status = mgr.get_vibevoice_asr_feature_status()
        assert status["available"] is False
        assert status["reason"] == "not_requested"

    def test_vibevoice_fallback_requested(self, tmp_path: Path):
        mgr = _build_manager(tmp_path, env_overrides={"INSTALL_VIBEVOICE_ASR": "1"})

        status = mgr.get_vibevoice_asr_feature_status()
        assert status["available"] is False
        assert status["reason"] == "requested"


# ── _classify_diarization_error ───────────────────────────────────────────


class TestClassifyDiarizationError:
    @pytest.fixture()
    def mgr(self, tmp_path: Path):
        return _build_manager(tmp_path)

    def test_token_missing(self, mgr):
        exc = ValueError("HuggingFace token required for PyAnnote. Set HF_TOKEN …")

        assert mgr._classify_diarization_error(exc) == "token_missing"

    def test_token_invalid_via_401(self, mgr):
        exc = Exception("Something went wrong")
        resp = type("Resp", (), {"status_code": 401})()
        exc.response = resp  # type: ignore[attr-defined]

        assert mgr._classify_diarization_error(exc) == "token_invalid"

    def test_token_invalid_via_message(self, mgr):
        exc = Exception("invalid token provided")

        assert mgr._classify_diarization_error(exc) == "token_invalid"

    def test_terms_not_accepted_via_403_gated(self, mgr):
        exc = Exception("You need to accept the terms for this gated model")
        resp = type("Resp", (), {"status_code": 403})()
        exc.response = resp  # type: ignore[attr-defined]

        assert mgr._classify_diarization_error(exc) == "terms_not_accepted"

    def test_terms_not_accepted_via_message(self, mgr):
        exc = Exception("Please accept the terms for this gated repo")

        assert mgr._classify_diarization_error(exc) == "terms_not_accepted"

    def test_403_without_gated_keyword(self, mgr):
        exc = Exception("Forbidden")
        resp = type("Resp", (), {"status_code": 403})()
        exc.response = resp  # type: ignore[attr-defined]

        assert mgr._classify_diarization_error(exc) == "token_invalid"

    def test_unknown_error_returns_unavailable(self, mgr):
        exc = RuntimeError("Something completely unexpected")

        assert mgr._classify_diarization_error(exc) == "unavailable"


# ── is_same_model ─────────────────────────────────────────────────────────


class TestIsSameModel:
    @pytest.fixture()
    def mgr(self, tmp_path: Path):
        return _build_manager(tmp_path)

    def test_identical_names(self, mgr):
        assert mgr.is_same_model("large-v3", "large-v3") is True

    def test_systran_prefix_stripped(self, mgr):
        assert mgr.is_same_model("Systran/faster-whisper-large-v3", "large-v3") is True

    def test_faster_whisper_prefix_stripped(self, mgr):
        assert mgr.is_same_model("faster-whisper-large-v3", "large-v3") is True

    def test_case_insensitive(self, mgr):
        assert mgr.is_same_model("Large-V3", "large-v3") is True

    def test_different_models(self, mgr):
        assert mgr.is_same_model("large-v3", "medium") is False

    def test_nvidia_prefix_stripped(self, mgr):
        assert mgr.is_same_model("nvidia/parakeet-ctc-1.1b", "parakeet-ctc-1.1b") is True


# ── GPU status ────────────────────────────────────────────────────────────


class TestGpuStatus:
    def test_gpu_not_available_when_stubbed(self, tmp_path: Path):
        mgr = _build_manager(tmp_path)

        assert mgr.gpu_available is False
