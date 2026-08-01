"""Tests for the parallel transcription + diarization orchestrator."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest
from server.core.model_manager import ModelManager, TranscriptionCancelledError
from server.core.parallel_diarize import (
    transcribe_and_diarize,
    transcribe_then_diarize,
)


def _make_engine(result=None, side_effect=None):
    """Create a mock AudioToTextRecorder."""
    engine = MagicMock()
    if side_effect is not None:
        engine.transcribe_file.side_effect = side_effect
    else:
        engine.transcribe_file.return_value = result or MagicMock(words=[], segments=[])
    return engine


def _make_model_manager(diar_segments=None, load_error=None, diarize_error=None):
    """Create a mock ModelManager with diarization support."""
    mm = MagicMock()
    mm.get_diarization_feature_status.return_value = {"reason": "unavailable"}

    if load_error is not None:
        mm.load_diarization_model.side_effect = load_error
    else:
        diar_engine = MagicMock()
        if diarize_error is not None:
            diar_engine.diarize_audio.side_effect = diarize_error
        else:
            diar_result = MagicMock()
            diar_result.segments = diar_segments or []
            diar_result.num_speakers = 2
            diar_engine.diarize_audio.return_value = diar_result
        mm.diarization_engine = diar_engine

    return mm


@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_both_succeed_and_run_on_different_threads(mock_load_audio):
    """Transcription and diarization both succeed, running on separate threads."""
    transcribe_thread_name = None
    diarize_thread_name = None

    transcript_result = MagicMock(words=[], segments=[])
    diar_segments = [MagicMock()]

    engine = MagicMock()

    def fake_transcribe(*args, **kwargs):
        nonlocal transcribe_thread_name
        transcribe_thread_name = threading.current_thread().name
        return transcript_result

    engine.transcribe_file.side_effect = fake_transcribe

    mm = MagicMock()
    diar_engine = MagicMock()
    diar_result = MagicMock()
    diar_result.segments = diar_segments
    diar_result.num_speakers = 2

    def fake_diarize(*args, **kwargs):
        nonlocal diarize_thread_name
        diarize_thread_name = threading.current_thread().name
        return diar_result

    diar_engine.diarize_audio.side_effect = fake_diarize
    mm.diarization_engine = diar_engine

    result, diar = transcribe_and_diarize(
        engine=engine,
        model_manager=mm,
        file_path="/tmp/test.wav",
    )

    assert result is transcript_result
    assert diar is diar_result
    assert transcribe_thread_name is not None
    assert diarize_thread_name is not None
    assert "parallel_diarize" in transcribe_thread_name
    assert "parallel_diarize" in diarize_thread_name


@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_diarization_model_load_fails_graceful_fallback(mock_load_audio):
    """When load_diarization_model() raises, transcription still runs normally."""
    transcript_result = MagicMock(words=[], segments=[])
    engine = _make_engine(result=transcript_result)
    mm = _make_model_manager(load_error=ValueError("HF token missing"))

    result, diar = transcribe_and_diarize(
        engine=engine,
        model_manager=mm,
        file_path="/tmp/test.wav",
    )

    assert result is transcript_result
    assert diar is None
    engine.transcribe_file.assert_called_once()


@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_diarization_runtime_error_returns_transcript(mock_load_audio):
    """When diarize_audio() raises at runtime, transcript is still returned."""
    transcript_result = MagicMock(words=[], segments=[])
    engine = _make_engine(result=transcript_result)
    mm = _make_model_manager(diarize_error=RuntimeError("GPU OOM"))

    result, diar = transcribe_and_diarize(
        engine=engine,
        model_manager=mm,
        file_path="/tmp/test.wav",
    )

    assert result is transcript_result
    assert diar is None


@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_transcription_cancellation_propagates(mock_load_audio):
    """TranscriptionCancelledError from transcription propagates to caller."""
    engine = _make_engine(side_effect=TranscriptionCancelledError("cancelled"))
    mm = _make_model_manager()

    with pytest.raises(TranscriptionCancelledError):
        transcribe_and_diarize(
            engine=engine,
            model_manager=mm,
            file_path="/tmp/test.wav",
        )


@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_transcription_error_propagates(mock_load_audio):
    """General transcription errors propagate to caller."""
    engine = _make_engine(side_effect=RuntimeError("model crashed"))
    mm = _make_model_manager()

    with pytest.raises(RuntimeError, match="model crashed"):
        transcribe_and_diarize(
            engine=engine,
            model_manager=mm,
            file_path="/tmp/test.wav",
        )


def test_load_audio_failure_falls_back_to_transcription_only():
    """When load_audio fails, transcription still runs without diarization."""
    transcript_result = MagicMock(words=[], segments=[])
    engine = _make_engine(result=transcript_result)
    mm = MagicMock()

    with patch(
        "server.core.audio_utils.load_audio",
        side_effect=RuntimeError("corrupt file"),
    ):
        result, diar = transcribe_and_diarize(
            engine=engine,
            model_manager=mm,
            file_path="/tmp/test.wav",
        )

    assert result is transcript_result
    assert diar is None
    engine.transcribe_file.assert_called_once()


@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_passes_expected_speakers_to_diarize(mock_load_audio):
    """The expected_speakers parameter is forwarded to diarize_audio."""
    engine = _make_engine()
    mm = _make_model_manager()

    transcribe_and_diarize(
        engine=engine,
        model_manager=mm,
        file_path="/tmp/test.wav",
        expected_speakers=3,
    )

    mm.diarization_engine.diarize_audio.assert_called_once()
    call_kwargs = mm.diarization_engine.diarize_audio.call_args
    assert call_kwargs[1]["num_speakers"] == 3


@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_passes_language_and_task_to_transcribe(mock_load_audio):
    """Language and task are forwarded to engine.transcribe_file."""
    engine = _make_engine()
    mm = _make_model_manager()

    transcribe_and_diarize(
        engine=engine,
        model_manager=mm,
        file_path="/tmp/test.wav",
        language="fr",
        task="translate",
        translation_target_language="en",
    )

    engine.transcribe_file.assert_called_once()
    call_kwargs = engine.transcribe_file.call_args[1]
    assert call_kwargs["language"] == "fr"
    assert call_kwargs["task"] == "translate"
    assert call_kwargs["translation_target_language"] == "en"


@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_parallel_success_unloads_diarization_model(mock_load_audio):
    """After a successful parallel run the diarization model must be unloaded."""
    engine = MagicMock()
    engine.transcribe_file.return_value = MagicMock(words=[], segments=[])
    mm = MagicMock()
    diar_engine = MagicMock()
    diar_result = MagicMock()
    diar_result.segments = [MagicMock()]
    diar_result.num_speakers = 2
    diar_engine.diarize_audio.return_value = diar_result
    mm.diarization_engine = diar_engine

    result, diar = transcribe_and_diarize(
        engine=engine, model_manager=mm, file_path="/tmp/test.wav"
    )

    assert diar is diar_result
    mm.unload_diarization_model.assert_called_once()


@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_parallel_transcribe_failure_still_unloads_diarization_model(mock_load_audio):
    """A transcription crash must not leave the diarization model resident."""
    engine = MagicMock()
    engine.transcribe_file.side_effect = RuntimeError("boom")
    mm = MagicMock()
    mm.diarization_engine = MagicMock()

    with pytest.raises(RuntimeError):
        transcribe_and_diarize(engine=engine, model_manager=mm, file_path="/tmp/test.wav")

    mm.unload_diarization_model.assert_called_once()


@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_parallel_unload_failure_does_not_mask_original_exception(mock_load_audio):
    """A raising unload_diarization_model in the outer finally must not replace
    the exception already propagating from transcription (e.g. a cancellation) -
    it should be logged and swallowed, not let it clobber the real error."""
    engine = MagicMock()
    engine.transcribe_file.side_effect = RuntimeError("distinctive transcribe failure")
    mm = MagicMock()
    mm.diarization_engine = MagicMock()
    mm.unload_diarization_model.side_effect = RuntimeError("unload exploded")

    with pytest.raises(RuntimeError, match="distinctive transcribe failure"):
        transcribe_and_diarize(engine=engine, model_manager=mm, file_path="/tmp/test.wav")


@patch("server.core.audio_utils.load_audio", side_effect=RuntimeError("bad audio"))
def test_preload_failure_unloads_diarization_model(mock_load_audio):
    """load_diarization_model may succeed before load_audio fails - release it."""
    engine = MagicMock()
    engine.transcribe_file.return_value = MagicMock(words=[], segments=[])
    mm = MagicMock()
    mm.diarization_engine = MagicMock()

    result, diar = transcribe_and_diarize(
        engine=engine, model_manager=mm, file_path="/tmp/test.wav"
    )

    assert diar is None
    mm.unload_diarization_model.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# Sequential: transcribe_then_diarize
# ──────────────────────────────────────────────────────────────────────────────


@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_sequential_both_succeed(mock_load_audio):
    """Transcription completes before diarization starts (sequential)."""
    call_order: list[str] = []

    transcript_result = MagicMock(words=[], segments=[])
    engine = MagicMock()

    def fake_transcribe(*args, **kwargs):
        call_order.append("transcribe")
        return transcript_result

    engine.transcribe_file.side_effect = fake_transcribe

    mm = MagicMock()
    diar_engine = MagicMock()
    diar_result = MagicMock()
    diar_result.segments = [MagicMock()]
    diar_result.num_speakers = 2

    def fake_diarize(*args, **kwargs):
        call_order.append("diarize")
        return diar_result

    diar_engine.diarize_audio.side_effect = fake_diarize
    mm.diarization_engine = diar_engine

    result, diar = transcribe_then_diarize(
        engine=engine,
        model_manager=mm,
        file_path="/tmp/test.wav",
    )

    assert result is transcript_result
    assert diar is diar_result
    # Verify sequential order: transcription must finish before diarization
    assert call_order == ["transcribe", "diarize"]


@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_sequential_diarization_failure_returns_transcript(mock_load_audio):
    """When diarization fails in sequential mode, transcript is still returned."""
    transcript_result = MagicMock(words=[], segments=[])
    engine = _make_engine(result=transcript_result)
    mm = _make_model_manager(diarize_error=RuntimeError("GPU OOM"))

    result, diar = transcribe_then_diarize(
        engine=engine,
        model_manager=mm,
        file_path="/tmp/test.wav",
    )

    assert result is transcript_result
    assert diar is None


def test_sequential_cancellation_propagates():
    """TranscriptionCancelledError propagates from sequential transcription."""
    engine = _make_engine(side_effect=TranscriptionCancelledError("cancelled"))
    mm = _make_model_manager()

    with pytest.raises(TranscriptionCancelledError):
        transcribe_then_diarize(
            engine=engine,
            model_manager=mm,
            file_path="/tmp/test.wav",
        )


@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_sequential_passes_parameters(mock_load_audio):
    """Language, task, and expected_speakers are forwarded correctly in sequential mode."""
    engine = _make_engine()
    mm = _make_model_manager()

    transcribe_then_diarize(
        engine=engine,
        model_manager=mm,
        file_path="/tmp/test.wav",
        language="de",
        task="translate",
        translation_target_language="en",
        expected_speakers=4,
    )

    # Check transcription params
    engine.transcribe_file.assert_called_once()
    t_kwargs = engine.transcribe_file.call_args[1]
    assert t_kwargs["language"] == "de"
    assert t_kwargs["task"] == "translate"
    assert t_kwargs["translation_target_language"] == "en"

    # Check diarization params
    mm.diarization_engine.diarize_audio.assert_called_once()
    d_kwargs = mm.diarization_engine.diarize_audio.call_args[1]
    assert d_kwargs["num_speakers"] == 4


# ──────────────────────────────────────────────────────────────────────────────
# ModelManager.unload_diarization_model idempotency
#
# The Sortformer branch in transcribe_and_diarize relies on this method being
# safe to call twice: transcribe_then_diarize()'s own finally unloads first,
# then the outer finally in transcribe_and_diarize unloads again on the way
# out. This test pins the real (non-mocked) implementation's idempotency
# guard so a future change to it can't silently reintroduce a double
# teardown. Lives here rather than in test_model_manager_init.py (scoped to
# init/feature-flag logic) or test_ensure_transcription_loaded.py (scoped to
# the transcription-reload lock) - neither covers diarization unload
# lifecycle, and this file is where that lifecycle is exercised end to end.
# ──────────────────────────────────────────────────────────────────────────────


def test_unload_diarization_model_is_idempotent():
    """Calling unload_diarization_model twice must only tear down once."""
    mgr = object.__new__(ModelManager)
    engine = MagicMock()
    mgr._diarization_engine = engine

    mgr.unload_diarization_model()
    mgr.unload_diarization_model()

    engine.unload.assert_called_once()
    assert mgr._diarization_engine is None
