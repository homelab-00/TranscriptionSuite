"""Tests for salvaging buffered head audio on a mid-recording WS disconnect (GH-239).

A longform ``/ws`` session buffers client-streamed PCM but only ever transcribes
it in ``process_transcription()``, which used to run exclusively on the ``stop``
message. A mid-recording disconnect therefore discarded everything the user had
already streamed, and left the job row stuck in 'processing' until the orphan
sweep reaped it.

Invariants covered here:
  1. ``send_message`` reports whether the frame actually reached the client, and
     a job is only marked delivered when it did. Otherwise a result nobody
     received is hidden from the ``/recent`` recovery list.
  2. A mid-recording disconnect with usable audio finalizes durably, flagged
     ``partial`` so the UI can say the transcript is truncated.
  3. The junk-job guard: a connect-then-drop with (almost) no audio must not
     produce a saved result, and must reach a terminal state immediately.
  4. Salvage must not cancel itself - ``_client_disconnected`` is True by
     definition on this path, and it feeds the backend's ``cancellation_check``.

Run:  ../../build/.venv/bin/pytest tests/test_websocket_disconnect_salvage.py -v --tb=short
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from server.api.routes import websocket as ws_mod
from server.core import model_manager as mm_mod
from starlette.websockets import WebSocketState


@dataclass
class _FakeResult:
    """Duck-typed TranscriptionResult (avoids the torch/webrtcvad import chain)."""

    text: str = "hello world"
    segments: list[dict[str, Any]] = field(default_factory=list)
    words: list[dict[str, Any]] = field(default_factory=list)
    language: str | None = "en"
    language_probability: float = 0.9
    duration: float = 2.0
    num_speakers: int = 0
    partial: bool = False
    partial_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "segments": self.segments,
            "words": self.words,
            "language": self.language,
            "language_probability": self.language_probability,
            "duration": self.duration,
            "num_speakers": self.num_speakers,
            "total_words": len(self.words),
            "partial": self.partial,
            "partial_reason": self.partial_reason,
            "metadata": {"num_segments": len(self.segments)},
        }


def _pcm(seconds: float, sample_rate: int = 16000) -> bytes:
    """`seconds` of Int16 mono PCM at `sample_rate`."""
    return b"\x00\x01" * int(seconds * sample_rate)


def _make_session(
    *,
    job_id: str | None = "job-001",
    is_recording: bool = True,
    audio_seconds: float = 5.0,
    real_send: bool = False,
):
    """Build a TranscriptionSession without running the heavy __init__."""
    session = object.__new__(ws_mod.TranscriptionSession)
    session.websocket = MagicMock()
    session.websocket.client_state = WebSocketState.CONNECTED
    session.websocket.send_json = AsyncMock()
    session.client_name = "test-client"
    session.session_id = "sess-001"
    session.is_recording = is_recording
    session.language = None
    session.audio_chunks = [_pcm(audio_seconds)] if audio_seconds else []
    session.sample_rate = 16000
    session.temp_file = None
    session.translation_enabled = False
    session.translation_target_language = "en"
    session._preview_in_progress = False
    session._preview_task = None
    session._client_disconnected = True  # the whole point of this path
    session._current_job_id = job_id
    session._realtime_engine = None
    session._use_realtime_engine = False
    session.auto_add_to_notebook = False
    session.diarization_enabled = False
    session.expected_speakers = None
    session._salvage_reason = None
    if not real_send:
        session.send_message = AsyncMock()
    return session


def _patch_transcription(monkeypatch, tmp_path, *, result: _FakeResult | None = None):
    """Patch everything process_transcription() touches. Returns the fake engine."""
    fake_engine = MagicMock()
    fake_engine.model_name = "large-v3"
    fake_engine.transcribe_file.return_value = result or _FakeResult()

    fake_manager = MagicMock()
    fake_manager.ensure_transcription_loaded.return_value = fake_engine
    fake_manager.job_tracker.is_cancelled.return_value = False
    fake_manager.job_tracker.get_status.return_value = {}
    fake_manager.gpu_device_index = 0
    monkeypatch.setattr(mm_mod, "get_model_manager", lambda: fake_manager)

    monkeypatch.setattr(ws_mod, "_save_result", MagicMock())
    monkeypatch.setattr(ws_mod, "_mark_delivered", MagicMock())
    monkeypatch.setattr(ws_mod, "_mark_failed", MagicMock())
    monkeypatch.setattr(ws_mod, "_set_audio_path", MagicMock())

    import server.config as cfg_mod

    fake_cfg = MagicMock()
    fake_cfg.get.side_effect = lambda *a, **kw: (
        str(tmp_path) if a[:2] == ("durability", "recordings_dir") else kw.get("default")
    )
    monkeypatch.setattr(cfg_mod, "get_config", lambda: fake_cfg)

    import server.core.webhook as wh_mod

    monkeypatch.setattr(wh_mod, "dispatch", AsyncMock())

    return fake_engine


def _saved_payload() -> dict[str, Any]:
    """The result_json handed to _save_result, decoded."""
    import json

    return json.loads(ws_mod._save_result.call_args.kwargs["result_json"])


# ── 1. send_message reports real delivery ──────────────────────────────────


def test_send_message_reports_success():
    session = _make_session(real_send=True)

    assert asyncio.run(session.send_message("final", {"text": "hi"})) is True


def test_send_message_reports_failure_when_socket_is_closed():
    session = _make_session(real_send=True)
    session.websocket.client_state = WebSocketState.DISCONNECTED

    assert asyncio.run(session.send_message("final", {"text": "hi"})) is False


def test_send_message_reports_failure_when_the_send_raises():
    """starlette only flips client_state inside receive(), so a dead socket can
    still read CONNECTED - the send itself is the only honest signal."""
    session = _make_session(real_send=True)
    session.websocket.send_json = AsyncMock(side_effect=RuntimeError("socket gone"))

    assert asyncio.run(session.send_message("final", {"text": "hi"})) is False


# ── 2. mark_delivered only on a real delivery ──────────────────────────────


def test_undelivered_result_is_not_marked_delivered(monkeypatch, tmp_path):
    """A result the client never received must stay delivered=0 so it surfaces
    in the /recent recovery list instead of being silently buried."""
    _patch_transcription(monkeypatch, tmp_path)
    session = _make_session()
    session.send_message = AsyncMock(return_value=False)

    asyncio.run(session.process_transcription())

    ws_mod._save_result.assert_called_once()
    ws_mod._mark_delivered.assert_not_called()


def test_delivered_result_is_still_marked_delivered(monkeypatch, tmp_path):
    """The happy path must not regress."""
    _patch_transcription(monkeypatch, tmp_path)
    session = _make_session()
    session.send_message = AsyncMock(return_value=True)

    asyncio.run(session.process_transcription())

    ws_mod._mark_delivered.assert_called_once_with("job-001")


# ── 3. Salvage on a mid-recording disconnect ───────────────────────────────


def test_disconnect_mid_recording_salvages_the_buffered_audio(monkeypatch, tmp_path):
    """The GH-239 bug: this discarded the head audio and saved nothing."""
    _patch_transcription(monkeypatch, tmp_path)
    session = _make_session(audio_seconds=5.0)

    asyncio.run(session.finalize_interrupted_recording())

    ws_mod._save_result.assert_called_once()
    assert ws_mod._save_result.call_args.kwargs["job_id"] == "job-001"
    assert ws_mod._save_result.call_args.kwargs["result_text"] == "hello world"


def test_salvaged_result_is_flagged_partial(monkeypatch, tmp_path):
    """The transcript covers only what arrived before the drop - say so."""
    _patch_transcription(monkeypatch, tmp_path)
    session = _make_session(audio_seconds=5.0)

    asyncio.run(session.finalize_interrupted_recording())

    payload = _saved_payload()
    assert payload["partial"] is True
    assert "disconnect" in (payload["partial_reason"] or "").lower()


def test_salvage_keeps_a_pre_existing_partial_reason(monkeypatch, tmp_path):
    """A chunking backend that already gave up partway must not lose its reason."""
    _patch_transcription(
        monkeypatch,
        tmp_path,
        result=_FakeResult(partial=True, partial_reason="chunk 3 timed out"),
    )
    session = _make_session(audio_seconds=5.0)

    asyncio.run(session.finalize_interrupted_recording())

    reason = _saved_payload()["partial_reason"] or ""
    assert "chunk 3 timed out" in reason
    assert "disconnect" in reason.lower()


def test_salvage_does_not_cancel_itself(monkeypatch, tmp_path):
    """_client_disconnected is True by definition here and feeds the backend's
    cancellation_check - left unguarded, the salvage aborts on its first poll."""
    engine = _patch_transcription(monkeypatch, tmp_path)
    session = _make_session(audio_seconds=5.0)

    asyncio.run(session.finalize_interrupted_recording())

    cancellation_check = engine.transcribe_file.call_args.kwargs["cancellation_check"]
    assert cancellation_check() is False


def test_salvage_still_honours_an_explicit_cancel(monkeypatch, tmp_path):
    """POST /cancel must keep working during a salvage."""
    engine = _patch_transcription(monkeypatch, tmp_path)
    mm_mod.get_model_manager().job_tracker.is_cancelled.return_value = True
    session = _make_session(audio_seconds=5.0)

    asyncio.run(session.finalize_interrupted_recording())

    cancellation_check = engine.transcribe_file.call_args.kwargs["cancellation_check"]
    assert cancellation_check() is True


def test_salvage_stops_the_realtime_engine_first(monkeypatch, tmp_path):
    """VAD sessions keep a recorder running; it must be stopped before the
    buffer is transcribed, exactly as the clean stop_recording() path does."""
    _patch_transcription(monkeypatch, tmp_path)
    session = _make_session(audio_seconds=5.0)
    session._realtime_engine = MagicMock()

    asyncio.run(session.finalize_interrupted_recording())

    session._realtime_engine.stop_recording.assert_called_once()


# ── 4. Junk-job guard ──────────────────────────────────────────────────────


def test_connect_then_drop_saves_no_result(monkeypatch, tmp_path):
    """Below the minimum, a salvage would only manufacture an empty job."""
    _patch_transcription(monkeypatch, tmp_path)
    session = _make_session(audio_seconds=0.5)

    asyncio.run(session.finalize_interrupted_recording())

    ws_mod._save_result.assert_not_called()


def test_connect_then_drop_reaches_a_terminal_state(monkeypatch, tmp_path):
    """Leaving the row in 'processing' means waiting on the orphan sweep to
    guess. The disconnect is not a guess - fail it now, with the real reason."""
    _patch_transcription(monkeypatch, tmp_path)
    session = _make_session(audio_seconds=0.5)

    asyncio.run(session.finalize_interrupted_recording())

    ws_mod._mark_failed.assert_called_once()
    assert ws_mod._mark_failed.call_args[0][0] == "job-001"
    assert "disconnect" in ws_mod._mark_failed.call_args[0][1].lower()


def test_no_audio_at_all_is_handled(monkeypatch, tmp_path):
    _patch_transcription(monkeypatch, tmp_path)
    session = _make_session(audio_seconds=0)

    asyncio.run(session.finalize_interrupted_recording())

    ws_mod._save_result.assert_not_called()
    ws_mod._mark_failed.assert_called_once()


def test_min_salvage_seconds_is_configurable(monkeypatch, tmp_path):
    """An 8s head is salvaged by default, but not when the operator raises the
    floor above it."""
    _patch_transcription(monkeypatch, tmp_path)
    import server.config as cfg_mod

    fake_cfg = MagicMock()
    fake_cfg.get.side_effect = lambda *a, **kw: (
        str(tmp_path)
        if a[:2] == ("durability", "recordings_dir")
        else 30.0
        if a[:2] == ("durability", "min_salvage_seconds")
        else kw.get("default")
    )
    monkeypatch.setattr(cfg_mod, "get_config", lambda: fake_cfg)
    session = _make_session(audio_seconds=8.0)

    asyncio.run(session.finalize_interrupted_recording())

    ws_mod._save_result.assert_not_called()


# ── 5. No double-finalize ──────────────────────────────────────────────────


def test_clean_stop_is_not_salvaged_again(monkeypatch, tmp_path):
    """stop_recording() clears is_recording before transcribing, so the
    teardown that follows must not run a second transcription."""
    _patch_transcription(monkeypatch, tmp_path)
    session = _make_session(is_recording=False, audio_seconds=5.0)

    asyncio.run(session.finalize_interrupted_recording())

    ws_mod._save_result.assert_not_called()
    ws_mod._mark_failed.assert_not_called()


def test_salvage_clears_is_recording(monkeypatch, tmp_path):
    """Guards against a re-entrant second salvage."""
    _patch_transcription(monkeypatch, tmp_path)
    session = _make_session(audio_seconds=5.0)

    asyncio.run(session.finalize_interrupted_recording())

    assert session.is_recording is False


def test_drop_without_a_job_row_saves_nothing(monkeypatch, tmp_path):
    """No job_id means create_job failed at start - there is nothing to attach
    a result to, and mark_failed has no row to touch."""
    _patch_transcription(monkeypatch, tmp_path)
    session = _make_session(job_id=None, audio_seconds=0.5)

    asyncio.run(session.finalize_interrupted_recording())

    ws_mod._save_result.assert_not_called()
    ws_mod._mark_failed.assert_not_called()


# ── 6. Salvage must never break connection teardown ────────────────────────


def test_salvage_failure_does_not_propagate(monkeypatch, tmp_path):
    """This runs in the endpoint's finally block. An exception escaping here
    would skip session cleanup and leak the job slot."""
    _patch_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ws_mod.TranscriptionSession,
        "process_transcription",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    session = _make_session(audio_seconds=5.0)

    asyncio.run(session.finalize_interrupted_recording())  # must not raise


# ── 7. Endpoint wiring ─────────────────────────────────────────────────────


def _endpoint_finally_calls() -> list[str]:
    """Awaited method names in websocket_endpoint's finally block, in order."""
    import ast
    from pathlib import Path

    source = (Path(ws_mod.__file__)).read_text()
    tree = ast.parse(source)
    endpoint = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "websocket_endpoint"
    )
    handler = next(
        node for node in ast.walk(endpoint) if isinstance(node, ast.Try) and node.finalbody
    )
    return [
        node.func.attr
        for stmt in handler.finalbody
        for node in ast.walk(stmt)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]


def test_endpoint_salvages_before_releasing_the_job_slot():
    """cleanup() calls _release_job(), which drops _current_job_id - salvage
    after it would persist the result nowhere."""
    calls = _endpoint_finally_calls()

    assert "finalize_interrupted_recording" in calls, (
        "websocket_endpoint's finally must salvage the buffered audio (GH-239)"
    )
    assert calls.index("finalize_interrupted_recording") < calls.index("cleanup")


def _drive_endpoint(monkeypatch, session_holder: dict, order: list[str]):
    """Run websocket_endpoint against a socket that drops immediately."""
    auth = MagicMock()
    auth.client_name = "test-client"
    auth.is_admin = False
    auth.is_localhost_bypass = False
    monkeypatch.setattr(ws_mod, "authenticate_websocket_from_message", AsyncMock(return_value=auth))

    async def _record_salvage(self):
        order.append("salvage")

    async def _record_cleanup(self):
        order.append("cleanup")

    monkeypatch.setattr(
        ws_mod.TranscriptionSession, "finalize_interrupted_recording", _record_salvage
    )
    monkeypatch.setattr(ws_mod.TranscriptionSession, "cleanup", _record_cleanup)

    websocket = MagicMock()
    websocket.accept = AsyncMock()
    websocket.headers = {}
    websocket.query_params = {}
    websocket.client = MagicMock(host="127.0.0.1")
    websocket.client_state = WebSocketState.DISCONNECTED  # sends become no-ops
    websocket.receive = AsyncMock(return_value={"type": "websocket.disconnect"})

    asyncio.run(ws_mod.websocket_endpoint(websocket))
    session_holder["sessions"] = dict(ws_mod._connected_sessions)


def test_endpoint_runs_the_salvage_hook_on_a_drop(monkeypatch):
    """AST order is necessary but not sufficient - prove the call actually fires."""
    order: list[str] = []
    _drive_endpoint(monkeypatch, {}, order)

    assert order == ["salvage", "cleanup"]


def test_endpoint_deregisters_the_session_after_a_drop(monkeypatch):
    """A salvage that leaked the session would keep it in _connected_sessions."""
    holder: dict = {}
    _drive_endpoint(monkeypatch, holder, [])

    assert holder["sessions"] == {}


@pytest.mark.parametrize("audio_seconds", [5.0, 0.5])
def test_salvage_releases_the_buffer(monkeypatch, tmp_path, audio_seconds):
    """A long recording's PCM buffer can be ~100 MB; the session object may
    outlive this call in _connected_sessions until the endpoint's finally
    removes it."""
    _patch_transcription(monkeypatch, tmp_path)
    session = _make_session(audio_seconds=audio_seconds)

    asyncio.run(session.finalize_interrupted_recording())

    assert session.audio_chunks == []


# ── 8. Job tracker salvage flag ─────────────────────────────────────────────


def test_salvage_marks_the_job_tracker(monkeypatch, tmp_path):
    """The dashboard popup and progress notification hinge on this flag."""
    _patch_transcription(monkeypatch, tmp_path)
    session = _make_session(audio_seconds=5.0)

    asyncio.run(session.finalize_interrupted_recording())

    tracker = mm_mod.get_model_manager().job_tracker
    tracker.mark_salvage.assert_called_once_with("job-001")


def test_junk_guard_does_not_mark_salvage(monkeypatch, tmp_path):
    """Below the salvage minimum nothing runs, so nothing must be flagged."""
    _patch_transcription(monkeypatch, tmp_path)
    session = _make_session(audio_seconds=1.0)

    asyncio.run(session.finalize_interrupted_recording())

    tracker = mm_mod.get_model_manager().job_tracker
    tracker.mark_salvage.assert_not_called()
