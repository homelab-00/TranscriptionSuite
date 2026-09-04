"""A GPU out-of-memory failure must take the poisoned backend down with it.

Incident of 2026-09-04: a longform WebSocket transcription died with
``CUDA failed with error out of memory`` at 22.65/24 GB VRAM. The user freed
VRAM and pressed Retry; that retry failed in one second with
``parallel_for failed: cudaErrorInvalidDevice: invalid device ordinal``, a
*sticky* error code left on the CUDA context by the OOM and unrelated to the
VRAM actually free at that moment. A second retry 19 seconds later succeeded.

The OOM handler used to re-raise without touching ``self._backend``, so the
CTranslate2 instance kept its broken context and every retry replayed the same
failure. ``_model_loaded`` was never cleared either, so ``load_model()`` and
``ensure_transcription_loaded()`` both no-opped and could not heal it.

These tests pin the fix: on a *classified* OOM the recorder discards its owned
backend (``_backend is None``, ``_model_loaded is False``) while still raising
the ``GpuOutOfMemoryError`` with its remedy. Reset only - no auto-retry.

Run:  ../../build/.venv/bin/pytest tests/test_oom_discards_backend.py -v --tb=short
"""

from __future__ import annotations

import sys
import threading
import types
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# The observed OOM wordings live with the classifier's own tests; import them
# rather than retyping strings that were copied verbatim from container logs.
from test_cuda_oom_classification import CT2_PLAIN_OOM, CT2_THRUST_OOM


def _ensure_engine_importable() -> None:
    """Install lightweight stubs for engine top-level imports.

    Mirrors tests/test_stt_engine_shared_backend.py - keep the two in sync.
    """
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
    from server.core.stt.backends.base import (  # noqa: E402
        BackendSegment,
        BackendTranscriptionInfo,
        GpuOutOfMemoryError,
        PartialTranscriptionError,
    )
    from server.core.stt.engine import AudioToTextRecorder  # noqa: E402


AUDIO = np.zeros(16000, dtype=np.float32)


def _bare_recorder(backend: Any, *, owns_backend: bool = True) -> AudioToTextRecorder:
    """Build a recorder without running __init__ (which starts a worker thread).

    Only the attributes the two transcription entry points actually touch are
    populated, matching the bare-recorder pattern in
    tests/test_stt_engine_shared_backend.py.
    """
    rec = object.__new__(AudioToTextRecorder)
    rec.transcription_lock = threading.Lock()
    rec._backend = backend
    rec._model_loaded = True
    rec._owns_backend = owns_backend
    rec.instance_name = "main"
    rec.model_name = "tiny"
    rec.normalize_audio = False
    rec.language = "en"
    rec.task = "transcribe"
    rec.translation_target_language = None
    rec.initial_prompt = None
    rec.beam_size = 5
    rec.suppress_tokens = [-1]
    rec.faster_whisper_vad_filter = False
    rec.ensure_sentence_starting_uppercase = False
    rec.ensure_sentence_ends_with_period = False
    rec.state = "inactive"
    rec.audio = None
    return rec


def _make_partial(message: str = "chunk 4 of 9 failed") -> PartialTranscriptionError:
    """A salvageable partial carrying one completed chunk."""
    return PartialTranscriptionError(
        message,
        segments=[BackendSegment(text="salvaged words", start=0.0, end=1.0)],
        info=BackendTranscriptionInfo(language="en", language_probability=0.9),
        completed_seconds=42.0,
    )


def _raise_partial_from(cause: BaseException):
    """Return a side_effect that raises a partial chained to ``cause``.

    Raising inside an ``except`` block is what sets ``__cause__`` the way a real
    chunking backend does, which is exactly what the fix reads.
    """

    def _side_effect(*_a: Any, **_kw: Any):
        try:
            raise cause
        except BaseException as err:
            raise _make_partial() from err

    return _side_effect


class TestTranscribeAudioDiscardsOnOom:
    @pytest.mark.parametrize(
        "message",
        [CT2_PLAIN_OOM, CT2_THRUST_OOM],
        ids=["ct2-plain", "ct2-thrust-misreport"],
    )
    def test_backend_is_discarded_and_the_oom_still_propagates(self, message: str) -> None:
        """The thrust wording is the regression guard for the 2026-09-04 incident."""
        backend = MagicMock()
        backend.transcribe.side_effect = RuntimeError(message)
        rec = _bare_recorder(backend)

        with pytest.raises(GpuOutOfMemoryError) as excinfo:
            rec.transcribe_audio(AUDIO)

        assert rec._backend is None
        assert rec._model_loaded is False
        backend.unload.assert_called_once_with()
        # The remedy must survive the discard - it is the whole user-facing value
        # of the classification.
        assert excinfo.value.remedy
        assert message in str(excinfo.value)

    def test_non_oom_failure_keeps_the_backend(self) -> None:
        """A plain bug must not cost a model reload."""
        backend = MagicMock()
        backend.transcribe.side_effect = ValueError("boom")
        rec = _bare_recorder(backend)

        with pytest.raises(ValueError, match="boom"):
            rec.transcribe_audio(AUDIO)

        assert rec._backend is backend
        assert rec._model_loaded is True
        backend.unload.assert_not_called()

    def test_shared_backend_is_left_attached(self) -> None:
        """A borrowed Live Mode backend is not ours to tear down or drop."""
        backend = MagicMock()
        backend.transcribe.side_effect = RuntimeError(CT2_PLAIN_OOM)
        rec = _bare_recorder(backend, owns_backend=False)

        with pytest.raises(GpuOutOfMemoryError):
            rec.transcribe_audio(AUDIO)

        assert rec._backend is backend
        backend.unload.assert_not_called()

    def test_failing_unload_still_detaches(self) -> None:
        """Guards the ``finally``: unload() on a poisoned context can itself trip
        the sticky CUDA error, and the recorder must not stay wedged on it."""
        backend = MagicMock()
        backend.transcribe.side_effect = RuntimeError(CT2_PLAIN_OOM)
        backend.unload.side_effect = RuntimeError(CT2_THRUST_OOM)
        rec = _bare_recorder(backend)

        with pytest.raises(GpuOutOfMemoryError):
            rec.transcribe_audio(AUDIO)

        assert rec._backend is None
        assert rec._model_loaded is False


class TestPartialResultsStillSalvaged:
    """Save first, clean up second - the durability invariant outranks the reset."""

    def test_partial_caused_by_oom_returns_the_text_and_discards(self) -> None:
        backend = MagicMock()
        backend.transcribe.side_effect = _raise_partial_from(RuntimeError(CT2_PLAIN_OOM))
        rec = _bare_recorder(backend)

        result = rec.transcribe_audio(AUDIO)

        assert result.partial is True
        assert "salvaged words" in result.text
        assert rec._backend is None
        assert rec._model_loaded is False
        backend.unload.assert_called_once_with()

    def test_partial_from_a_non_oom_cause_keeps_the_backend(self) -> None:
        backend = MagicMock()
        backend.transcribe.side_effect = _raise_partial_from(ValueError("corrupt chunk"))
        rec = _bare_recorder(backend)

        result = rec.transcribe_audio(AUDIO)

        assert result.partial is True
        assert "salvaged words" in result.text
        assert rec._backend is backend
        assert rec._model_loaded is True
        backend.unload.assert_not_called()


class TestPerformTranscriptionDiscardsOnOom:
    def test_oom_discards_the_backend(self) -> None:
        backend = MagicMock()
        backend.transcribe.side_effect = RuntimeError(CT2_THRUST_OOM)
        rec = _bare_recorder(backend)

        with pytest.raises(GpuOutOfMemoryError):
            rec._perform_transcription(AUDIO)

        assert rec._backend is None
        assert rec._model_loaded is False
        backend.unload.assert_called_once_with()

    def test_non_oom_keeps_the_backend(self) -> None:
        backend = MagicMock()
        backend.transcribe.side_effect = ValueError("boom")
        rec = _bare_recorder(backend)

        with pytest.raises(ValueError, match="boom"):
            rec._perform_transcription(AUDIO)

        assert rec._backend is backend
        backend.unload.assert_not_called()
