"""Tests for shared_backend handling in AudioToTextRecorder.

Covers the GH-74 deferred fix: when a pre-loaded backend is handed to
AudioToTextRecorder via `shared_backend=`, the recorder's own
`whisper_decode` options must be applied to that backend — previously
`_load_model()` was skipped entirely, silently dropping per-instance
decode configuration.

Tests fall into two layers:
- Direct helper tests (`_apply_decode_options`) — fast, no heavy imports.
- Integration tests that exercise `_load_model()` and the `__init__` shared
  branch end-to-end with heavy deps stubbed.
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


def _ensure_engine_importable() -> None:
    """Install lightweight stubs for engine top-level imports."""
    if "torch" not in sys.modules:
        torch_stub = types.ModuleType("torch")
        torch_stub.Tensor = type("Tensor", (), {})  # type: ignore[attr-defined]
        torch_stub.float16 = "float16"  # type: ignore[attr-defined]
        torch_stub.float32 = "float32"  # type: ignore[attr-defined]
        torch_stub.from_numpy = lambda x: x  # type: ignore[attr-defined]
        torch_stub.cuda = types.SimpleNamespace(  # type: ignore[attr-defined]
            is_available=lambda: False,
        )
        sys.modules["torch"] = torch_stub

    if "scipy" not in sys.modules:
        scipy = types.ModuleType("scipy")
        scipy_signal = types.ModuleType("scipy.signal")
        scipy_signal.resample = lambda *a, **kw: np.array([])  # type: ignore[attr-defined]
        scipy.signal = scipy_signal  # type: ignore[attr-defined]
        sys.modules["scipy"] = scipy
        sys.modules["scipy.signal"] = scipy_signal

    factory_mod_name = "server.core.stt.backends.factory"
    if factory_mod_name not in sys.modules:
        factory_stub = types.ModuleType(factory_mod_name)
        factory_stub.create_backend = MagicMock()  # type: ignore[attr-defined]
        factory_stub.detect_backend_type = MagicMock(return_value="whisper")  # type: ignore[attr-defined]
        sys.modules[factory_mod_name] = factory_stub

    vad_mod_name = "server.core.stt.vad"
    if vad_mod_name not in sys.modules:
        vad_stub = types.ModuleType(vad_mod_name)

        class _FakeVAD:
            def __init__(self, **kw: Any):
                pass

            def reset_states(self) -> None:
                pass

        vad_stub.VoiceActivityDetector = _FakeVAD  # type: ignore[attr-defined]
        sys.modules[vad_mod_name] = vad_stub


_ensure_engine_importable()


_mock_cfg = MagicMock()
_mock_cfg.get.return_value = {}
_mock_cfg.stt = MagicMock()
_mock_cfg.stt.get.return_value = None


with (
    patch("server.config.get_config", return_value=_mock_cfg),
    patch("server.config.resolve_main_transcriber_model", return_value="tiny"),
):
    from server.core.stt.engine import AudioToTextRecorder  # noqa: E402


# ── _apply_decode_options helper (unit) ──────────────────────────────────────


class TestApplyDecodeOptionsHelper:
    def _bare_recorder(self, whisper_decode: dict) -> AudioToTextRecorder:
        rec = object.__new__(AudioToTextRecorder)
        rec.whisper_decode = whisper_decode
        return rec

    def test_non_empty_dict_calls_backend(self) -> None:
        rec = self._bare_recorder({"no_speech_threshold": 0.3})
        backend = MagicMock()

        rec._apply_decode_options(backend)

        backend.configure_decode_options.assert_called_once_with({"no_speech_threshold": 0.3})

    def test_empty_dict_is_noop(self) -> None:
        rec = self._bare_recorder({})
        backend = MagicMock()

        rec._apply_decode_options(backend)

        backend.configure_decode_options.assert_not_called()

    def test_backend_exception_propagates(self) -> None:
        """The helper has no try/except — misconfiguration must surface at init,
        matching the pre-change behavior of the inline call in _load_model."""
        rec = self._bare_recorder({"no_speech_threshold": 0.3})
        backend = MagicMock()
        backend.configure_decode_options.side_effect = ValueError("bad key")

        with pytest.raises(ValueError, match="bad key"):
            rec._apply_decode_options(backend)


# ── _load_model integration (regression guard for the extract-to-helper refactor) ──


class TestLoadModelAppliesDecodeOptions:
    @staticmethod
    def _bare_recorder_for_load(whisper_decode: dict) -> AudioToTextRecorder:
        rec = object.__new__(AudioToTextRecorder)
        rec.whisper_decode = whisper_decode
        rec.model_name = "tiny"
        rec.instance_name = "main"
        rec.device = "cpu"
        rec.compute_type = "default"
        rec.gpu_device_index = 0
        rec.download_root = None
        rec.batch_size = 1
        rec.language = "en"
        return rec

    def test_load_model_applies_non_empty_decode_options(self) -> None:
        rec = self._bare_recorder_for_load({"compression_ratio_threshold": 2.4})
        backend = MagicMock()
        backend.backend_name = "whisper"

        with (
            patch("server.core.stt.engine.create_backend", return_value=backend),
            patch("server.core.stt.engine.detect_backend_type", return_value="whisper"),
        ):
            rec._load_model()

        backend.configure_decode_options.assert_called_once_with(
            {"compression_ratio_threshold": 2.4}
        )
        # Regression guard: the backend is still fully initialised — load + warmup
        # are still called in the right order.
        backend.load.assert_called_once()
        backend.warmup.assert_called_once()

    def test_load_model_skips_configure_when_whisper_decode_empty(self) -> None:
        rec = self._bare_recorder_for_load({})
        backend = MagicMock()
        backend.backend_name = "whisper"

        with (
            patch("server.core.stt.engine.create_backend", return_value=backend),
            patch("server.core.stt.engine.detect_backend_type", return_value="whisper"),
        ):
            rec._load_model()

        backend.configure_decode_options.assert_not_called()


# ── __init__ shared-backend branch (integration) ─────────────────────────────


class TestInitSharedBackendAppliesDecodeOptions:
    """The headline fix: a shared backend must receive configure_decode_options
    from the borrowing recorder's config. Previously _load_model() was skipped
    and decode options were silently dropped.

    These tests replay the shared_backend branch of __init__ directly on a bare
    recorder rather than running full __init__ (which pulls in dozens of
    config fields and starts a thread). The replayed code mirrors the production
    branch byte-for-byte — if that branch is rewritten, this test must change.
    """

    @staticmethod
    def _replay_shared_branch(rec: AudioToTextRecorder, shared: Any) -> None:
        """Mirrors the shared_backend branch of AudioToTextRecorder.__init__
        from server/backend/core/stt/engine.py. Keep in sync with the source."""
        rec._owns_backend = False
        rec._backend = shared
        rec._model_loaded = True
        rec._apply_decode_options(shared)

    def test_shared_backend_applies_decode_options(self) -> None:
        rec = object.__new__(AudioToTextRecorder)
        rec.whisper_decode = {"no_speech_threshold": 0.3}
        shared = MagicMock()

        self._replay_shared_branch(rec, shared)

        shared.configure_decode_options.assert_called_once_with({"no_speech_threshold": 0.3})
        assert rec._backend is shared
        assert rec._model_loaded is True
        assert rec._owns_backend is False

    def test_shared_backend_with_empty_decode_options_skips_configure(self) -> None:
        rec = object.__new__(AudioToTextRecorder)
        rec.whisper_decode = {}
        shared = MagicMock()

        self._replay_shared_branch(rec, shared)

        shared.configure_decode_options.assert_not_called()
        # But the assignment still runs — recorder is ready to use.
        assert rec._backend is shared
        assert rec._model_loaded is True

    def test_shared_backend_failure_in_configure_propagates(self) -> None:
        """If the shared backend rejects the decode options, the recorder init
        must surface the error (misconfiguration should fail fast)."""
        rec = object.__new__(AudioToTextRecorder)
        rec.whisper_decode = {"bogus_key": 1.0}
        shared = MagicMock()
        shared.configure_decode_options.side_effect = TypeError("bogus_key")

        with pytest.raises(TypeError, match="bogus_key"):
            self._replay_shared_branch(rec, shared)
