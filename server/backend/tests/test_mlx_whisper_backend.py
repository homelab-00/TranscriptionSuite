"""Unit tests for the MLX Whisper STT backend (mlx-audio) and factory detection.

These tests run in the standard CI environment (no Apple Silicon required).
Heavy dependencies (mlx-audio, mlx, scipy) are stubbed out so that the logic
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


class _FakeSTTOutput:
    """Minimal fake for ``mlx_audio.stt.models.whisper.whisper.STTOutput``."""

    def __init__(self, segments: list[dict[str, Any]], text: str = "", language: str | None = "en"):
        self.segments = segments
        self.text = text
        self.language = language


class _FakeModel:
    """Minimal fake for the model object returned by ``mlx_audio.stt.load()``."""

    def __init__(self, segments: list[dict[str, Any]] | None = None):
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
        self._segments = segments
        # Simulate the alignment_heads stored by set_alignment_heads()
        self._alignment_heads = [[0, 1], [1, 2]]
        self.generate = MagicMock(
            side_effect=lambda *a, **kw: _FakeSTTOutput(self._segments, language="en")
        )


def _make_mlx_audio_stubs(model: _FakeModel | None = None) -> dict[str, types.ModuleType]:
    """Return module stubs for mlx_audio.stt and mlx.core."""
    if model is None:
        model = _FakeModel()

    stt_module = types.ModuleType("mlx_audio.stt")
    stt_module.load = MagicMock(return_value=model)  # type: ignore[attr-defined]

    mlx_audio = types.ModuleType("mlx_audio")
    mlx_audio.stt = stt_module  # type: ignore[attr-defined]

    mlx_core = types.ModuleType("mlx.core")
    mlx_core.clear_cache = MagicMock()  # type: ignore[attr-defined]

    mlx_mod = types.ModuleType("mlx")
    mlx_mod.core = mlx_core  # type: ignore[attr-defined]

    return {
        "mlx_audio": mlx_audio,
        "mlx_audio.stt": stt_module,
        "mlx": mlx_mod,
        "mlx.core": mlx_core,
    }


def _import_mlx_backend():
    key = "server.core.stt.backends.mlx_whisper_backend"
    sys.modules.pop(key, None)
    return importlib.import_module(key)


# ---------------------------------------------------------------------------
# Factory detection
# ---------------------------------------------------------------------------


class TestFactoryDetection:
    def test_detects_mlx_backend_prefix(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("mlx-community/whisper-small-asr-fp16") == "mlx_whisper"

    def test_detects_old_mlx_model_prefix(self) -> None:
        """Old model IDs still route to mlx_whisper via the generic mlx-community/ match."""
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("mlx-community/whisper-small-mlx") == "mlx_whisper"

    def test_detects_mlx_backend_case_insensitive(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("MLX-Community/whisper-large-v3-asr-fp16") == "mlx_whisper"

    def test_non_mlx_models_unchanged(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("Systran/faster-whisper-large-v3") == "whisper"
        assert detect_backend_type("nvidia/parakeet-tdt-0.6b-v3") == "parakeet"
        assert detect_backend_type("nvidia/canary-1b-v2") == "canary"

    def test_is_mlx_model_helper(self) -> None:
        from server.core.stt.backends.factory import is_mlx_model

        assert is_mlx_model("mlx-community/whisper-tiny-asr-fp16")
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
        stubs = _make_mlx_audio_stubs()
        with patch.dict(sys.modules, stubs):
            backend = mod.MLXWhisperBackend()
            backend.load("mlx-community/whisper-small-asr-fp16", device="cpu")
            assert backend.is_loaded()
            assert backend._model_name == "mlx-community/whisper-small-asr-fp16"

    def test_unload_clears_state(self) -> None:
        mod = _import_mlx_backend()
        stubs = _make_mlx_audio_stubs()
        with patch.dict(sys.modules, stubs):
            backend = mod.MLXWhisperBackend()
            backend.load("mlx-community/whisper-small-asr-fp16", device="cpu")
            backend.unload()
            assert not backend.is_loaded()

    def test_load_raises_if_mlx_audio_not_installed(self) -> None:
        """If mlx_audio cannot be imported, load() should raise a RuntimeError."""
        mod = _import_mlx_backend()
        backend = mod.MLXWhisperBackend()

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__  # type: ignore[union-attr]

        def _blocking_import(name, *args, **kwargs):
            if "mlx_audio" in name:
                raise ImportError("mlx_audio not available")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_blocking_import):
            with pytest.raises(RuntimeError, match="mlx-audio is not installed"):
                backend.load("mlx-community/whisper-small-asr-fp16", device="cpu")

    def test_alignment_heads_monkey_patch(self) -> None:
        """Load should apply alignment_heads monkey-patch when _alignment_heads exists."""
        mod = _import_mlx_backend()
        fake_model = _FakeModel()
        stubs = _make_mlx_audio_stubs(fake_model)
        with patch.dict(sys.modules, stubs):
            backend = mod.MLXWhisperBackend()
            backend.load("mlx-community/whisper-small-asr-fp16", device="cpu")
            assert hasattr(backend._model, "alignment_heads")
            assert backend._model.alignment_heads == fake_model._alignment_heads


# ---------------------------------------------------------------------------
# MLXWhisperBackend — transcribe output format
# ---------------------------------------------------------------------------


class TestMLXWhisperBackendTranscribe:
    def _loaded_backend(self, model: _FakeModel | None = None):
        mod = _import_mlx_backend()
        stubs = _make_mlx_audio_stubs(model)
        backend = mod.MLXWhisperBackend()
        with patch.dict(sys.modules, stubs):
            backend.load("mlx-community/whisper-small-asr-fp16", device="cpu")
        return backend

    def test_transcribe_returns_segments_and_info(self) -> None:
        backend = self._loaded_backend()
        audio = np.zeros(16000, dtype=np.float32)
        segments, info = backend.transcribe(audio)

        assert len(segments) == 1
        assert segments[0].text == "Hello world."
        assert segments[0].start == pytest.approx(0.0)
        assert segments[0].end == pytest.approx(2.5)
        assert len(segments[0].words) == 2
        assert info.language == "en"

    def test_transcribe_words_structure(self) -> None:
        backend = self._loaded_backend()
        audio = np.zeros(16000, dtype=np.float32)
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
        with pytest.raises(RuntimeError, match="not loaded"):
            backend.transcribe(audio)

    def test_empty_segments(self) -> None:
        model = _FakeModel(segments=[])
        backend = self._loaded_backend(model)
        audio = np.zeros(16000, dtype=np.float32)
        segments, info = backend.transcribe(audio)
        assert segments == []
        assert info.language == "en"

    def test_empty_text_segments_filtered(self) -> None:
        """Segments with empty text should be filtered out."""
        model = _FakeModel(
            segments=[
                {"id": 0, "start": 0.0, "end": 1.0, "text": " Hello."},
                {"id": 1, "start": 1.0, "end": 1.0, "text": ""},
                {"id": 2, "start": 1.0, "end": 1.0, "text": "   "},
            ]
        )
        backend = self._loaded_backend(model)
        audio = np.zeros(16000, dtype=np.float32)
        segments, _ = backend.transcribe(audio)
        assert len(segments) == 1
        assert segments[0].text == "Hello."


# ---------------------------------------------------------------------------
# MLXWhisperBackend — audio resampling
# ---------------------------------------------------------------------------


class TestMLXWhisperResampling:
    def test_resamples_when_sample_rate_differs(self) -> None:
        """Audio at 44100 Hz should be resampled to 16000 Hz before inference."""
        mod = _import_mlx_backend()
        fake_model = _FakeModel()
        stubs = _make_mlx_audio_stubs(fake_model)

        scipy_signal_stub = types.ModuleType("scipy.signal")
        target_samples = int(44100 * 16000 / 44100)  # == 16000
        resampled = np.zeros(target_samples, dtype=np.float32)
        scipy_signal_stub.resample = MagicMock(return_value=resampled)  # type: ignore[attr-defined]
        scipy_stub = types.ModuleType("scipy")
        scipy_stub.signal = scipy_signal_stub  # type: ignore[attr-defined]

        all_stubs = {**stubs, "scipy": scipy_stub, "scipy.signal": scipy_signal_stub}

        with patch.dict(sys.modules, all_stubs):
            backend = mod.MLXWhisperBackend()
            backend.load("mlx-community/whisper-small-asr-fp16", device="cpu")
            audio_44k = np.zeros(44100, dtype=np.float32)
            backend.transcribe(audio_44k, audio_sample_rate=44100)

        scipy_signal_stub.resample.assert_called_once()

    def test_no_resample_at_native_rate(self) -> None:
        """Audio at 16000 Hz should not trigger a scipy call."""
        mod = _import_mlx_backend()
        fake_model = _FakeModel()
        stubs = _make_mlx_audio_stubs(fake_model)

        scipy_signal_stub = types.ModuleType("scipy.signal")
        scipy_signal_stub.resample = MagicMock()  # type: ignore[attr-defined]
        scipy_stub = types.ModuleType("scipy")
        scipy_stub.signal = scipy_signal_stub  # type: ignore[attr-defined]

        all_stubs = {**stubs, "scipy": scipy_stub, "scipy.signal": scipy_signal_stub}

        with patch.dict(sys.modules, all_stubs):
            backend = mod.MLXWhisperBackend()
            backend.load("mlx-community/whisper-small-asr-fp16", device="cpu")
            audio_16k = np.zeros(16000, dtype=np.float32)
            backend.transcribe(audio_16k, audio_sample_rate=16000)

        scipy_signal_stub.resample.assert_not_called()
