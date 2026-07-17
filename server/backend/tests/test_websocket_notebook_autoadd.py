"""Tests for "Auto-add recordings to Audio Notebook" on the session (WS) path.

GH #199 — the toggle existed in Settings but was a write-only orphan: nothing
read `notebook.autoAdd` (client) or `longform_recording.auto_add_to_audio_notebook`
(server), and `save_longform_recording()` — the helper purpose-built to persist a
session recording into the Notebook — had zero callers. Session transcriptions
therefore never produced a Notebook entry.

Invariants covered here:
  1. The flag is resolved from the client `start` payload OR the server config.
  2. When enabled, a completed session recording is written to the Notebook.
  3. The Notebook write happens AFTER the result is persisted and delivered, and
     a Notebook failure NEVER costs the user their transcript (delivery still
     happens, no `error` is sent, the job is not marked failed).

Run:  ../../build/.venv/bin/pytest tests/test_websocket_notebook_autoadd.py -v --tb=short
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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


def _make_session(*, auto_add: bool = False, job_id: str | None = "job-001"):
    """Build a TranscriptionSession without running the heavy __init__."""
    session = object.__new__(ws_mod.TranscriptionSession)
    session.websocket = MagicMock()
    session.websocket.client_state = WebSocketState.CONNECTED
    session.websocket.send_json = AsyncMock()
    session.client_name = "test-client"
    session.is_recording = False
    session.language = None
    session.audio_chunks = [b"\x00\x01" * 16000]  # 1s of 16 kHz Int16 mono
    session.sample_rate = 16000
    session.temp_file = None
    session.translation_enabled = False
    session.translation_target_language = "en"
    session._preview_in_progress = False
    session._preview_task = None
    session._client_disconnected = False
    session._current_job_id = job_id
    session.auto_add_to_notebook = auto_add
    session.send_message = AsyncMock()
    return session


def _patch_transcription(monkeypatch, tmp_path, *, result: _FakeResult | None = None):
    """Patch everything process_transcription() touches except the notebook hop."""
    fake_engine = MagicMock()
    fake_engine.model_name = "large-v3"
    fake_engine.transcribe_file.return_value = result or _FakeResult()

    fake_manager = MagicMock()
    fake_manager.ensure_transcription_loaded.return_value = fake_engine
    monkeypatch.setattr(mm_mod, "get_model_manager", lambda: fake_manager)

    # Durability writes — irrelevant here, keep them silent.
    monkeypatch.setattr(ws_mod, "_save_result", MagicMock())
    monkeypatch.setattr(ws_mod, "_mark_delivered", MagicMock())
    monkeypatch.setattr(ws_mod, "_mark_failed", MagicMock())
    monkeypatch.setattr(ws_mod, "_set_audio_path", MagicMock())

    # recordings_dir -> tmp so the persistent-audio write succeeds.
    import server.config as cfg_mod

    fake_cfg = MagicMock()
    fake_cfg.get.side_effect = lambda *a, **kw: (
        str(tmp_path) if a[:2] == ("durability", "recordings_dir") else kw.get("default")
    )
    monkeypatch.setattr(cfg_mod, "get_config", lambda: fake_cfg)

    # Outgoing webhook — no-op.
    import server.core.webhook as wh_mod

    monkeypatch.setattr(wh_mod, "dispatch", AsyncMock())

    return fake_engine


def _sent(session) -> list[str]:
    """Message types sent to the client, in order."""
    return [c.args[0] for c in session.send_message.call_args_list]


# ── Flag resolution (client payload OR server config) ──────────────────────


def _patch_start_deps(monkeypatch, *, server_default: bool = False):
    fake_tracker = MagicMock()
    fake_tracker.try_start_job.return_value = (True, "job-xyz", None)
    fake_manager = MagicMock()
    fake_manager.job_tracker = fake_tracker
    monkeypatch.setattr(mm_mod, "get_model_manager", lambda: fake_manager)
    monkeypatch.setattr(ws_mod, "_create_job", MagicMock())

    import server.config as cfg_mod

    fake_cfg = MagicMock()
    fake_cfg.get.side_effect = lambda *a, **kw: (
        server_default
        if a[:2] == ("longform_recording", "auto_add_to_audio_notebook")
        else kw.get("default")
    )
    monkeypatch.setattr(cfg_mod, "get_config", lambda: fake_cfg)


def _start_kwargs(session) -> dict[str, Any]:
    _, kwargs = session.start_recording.call_args
    return kwargs


def test_start_payload_enables_auto_add(monkeypatch):
    """Client toggle ON -> the session records into the Notebook."""
    _patch_start_deps(monkeypatch, server_default=False)
    session = _make_session()
    session.start_recording = AsyncMock()

    asyncio.run(
        ws_mod.handle_client_message(
            session, {"type": "start", "data": {"auto_add_to_notebook": True}}
        )
    )

    assert _start_kwargs(session)["auto_add_to_notebook"] is True


def test_start_payload_absent_defaults_off(monkeypatch):
    _patch_start_deps(monkeypatch, server_default=False)
    session = _make_session()
    session.start_recording = AsyncMock()

    asyncio.run(ws_mod.handle_client_message(session, {"type": "start", "data": {}}))

    assert _start_kwargs(session)["auto_add_to_notebook"] is False


def test_server_config_forces_auto_add_on(monkeypatch):
    """The Server-tab key is a server-wide force-on, even if the client omits/disables it.

    The GH #199 reporter ticked BOTH the Client and the Server checkbox; both
    must actually do something.
    """
    _patch_start_deps(monkeypatch, server_default=True)
    session = _make_session()
    session.start_recording = AsyncMock()

    asyncio.run(
        ws_mod.handle_client_message(
            session, {"type": "start", "data": {"auto_add_to_notebook": False}}
        )
    )

    assert _start_kwargs(session)["auto_add_to_notebook"] is True


def test_non_bool_flag_is_not_trusted(monkeypatch):
    """Untrusted client input: a non-bool must not enable the write."""
    _patch_start_deps(monkeypatch, server_default=False)
    session = _make_session()
    session.start_recording = AsyncMock()

    asyncio.run(
        ws_mod.handle_client_message(
            session, {"type": "start", "data": {"auto_add_to_notebook": "sure"}}
        )
    )

    assert _start_kwargs(session)["auto_add_to_notebook"] is False


# ── The Notebook write itself ──────────────────────────────────────────────


def test_completed_session_is_saved_to_notebook(monkeypatch, tmp_path):
    """The bug: this produced no Notebook entry. Now it must."""
    _patch_transcription(monkeypatch, tmp_path)
    saved = MagicMock(return_value=42)
    monkeypatch.setattr(ws_mod, "_save_session_to_notebook", saved)

    session = _make_session(auto_add=True)
    asyncio.run(session.process_transcription())

    saved.assert_called_once()
    kwargs = saved.call_args.kwargs
    assert kwargs["result"].text == "hello world"
    assert kwargs["duration_seconds"] == 2.0
    # The recording's persisted audio is what gets promoted into the notebook.
    assert kwargs["audio_path"] == tmp_path / "job-001.wav"
    # The transcript still reaches the user.
    assert "final" in _sent(session)


def test_notebook_write_skipped_when_toggle_off(monkeypatch, tmp_path):
    _patch_transcription(monkeypatch, tmp_path)
    saved = MagicMock(return_value=42)
    monkeypatch.setattr(ws_mod, "_save_session_to_notebook", saved)

    session = _make_session(auto_add=False)
    asyncio.run(session.process_transcription())

    saved.assert_not_called()
    assert "final" in _sent(session)


def test_notebook_failure_never_costs_the_transcript(monkeypatch, tmp_path):
    """AVOID DATA LOSS: a Notebook failure must not break result delivery."""
    _patch_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ws_mod,
        "_save_session_to_notebook",
        MagicMock(side_effect=RuntimeError("disk full")),
    )
    warned = MagicMock()
    monkeypatch.setattr(ws_mod, "_warn_notebook_autoadd_failed", warned)

    session = _make_session(auto_add=True)
    asyncio.run(session.process_transcription())

    sent = _sent(session)
    assert "final" in sent  # transcript delivered anyway
    assert "error" not in sent  # not reported as a transcription failure
    ws_mod._mark_failed.assert_not_called()  # job is not failed over a notebook hiccup
    # ...but the failure is NOT silent — that was the original bug's whole shape.
    warned.assert_called_once()


def test_notebook_write_returning_none_is_surfaced(monkeypatch, tmp_path):
    """A no-op write must warn too, rather than pretend it saved."""
    _patch_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(ws_mod, "_save_session_to_notebook", MagicMock(return_value=None))
    warned = MagicMock()
    monkeypatch.setattr(ws_mod, "_warn_notebook_autoadd_failed", warned)

    session = _make_session(auto_add=True)
    asyncio.run(session.process_transcription())

    warned.assert_called_once()
    assert "final" in _sent(session)


def test_notebook_warning_reaches_the_dashboard_event_channel(monkeypatch):
    """The warning must go over the startup-event channel, not the WS socket.

    The client disconnects on `final`, so a WS message would be dropped.
    """
    import server.core.startup_events as ev_mod

    emitted = MagicMock()
    monkeypatch.setattr(ev_mod, "emit_event", emitted)

    ws_mod._warn_notebook_autoadd_failed("disk full")

    emitted.assert_called_once()
    args, kwargs = emitted.call_args
    assert args[1] == "warning"
    assert "disk full" in args[2]
    assert kwargs["status"] == "error"


def test_notebook_write_happens_after_result_is_persisted(monkeypatch, tmp_path):
    """Persist-before-deliver: the durable job row is written before the notebook hop."""
    _patch_transcription(monkeypatch, tmp_path)
    order: list[str] = []
    monkeypatch.setattr(
        ws_mod, "_save_result", MagicMock(side_effect=lambda **kw: order.append("save_result"))
    )
    monkeypatch.setattr(
        ws_mod,
        "_save_session_to_notebook",
        MagicMock(side_effect=lambda **kw: order.append("notebook") or 7),
    )

    session = _make_session(auto_add=True)
    asyncio.run(session.process_transcription())

    assert order == ["save_result", "notebook"]


# ── _save_session_to_notebook() ────────────────────────────────────────────


def _patch_notebook_write(monkeypatch, tmp_path, *, mp3_raises: bool = False):
    """Patch the notebook-write dependencies; return (recorded_kwargs, audio_dir)."""
    import server.config as cfg_mod
    import server.core.audio_utils as au_mod
    import server.database.database as db_mod

    audio_dir = tmp_path / "audio"
    fake_cfg = MagicMock()
    fake_cfg.get.side_effect = lambda *a, **kw: (
        str(audio_dir) if a[:2] == ("audio_notebook", "audio_dir") else kw.get("default")
    )
    monkeypatch.setattr(cfg_mod, "get_config", lambda: fake_cfg)

    def _fake_mp3(src, dst, *a, **kw):
        if mp3_raises:
            raise RuntimeError("ffmpeg is not installed or not in PATH")
        Path(dst).write_bytes(b"ID3-fake")
        return dst

    monkeypatch.setattr(au_mod, "convert_to_mp3", _fake_mp3)

    recorded: dict[str, Any] = {}

    def _fake_save(**kwargs):
        recorded.update(kwargs)
        return 99

    monkeypatch.setattr(db_mod, "save_longform_to_database", _fake_save)
    return recorded, audio_dir


def _wav(tmp_path) -> Path:
    src = tmp_path / "job-001.wav"
    src.write_bytes(b"RIFF-fake-wav")
    return src


def test_save_session_to_notebook_persists_audio_and_words(monkeypatch, tmp_path):
    recorded, audio_dir = _patch_notebook_write(monkeypatch, tmp_path)

    result = _FakeResult(
        text="hello world",
        segments=[
            {
                "text": "hello world",
                "start": 0.0,
                "end": 1.0,
                "words": [{"word": "hello", "start": 0.0, "end": 0.5}],
            }
        ],
    )

    rec_id = ws_mod._save_session_to_notebook(
        audio_path=_wav(tmp_path),
        duration_seconds=2.0,
        result=result,
        model_name="large-v3",
    )

    assert rec_id == 99
    assert recorded["transcription_text"] == "hello world"
    assert recorded["duration_seconds"] == 2.0
    assert recorded["transcription_backend"] == "whisper"
    # The notebook gets its own copy in the notebook audio dir (deleting the
    # entry must not delete the job's retry audio).
    assert recorded["audio_path"].parent == audio_dir
    assert recorded["audio_path"].suffix == ".mp3"
    # Word timestamps are lifted out of the segments so the entry carries real
    # word-level timing, not just a wall of text.
    assert recorded["word_timestamps"] == [{"word": "hello", "start": 0.0, "end": 0.5}]


def test_notebook_entry_survives_missing_ffmpeg(monkeypatch, tmp_path):
    """A stock macOS box has no ffmpeg — store the audio verbatim, don't drop the entry."""
    recorded, audio_dir = _patch_notebook_write(monkeypatch, tmp_path, mp3_raises=True)

    rec_id = ws_mod._save_session_to_notebook(
        audio_path=_wav(tmp_path),
        duration_seconds=2.0,
        result=_FakeResult(),
        model_name="large-v3",
    )

    assert rec_id == 99
    assert recorded["audio_path"].suffix == ".wav"
    assert recorded["audio_path"].parent == audio_dir
    assert recorded["audio_path"].read_bytes() == b"RIFF-fake-wav"


def test_save_session_to_notebook_returns_none_when_db_fails(monkeypatch, tmp_path):
    _patch_notebook_write(monkeypatch, tmp_path)
    import server.database.database as db_mod

    monkeypatch.setattr(db_mod, "save_longform_to_database", lambda **kw: None)

    assert (
        ws_mod._save_session_to_notebook(
            audio_path=_wav(tmp_path),
            duration_seconds=2.0,
            result=_FakeResult(),
            model_name="large-v3",
        )
        is None
    )


def test_missing_audio_file_is_not_written_to_notebook(monkeypatch, tmp_path):
    recorded, _ = _patch_notebook_write(monkeypatch, tmp_path)

    assert (
        ws_mod._save_session_to_notebook(
            audio_path=tmp_path / "gone.wav",
            duration_seconds=2.0,
            result=_FakeResult(),
            model_name="large-v3",
        )
        is None
    )
    assert recorded == {}


def test_empty_audio_is_not_written_to_notebook(monkeypatch, tmp_path):
    """Silence in, nothing out — a zero-length recording must not create an entry."""
    recorded, _ = _patch_notebook_write(monkeypatch, tmp_path)

    assert (
        ws_mod._save_session_to_notebook(
            audio_path=_wav(tmp_path),
            duration_seconds=0.0,
            result=_FakeResult(),
            model_name="large-v3",
        )
        is None
    )
    assert recorded == {}


def test_no_audio_chunks_never_reaches_the_notebook(monkeypatch, tmp_path):
    """The pre-existing 'No audio data received' bail-out short-circuits everything."""
    _patch_transcription(monkeypatch, tmp_path)
    saved = MagicMock()
    monkeypatch.setattr(ws_mod, "_save_session_to_notebook", saved)

    session = _make_session(auto_add=True)
    session.audio_chunks = []

    asyncio.run(session.process_transcription())

    saved.assert_not_called()
    assert _sent(session) == ["error"]
