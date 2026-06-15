"""Tests for the ephemeral "Preview last N seconds" feature.

Covers TranscriptionSession.preview_transcription() and the `preview` message
dispatch in handle_client_message(). The defining invariant of this feature is
that a preview is a THROWAWAY UX aid: it must never persist a job, never create
an audio file, and never mutate recording state.

Run:  ../../build/.venv/bin/pytest tests/test_websocket_preview.py -v --tb=short
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from server.api.routes import websocket as ws_mod
from server.core import model_manager as mm_mod
from starlette.websockets import WebSocketState

# 16 kHz Int16 mono => 2 bytes/sample => 32000 bytes per second.
_BYTES_PER_SECOND = 16000 * 2


def _make_preview_session(
    *,
    is_recording: bool = True,
    audio_chunks: list[bytes] | None = None,
    sample_rate: int = 16000,
    translation_enabled: bool = False,
    preview_in_progress: bool = False,
) -> ws_mod.TranscriptionSession:
    """Build a TranscriptionSession for preview tests (bypasses __init__)."""
    session = object.__new__(ws_mod.TranscriptionSession)
    session.websocket = MagicMock()
    session.websocket.client_state = WebSocketState.CONNECTED
    session.websocket.send_json = AsyncMock()
    session.client_name = "test-client"
    session.is_recording = is_recording
    session.language = None
    session.audio_chunks = [] if audio_chunks is None else audio_chunks
    session.sample_rate = sample_rate
    session.translation_enabled = translation_enabled
    session.translation_target_language = "en"
    session._preview_in_progress = preview_in_progress
    session._preview_task = None
    session._current_job_id = "job-001"
    # Capture outbound messages directly.
    session.send_message = AsyncMock()
    return session


def _patch_engine(monkeypatch, *, text: str = "the last thing I said", raises: bool = False):
    """Patch model_manager so preview transcription uses a fake engine."""
    fake_engine = MagicMock()
    if raises:
        fake_engine.transcribe_audio.side_effect = RuntimeError("boom")
    else:
        fake_engine.transcribe_audio.return_value = SimpleNamespace(
            text=text, language="en", duration=20.0
        )
    fake_manager = MagicMock()
    fake_manager.ensure_transcription_loaded.return_value = fake_engine
    # Lazy `from server.core.model_manager import get_model_manager` inside the
    # method re-reads the attribute from the source module at call time.
    monkeypatch.setattr(mm_mod, "get_model_manager", lambda: fake_manager)
    return fake_engine


def _last_message(session) -> tuple[str, dict]:
    """Return (msg_type, data) of the last send_message call."""
    args, _ = session.send_message.call_args
    return args[0], (args[1] if len(args) > 1 else {})


# ── Happy path ─────────────────────────────────────────────────────────


def test_preview_happy_path_returns_text(monkeypatch):
    fake_engine = _patch_engine(monkeypatch, text="hello there")
    # 25 seconds of audio buffered; request 20.
    session = _make_preview_session(audio_chunks=[b"\x00" * (25 * _BYTES_PER_SECOND)])

    asyncio.run(session.preview_transcription(20))

    msg_type, data = _last_message(session)
    assert msg_type == "preview_result"
    assert data["text"] == "hello there"
    assert data["requested_seconds"] == 20
    assert data["actual_seconds"] == 20.0
    # Only the last 20s should have been sliced and transcribed.
    audio_arg = fake_engine.transcribe_audio.call_args.args[0]
    assert len(audio_arg) == 20 * 16000
    # Flag reset for the next request.
    assert session._preview_in_progress is False


def test_preview_does_not_persist(monkeypatch):
    """The defining invariant: preview never writes a job or result."""
    _patch_engine(monkeypatch)
    create = MagicMock()
    save = MagicMock()
    set_audio = MagicMock()
    monkeypatch.setattr(ws_mod, "_create_job", create)
    monkeypatch.setattr(ws_mod, "_save_result", save)
    monkeypatch.setattr(ws_mod, "_set_audio_path", set_audio)
    session = _make_preview_session(audio_chunks=[b"\x00" * (25 * _BYTES_PER_SECOND)])

    asyncio.run(session.preview_transcription(20))

    create.assert_not_called()
    save.assert_not_called()
    set_audio.assert_not_called()


def test_preview_does_not_change_recording_state(monkeypatch):
    _patch_engine(monkeypatch)
    session = _make_preview_session(audio_chunks=[b"\x00" * (25 * _BYTES_PER_SECOND)])

    asyncio.run(session.preview_transcription(20))

    assert session.is_recording is True


# ── Edge cases from the I/O matrix ─────────────────────────────────────


def test_preview_short_buffer_transcribes_what_exists(monkeypatch):
    fake_engine = _patch_engine(monkeypatch)
    # Only 6 seconds buffered; request 20.
    session = _make_preview_session(audio_chunks=[b"\x00" * (6 * _BYTES_PER_SECOND)])

    asyncio.run(session.preview_transcription(20))

    msg_type, data = _last_message(session)
    assert msg_type == "preview_result"
    assert data["actual_seconds"] == 6.0
    audio_arg = fake_engine.transcribe_audio.call_args.args[0]
    assert len(audio_arg) == 6 * 16000


def test_preview_clamps_below_minimum(monkeypatch):
    fake_engine = _patch_engine(monkeypatch)
    session = _make_preview_session(audio_chunks=[b"\x00" * (60 * _BYTES_PER_SECOND)])

    asyncio.run(session.preview_transcription(3))

    _, data = _last_message(session)
    assert data["requested_seconds"] == 10  # clamped up to the 10s floor
    assert len(fake_engine.transcribe_audio.call_args.args[0]) == 10 * 16000


def test_preview_clamps_above_maximum(monkeypatch):
    fake_engine = _patch_engine(monkeypatch)
    session = _make_preview_session(audio_chunks=[b"\x00" * (120 * _BYTES_PER_SECOND)])

    asyncio.run(session.preview_transcription(900))

    _, data = _last_message(session)
    assert data["requested_seconds"] == 60  # clamped down to the 60s ceiling
    assert len(fake_engine.transcribe_audio.call_args.args[0]) == 60 * 16000


def test_preview_rejected_when_not_recording(monkeypatch):
    _patch_engine(monkeypatch)
    session = _make_preview_session(is_recording=False, audio_chunks=[b"\x00" * _BYTES_PER_SECOND])

    asyncio.run(session.preview_transcription(20))

    msg_type, data = _last_message(session)
    assert msg_type == "preview_error"
    assert "not recording" in data["message"].lower()


def test_preview_rejected_when_no_audio(monkeypatch):
    _patch_engine(monkeypatch)
    session = _make_preview_session(audio_chunks=[])

    asyncio.run(session.preview_transcription(20))

    msg_type, data = _last_message(session)
    assert msg_type == "preview_error"
    assert "no audio" in data["message"].lower()


def test_preview_rejected_when_already_in_progress(monkeypatch):
    _patch_engine(monkeypatch)
    session = _make_preview_session(
        audio_chunks=[b"\x00" * (25 * _BYTES_PER_SECOND)], preview_in_progress=True
    )

    asyncio.run(session.preview_transcription(20))

    msg_type, data = _last_message(session)
    assert msg_type == "preview_error"
    assert "in progress" in data["message"].lower()


def test_preview_engine_error_sends_error_and_resets_flag(monkeypatch):
    _patch_engine(monkeypatch, raises=True)
    session = _make_preview_session(audio_chunks=[b"\x00" * (25 * _BYTES_PER_SECOND)])

    asyncio.run(session.preview_transcription(20))

    msg_type, data = _last_message(session)
    assert msg_type == "preview_error"
    assert data["message"] == "Preview failed"
    assert session._preview_in_progress is False  # reset in finally
    assert session.is_recording is True  # recording untouched


def test_preview_odd_byte_tail_is_trimmed(monkeypatch):
    """A dangling odd byte must not break the int16 view."""
    fake_engine = _patch_engine(monkeypatch)
    # 10 seconds + 1 stray byte.
    session = _make_preview_session(audio_chunks=[b"\x00" * (10 * _BYTES_PER_SECOND + 1)])

    asyncio.run(session.preview_transcription(20))

    msg_type, _ = _last_message(session)
    assert msg_type == "preview_result"
    # Even sample count despite the odd trailing byte.
    assert len(fake_engine.transcribe_audio.call_args.args[0]) == 10 * 16000


# ── Dispatch ───────────────────────────────────────────────────────────


def test_dispatch_preview_creates_task_with_parsed_duration(monkeypatch):
    async def _run():
        session = _make_preview_session(audio_chunks=[b"\x00" * _BYTES_PER_SECOND])
        session.preview_transcription = AsyncMock()
        await ws_mod.handle_client_message(
            session, {"type": "preview", "data": {"duration_seconds": 30}}
        )
        assert session._preview_task is not None
        await session._preview_task
        session.preview_transcription.assert_awaited_once_with(30)

    asyncio.run(_run())


def test_dispatch_preview_defaults_on_invalid_duration(monkeypatch):
    async def _run():
        session = _make_preview_session(audio_chunks=[b"\x00" * _BYTES_PER_SECOND])
        session.preview_transcription = AsyncMock()
        await ws_mod.handle_client_message(
            session, {"type": "preview", "data": {"duration_seconds": "abc"}}
        )
        await session._preview_task
        session.preview_transcription.assert_awaited_once_with(ws_mod._PREVIEW_DEFAULT_SECONDS)

    asyncio.run(_run())


def test_dispatch_preview_rejected_while_task_running(monkeypatch):
    """A live preview task must not be overwritten by a second preview message."""

    async def _run():
        session = _make_preview_session(audio_chunks=[b"\x00" * _BYTES_PER_SECOND])

        async def _never():
            await asyncio.sleep(10)

        running = asyncio.create_task(_never())
        session._preview_task = running
        session.preview_transcription = AsyncMock()
        try:
            await ws_mod.handle_client_message(
                session, {"type": "preview", "data": {"duration_seconds": 20}}
            )
            # The live task handle is preserved; no new preview was started.
            assert session._preview_task is running
            session.preview_transcription.assert_not_awaited()
            msg_type, data = _last_message(session)
            assert msg_type == "preview_error"
            assert "in progress" in data["message"].lower()
        finally:
            running.cancel()

    asyncio.run(_run())
