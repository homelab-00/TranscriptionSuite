"""session_busy payload carries salvage awareness (GH-239 follow-up).

The dashboard branches on is_salvage: a salvage-held slot opens the
drop-confirmation popup; a live user's job keeps the generic busy error.
salvage_job_id must be the FULL id - the client matches it against /recent
and /result/{job_id}.

Run:  ../../build/.venv/bin/pytest tests/test_websocket_session_busy.py -v --tb=short
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import server.api.routes.websocket as ws_mod


def _session():
    # Plain MagicMock, NOT spec=TranscriptionSession: `spec` builds its allowed
    # attribute set from dir(cls), which excludes anything assigned in __init__.
    session = MagicMock()
    session.client_name = "test-client"
    session._current_job_id = None
    session.start_recording = AsyncMock()
    session.send_message = AsyncMock()
    return session


def _busy_payload(salvage_info: dict[str, Any] | None) -> dict[str, Any]:
    """Drive a `start` frame into a busy tracker; return the session_busy payload."""
    session = _session()
    model_manager = MagicMock()
    model_manager.job_tracker.try_start_job.return_value = (False, None, "other-user")
    model_manager.job_tracker.get_salvage_info.return_value = salvage_info

    with patch("server.core.model_manager.get_model_manager", return_value=model_manager):
        asyncio.run(ws_mod.handle_client_message(session, {"type": "start", "data": {}}))

    assert session.send_message.await_count == 1
    msg_type, payload = session.send_message.await_args.args
    assert msg_type == "session_busy"
    assert session.start_recording.await_count == 0
    return payload


def test_busy_without_salvage_is_not_flagged():
    payload = _busy_payload(None)
    assert payload == {
        "active_user": "other-user",
        "is_salvage": False,
        "salvage_job_id": None,
    }


def test_busy_with_salvage_carries_the_full_job_id():
    payload = _busy_payload(
        {
            "job_id": "11111111-2222-3333-4444-555555555555",
            "client_name": "other-user",
            "started_at": 1.0,
        }
    )
    assert payload == {
        "active_user": "other-user",
        "is_salvage": True,
        "salvage_job_id": "11111111-2222-3333-4444-555555555555",
    }
