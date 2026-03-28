"""Unit tests for the MLX Whisper STT backend and factory detection.

These tests run in the standard CI environment (no Apple Silicon required).
Heavy dependencies (mlx_whisper, scipy) are stubbed out so that the logic
can be verified on any platform.
"""

from __future__ import annotations

import importlib
import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mlx_whisper_stub(segments: list[dict[str, Any]] | None = None) -> types.ModuleType:
    """Return a minimal mlx_whisper stub.

    The stub's ``transcribe`` function returns ``segments`` wrapped in the
    dict structure that the real mlx_whisper package returns.
    """
    if segments is None:
        segments = [
            {
                "id": 0,
                "start": 0.0,
                "end": 2.5,
                "text": " Hello world.",
                "words": [
                    {"word": " Hello", "start": 0.0, "end": 1.0, "probability": 0.98},
                    {"word": " world.", "start": 1.0, "end": 2.5, "probability": 0.97},
                ],
            }
        ]

    stub = types.ModuleType("mlx_whisper")
    stub.transcribe = MagicMock(  # type: ignore[attr-defined]
        return_value={
            "text": " Hello world.",
            "language": "en",
            "segments": segments,
        }
    )
    return stub


def _install_soundfile_stub() -> None:
    if "soundfile" not in sys.modules:
        sf_stub = types.ModuleType("soundfile")
        sf_stub.read = lambda *a, **kw: (np.zeros(16000, dtype=np.float32), 16000)  # type: ignore[attr-defined]
        sf_stub.write = MagicMock()  # type: ignore[attr-defined]
        sys.modules["soundfile"] = sf_stub


def _import_mlx_backend():
    _install_soundfile_stub()
    # Reload to pick up any freshly-installed stubs.
    key = "server.core.stt.backends.mlx_whisper_backend"
    sys.modules.pop(key, None)
    return importlib.import_module(key)


# ---------------------------------------------------------------------------
# Factory detection
# ---------------------------------------------------------------------------


class TestFactoryDetection:
    def test_detects_mlx_backend_prefix(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("mlx-community/whisper-small-mlx") == "mlx_whisper"

    def test_detects_mlx_backend_case_insensitive(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("MLX-Community/whisper-large-v3-mlx") == "mlx_whisper"

    def test_non_mlx_models_unchanged(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("Systran/faster-whisper-large-v3") == "whisper"
        assert detect_backend_type("nvidia/parakeet-tdt-0.6b-v3") == "parakeet"
        assert detect_backend_type("nvidia/canary-1b-v2") == "canary"

    def test_is_mlx_model_helper(self) -> None:
        from server.core.stt.backends.factory import is_mlx_model

        assert is_mlx_model("mlx-community/whisper-tiny-mlx")
        assert not is_mlx_model("Systran/faster-whisper-large-v3")


# ---------------------------------------------------------------------------
# MLXWhisperBackend — load / unload / is_loaded
# ---------------------------------------------------------------------------


class TestMLXWhisperBackendLifecycle:
    def test_not_loaded_initially(self) -> None:
        mod = _import_mlx_backend()
        backend = mod.MLXWhisperBackend()
        assert not backend.is_loaded()

    def test_load_sets_loaded(self) -> None:
        mod = _import_mlx_backend()
        mlx_stub = _make_mlx_whisper_stub()
        with patch.dict(sys.modules, {"mlx_whisper": mlx_stub}):
            backend = mod.MLXWhisperBackend()
            backend.load("mlx-community/whisper-small-mlx", device="cpu")
            assert backend.is_loaded()
            assert backend._model_name == "mlx-community/whisper-small-mlx"

    def test_unload_clears_state(self) -> None:
        mod = _import_mlx_backend()
        mlx_stub = _make_mlx_whisper_stub()
        with patch.dict(sys.modules, {"mlx_whisper": mlx_stub}):
            backend = mod.MLXWhisperBackend()
            backend.load("mlx-community/whisper-small-mlx", device="cpu")
            backend.unload()
            assert not backend.is_loaded()
            assert backend._model_name is None

    def test_load_raises_if_mlx_not_installed(self) -> None:
        """If mlx_whisper cannot be imported, load() should raise a RuntimeError."""
        mod = _import_mlx_backend()
        backend = mod.MLXWhisperBackend()

        # Simulate ImportError inside load() by patching builtins.__import__.
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__  # type: ignore[union-attr]

        def _blocking_import(name, *args, **kwargs):
            if name == "mlx_whisper":
                raise ImportError("mlx_whisper not available")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_blocking_import):
            with pytest.raises(RuntimeError, match="mlx-whisper is not installed"):
                backend.load("mlx-community/whisper-small-mlx", device="cpu")


# ---------------------------------------------------------------------------
# MLXWhisperBackend — transcribe output format
# ---------------------------------------------------------------------------


class TestMLXWhisperBackendTranscribe:
    def _loaded_backend(self, mlx_stub: types.ModuleType):
        mod = _import_mlx_backend()
        backend = mod.MLXWhisperBackend()
        with patch.dict(sys.modules, {"mlx_whisper": mlx_stub}):
            backend.load("mlx-community/whisper-small-mlx", device="cpu")
        return backend, mod

    def test_transcribe_returns_segments_and_info(self) -> None:
        mlx_stub = _make_mlx_whisper_stub()
        backend, mod = self._loaded_backend(mlx_stub)
        audio = np.zeros(16000, dtype=np.float32)
        with patch.dict(sys.modules, {"mlx_whisper": mlx_stub}):
            segments, info = backend.transcribe(audio)

        assert len(segments) == 1
        assert segments[0].text == " Hello world."
        assert segments[0].start == pytest.approx(0.0)
        assert segments[0].end == pytest.approx(2.5)
        assert len(segments[0].words) == 2
        assert info.language == "en"

    def test_transcribe_words_structure(self) -> None:
        mlx_stub = _make_mlx_whisper_stub()
        backend, _ = self._loaded_backend(mlx_stub)
        audio = np.zeros(16000, dtype=np.float32)
        with patch.dict(sys.modules, {"mlx_whisper": mlx_stub}):
            segments, _ = backend.transcribe(audio, word_timestamps=True)

        w = segments[0].words[0]
        assert "word" in w
        assert "start" in w
        assert "end" in w
        assert "probability" in w

    def test_transcribe_raises_if_not_loaded(self) -> None:
        mod = _import_mlx_backend()
        backend = mod.MLXWhisperBackend()
        audio = np.zeros(16000, dtype=np.float32)
        mlx_stub = _make_mlx_whisper_stub()
        with patch.dict(sys.modules, {"mlx_whisper": mlx_stub}):
            with pytest.raises(RuntimeError, match="not loaded"):
                backend.transcribe(audio)

    def test_empty_segments(self) -> None:
        mlx_stub = _make_mlx_whisper_stub(segments=[])
        backend, _ = self._loaded_backend(mlx_stub)
        audio = np.zeros(16000, dtype=np.float32)
        with patch.dict(sys.modules, {"mlx_whisper": mlx_stub}):
            segments, info = backend.transcribe(audio)
        assert segments == []
        assert info.language == "en"


# ---------------------------------------------------------------------------
# MLXWhisperBackend — beam_size greedy fallback
# ---------------------------------------------------------------------------


class TestMLXWhisperBeamSizeFallback:
    def test_beam_size_gt_1_falls_back_to_greedy(self, caplog: pytest.LogCaptureFixture) -> None:
        """beam_size > 1 is silently converted to greedy (None) with a debug log."""
        mlx_stub = _make_mlx_whisper_stub()
        mod = _import_mlx_backend()
        backend = mod.MLXWhisperBackend()
        with patch.dict(sys.modules, {"mlx_whisper": mlx_stub}):
            backend.load("mlx-community/whisper-small-mlx", device="cpu")
            audio = np.zeros(16000, dtype=np.float32)
            with caplog.at_level("DEBUG"):
                backend.transcribe(audio, beam_size=5)
            # Verify the actual call passed beam_size=None (greedy)
            call_kwargs = mlx_stub.transcribe.call_args
            assert call_kwargs.kwargs.get("beam_size") is None

    def test_beam_size_none_passes_through(self) -> None:
        mlx_stub = _make_mlx_whisper_stub()
        mod = _import_mlx_backend()
        backend = mod.MLXWhisperBackend()
        with patch.dict(sys.modules, {"mlx_whisper": mlx_stub}):
            backend.load("mlx-community/whisper-small-mlx", device="cpu")
            audio = np.zeros(16000, dtype=np.float32)
            backend.transcribe(audio, beam_size=None)  # type: ignore[arg-type]
            call_kwargs = mlx_stub.transcribe.call_args
            assert call_kwargs.kwargs.get("beam_size") is None


# ---------------------------------------------------------------------------
# MLXWhisperBackend — audio resampling
# ---------------------------------------------------------------------------


class TestMLXWhisperResampling:
    def test_resamples_when_sample_rate_differs(self) -> None:
        """Audio at 44100 Hz should be resampled to 16000 Hz before inference."""
        mlx_stub = _make_mlx_whisper_stub()
        mod = _import_mlx_backend()
        backend = mod.MLXWhisperBackend()

        # Stub scipy so the test runs without the full signal-processing stack.
        scipy_signal_stub = types.ModuleType("scipy.signal")
        target_samples = int(44100 * 16000 / 44100)  # == 16000
        resampled = np.zeros(target_samples, dtype=np.float32)
        scipy_signal_stub.resample = MagicMock(return_value=resampled)  # type: ignore[attr-defined]
        scipy_stub = types.ModuleType("scipy")
        scipy_stub.signal = scipy_signal_stub  # type: ignore[attr-defined]

        with patch.dict(
            sys.modules,
            {"mlx_whisper": mlx_stub, "scipy": scipy_stub, "scipy.signal": scipy_signal_stub},
        ):
            backend.load("mlx-community/whisper-small-mlx", device="cpu")
            audio_44k = np.zeros(44100, dtype=np.float32)
            backend.transcribe(audio_44k, audio_sample_rate=44100)

        scipy_signal_stub.resample.assert_called_once()
        # The first positional arg to mlx_whisper.transcribe should be the resampled audio.
        call_args = mlx_stub.transcribe.call_args
        passed_audio = call_args.args[0]
        assert passed_audio.dtype == np.float32

    def test_no_resample_at_native_rate(self) -> None:
        """Audio at 16000 Hz should not trigger a scipy call."""
        mlx_stub = _make_mlx_whisper_stub()
        mod = _import_mlx_backend()
        backend = mod.MLXWhisperBackend()
        scipy_signal_stub = types.ModuleType("scipy.signal")
        scipy_signal_stub.resample = MagicMock()  # type: ignore[attr-defined]
        scipy_stub = types.ModuleType("scipy")
        scipy_stub.signal = scipy_signal_stub  # type: ignore[attr-defined]

        with patch.dict(
            sys.modules,
            {"mlx_whisper": mlx_stub, "scipy": scipy_stub, "scipy.signal": scipy_signal_stub},
        ):
            backend.load("mlx-community/whisper-small-mlx", device="cpu")
            audio_16k = np.zeros(16000, dtype=np.float32)
            backend.transcribe(audio_16k, audio_sample_rate=16000)

        scipy_signal_stub.resample.assert_not_called()
