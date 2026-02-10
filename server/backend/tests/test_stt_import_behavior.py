"""Regression tests for lazy STT import behavior."""

from __future__ import annotations

import importlib
import sys
import types

import pytest


def _clear_stt_modules() -> None:
    """Clear STT modules from sys.modules for deterministic import checks."""
    sys.modules.pop("server.core.stt.capabilities", None)
    sys.modules.pop("server.core.stt.engine", None)
    sys.modules.pop("server.core.stt", None)


def test_importing_capabilities_does_not_load_engine() -> None:
    _clear_stt_modules()

    importlib.import_module("server.core.stt.capabilities")

    assert "server.core.stt.engine" not in sys.modules


def test_lazy_stt_exports_resolve_recorder_and_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_stt_modules()

    fake_engine = types.ModuleType("server.core.stt.engine")

    class FakeRecorder:  # pragma: no cover - simple sentinel class
        pass

    class FakeResult:  # pragma: no cover - simple sentinel class
        pass

    fake_engine.AudioToTextRecorder = FakeRecorder
    fake_engine.TranscriptionResult = FakeResult
    monkeypatch.setitem(sys.modules, "server.core.stt.engine", fake_engine)

    from server.core.stt import AudioToTextRecorder, TranscriptionResult

    assert AudioToTextRecorder is FakeRecorder
    assert TranscriptionResult is FakeResult
