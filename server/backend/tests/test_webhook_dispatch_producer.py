"""Coordinator producer-side webhook dispatch (Issue #104, Story 7.5).

Verifies that ``trigger_auto_actions`` with a profile that has
``webhook_url`` set inserts a ``pending`` row into ``webhook_deliveries``
BEFORE returning. The actual HTTP fire is the WebhookWorker's job and
is covered separately in ``test_webhook_worker.py`` — here we assert
only the producer half (Persist-Before-Deliver: row exists durably
before any worker runs).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import server.database.database as db
from server.core.auto_action_coordinator import trigger_auto_actions
from server.database import webhook_deliveries_repository as wdr

pytest.importorskip("alembic")


@pytest.fixture()
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    (data_dir / "database").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setattr(db, "_data_dir", None)
    monkeypatch.setattr(db, "_db_path", None)
    db.set_data_directory(data_dir)
    db.init_db()
    return db.get_db_path()


@pytest.fixture()
def recording_id(fresh_db: Path) -> int:
    return db.insert_recording(
        filename="r.wav",
        filepath="/tmp/r.wav",
        duration_seconds=1.0,
        recorded_at="2026-05-04T00:00:00",
    )


def test_trigger_with_webhook_url_inserts_pending_row(
    recording_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Producer half — durable row exists after trigger."""
    snapshot = {
        "name": "webhook-only",
        "public_fields": {
            "webhook_url": "https://hooks.example.com/incoming",
            # Other auto-actions disabled so we test the webhook branch
            # in isolation.
            "auto_summary_enabled": False,
            "auto_export_enabled": False,
        },
    }
    asyncio.run(trigger_auto_actions(recording_id, snapshot))

    rows = wdr.list_pending()
    assert len(rows) == 1
    body = json.loads(rows[0]["payload_json"])
    # The URL is baked into the payload (frozen-at-INSERT — no drift).
    assert body["__webhook_url__"] == "https://hooks.example.com/incoming"
    assert body["recording_id"] == recording_id
    assert body["event"] == "transcription.completed"


def test_trigger_with_no_webhook_url_does_not_insert_row(
    recording_id: int,
) -> None:
    snapshot = {
        "name": "no-webhook",
        "public_fields": {
            "webhook_url": "",
            "auto_summary_enabled": False,
            "auto_export_enabled": False,
        },
    }
    asyncio.run(trigger_auto_actions(recording_id, snapshot))
    assert wdr.list_pending() == []


def test_trigger_with_include_transcript_text_appends_text(
    recording_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opt-in transcript text reaches the payload (Story 7.6 AC2)."""
    # Insert a couple of segments so the transcript-text builder has
    # something to work with.
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO segments "
            "(recording_id, segment_index, speaker, text, start_time, end_time) "
            "VALUES (?, 0, 'spk0', 'Hello.', 0.0, 1.0)",
            (recording_id,),
        )
        conn.execute(
            "INSERT INTO segments "
            "(recording_id, segment_index, speaker, text, start_time, end_time) "
            "VALUES (?, 1, 'spk0', 'World.', 1.0, 2.0)",
            (recording_id,),
        )
        conn.commit()

    snapshot = {
        "name": "verbose",
        "public_fields": {
            "webhook_url": "https://hooks.example.com/x",
            "webhook_include_transcript_text": True,
            "auto_summary_enabled": False,
            "auto_export_enabled": False,
        },
    }
    asyncio.run(trigger_auto_actions(recording_id, snapshot))

    rows = wdr.list_pending()
    assert len(rows) == 1
    body = json.loads(rows[0]["payload_json"])
    assert "transcript_text" in body
    # Plaintext export joins segments — exact format depends on
    # stream_plaintext, but we should see both segments' words.
    assert "Hello" in body["transcript_text"]
    assert "World" in body["transcript_text"]


def test_trigger_with_auth_header_bakes_into_payload(
    recording_id: int,
) -> None:
    snapshot = {
        "name": "with-auth",
        "public_fields": {
            "webhook_url": "https://hooks.example.com/x",
            "webhook_auth_header": "Bearer secret-token",
            "auto_summary_enabled": False,
            "auto_export_enabled": False,
        },
    }
    asyncio.run(trigger_auto_actions(recording_id, snapshot))
    rows = wdr.list_pending()
    body = json.loads(rows[0]["payload_json"])
    assert body["__auth_header__"] == "Bearer secret-token"


def test_trigger_persist_before_worker_runs(
    recording_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row must exist DURABLY before any worker activity.

    We simulate a "crash immediately after trigger" by NOT starting any
    worker. The row must still be visible to a fresh DB connection.
    """
    snapshot = {
        "name": "x",
        "public_fields": {
            "webhook_url": "https://hooks.example.com/x",
            "auto_summary_enabled": False,
            "auto_export_enabled": False,
        },
    }
    asyncio.run(trigger_auto_actions(recording_id, snapshot))
    # No worker ever started; the row would be lost if we relied on
    # in-memory state. list_pending hits a fresh connection — proves
    # the COMMIT happened.
    rows = wdr.list_pending()
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
