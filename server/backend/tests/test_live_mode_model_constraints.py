"""Tests for Live Mode model backend constraints."""

import sys
from pathlib import Path
from types import ModuleType

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if "server" not in sys.modules:
    server_pkg = ModuleType("server")
    server_pkg.__path__ = [str(BACKEND_ROOT)]
    server_pkg.__version__ = "test"
    sys.modules["server"] = server_pkg


def test_live_mode_accepts_whisper_models_only() -> None:
    pytest.importorskip("fastapi")
    from server.api.routes.live import is_live_mode_model_supported

    assert is_live_mode_model_supported("Systran/faster-whisper-large-v3")
    assert is_live_mode_model_supported("Systran/faster-whisper-small")

    assert not is_live_mode_model_supported("nvidia/parakeet-tdt-0.6b-v3")
    assert not is_live_mode_model_supported("nvidia/canary-1b-v2")
    assert not is_live_mode_model_supported("microsoft/VibeVoice-ASR")
