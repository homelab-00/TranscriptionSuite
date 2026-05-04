"""Webhook deliveries repository (Issue #104, Story 7.1).

Verifies CRUD invariants, status-transition correctness, retention
cleanup behavior, and the consecutive-failure counter that the worker's
escalation policy relies on.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
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
    """Insert one recording and return its id."""
    return db.insert_recording(
        filename="r.wav",
        filepath="/tmp/r.wav",
        duration_seconds=1.0,
        recorded_at="2026-05-04T00:00:00",
    )


# ──────────────────────────────────────────────────────────────────────────
# Producer-side
# ──────────────────────────────────────────────────────────────────────────


def test_create_pending_returns_id_and_persists(recording_id: int) -> None:
    payload = {"event": "transcription.completed", "recording_id": recording_id}
    row_id = wdr.create_pending(recording_id, profile_id=None, payload=payload)
    assert isinstance(row_id, int) and row_id > 0
    fetched = wdr.get_by_id(row_id)
    assert fetched is not None
    assert fetched["status"] == "pending"
    assert fetched["recording_id"] == recording_id
    assert fetched["profile_id"] is None
    body = json.loads(fetched["payload_json"])
    assert body == payload


def test_create_pending_visible_to_fresh_connection(recording_id: int) -> None:
    """Persist-Before-Deliver — the row must be committed before return."""
    row_id = wdr.create_pending(recording_id, profile_id=None, payload={"k": "v"})
    # Open a brand-new connection — if create_pending forgot to COMMIT,
    # this would not see the row.
    conn = sqlite3.connect(db.get_db_path())
    try:
        cur = conn.execute("SELECT status FROM webhook_deliveries WHERE id = ?", (row_id,))
        row = cur.fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "pending"


# ──────────────────────────────────────────────────────────────────────────
# State transitions
# ──────────────────────────────────────────────────────────────────────────


def test_mark_in_flight_updates_status(recording_id: int) -> None:
    row_id = wdr.create_pending(recording_id, None, {"x": 1})
    wdr.mark_in_flight(row_id)
    assert wdr.get_by_id(row_id)["status"] == "in_flight"


def test_mark_success_sets_status_and_attempted_at(recording_id: int) -> None:
    row_id = wdr.create_pending(recording_id, None, {"x": 1})
    wdr.mark_in_flight(row_id)
    wdr.mark_success(row_id)
    row = wdr.get_by_id(row_id)
    assert row["status"] == "success"
    assert row["last_attempted_at"] is not None


def test_mark_failed_increments_attempt_count_and_records_error(recording_id: int) -> None:
    row_id = wdr.create_pending(recording_id, None, {"x": 1})
    wdr.mark_failed(row_id, "timeout")
    row1 = wdr.get_by_id(row_id)
    assert row1["status"] == "failed"
    assert row1["attempt_count"] == 1
    assert row1["last_error"] == "timeout"
    wdr.mark_failed(row_id, "http_500")
    row2 = wdr.get_by_id(row_id)
    assert row2["attempt_count"] == 2
    assert row2["last_error"] == "http_500"


def test_mark_manual_intervention_terminal(recording_id: int) -> None:
    row_id = wdr.create_pending(recording_id, None, {"x": 1})
    wdr.mark_manual_intervention(row_id, "exhausted")
    row = wdr.get_by_id(row_id)
    assert row["status"] == "manual_intervention_required"
    assert row["last_error"] == "exhausted"
    assert row["attempt_count"] == 1


def test_requeue_in_flight_to_pending_reverts_only_in_flight(recording_id: int) -> None:
    """Story 7.3 AC5 — shutdown sweep flips in_flight → pending; leaves others."""
    a = wdr.create_pending(recording_id, None, {"a": 1})
    b = wdr.create_pending(recording_id, None, {"b": 2})
    c = wdr.create_pending(recording_id, None, {"c": 3})
    wdr.mark_in_flight(a)
    wdr.mark_in_flight(b)
    wdr.mark_failed(c, "boom")
    reverted = wdr.requeue_in_flight_to_pending()
    assert reverted == 2
    assert wdr.get_by_id(a)["status"] == "pending"
    assert wdr.get_by_id(b)["status"] == "pending"
    assert wdr.get_by_id(c)["status"] == "failed"  # untouched


# ──────────────────────────────────────────────────────────────────────────
# Read-side queries
# ──────────────────────────────────────────────────────────────────────────


def test_list_pending_returns_pending_and_in_flight_in_id_order(recording_id: int) -> None:
    a = wdr.create_pending(recording_id, None, {"a": 1})
    b = wdr.create_pending(recording_id, None, {"b": 2})
    c = wdr.create_pending(recording_id, None, {"c": 3})
    wdr.mark_in_flight(a)
    wdr.mark_success(c)
    rows = wdr.list_pending()
    ids = [r["id"] for r in rows]
    assert ids == [a, b]  # success row excluded; ordered ASC


def test_list_pending_excludes_failed_and_manual(recording_id: int) -> None:
    a = wdr.create_pending(recording_id, None, {})
    b = wdr.create_pending(recording_id, None, {})
    wdr.mark_failed(a, "x")
    wdr.mark_manual_intervention(b, "y")
    assert wdr.list_pending() == []


def test_get_latest_for_recording_returns_newest_id(recording_id: int) -> None:
    older = wdr.create_pending(recording_id, None, {"first": True})
    newer = wdr.create_pending(recording_id, None, {"second": True})
    latest = wdr.get_latest_for_recording(recording_id)
    assert latest is not None
    assert latest["id"] == newer
    assert latest["id"] != older


def test_get_latest_for_recording_returns_none_when_no_rows(fresh_db: Path) -> None:
    rec_id = db.insert_recording(
        filename="x.wav",
        filepath="/tmp/x.wav",
        duration_seconds=1.0,
        recorded_at="2026-05-04T00:00:00",
    )
    assert wdr.get_latest_for_recording(rec_id) is None


def test_count_consecutive_recent_failures_basic(recording_id: int) -> None:
    a = wdr.create_pending(recording_id, None, {})
    b = wdr.create_pending(recording_id, None, {})
    c = wdr.create_pending(recording_id, None, {})
    wdr.mark_failed(a, "1st")
    wdr.mark_failed(b, "2nd")
    wdr.mark_failed(c, "3rd")
    assert wdr.count_consecutive_recent_failures(recording_id) == 3


def test_count_consecutive_recent_failures_resets_on_success(recording_id: int) -> None:
    a = wdr.create_pending(recording_id, None, {})
    b = wdr.create_pending(recording_id, None, {})
    c = wdr.create_pending(recording_id, None, {})
    wdr.mark_failed(a, "1st")
    wdr.mark_success(b)  # success in the middle resets the counter
    wdr.mark_failed(c, "after success")
    assert wdr.count_consecutive_recent_failures(recording_id) == 1


def test_count_consecutive_resets_on_manual_intervention(recording_id: int) -> None:
    a = wdr.create_pending(recording_id, None, {})
    b = wdr.create_pending(recording_id, None, {})
    c = wdr.create_pending(recording_id, None, {})
    wdr.mark_failed(a, "1st")
    wdr.mark_manual_intervention(b, "exhausted")
    wdr.mark_failed(c, "fresh")
    # The manual_intervention row is a "boundary" — counter only sees
    # consecutive failed rows since then.
    assert wdr.count_consecutive_recent_failures(recording_id) == 1


# ──────────────────────────────────────────────────────────────────────────
# Retention cleanup (NFR40 / Story 7.7 AC3)
# ──────────────────────────────────────────────────────────────────────────


def _force_created_at(row_id: int, days_ago: int) -> None:
    """Backdate created_at on a row to simulate old data."""
    with sqlite3.connect(db.get_db_path()) as conn:
        conn.execute(
            "UPDATE webhook_deliveries "
            f"SET created_at = datetime('now', '-{days_ago} days') WHERE id = ?",
            (row_id,),
        )
        conn.commit()


def test_cleanup_deletes_old_success_rows(recording_id: int) -> None:
    a = wdr.create_pending(recording_id, None, {"a": 1})
    wdr.mark_success(a)
    _force_created_at(a, days_ago=31)
    deleted = wdr.cleanup_older_than(retention_days=30)
    assert deleted == 1
    assert wdr.get_by_id(a) is None


def test_cleanup_skips_recent_success(recording_id: int) -> None:
    a = wdr.create_pending(recording_id, None, {})
    wdr.mark_success(a)
    _force_created_at(a, days_ago=5)
    assert wdr.cleanup_older_than(30) == 0
    assert wdr.get_by_id(a) is not None


def test_cleanup_deletes_old_manual_intervention(recording_id: int) -> None:
    a = wdr.create_pending(recording_id, None, {})
    wdr.mark_manual_intervention(a, "x")
    _force_created_at(a, days_ago=45)
    assert wdr.cleanup_older_than(30) == 1


def test_cleanup_never_deletes_pending_or_in_flight(recording_id: int) -> None:
    """Pending / in_flight are still actionable — never delete."""
    a = wdr.create_pending(recording_id, None, {})  # pending
    b = wdr.create_pending(recording_id, None, {})
    wdr.mark_in_flight(b)
    _force_created_at(a, days_ago=999)
    _force_created_at(b, days_ago=999)
    assert wdr.cleanup_older_than(30) == 0


def test_cleanup_never_deletes_failed_rows(recording_id: int) -> None:
    """failed rows are queryable for diagnostics until manually retried or escalated."""
    a = wdr.create_pending(recording_id, None, {})
    wdr.mark_failed(a, "something")
    _force_created_at(a, days_ago=999)
    assert wdr.cleanup_older_than(30) == 0


def test_cleanup_zero_retention_skips(recording_id: int) -> None:
    a = wdr.create_pending(recording_id, None, {})
    wdr.mark_success(a)
    _force_created_at(a, days_ago=999)
    assert wdr.cleanup_older_than(0) == 0
    assert wdr.get_by_id(a) is not None  # untouched


# ──────────────────────────────────────────────────────────────────────────
# Misc
# ──────────────────────────────────────────────────────────────────────────


def test_invalid_status_error_constructable() -> None:
    """The exception class is importable + carries the offending value."""
    exc = wdr.InvalidWebhookStatusError("bogus")
    assert exc.received == "bogus"
    assert "bogus" in str(exc)


def test_requeue_failed_row_inserts_fresh_pending(recording_id: int) -> None:
    # Need a real profile row for the profile_id FK.
    with sqlite3.connect(db.get_db_path()) as conn:
        conn.execute(
            "INSERT INTO profiles (name, schema_version, public_fields_json, "
            "private_field_refs_json) VALUES ('p', '1.0', '{}', '{}')"
        )
        conn.commit()
        profile_id = conn.execute("SELECT id FROM profiles").fetchone()[0]
    a = wdr.create_pending(recording_id, profile_id=profile_id, payload={"orig": True})
    wdr.mark_failed(a, "boom")
    new_id = wdr.requeue_failed_row(recording_id)
    assert new_id is not None and new_id != a
    new_row = wdr.get_by_id(new_id)
    assert new_row["status"] == "pending"
    assert new_row["profile_id"] == profile_id
    # Payload preserved bytewise.
    assert json.loads(new_row["payload_json"]) == {"orig": True}


def test_requeue_failed_row_returns_none_when_no_failed_rows(recording_id: int) -> None:
    a = wdr.create_pending(recording_id, None, {})
    wdr.mark_success(a)  # nothing failed
    assert wdr.requeue_failed_row(recording_id) is None
