"""Unit tests for the MLX Parakeet STT backend and factory detection.

These tests run in the standard CI environment (no Apple Silicon required).
Heavy dependencies (parakeet_mlx, soundfile, scipy) are stubbed out so that
the logic can be verified on any platform.
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
# Mock objects that stand in for parakeet-mlx's typed result objects
# ---------------------------------------------------------------------------


class _MockToken:
    """Minimal stand-in for a parakeet-mlx AlignedToken."""

    def __init__(
        self,
        text: str,
        start: float,
        end: float,
        confidence: float = 1.0,
    ) -> None:
        self.text = text
        self.start = start
        self.end = end
        self.confidence = confidence


class _MockSentence:
    """Minimal stand-in for a parakeet-mlx AlignedSentence."""

    def __init__(
        self,
        text: str,
        start: float,
        end: float,
        tokens: list[_MockToken],
    ) -> None:
        self.text = text
        self.start = start
        self.end = end
        self.tokens = tokens


class _MockTranscriptionResult:
    """Minimal stand-in for a parakeet-mlx TranscriptionResult."""

    def __init__(
        self,
        sentences: list[_MockSentence] | None = None,
        text: str = "",
    ) -> None:
        self.sentences = sentences or []
        self.text = text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_result() -> _MockTranscriptionResult:
    return _MockTranscriptionResult(
        sentences=[
            _MockSentence(
                text="Hello world.",
                start=0.0,
                end=2.5,
                tokens=[
                    _MockToken(text=" Hello", start=0.0, end=1.0, confidence=0.98),
                    _MockToken(text=" world.", start=1.0, end=2.5, confidence=0.97),
                ],
            )
        ]
    )


def _make_parakeet_stub(
    result: _MockTranscriptionResult | None = None,
) -> tuple[types.ModuleType, MagicMock]:
    """Return (parakeet_mlx module stub, mock model).

    The stub's ``from_pretrained`` returns a *mock_model* whose
    ``transcribe`` method returns ``result``.
    """
    if result is None:
        result = _default_result()

    mock_model = MagicMock()
    mock_model.transcribe = MagicMock(return_value=result)

    stub = types.ModuleType("parakeet_mlx")
    stub.from_pretrained = MagicMock(return_value=mock_model)  # type: ignore[attr-defined]
    stub.DecodingConfig = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    stub.SentenceConfig = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]

    return stub, mock_model


def _install_soundfile_stub() -> None:
    if "soundfile" not in sys.modules:
        sf_stub = types.ModuleType("soundfile")
        sf_stub.write = MagicMock()  # type: ignore[attr-defined]
        sys.modules["soundfile"] = sf_stub


def _import_parakeet_backend() -> types.ModuleType:
    _install_soundfile_stub()
    key = "server.core.stt.backends.mlx_parakeet_backend"
    sys.modules.pop(key, None)
    return importlib.import_module(key)


def _loaded_backend(
    result: _MockTranscriptionResult | None = None,
) -> tuple[Any, types.ModuleType, MagicMock]:
    """Return (backend, module, mock_model) with ``_loaded=True`` without
    calling ``load()``.  Avoids needing to stub ``from_pretrained`` just to
    prepare the backend for transcription tests.
    """
    mod = _import_parakeet_backend()
    _, mock_model = _make_parakeet_stub(result)

    backend = mod.MLXParakeetBackend()
    backend._model = mock_model
    backend._model_name = "mlx-community/parakeet-tdt-0.6b-v3"
    backend._loaded = True

    return backend, mod, mock_model


# ---------------------------------------------------------------------------
# Factory detection for MLX Parakeet models
# ---------------------------------------------------------------------------


class TestFactoryDetectionParakeet:
    def test_parakeet_community_model(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("mlx-community/parakeet-tdt-0.6b-v3") == "mlx_parakeet"

    def test_parakeet_community_model_case_insensitive(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("MLX-COMMUNITY/Parakeet-TDT-1.1b") == "mlx_parakeet"

    def test_nvidia_parakeet_is_nemo_not_mlx(self) -> None:
        """nvidia/ prefix routes to the NeMo backend, not the MLX one."""
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("nvidia/parakeet-tdt-0.6b-v3") == "parakeet"

    def test_mlx_whisper_not_parakeet(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("mlx-community/whisper-small-mlx") == "mlx_whisper"

    def test_is_mlx_parakeet_model_helper(self) -> None:
        from server.core.stt.backends.factory import is_mlx_parakeet_model

        assert is_mlx_parakeet_model("mlx-community/parakeet-tdt-0.6b-v3")
        assert not is_mlx_parakeet_model("nvidia/parakeet-tdt-0.6b-v3")
        assert not is_mlx_parakeet_model("mlx-community/whisper-tiny-mlx")


# ---------------------------------------------------------------------------
# Lifecycle: load / unload / is_loaded
# ---------------------------------------------------------------------------


class TestMLXParakeetBackendLifecycle:
    def test_not_loaded_initially(self) -> None:
        mod = _import_parakeet_backend()
        backend = mod.MLXParakeetBackend()
        assert not backend.is_loaded()

    def test_load_sets_loaded(self) -> None:
        mod = _import_parakeet_backend()
        stub, _ = _make_parakeet_stub()
        with patch.dict(sys.modules, {"parakeet_mlx": stub}):
            backend = mod.MLXParakeetBackend()
            backend.load("mlx-community/parakeet-tdt-0.6b-v3", device="metal")
            assert backend.is_loaded()
            assert backend._model_name == "mlx-community/parakeet-tdt-0.6b-v3"

    def test_load_calls_from_pretrained(self) -> None:
        mod = _import_parakeet_backend()
        stub, _ = _make_parakeet_stub()
        with patch.dict(sys.modules, {"parakeet_mlx": stub}):
            backend = mod.MLXParakeetBackend()
            backend.load("mlx-community/parakeet-tdt-0.6b-v3", device="metal")
            stub.from_pretrained.assert_called_once_with("mlx-community/parakeet-tdt-0.6b-v3")

    def test_unload_clears_state(self) -> None:
        mod = _import_parakeet_backend()
        stub, _ = _make_parakeet_stub()
        with patch.dict(sys.modules, {"parakeet_mlx": stub}):
            backend = mod.MLXParakeetBackend()
            backend.load("mlx-community/parakeet-tdt-0.6b-v3", device="metal")
            backend.unload()
        assert not backend.is_loaded()
        assert backend._model is None
        assert backend._model_name is None

    def test_load_raises_if_parakeet_mlx_not_installed(self) -> None:
        mod = _import_parakeet_backend()
        backend = mod.MLXParakeetBackend()
        with patch.dict(sys.modules, {"parakeet_mlx": None}):  # type: ignore[dict-item]
            with pytest.raises(RuntimeError, match="parakeet-mlx is not installed"):
                backend.load("mlx-community/parakeet-tdt-0.6b-v3", device="metal")

    def test_backend_name(self) -> None:
        mod = _import_parakeet_backend()
        assert mod.MLXParakeetBackend().backend_name == "mlx_parakeet"

    def test_supports_translation_false(self) -> None:
        mod = _import_parakeet_backend()
        assert mod.MLXParakeetBackend().supports_translation() is False

    def test_preferred_sample_rate(self) -> None:
        mod = _import_parakeet_backend()
        assert mod.MLXParakeetBackend().preferred_input_sample_rate_hz == 16000


# ---------------------------------------------------------------------------
# Transcribe — output shape and content
# ---------------------------------------------------------------------------


class TestMLXParakeetBackendTranscribe:
    def test_transcribe_returns_segments_and_info(self) -> None:
        backend, mod, mock_model = _loaded_backend()
        stub, _ = _make_parakeet_stub()
        audio = np.zeros(16000, dtype=np.float32)

        with patch.dict(sys.modules, {"parakeet_mlx": stub}):
            # Point the existing loaded backend's model at the stub's model.
            backend._model = mock_model
            segments, info = backend.transcribe(audio)

        assert len(segments) == 1
        assert segments[0].text == "Hello world."
        assert segments[0].start == pytest.approx(0.0)
        assert segments[0].end == pytest.approx(2.5)
        assert len(segments[0].words) == 2
        assert info.language == "en"
        assert info.language_probability == pytest.approx(1.0)

    def test_transcribe_always_reports_english(self) -> None:
        """Parakeet is English-only; language in info is always 'en'."""
        backend, mod, mock_model = _loaded_backend()
        stub, _ = _make_parakeet_stub()
        audio = np.zeros(16000, dtype=np.float32)

        with patch.dict(sys.modules, {"parakeet_mlx": stub}):
            backend._model = mock_model
            _, info = backend.transcribe(audio, language="de")

        assert info.language == "en"

    def test_transcribe_raises_if_not_loaded(self) -> None:
        mod = _import_parakeet_backend()
        backend = mod.MLXParakeetBackend()
        stub, _ = _make_parakeet_stub()
        audio = np.zeros(16000, dtype=np.float32)

        with patch.dict(sys.modules, {"parakeet_mlx": stub}):
            with pytest.raises(RuntimeError, match="not loaded"):
                backend.transcribe(audio)

    def test_transcribe_empty_sentences_returns_empty_list(self) -> None:
        result = _MockTranscriptionResult(sentences=[], text="")
        backend, _, mock_model = _loaded_backend(result)
        stub, _ = _make_parakeet_stub(result)
        audio = np.zeros(16000, dtype=np.float32)

        with patch.dict(sys.modules, {"parakeet_mlx": stub}):
            backend._model = mock_model
            segments, _ = backend.transcribe(audio)

        assert segments == []

    def test_transcribe_fallback_to_text_when_no_sentences(self) -> None:
        """When result has no sentences but has text, produce one segment."""
        result = _MockTranscriptionResult(sentences=[], text="  Fallback text.  ")
        backend, _, mock_model = _loaded_backend(result)
        stub, _ = _make_parakeet_stub(result)
        audio = np.zeros(16000, dtype=np.float32)

        with patch.dict(sys.modules, {"parakeet_mlx": stub}):
            backend._model = mock_model
            segments, _ = backend.transcribe(audio)

        assert len(segments) == 1
        assert segments[0].text == "Fallback text."
        assert segments[0].start == pytest.approx(0.0)
        # end == audio_duration (1.0 s)
        assert segments[0].end == pytest.approx(1.0)
        assert segments[0].words == []

    def test_transcribe_strips_leading_trailing_whitespace(self) -> None:
        result = _MockTranscriptionResult(
            sentences=[
                _MockSentence(
                    text="  Padded sentence.  ",
                    start=0.1,
                    end=1.5,
                    tokens=[_MockToken(text=" Padded", start=0.1, end=0.8)],
                )
            ]
        )
        backend, _, mock_model = _loaded_backend(result)
        stub, _ = _make_parakeet_stub(result)
        audio = np.zeros(16000, dtype=np.float32)

        with patch.dict(sys.modules, {"parakeet_mlx": stub}):
            backend._model = mock_model
            segments, _ = backend.transcribe(audio)

        assert segments[0].text == "Padded sentence."

    def test_transcribe_multiple_sentences(self) -> None:
        result = _MockTranscriptionResult(
            sentences=[
                _MockSentence(
                    text="First.",
                    start=0.0,
                    end=1.0,
                    tokens=[_MockToken(text=" First.", start=0.0, end=1.0)],
                ),
                _MockSentence(
                    text="Second.",
                    start=1.5,
                    end=3.0,
                    tokens=[_MockToken(text=" Second.", start=1.5, end=3.0)],
                ),
            ]
        )
        backend, _, mock_model = _loaded_backend(result)
        stub, _ = _make_parakeet_stub(result)
        audio = np.zeros(48000, dtype=np.float32)

        with patch.dict(sys.modules, {"parakeet_mlx": stub}):
            backend._model = mock_model
            segments, _ = backend.transcribe(audio)

        assert len(segments) == 2
        assert segments[0].text == "First."
        assert segments[0].start == pytest.approx(0.0)
        assert segments[1].text == "Second."
        assert segments[1].start == pytest.approx(1.5)
        assert segments[1].end == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Transcribe — word-level output from _tokens_to_words
# ---------------------------------------------------------------------------


class TestMLXParakeetWordTimestamps:
    """Verify that sentence tokens are correctly assembled into word dicts."""

    def _transcribe_and_get_words(
        self, tokens: list[_MockToken], audio_len: int = 16000
    ) -> list[dict]:
        result = _MockTranscriptionResult(
            sentences=[
                _MockSentence(
                    text="ignored",
                    start=tokens[0].start if tokens else 0.0,
                    end=tokens[-1].end if tokens else 0.0,
                    tokens=tokens,
                )
            ]
        )
        backend, _, mock_model = _loaded_backend(result)
        stub, _ = _make_parakeet_stub(result)
        audio = np.zeros(audio_len, dtype=np.float32)
        with patch.dict(sys.modules, {"parakeet_mlx": stub}):
            backend._model = mock_model
            segments, _ = backend.transcribe(audio)
        return segments[0].words

    def test_single_word(self) -> None:
        words = self._transcribe_and_get_words(
            [_MockToken(text=" Hello", start=0.1, end=0.6, confidence=0.9)]
        )
        assert len(words) == 1
        assert words[0]["word"] == "Hello"
        assert words[0]["start"] == pytest.approx(0.1)
        assert words[0]["end"] == pytest.approx(0.6)
        assert words[0]["probability"] == pytest.approx(0.9)

    def test_multi_piece_word_assembles_correctly(self) -> None:
        """Sub-word pieces without leading space should be joined."""
        words = self._transcribe_and_get_words(
            [
                _MockToken(text=" un", start=0.0, end=0.2, confidence=0.95),
                _MockToken(text="able", start=0.2, end=0.5, confidence=0.98),
            ]
        )
        assert len(words) == 1
        assert words[0]["word"] == "unable"
        assert words[0]["start"] == pytest.approx(0.0)
        assert words[0]["end"] == pytest.approx(0.5)
        # Confidence is the minimum across pieces.
        assert words[0]["probability"] == pytest.approx(0.95)

    def test_multiple_words(self) -> None:
        words = self._transcribe_and_get_words(
            [
                _MockToken(text=" Hello", start=0.0, end=0.4, confidence=0.9),
                _MockToken(text=" world", start=0.5, end=0.9, confidence=0.8),
            ]
        )
        assert len(words) == 2
        assert words[0]["word"] == "Hello"
        assert words[1]["word"] == "world"

    def test_whitespace_tokens_are_discarded(self) -> None:
        """A pure-whitespace token acts as a word separator and is not output."""
        words = self._transcribe_and_get_words(
            [
                _MockToken(text=" one", start=0.0, end=0.3),
                _MockToken(text=" ", start=0.3, end=0.4),
                _MockToken(text=" two", start=0.4, end=0.7),
            ]
        )
        assert len(words) == 2
        assert words[0]["word"] == "one"
        assert words[1]["word"] == "two"

    def test_empty_token_list_returns_empty_words(self) -> None:
        # Direct test of the helper function.
        mod = _import_parakeet_backend()
        assert mod._tokens_to_words([]) == []


# ---------------------------------------------------------------------------
# Audio resampling
# ---------------------------------------------------------------------------


class TestMLXParakeetResampling:
    def test_resamples_when_sample_rate_differs(self) -> None:
        """Audio at 44100 Hz must be resampled to 16000 Hz before inference."""
        backend, mod, mock_model = _loaded_backend()
        stub, _ = _make_parakeet_stub()

        scipy_signal_stub = types.ModuleType("scipy.signal")
        resampled = np.zeros(16000, dtype=np.float32)
        scipy_signal_stub.resample = MagicMock(return_value=resampled)  # type: ignore[attr-defined]
        scipy_stub = types.ModuleType("scipy")
        scipy_stub.signal = scipy_signal_stub  # type: ignore[attr-defined]

        with patch.dict(
            sys.modules,
            {
                "parakeet_mlx": stub,
                "scipy": scipy_stub,
                "scipy.signal": scipy_signal_stub,
            },
        ):
            backend._model = mock_model
            audio_44k = np.zeros(44100, dtype=np.float32)
            backend.transcribe(audio_44k, audio_sample_rate=44100)

        scipy_signal_stub.resample.assert_called_once()

    def test_no_resample_at_native_rate(self) -> None:
        """Audio already at 16000 Hz must not trigger a scipy call."""
        backend, mod, mock_model = _loaded_backend()
        stub, _ = _make_parakeet_stub()

        scipy_signal_stub = types.ModuleType("scipy.signal")
        scipy_signal_stub.resample = MagicMock()  # type: ignore[attr-defined]
        scipy_stub = types.ModuleType("scipy")
        scipy_stub.signal = scipy_signal_stub  # type: ignore[attr-defined]

        with patch.dict(
            sys.modules,
            {
                "parakeet_mlx": stub,
                "scipy": scipy_stub,
                "scipy.signal": scipy_signal_stub,
            },
        ):
            backend._model = mock_model
            audio_16k = np.zeros(16000, dtype=np.float32)
            backend.transcribe(audio_16k, audio_sample_rate=16000)

        scipy_signal_stub.resample.assert_not_called()

    def test_integer_audio_is_normalised_to_float32(self) -> None:
        """int16 audio must be normalised and cast to float32."""
        backend, mod, mock_model = _loaded_backend()
        stub, _ = _make_parakeet_stub()
        audio_int16 = np.zeros(16000, dtype=np.int16)

        with patch.dict(sys.modules, {"parakeet_mlx": stub}):
            backend._model = mock_model
            # Should not raise a dtype-related error.
            segments, _ = backend.transcribe(audio_int16)

        assert isinstance(segments, list)
