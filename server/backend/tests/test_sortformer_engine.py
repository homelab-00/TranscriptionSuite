"""Unit tests for SortformerEngine (Metal-native diarization via mlx-audio).

These tests run on any platform using ``patch.object`` to inject stubs for
``HAS_MLX_AUDIO`` and ``_load_sortformer``; no Apple Silicon required.
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeDiarSegment:
    """Fake segment object produced by Sortformer model.generate()."""

    def __init__(self, speaker: str, start: float, end: float):
        self.speaker = speaker
        self.start = start
        self.end = end


class _FakeDiarResult:
    """Fake diarization result produced by Sortformer model.generate()."""

    def __init__(self, segments: list[_FakeDiarSegment] | None = None):
        self.segments = (
            segments
            if segments is not None
            else [
                _FakeDiarSegment("SPEAKER_00", 0.0, 2.0),
                _FakeDiarSegment("SPEAKER_01", 2.5, 5.0),
                _FakeDiarSegment("SPEAKER_00", 5.5, 8.0),
            ]
        )


class _FakeSortformerModel:
    """Minimal stub for the mlx_audio Sortformer model object."""

    def __init__(self, result: _FakeDiarResult | None = None):
        self._result = result or _FakeDiarResult()
        self.generate = MagicMock(return_value=self._result)


def _engine_mod():
    return importlib.import_module("server.core.sortformer_engine")


# ---------------------------------------------------------------------------
# sortformer_available()
# ---------------------------------------------------------------------------


class TestSortformerAvailable:
    def test_returns_true_when_has_mlx_audio_true(self) -> None:
        mod = _engine_mod()
        with patch.object(mod, "HAS_MLX_AUDIO", True):
            assert mod.sortformer_available() is True

    def test_returns_false_when_has_mlx_audio_false(self) -> None:
        mod = _engine_mod()
        with patch.object(mod, "HAS_MLX_AUDIO", False):
            assert mod.sortformer_available() is False


# ---------------------------------------------------------------------------
# SortformerEngine — initialisation guard
# ---------------------------------------------------------------------------


class TestSortformerEngineInitGuard:
    def test_raises_import_error_when_mlx_audio_absent(self) -> None:
        mod = _engine_mod()
        with patch.object(mod, "HAS_MLX_AUDIO", False):
            with pytest.raises(ImportError, match="mlx-audio is required"):
                mod.SortformerEngine()

    def test_init_succeeds_when_mlx_audio_present(self) -> None:
        mod = _engine_mod()
        fake_load = MagicMock(return_value=_FakeSortformerModel())
        with (
            patch.object(mod, "HAS_MLX_AUDIO", True),
            patch.object(mod, "_load_sortformer", fake_load),
        ):
            engine = mod.SortformerEngine()
            assert engine is not None
            assert not engine.is_loaded()

    def test_default_model_name(self) -> None:
        mod = _engine_mod()
        fake_load = MagicMock(return_value=_FakeSortformerModel())
        with (
            patch.object(mod, "HAS_MLX_AUDIO", True),
            patch.object(mod, "_load_sortformer", fake_load),
        ):
            engine = mod.SortformerEngine()
            assert "sortformer" in engine.model_name.lower()

    def test_custom_threshold(self) -> None:
        mod = _engine_mod()
        fake_load = MagicMock(return_value=_FakeSortformerModel())
        with (
            patch.object(mod, "HAS_MLX_AUDIO", True),
            patch.object(mod, "_load_sortformer", fake_load),
        ):
            engine = mod.SortformerEngine(threshold=0.7)
            assert engine.threshold == 0.7


# ---------------------------------------------------------------------------
# SortformerEngine — lifecycle
# ---------------------------------------------------------------------------


class TestSortformerEngineLifecycle:
    def test_not_loaded_initially(self) -> None:
        mod = _engine_mod()
        fake_load = MagicMock(return_value=_FakeSortformerModel())
        with (
            patch.object(mod, "HAS_MLX_AUDIO", True),
            patch.object(mod, "_load_sortformer", fake_load),
        ):
            engine = mod.SortformerEngine()
            assert not engine.is_loaded()

    def test_load_sets_loaded(self) -> None:
        mod = _engine_mod()
        fake_model = _FakeSortformerModel()
        fake_load = MagicMock(return_value=fake_model)
        with (
            patch.object(mod, "HAS_MLX_AUDIO", True),
            patch.object(mod, "_load_sortformer", fake_load),
        ):
            engine = mod.SortformerEngine()
            engine.load()
            assert engine.is_loaded()
            fake_load.assert_called_once_with(engine.model_name)

    def test_load_is_idempotent(self) -> None:
        """Calling load() a second time must be a no-op."""
        mod = _engine_mod()
        fake_load = MagicMock(return_value=_FakeSortformerModel())
        with (
            patch.object(mod, "HAS_MLX_AUDIO", True),
            patch.object(mod, "_load_sortformer", fake_load),
        ):
            engine = mod.SortformerEngine()
            engine.load()
            engine.load()
            fake_load.assert_called_once()

    def test_unload_clears_state(self) -> None:
        mod = _engine_mod()
        fake_load = MagicMock(return_value=_FakeSortformerModel())
        with (
            patch.object(mod, "HAS_MLX_AUDIO", True),
            patch.object(mod, "_load_sortformer", fake_load),
        ):
            engine = mod.SortformerEngine()
            engine.load()
            engine.unload()
            assert not engine.is_loaded()
            assert engine._model is None

    def test_unload_when_not_loaded_is_safe(self) -> None:
        mod = _engine_mod()
        fake_load = MagicMock(return_value=_FakeSortformerModel())
        with (
            patch.object(mod, "HAS_MLX_AUDIO", True),
            patch.object(mod, "_load_sortformer", fake_load),
        ):
            engine = mod.SortformerEngine()
            engine.unload()  # must not raise


# ---------------------------------------------------------------------------
# SortformerEngine — diarize_audio
# ---------------------------------------------------------------------------


class TestSortformerEngineDiarize:
    def _make_loaded_engine(self, fake_model: _FakeSortformerModel | None = None):
        mod = _engine_mod()
        fake = fake_model or _FakeSortformerModel()
        fake_load = MagicMock(return_value=fake)
        ctx = patch.multiple(
            mod.__name__,
            HAS_MLX_AUDIO=True,
            _load_sortformer=fake_load,
        )
        ctx.start()
        engine = mod.SortformerEngine()
        engine.load()
        return engine, fake, ctx

    def test_returns_diarization_result_type(self) -> None:
        engine, _, ctx = self._make_loaded_engine()
        try:
            from server.core.diarization_engine import DiarizationResult

            audio = np.zeros(16000, dtype=np.float32)
            result = engine.diarize_audio(audio, sample_rate=16000)
            assert isinstance(result, DiarizationResult)
        finally:
            ctx.stop()

    def test_segment_count(self) -> None:
        engine, _, ctx = self._make_loaded_engine()
        try:
            audio = np.zeros(16000, dtype=np.float32)
            result = engine.diarize_audio(audio, sample_rate=16000)
            assert len(result.segments) == 3
        finally:
            ctx.stop()

    def test_speaker_labels(self) -> None:
        engine, _, ctx = self._make_loaded_engine()
        try:
            audio = np.zeros(16000, dtype=np.float32)
            result = engine.diarize_audio(audio, sample_rate=16000)
            speakers = {seg.speaker for seg in result.segments}
            assert speakers == {"SPEAKER_00", "SPEAKER_01"}
        finally:
            ctx.stop()

    def test_num_speakers_count(self) -> None:
        engine, _, ctx = self._make_loaded_engine()
        try:
            audio = np.zeros(16000, dtype=np.float32)
            result = engine.diarize_audio(audio, sample_rate=16000)
            assert result.num_speakers == 2
        finally:
            ctx.stop()

    def test_segment_timestamps(self) -> None:
        engine, _, ctx = self._make_loaded_engine()
        try:
            audio = np.zeros(16000, dtype=np.float32)
            result = engine.diarize_audio(audio, sample_rate=16000)
            assert result.segments[0].start == 0.0
            assert result.segments[0].end == 2.0
            assert result.segments[1].start == 2.5
            assert result.segments[1].end == 5.0
        finally:
            ctx.stop()

    def test_diarize_auto_loads_when_not_loaded(self) -> None:
        """diarize_audio() calls load() if the model has not been loaded yet."""
        mod = _engine_mod()
        fake_model = _FakeSortformerModel()
        fake_load = MagicMock(return_value=fake_model)
        with (
            patch.object(mod, "HAS_MLX_AUDIO", True),
            patch.object(mod, "_load_sortformer", fake_load),
        ):
            engine = mod.SortformerEngine()
            assert not engine.is_loaded()
            audio = np.zeros(16000, dtype=np.float32)
            result = engine.diarize_audio(audio, sample_rate=16000)
        assert engine.is_loaded()
        assert len(result.segments) == 3
        fake_load.assert_called_once()

    def test_passes_threshold_to_generate(self) -> None:
        """The engine's threshold value must be forwarded to model.generate()."""
        mod = _engine_mod()
        fake_model = _FakeSortformerModel()
        fake_load = MagicMock(return_value=fake_model)
        with (
            patch.object(mod, "HAS_MLX_AUDIO", True),
            patch.object(mod, "_load_sortformer", fake_load),
        ):
            engine = mod.SortformerEngine(threshold=0.75)
            engine.load()
            audio = np.zeros(16000, dtype=np.float32)
            engine.diarize_audio(audio, sample_rate=16000)
        call_kwargs = fake_model.generate.call_args[1]
        assert call_kwargs.get("threshold") == pytest.approx(0.75)

    def test_single_speaker_result(self) -> None:
        single_result = _FakeDiarResult([_FakeDiarSegment("SPEAKER_00", 0.0, 5.0)])
        fake_model = _FakeSortformerModel(single_result)
        engine, _, ctx = self._make_loaded_engine(fake_model)
        try:
            audio = np.zeros(16000, dtype=np.float32)
            result = engine.diarize_audio(audio, sample_rate=16000)
            assert result.num_speakers == 1
            assert result.segments[0].speaker == "SPEAKER_00"
        finally:
            ctx.stop()

    def test_generate_receives_file_path(self) -> None:
        """diarize_audio() writes a temp WAV and passes its path to generate()."""
        engine, fake_model, ctx = self._make_loaded_engine()
        try:
            audio = np.zeros(16000, dtype=np.float32)
            engine.diarize_audio(audio, sample_rate=16000)
            # generate() must have been called with a positional path argument
            args, _ = fake_model.generate.call_args
            assert len(args) == 1
            assert isinstance(args[0], str)
            assert args[0].endswith(".wav")
        finally:
            ctx.stop()
