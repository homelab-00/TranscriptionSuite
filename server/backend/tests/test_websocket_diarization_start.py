"""GH-258: the WebSocket `start` frame carries diarization options."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from server.api.routes import websocket as ws


def _session():
    # Plain MagicMock, NOT spec=TranscriptionSession: `spec` builds its allowed
    # attribute set from dir(cls), which excludes anything assigned in __init__,
    # so `session._current_job_id = None` would raise AttributeError.
    session = MagicMock()
    session.client_name = "test-client"
    session._current_job_id = None
    session.start_recording = AsyncMock()
    session.send_message = AsyncMock()
    return session


def _dispatch(data: dict) -> dict:
    """Run handle_client_message for a `start` frame; return start_recording kwargs."""
    session = _session()
    model_manager = MagicMock()
    model_manager.job_tracker.try_start_job.return_value = (True, "job-1", None)

    with (
        patch("server.core.model_manager.get_model_manager", return_value=model_manager),
        patch.object(ws, "_create_job"),
    ):
        asyncio.run(ws.handle_client_message(session, {"type": "start", "data": data}))

    assert session.start_recording.await_count == 1
    return session.start_recording.await_args.kwargs


def test_diarization_defaults_to_off_when_absent():
    kwargs = _dispatch({})
    assert kwargs["diarization"] is False
    assert kwargs["expected_speakers"] is None


def test_diarization_true_is_accepted():
    assert _dispatch({"diarization": True})["diarization"] is True


@pytest.mark.parametrize("bad", ["yes", 1, None, [], {}])
def test_non_bool_diarization_is_rejected(bad):
    assert _dispatch({"diarization": bad})["diarization"] is False


@pytest.mark.parametrize("value", [1, 2, 10])
def test_expected_speakers_in_range_is_accepted(value):
    kwargs = _dispatch({"diarization": True, "expected_speakers": value})
    assert kwargs["expected_speakers"] == value


@pytest.mark.parametrize("bad", [0, -1, 11, 99, "2", 2.5, None])
def test_expected_speakers_out_of_range_or_wrong_type_becomes_none(bad):
    kwargs = _dispatch({"diarization": True, "expected_speakers": bad})
    assert kwargs["expected_speakers"] is None


def test_bool_true_is_not_accepted_as_a_speaker_count():
    """`True` is an int in Python and 1 <= True <= 10 - it must still be rejected."""
    kwargs = _dispatch({"diarization": True, "expected_speakers": True})
    assert kwargs["expected_speakers"] is None


def test_notebook_auto_add_forwards_speaker_segments(tmp_path):
    """GH-258: a diarized recording must reach the Notebook WITH its speakers."""
    segments = [{"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0}]
    result = MagicMock(text="SPEAKER_00: hi", segments=[{"text": "hi", "words": []}])

    # Real files on purpose. `_free_path` loops `while candidate.exists()`, so
    # patching Path.exists to a blanket True spins forever looking for a free
    # name; a real (absent) destination terminates on the first candidate.
    audio_path = tmp_path / "session.wav"
    audio_path.write_bytes(b"\x00\x00")

    with (
        patch("server.config.get_config") as get_config,
        patch("server.core.audio_utils.convert_to_mp3"),
        patch("server.core.stt.backends.factory.detect_backend_type", return_value="whisperx"),
        patch("server.database.database.save_longform_to_database", return_value=7) as save,
    ):
        get_config.return_value.get.return_value = str(tmp_path / "audio")
        recording_id = ws._save_session_to_notebook(
            audio_path=audio_path,
            duration_seconds=12.0,
            result=result,
            model_name="large-v3",
            diarization_segments=segments,
        )

    assert recording_id == 7
    assert save.call_args.kwargs["diarization_segments"] == segments
