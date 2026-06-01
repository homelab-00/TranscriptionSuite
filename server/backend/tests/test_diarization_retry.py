"""GH #122: bounded retry on transient CUDA errors during diarization.

On WSL2 the pyannote pipeline intermittently raises
``RuntimeError: CUDA driver error: device not ready`` right after a model swap.
Previously this aborted diarization and silently dropped speaker labels. The
retry loop in ``DiarizationEngine.diarize_audio`` now self-heals transient CUDA
errors while still failing fast on unrelated errors.
"""

from __future__ import annotations

import importlib
import types

import numpy as np
import pytest


def _import_engine_module():
    return importlib.import_module("server.core.diarization_engine")


class _FakeTensor:
    def float(self) -> _FakeTensor:
        return self

    def unsqueeze(self, _dim: int) -> _FakeTensor:
        return self


class _FakeTorch:
    """Minimal torch shim so diarize_audio's waveform prep is env-independent."""

    @staticmethod
    def from_numpy(_arr):  # noqa: ANN001
        return _FakeTensor()


class _FakeAnnotation:
    def __init__(self, tracks: list[tuple[float, float, str]]) -> None:
        self._tracks = tracks

    def itertracks(self, yield_label: bool = True):  # noqa: ARG002
        for start, end, speaker in self._tracks:
            yield types.SimpleNamespace(start=start, end=end), None, speaker


class _FlakyPipeline:
    """Raises the queued exceptions on successive calls, then succeeds."""

    def __init__(self, errors: list[Exception]) -> None:
        self._errors = list(errors)
        self.calls = 0

    def __call__(self, _audio_input, **_kwargs):  # noqa: ANN001
        self.calls += 1
        if self._errors:
            raise self._errors.pop(0)
        return _FakeAnnotation([(0.0, 1.0, "SPEAKER_00")])


def _make_engine(module, pipeline) -> object:
    """Build a DiarizationEngine without running its heavy __init__."""
    engine = object.__new__(module.DiarizationEngine)
    engine._loaded = True
    engine._pipeline = pipeline
    engine.num_speakers = None
    engine.min_speakers = None
    engine.max_speakers = None
    return engine


@pytest.fixture
def patched_module(monkeypatch):
    module = _import_engine_module()
    # Make GPU-dependent calls inert and instant.
    monkeypatch.setattr(module, "torch", _FakeTorch())
    monkeypatch.setattr(module, "HAS_TORCH", True)
    monkeypatch.setattr(module, "clear_gpu_cache", lambda: None)
    monkeypatch.setattr("server.core.diarization_engine.time.sleep", lambda *a, **k: None)
    return module


def test_retries_then_succeeds_on_transient_cuda_error(patched_module) -> None:
    pipeline = _FlakyPipeline([RuntimeError("CUDA driver error: device not ready")])
    engine = _make_engine(patched_module, pipeline)

    result = engine.diarize_audio(np.zeros(16000, dtype=np.float32), 16000)

    assert pipeline.calls == 2  # 1 failure + 1 successful retry
    assert result.num_speakers == 1


def test_non_transient_error_is_not_retried(patched_module) -> None:
    pipeline = _FlakyPipeline([ValueError("malformed audio input")])
    engine = _make_engine(patched_module, pipeline)

    with pytest.raises(ValueError, match="malformed audio input"):
        engine.diarize_audio(np.zeros(16000, dtype=np.float32), 16000)

    assert pipeline.calls == 1  # failed fast, no retry


def test_transient_error_reraised_after_retries_exhausted(patched_module) -> None:
    # 4 transient failures = more than the 3 configured retries.
    errors = [RuntimeError("CUDA driver error: device not ready") for _ in range(4)]
    pipeline = _FlakyPipeline(errors)
    engine = _make_engine(patched_module, pipeline)

    with pytest.raises(RuntimeError, match="device not ready"):
        engine.diarize_audio(np.zeros(16000, dtype=np.float32), 16000)

    # 1 initial attempt + len(_CUDA_RETRY_DELAYS) retries.
    assert pipeline.calls == len(patched_module._CUDA_RETRY_DELAYS) + 1


def test_out_of_memory_is_not_treated_as_transient(patched_module) -> None:
    pipeline = _FlakyPipeline([RuntimeError("CUDA out of memory")])
    engine = _make_engine(patched_module, pipeline)

    with pytest.raises(RuntimeError, match="out of memory"):
        engine.diarize_audio(np.zeros(16000, dtype=np.float32), 16000)

    assert pipeline.calls == 1  # OOM is not retried — retrying cannot help
