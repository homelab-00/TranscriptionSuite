"""Unit tests for the MLX Canary STT backend and factory detection.

The factory-detection tests run anywhere, but the lifecycle/transcribe
tests in this module exercise code paths in ``mlx_canary_backend`` that
``import mlx`` at runtime — those paths require a real mlx install
(Apple Silicon). The whole module is therefore gated behind
``pytest.importorskip("mlx")`` so non-MLX environments (CI Linux,
non-arm64 dev machines) skip cleanly instead of erroring.
"""

from __future__ import annotations

import importlib
import sys
import types
from typing import Any
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest

# Skip the entire module when mlx is not importable. This is order-safe
# even if a sibling test installs a sys.modules['mlx'] stub later.
pytest.importorskip("mlx", reason="MLX backend tests require a real mlx install")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_canary_model_stub(text_response: str = "Hello world.") -> MagicMock:
    """Return a mock Canary model whose ``transcribe`` method returns text."""
    mock_model = MagicMock()
    mock_model.transcribe = MagicMock(return_value=text_response)
    return mock_model


def _install_soundfile_stub() -> None:
    if "soundfile" not in sys.modules:
        sf_stub = types.ModuleType("soundfile")
        sf_stub.write = MagicMock()  # type: ignore[attr-defined]
        sys.modules["soundfile"] = sf_stub


def _import_canary_backend() -> types.ModuleType:
    _install_soundfile_stub()
    key = "server.core.stt.backends.mlx_canary_backend"
    sys.modules.pop(key, None)
    return importlib.import_module(key)


def _loaded_backend(
    text_response: str = "Hello world.",
) -> tuple[Any, types.ModuleType, MagicMock]:
    """Return (backend, module, mock_model) with ``_loaded=True``.

    Bypasses ``load()`` to avoid needing stub for the heavy model-load path.
    """
    mod = _import_canary_backend()
    mock_model = _make_canary_model_stub(text_response)

    backend = mod.MLXCanaryBackend()
    backend._model = mock_model
    backend._model_name = "Mediform/canary-1b-v2-mlx-q8"
    backend._loaded = True

    return backend, mod, mock_model


# ---------------------------------------------------------------------------
# Factory detection for MLX Canary models
# ---------------------------------------------------------------------------


class TestFactoryDetectionCanary:
    def test_mediform_q8_model(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("Mediform/canary-1b-v2-mlx-q8") == "mlx_canary"

    def test_eelcor_community_mlx(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("eelcor/canary-1b-v2-mlx") == "mlx_canary"

    def test_qfuxa_bare_canary_mlx(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("qfuxa/canary-mlx") == "mlx_canary"

    def test_case_insensitive(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("Mediform/Canary-1B-V2-MLX-q8") == "mlx_canary"

    def test_nvidia_canary_routes_to_nemo_backend(self) -> None:
        """nvidia/ prefix → NeMo Canary backend, not MLX."""
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("nvidia/canary-1b-v2") == "canary"

    def test_parakeet_not_canary(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("mlx-community/parakeet-tdt-0.6b-v3") == "mlx_parakeet"

    def test_is_mlx_model_includes_canary(self) -> None:
        from server.core.stt.backends.factory import is_mlx_model

        assert is_mlx_model("Mediform/canary-1b-v2-mlx-q8")


# ---------------------------------------------------------------------------
# Language code resolution
# ---------------------------------------------------------------------------


class TestMLXCanaryLanguageResolution:
    def _resolve(self, lang: str | None) -> str:
        mod = _import_canary_backend()
        return mod._resolve_language_code(lang)

    def test_none_returns_english(self) -> None:
        assert self._resolve(None) == "en"

    def test_empty_string_returns_english(self) -> None:
        assert self._resolve("") == "en"

    def test_two_letter_code_passes_through(self) -> None:
        assert self._resolve("en") == "en"
        assert self._resolve("fr") == "fr"
        assert self._resolve("de") == "de"

    def test_two_letter_code_is_lowercased(self) -> None:
        assert self._resolve("EN") == "en"
        assert self._resolve("FR") == "fr"

    def test_full_name_english(self) -> None:
        assert self._resolve("english") == "en"
        assert self._resolve("English") == "en"

    def test_full_name_german(self) -> None:
        assert self._resolve("german") == "de"
        assert self._resolve("German") == "de"

    def test_full_name_french(self) -> None:
        assert self._resolve("french") == "fr"

    def test_unknown_language_defaults_to_english(self) -> None:
        assert self._resolve("klingon") == "en"
        assert self._resolve("xyz") == "en"


# ---------------------------------------------------------------------------
# Lifecycle: load / unload / is_loaded
# ---------------------------------------------------------------------------


class TestMLXCanaryBackendLifecycle:
    def test_not_loaded_initially(self) -> None:
        mod = _import_canary_backend()
        assert not mod.MLXCanaryBackend().is_loaded()

    def test_load_sets_loaded(self) -> None:
        mod = _import_canary_backend()
        mock_model = _make_canary_model_stub()
        canary_mlx_stub = types.ModuleType("canary_mlx")

        with patch.dict(sys.modules, {"canary_mlx": canary_mlx_stub}):
            with patch.object(mod, "_load_canary_model", return_value=mock_model):
                backend = mod.MLXCanaryBackend()
                backend.load("Mediform/canary-1b-v2-mlx-q8", device="metal")

        assert backend.is_loaded()
        assert backend._model_name == "Mediform/canary-1b-v2-mlx-q8"
        assert backend._model is mock_model

    def test_load_delegates_to_load_canary_model(self) -> None:
        mod = _import_canary_backend()
        mock_model = _make_canary_model_stub()
        canary_mlx_stub = types.ModuleType("canary_mlx")

        with patch.dict(sys.modules, {"canary_mlx": canary_mlx_stub}):
            with patch.object(mod, "_load_canary_model", return_value=mock_model) as load_fn:
                backend = mod.MLXCanaryBackend()
                backend.load("Mediform/canary-1b-v2-mlx-q8", device="metal")

        load_fn.assert_called_once_with("Mediform/canary-1b-v2-mlx-q8")

    def test_unload_clears_state(self) -> None:
        mod = _import_canary_backend()
        mock_model = _make_canary_model_stub()
        canary_mlx_stub = types.ModuleType("canary_mlx")

        with patch.dict(sys.modules, {"canary_mlx": canary_mlx_stub}):
            with patch.object(mod, "_load_canary_model", return_value=mock_model):
                backend = mod.MLXCanaryBackend()
                backend.load("Mediform/canary-1b-v2-mlx-q8", device="metal")

        backend.unload()
        assert not backend.is_loaded()
        assert backend._model is None
        assert backend._model_name is None

    def test_load_raises_if_canary_mlx_not_installed(self) -> None:
        mod = _import_canary_backend()
        backend = mod.MLXCanaryBackend()
        with patch.dict(sys.modules, {"canary_mlx": None}):  # type: ignore[dict-item]
            with pytest.raises(RuntimeError, match="canary-mlx is not installed"):
                backend.load("Mediform/canary-1b-v2-mlx-q8", device="metal")

    def test_backend_name(self) -> None:
        mod = _import_canary_backend()
        assert mod.MLXCanaryBackend().backend_name == "mlx_canary"

    def test_supports_translation_false(self) -> None:
        mod = _import_canary_backend()
        assert mod.MLXCanaryBackend().supports_translation() is False

    def test_preferred_sample_rate(self) -> None:
        mod = _import_canary_backend()
        assert mod.MLXCanaryBackend().preferred_input_sample_rate_hz == 16000


# ---------------------------------------------------------------------------
# Transcribe — VAD-based chunking (falls back to fixed 30 s on silence)
# ---------------------------------------------------------------------------


def _fixed_chunks(audio: Any, sample_rate: int = 16000, *, max_chunk_s: float = 30.0) -> list:
    """Simulate fixed 30 s chunking for tests that verify multi-chunk behaviour.

    With all-zeros audio Silero VAD finds no speech and returns a single chunk.
    This helper provides deterministic fixed-window chunking so tests  can verify
    that multiple chunks are handled correctly.
    """
    chunk_size = int(max_chunk_s * sample_rate)
    audio_len = len(audio)
    return [
        (s, min(s + chunk_size, audio_len))
        for s in range(0, audio_len, chunk_size)
        if min(s + chunk_size, audio_len) - s >= 400
    ]


class TestMLXCanaryBackendTranscribe:
    def test_transcribe_raises_if_not_loaded(self) -> None:
        mod = _import_canary_backend()
        backend = mod.MLXCanaryBackend()
        with pytest.raises(RuntimeError, match="not loaded"):
            backend.transcribe(np.zeros(16000, dtype=np.float32))

    def test_transcribe_single_chunk(self) -> None:
        """Audio ≤ 30 s produces exactly one segment."""
        backend, _, mock_model = _loaded_backend("One sentence.")
        audio = np.zeros(16000, dtype=np.float32)  # 1 s

        segments, info = backend.transcribe(audio, language="en")

        assert len(segments) == 1
        assert segments[0].text == "One sentence."
        assert segments[0].start == pytest.approx(0.0)
        assert segments[0].end == pytest.approx(1.0)
        assert info.language == "en"

    def test_transcribe_two_full_chunks(self) -> None:
        """60 s audio (exactly 2 chunks of 30 s) produces 2 segments."""
        backend, mod, mock_model = _loaded_backend("Some speech.")
        audio = np.zeros(60 * 16000, dtype=np.float32)

        with patch.object(mod, "_compute_speech_chunks", side_effect=_fixed_chunks):
            segments, info = backend.transcribe(audio, language="en")

        assert len(segments) == 2
        assert segments[0].start == pytest.approx(0.0)
        assert segments[0].end == pytest.approx(30.0)
        assert segments[1].start == pytest.approx(30.0)
        assert segments[1].end == pytest.approx(60.0)

    def test_transcribe_partial_third_chunk(self) -> None:
        """65 s audio (2 full + 1 partial chunk) produces 3 segments."""
        backend, mod, mock_model = _loaded_backend("Speech.")
        audio = np.zeros(65 * 16000, dtype=np.float32)

        with patch.object(mod, "_compute_speech_chunks", side_effect=_fixed_chunks):
            segments, _ = backend.transcribe(audio, language="en")

        assert len(segments) == 3
        assert segments[2].start == pytest.approx(60.0)
        assert segments[2].end == pytest.approx(65.0)

    def test_transcribe_skips_residual_chunk_under_400_samples(self) -> None:
        """A trailing residual of < 400 samples must not be sent to the model
        (it would cause a Metal integer-overflow / OOM crash)."""
        backend, mod, mock_model = _loaded_backend("Speech.")
        # 30 s + 300 sample residual (< 400 guard threshold)
        audio = np.zeros(30 * 16000 + 300, dtype=np.float32)

        with patch.object(mod, "_compute_speech_chunks", side_effect=_fixed_chunks):
            segments, _ = backend.transcribe(audio, language="en")

        # Only the first 30 s chunk should produce a segment.
        assert len(segments) == 1
        assert mock_model.transcribe.call_count == 1

    def test_transcribe_empty_text_chunks_excluded(self) -> None:
        """Chunks for which the model returns empty string are not added."""
        backend, mod, mock_model = _loaded_backend()
        # Return alternating empty / non-empty text for each chunk
        mock_model.transcribe.side_effect = ["", "Chunk two.", ""]
        audio = np.zeros(90 * 16000, dtype=np.float32)  # 3 chunks

        with patch.object(mod, "_compute_speech_chunks", side_effect=_fixed_chunks):
            segments, _ = backend.transcribe(audio, language="en")

        # Only the non-empty chunk contributes a segment
        assert len(segments) == 1
        assert segments[0].text == "Chunk two."
        assert segments[0].start == pytest.approx(30.0)
        assert segments[0].end == pytest.approx(60.0)

    def test_transcribe_passes_language_to_model(self) -> None:
        backend, _, mock_model = _loaded_backend("Bonjour.")
        audio = np.zeros(16000, dtype=np.float32)

        backend.transcribe(audio, language="french")

        call_kwargs = mock_model.transcribe.call_args
        assert call_kwargs.kwargs.get("language") == "fr"

    def test_transcribe_rejects_missing_language(self) -> None:
        """gh-81: MLX Canary must not silently default to English when no
        source language is given. Previously the resolver coerced ``None`` to
        "en", which translated every non-English audio to English."""
        backend, _, _ = _loaded_backend("Hello.")
        audio = np.zeros(16000, dtype=np.float32)

        with pytest.raises(ValueError, match="explicit source language"):
            backend.transcribe(audio)

    def test_transcribe_returns_correct_info(self) -> None:
        backend, _, _ = _loaded_backend("Text.")
        audio = np.zeros(8000, dtype=np.float32)

        _, info = backend.transcribe(audio, language="de")

        assert info.language == "de"
        assert info.language_probability == pytest.approx(1.0)

    def test_transcribe_whitespace_only_text_excluded(self) -> None:
        """A chunk whose transcription is only whitespace is discarded."""
        backend, _, mock_model = _loaded_backend()
        mock_model.transcribe.return_value = "   "
        audio = np.zeros(16000, dtype=np.float32)

        segments, _ = backend.transcribe(audio, language="en")

        assert segments == []

    def test_transcribe_model_called_with_timestamps_false(self) -> None:
        """The model must always be called with timestamps=False (known bug
        in canary_mlx 0.1.x where timestamps=True returns blank text)."""
        backend, _, mock_model = _loaded_backend("Hello.")
        audio = np.zeros(16000, dtype=np.float32)

        backend.transcribe(audio, language="en")

        call_kwargs = mock_model.transcribe.call_args
        assert call_kwargs.kwargs.get("timestamps") is False

    def test_progress_callback_is_called(self) -> None:
        backend, _, _ = _loaded_backend("Chunk 1.")
        audio = np.zeros(16000, dtype=np.float32)
        callback = MagicMock()

        backend.transcribe(audio, language="en", progress_callback=callback)

        assert callback.call_count >= 1
        # Final call reports completion: progress_callback(audio_len, audio_len)
        final_call = callback.call_args_list[-1]
        assert final_call == call(len(audio), len(audio))


# ---------------------------------------------------------------------------
# Audio resampling
# ---------------------------------------------------------------------------


class TestMLXCanaryResampling:
    def test_resamples_when_sample_rate_differs(self) -> None:
        """Audio at 44100 Hz must be resampled to 16000 Hz before processing."""
        backend, _, mock_model = _loaded_backend("Hello.")

        scipy_signal_stub = types.ModuleType("scipy.signal")
        resampled = np.zeros(16000, dtype=np.float32)
        scipy_signal_stub.resample = MagicMock(return_value=resampled)  # type: ignore[attr-defined]
        scipy_stub = types.ModuleType("scipy")
        scipy_stub.signal = scipy_signal_stub  # type: ignore[attr-defined]

        with patch.dict(
            sys.modules,
            {"scipy": scipy_stub, "scipy.signal": scipy_signal_stub},
        ):
            audio_44k = np.zeros(44100, dtype=np.float32)
            backend.transcribe(audio_44k, audio_sample_rate=44100, language="en")

        scipy_signal_stub.resample.assert_called_once()

    def test_no_resample_at_native_rate(self) -> None:
        """Audio at 16000 Hz must not trigger a scipy call."""
        backend, _, mock_model = _loaded_backend("Hello.")

        scipy_signal_stub = types.ModuleType("scipy.signal")
        scipy_signal_stub.resample = MagicMock()  # type: ignore[attr-defined]
        scipy_stub = types.ModuleType("scipy")
        scipy_stub.signal = scipy_signal_stub  # type: ignore[attr-defined]

        with patch.dict(
            sys.modules,
            {"scipy": scipy_stub, "scipy.signal": scipy_signal_stub},
        ):
            audio_16k = np.zeros(16000, dtype=np.float32)
            backend.transcribe(audio_16k, audio_sample_rate=16000, language="en")

        scipy_signal_stub.resample.assert_not_called()

    def test_integer_audio_is_normalised_to_float32(self) -> None:
        """int16 audio must be normalised to float32 range before processing."""
        backend, _, mock_model = _loaded_backend("Hello.")
        audio_int16 = np.zeros(16000, dtype=np.int16)

        segments, _ = backend.transcribe(audio_int16, language="en")

        # First positional arg is a temp file path (str) — audio conversion is
        # implicit before sf.write; no dtype assertion needed on the path itself.
        assert isinstance(segments, list)
