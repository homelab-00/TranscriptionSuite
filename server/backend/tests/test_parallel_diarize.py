"""Tests for the parallel transcription + diarization orchestrator."""

from __future__ import annotations

import importlib
import importlib.util
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _ensure_server_package_alias() -> None:
    if "server" in sys.modules:
        return

    backend_root = Path(__file__).resolve().parents[1]
    init_file = backend_root / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "server",
        init_file,
        submodule_search_locations=[str(backend_root)],
    )
    assert spec is not None and spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules["server"] = module
    spec.loader.exec_module(module)


_ensure_server_package_alias()

from server.core.model_manager import TranscriptionCancelledError  # noqa: E402
from server.core.parallel_diarize import transcribe_and_diarize  # noqa: E402


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
