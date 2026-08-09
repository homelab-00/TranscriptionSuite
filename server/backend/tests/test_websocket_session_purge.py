"""Tests for the WS session post-delivery purge (session ephemeral retention).

A mic-session job whose final actually reached the client must leave no
server-side trace: process_transcription purges the transcription_jobs row
(and its WAV) right after delivery + notebook auto-add. The purge must NOT
fire for the >1MB result_ready reference path (GET /result purges instead)
nor when a notebook auto-add fails (row + WAV stay as the recovery copy).

Factory copied from test_websocket_notebook_autoadd.py — do NOT add session
attributes here; the purge is method-local by design.

Run:  ../../build/.venv/bin/pytest tests/test_websocket_session_purge.py -v --tb=short
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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
    session.diarization_enabled = False
    session.expected_speakers = None
    session._salvage_reason = None
    session.send_message = AsyncMock()
    return session


def _patch_transcription(monkeypatch, tmp_path, *, result: _FakeResult | None = None):
    """Patch everything process_transcription() touches except the purge hop."""
    fake_engine = MagicMock()
    fake_engine.model_name = "large-v3"
    fake_engine.transcribe_file.return_value = result or _FakeResult()

    fake_manager = MagicMock()
    fake_manager.ensure_transcription_loaded.return_value = fake_engine
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


def _sent(session) -> list[str]:
    return [c.args[0] for c in session.send_message.call_args_list]


def test_delivered_session_purges_row(monkeypatch, tmp_path):
    """Happy path: persisted + delivered inline + no auto-add → purged."""
    _patch_transcription(monkeypatch, tmp_path)
    purge = MagicMock()
    monkeypatch.setattr(ws_mod, "_delete_job", purge)

    session = _make_session()
    asyncio.run(session.process_transcription())

    assert "final" in _sent(session)
    purge.assert_called_once_with("job-001")


def test_reference_path_defers_purge_to_result_fetch(monkeypatch, tmp_path):
    """>1MB payload goes out as a result_ready reference — GET /result purges."""
    big = _FakeResult(text="x" * 1_100_000)
    _patch_transcription(monkeypatch, tmp_path, result=big)
    purge = MagicMock()
    monkeypatch.setattr(ws_mod, "_delete_job", purge)

    session = _make_session()
    asyncio.run(session.process_transcription())

    assert "result_ready" in _sent(session)
    purge.assert_not_called()


def test_autoadd_success_still_purges(monkeypatch, tmp_path):
    """Notebook copy exists → the session row has no reason to stay."""
    _patch_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(ws_mod, "_save_session_to_notebook", MagicMock(return_value=42))
    purge = MagicMock()
    monkeypatch.setattr(ws_mod, "_delete_job", purge)

    session = _make_session(auto_add=True)
    asyncio.run(session.process_transcription())

    purge.assert_called_once_with("job-001")


def test_autoadd_returning_none_cancels_purge(monkeypatch, tmp_path):
    """No notebook copy was written → keep row + WAV, nothing may be lost."""
    _patch_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(ws_mod, "_save_session_to_notebook", MagicMock(return_value=None))
    monkeypatch.setattr(ws_mod, "_warn_notebook_autoadd_failed", MagicMock())
    purge = MagicMock()
    monkeypatch.setattr(ws_mod, "_delete_job", purge)

    session = _make_session(auto_add=True)
    asyncio.run(session.process_transcription())

    purge.assert_not_called()


def test_autoadd_exception_cancels_purge(monkeypatch, tmp_path):
    _patch_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ws_mod, "_save_session_to_notebook", MagicMock(side_effect=RuntimeError("disk full"))
    )
    monkeypatch.setattr(ws_mod, "_warn_notebook_autoadd_failed", MagicMock())
    purge = MagicMock()
    monkeypatch.setattr(ws_mod, "_delete_job", purge)

    session = _make_session(auto_add=True)
    asyncio.run(session.process_transcription())

    purge.assert_not_called()


def test_purge_error_never_reaches_the_client(monkeypatch, tmp_path):
    """delete_job is never-raise by contract, but the call site is belt-and-braces
    guarded: a purge error must not surface as a post-delivery error banner."""
    _patch_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(ws_mod, "_delete_job", MagicMock(side_effect=RuntimeError("boom")))

    session = _make_session()
    asyncio.run(session.process_transcription())

    sent = _sent(session)
    assert "final" in sent
    assert "error" not in sent
