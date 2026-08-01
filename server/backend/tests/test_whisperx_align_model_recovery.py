"""WhisperX alignment must survive a failed alignment-model load.

`_align()` used to `del self._align_model` before loading the replacement. When
that load raised — a CUDA OOM during alignment is the common case, since the
alignment model is loaded while the transcription model is still resident — the
attribute stayed *deleted*, not None. Every later call then died on

    AttributeError: 'WhisperXBackend' object has no attribute '_align_model'

at the `if self._align_model is None` guard, which cannot short-circuit an
attribute that does not exist. The caller logs that as "alignment failed, using
raw timestamps" and continues, so a single OOM silently disabled word-level
timestamps for the entire life of the process.

Observed 2026-08-01: an alignment OOM at 07:12:31 left every subsequent
transcription in that container without alignment.
"""

from __future__ import annotations

import importlib
import sys
import types

import numpy as np
import pytest

pytestmark = pytest.mark.usefixtures("torch_stub")


def _install_soundfile_stub() -> None:
    if "soundfile" not in sys.modules:
        soundfile_stub = types.ModuleType("soundfile")
        soundfile_stub.read = lambda *args, **kwargs: (
            np.zeros(16000, dtype=np.float32),
            16000,
        )
        sys.modules["soundfile"] = soundfile_stub


def _import_whisperx_backend():
    _install_soundfile_stub()
    return importlib.import_module("server.core.stt.backends.whisperx_backend")


class _BoomOnLoad:
    """Stands in for the `whisperx` module: loading an align model always fails."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.load_calls = 0

    def load_align_model(self, *args, **kwargs):
        self.load_calls += 1
        raise self._exc

    def align(self, *args, **kwargs):  # pragma: no cover - never reached
        raise AssertionError("align() must not run when the model failed to load")


def _make_backend(module):
    """A backend instance with an alignment model already cached for English."""
    backend = object.__new__(module.WhisperXBackend)
    backend._device = "cpu"
    backend._align_model = object()
    backend._align_metadata = {"language": "en"}
    backend._align_language = "en"
    return backend


def test_failed_align_load_leaves_attribute_defined(monkeypatch):
    """A raising load_align_model must leave _align_model as None, not deleted."""
    module = _import_whisperx_backend()
    fake_whisperx = _BoomOnLoad(RuntimeError("CUDA out of memory"))
    monkeypatch.setattr(module, "_import_whisperx_modules", lambda: (fake_whisperx, None))

    backend = _make_backend(module)

    # Switching to a new language forces the reload path that used to `del`.
    with pytest.raises(RuntimeError, match="CUDA out of memory"):
        backend._align({"segments": []}, np.zeros(16000, dtype=np.float32), "el")

    # The attribute must still exist. `getattr` with no default raises
    # AttributeError on the old code, which is exactly the production failure.
    assert backend._align_model is None
    assert backend._align_metadata is None


def test_alignment_retries_after_a_failed_load(monkeypatch):
    """A later call must reach the loader again instead of dying on AttributeError."""
    module = _import_whisperx_backend()
    fake_whisperx = _BoomOnLoad(RuntimeError("CUDA out of memory"))
    monkeypatch.setattr(module, "_import_whisperx_modules", lambda: (fake_whisperx, None))

    backend = _make_backend(module)
    audio = np.zeros(16000, dtype=np.float32)

    with pytest.raises(RuntimeError):
        backend._align({"segments": []}, audio, "el")
    # Second attempt: previously AttributeError, so the loader was never retried.
    with pytest.raises(RuntimeError):
        backend._align({"segments": []}, audio, "el")

    assert fake_whisperx.load_calls == 2, (
        "the second alignment attempt must reach load_align_model again"
    )
