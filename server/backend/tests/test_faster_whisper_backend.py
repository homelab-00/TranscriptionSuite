"""Unit tests for FasterWhisperBackend and its factory fallback.

These tests run in the standard CI environment (no Apple Silicon required).
The ``faster_whisper.WhisperModel`` is stubbed to avoid downloading any
model weights.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


class _FakeWord:
    """Fake word object returned by faster_whisper segment.words."""

    def __init__(self, word: str, start: float, end: float, probability: float = 0.95):
        self.word = word
        self.start = start
        self.end = end
        self.probability = probability


class _FakeSegment:
    """Fake segment object returned by WhisperModel.transcribe()."""

    def __init__(
        self,
        text: str = " Hello world.",
        start: float = 0.0,
        end: float = 2.5,
        words: list[_FakeWord] | None = None,
    ):
        self.text = text
        self.start = start
        self.end = end
        self.words = words if words is not None else [
            _FakeWord(" Hello", 0.0, 1.0),
            _FakeWord(" world.", 1.0, 2.5),
        ]


class _FakeInfo:
    """Fake TranscriptionInfo returned by WhisperModel.transcribe()."""

    def __init__(self, language: str = "en", language_probability: float = 0.99):
        self.language = language
        self.language_probability = language_probability


class _FakeWhisperModel:
    """Minimal stub for ``faster_whisper.WhisperModel``."""

    def __init__(
        self,
        segments: list[_FakeSegment] | None = None,
        info: _FakeInfo | None = None,
    ):
        self._segments = segments if segments is not None else [_FakeSegment()]
        self._info = info or _FakeInfo()
        self.transcribe = MagicMock(
            side_effect=lambda audio, **kw: (iter(self._segments), self._info)
        )


def _make_faster_whisper_stub(
    model: _FakeWhisperModel | None = None,
) -> dict[str, Any]:
    """Return a sys.modules patch dict that stubs out ``faster_whisper``."""
    if model is None:
        model = _FakeWhisperModel()

    fw_module = MagicMock()
    fw_module.WhisperModel = MagicMock(return_value=model)

    import types

    fw_mod = types.ModuleType("faster_whisper")
    fw_mod.WhisperModel = MagicMock(return_value=model)  # type: ignore[attr-defined]
    return {"faster_whisper": fw_mod}


# ---------------------------------------------------------------------------
# Factory fallback
# ---------------------------------------------------------------------------


class TestFactoryFallback:
    def test_whisper_type_detection_unchanged(self) -> None:
        """Systran/faster-whisper* models still resolve to 'whisper' backend type."""
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("Systran/faster-whisper-large-v3") == "whisper"
        assert detect_backend_type("Systran/faster-whisper-tiny") == "whisper"

    def test_falls_back_to_faster_whisper_when_whisperx_absent(self) -> None:
        """When whisperx cannot be imported, create_backend() returns FasterWhisperBackend."""
        from server.core.stt.backends.factory import create_backend
        from server.core.stt.backends.faster_whisper_backend import FasterWhisperBackend

        saved = sys.modules.get("whisperx", ...)
        # Setting a module to None in sys.modules causes ImportError on import
        sys.modules["whisperx"] = None  # type: ignore[assignment]
        try:
            backend = create_backend("Systran/faster-whisper-large-v3")
            assert isinstance(backend, FasterWhisperBackend)
        finally:
            if saved is ...:
                sys.modules.pop("whisperx", None)
            else:
                sys.modules["whisperx"] = saved  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# FasterWhisperBackend — lifecycle
# ---------------------------------------------------------------------------


class TestFasterWhisperBackendLifecycle:
    def test_not_loaded_initially(self) -> None:
        from server.core.stt.backends.faster_whisper_backend import FasterWhisperBackend

        backend = FasterWhisperBackend()
        assert not backend.is_loaded()

    def test_load_sets_loaded(self) -> None:
        from server.core.stt.backends.faster_whisper_backend import FasterWhisperBackend

        stubs = _make_faster_whisper_stub()
        with patch.dict(sys.modules, stubs):
            backend = FasterWhisperBackend()
            backend.load("Systran/faster-whisper-large-v3", device="cpu")
            assert backend.is_loaded()
            assert backend._model_name == "Systran/faster-whisper-large-v3"
            assert backend._device == "cpu"

    def test_unload_clears_model(self) -> None:
        from server.core.stt.backends.faster_whisper_backend import FasterWhisperBackend

        stubs = _make_faster_whisper_stub()
        with patch.dict(sys.modules, stubs):
            backend = FasterWhisperBackend()
            backend.load("Systran/faster-whisper-large-v3", device="cpu")
        backend.unload()
        assert not backend.is_loaded()
        assert backend._model_name is None

    def test_load_passes_kwargs_to_whisper_model(self) -> None:
        from server.core.stt.backends.faster_whisper_backend import FasterWhisperBackend

        stubs = _make_faster_whisper_stub()
        with patch.dict(sys.modules, stubs):
            backend = FasterWhisperBackend()
            backend.load(
                "Systran/faster-whisper-large-v3",
                device="cpu",
                compute_type="int8",
                download_root="/tmp/models",
            )
            stubs["faster_whisper"].WhisperModel.assert_called_once_with(
                "Systran/faster-whisper-large-v3",
                device="cpu",
                compute_type="int8",
                download_root="/tmp/models",
            )

    def test_load_defaults_compute_type(self) -> None:
        from server.core.stt.backends.faster_whisper_backend import FasterWhisperBackend

        stubs = _make_faster_whisper_stub()
        with patch.dict(sys.modules, stubs):
            backend = FasterWhisperBackend()
            backend.load("Systran/faster-whisper-tiny", device="cpu")
            call_kwargs = stubs["faster_whisper"].WhisperModel.call_args[1]
            assert call_kwargs["compute_type"] == "default"


# ---------------------------------------------------------------------------
# FasterWhisperBackend — transcribe
# ---------------------------------------------------------------------------


class TestFasterWhisperBackendTranscribe:
    def _make_loaded_backend(self, model: _FakeWhisperModel | None = None):
        from server.core.stt.backends.faster_whisper_backend import FasterWhisperBackend

        fake = model or _FakeWhisperModel()
        stubs = _make_faster_whisper_stub(fake)
        with patch.dict(sys.modules, stubs):
            backend = FasterWhisperBackend()
            backend.load("Systran/faster-whisper-large-v3", device="cpu")
        return backend, fake

    def test_transcribe_returns_segments_and_info(self) -> None:
        backend, _ = self._make_loaded_backend()
        audio = np.zeros(16000, dtype=np.float32)
        segments, info = backend.transcribe(audio)
        assert isinstance(segments, list)
        assert len(segments) == 1
        assert segments[0].text == " Hello world."
        assert info.language == "en"

    def test_transcribe_includes_word_timestamps(self) -> None:
        backend, _ = self._make_loaded_backend()
        audio = np.zeros(16000, dtype=np.float32)
        segments, _ = backend.transcribe(audio, word_timestamps=True)
        words = segments[0].words
        assert len(words) == 2
        assert words[0]["word"] == " Hello"
        assert words[0]["start"] == 0.0
        assert words[0]["end"] == 1.0
        assert "probability" in words[0]
        assert words[1]["word"] == " world."

    def test_transcribe_raises_if_not_loaded(self) -> None:
        from server.core.stt.backends.faster_whisper_backend import FasterWhisperBackend

        backend = FasterWhisperBackend()
        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(RuntimeError, match="not loaded"):
            backend.transcribe(audio)

    def test_transcribe_info_language_probability(self) -> None:
        backend, _ = self._make_loaded_backend()
        audio = np.zeros(16000, dtype=np.float32)
        _, info = backend.transcribe(audio)
        assert info.language_probability == pytest.approx(0.99)

    def test_transcribe_empty_segments(self) -> None:
        fake = _FakeWhisperModel(segments=[])
        backend, _ = self._make_loaded_backend(fake)
        audio = np.zeros(16000, dtype=np.float32)
        segments, info = backend.transcribe(audio)
        assert segments == []
        assert info.language == "en"

    def test_transcribe_multiple_segments(self) -> None:
        fake = _FakeWhisperModel(
            segments=[
                _FakeSegment(" First sentence.", 0.0, 2.0),
                _FakeSegment(" Second sentence.", 2.0, 4.5),
            ]
        )
        backend, _ = self._make_loaded_backend(fake)
        audio = np.zeros(32000, dtype=np.float32)
        segments, _ = backend.transcribe(audio)
        assert len(segments) == 2
        assert segments[1].text == " Second sentence."
        assert segments[1].start == 2.0

    def test_transcribe_no_words_when_disabled(self) -> None:
        """If word_timestamps=False, words list should be empty."""
        fake_seg = _FakeSegment(words=[])
        fake = _FakeWhisperModel(segments=[fake_seg])
        backend, _ = self._make_loaded_backend(fake)
        audio = np.zeros(16000, dtype=np.float32)
        segments, _ = backend.transcribe(audio, word_timestamps=False)
        assert segments[0].words == []


# ---------------------------------------------------------------------------
# FasterWhisperBackend — warmup
# ---------------------------------------------------------------------------


class TestFasterWhisperBackendWarmup:
    def test_warmup_is_noop_when_not_loaded(self) -> None:
        from server.core.stt.backends.faster_whisper_backend import FasterWhisperBackend

        backend = FasterWhisperBackend()
        backend.warmup()  # must not raise

    def test_warmup_calls_transcribe(self) -> None:
        from server.core.stt.backends.faster_whisper_backend import FasterWhisperBackend

        fake = _FakeWhisperModel()
        stubs = _make_faster_whisper_stub(fake)
        with patch.dict(sys.modules, stubs):
            backend = FasterWhisperBackend()
            backend.load("Systran/faster-whisper-large-v3", device="cpu")
            backend.warmup()
        fake.transcribe.assert_called_once()


# ---------------------------------------------------------------------------
# FasterWhisperBackend — metadata
# ---------------------------------------------------------------------------


class TestFasterWhisperBackendMetadata:
    def test_backend_name(self) -> None:
        from server.core.stt.backends.faster_whisper_backend import FasterWhisperBackend

        assert FasterWhisperBackend().backend_name == "faster_whisper"

    def test_supports_translation(self) -> None:
        from server.core.stt.backends.faster_whisper_backend import FasterWhisperBackend

        assert FasterWhisperBackend().supports_translation() is True
