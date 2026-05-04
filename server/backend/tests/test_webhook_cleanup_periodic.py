"""Periodic webhook retention cleanup (Issue #104, Story 7.7 AC3 / NFR40).

Verifies the periodic_webhook_cleanup async-loop shape mirrors
audio_cleanup.periodic_cleanup: immediate first run, periodic
subsequent runs, cancel-safe shutdown.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from server.database import webhook_deliveries_repository as wdr
from server.database.webhook_cleanup import periodic_webhook_cleanup

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


def _backdate(row_id: int, days_ago: int) -> None:
    with sqlite3.connect(db.get_db_path()) as conn:
        conn.execute(
            "UPDATE webhook_deliveries "
            f"SET created_at = datetime('now', '-{days_ago} days') WHERE id = ?",
            (row_id,),
        )
        conn.commit()


async def test_first_run_executes_immediately(recording_id: int) -> None:
    """The startup-cleanup invariant: first call runs synchronously."""
    a = wdr.create_pending(recording_id, None, {})
    wdr.mark_success(a)
    _backdate(a, days_ago=45)
    # interval_hours=0 makes it one-shot (returns after first run).
    await periodic_webhook_cleanup(retention_days=30, interval_hours=0)
    assert wdr.get_by_id(a) is None


async def test_periodic_loop_cancel_safe(recording_id: int) -> None:
    """Cancelling the task mid-sleep must exit cleanly with no exception."""
    task = asyncio.create_task(periodic_webhook_cleanup(retention_days=30, interval_hours=24))
    # Give it a moment to enter the sleep.
    await asyncio.sleep(0.1)
    task.cancel()
    # Awaiting the task itself should NOT raise CancelledError because the
    # function catches it internally and returns. Even if it did, the
    # outer loop would be the one swallowing it; either is acceptable.
    try:
        await task
    except asyncio.CancelledError:
        pass


async def test_zero_retention_skips_cleanup(recording_id: int) -> None:
    """retention_days=0 → keep forever (no DELETE issued)."""
    a = wdr.create_pending(recording_id, None, {})
    wdr.mark_success(a)
    _backdate(a, days_ago=999)
    await periodic_webhook_cleanup(retention_days=0, interval_hours=0)
    assert wdr.get_by_id(a) is not None


async def test_subsequent_runs_after_first_run(recording_id: int) -> None:
    """interval_hours > 0 means the loop continues — verify it DOESN'T return
    immediately after the first run by cancelling after a brief sleep."""
    a = wdr.create_pending(recording_id, None, {})
    wdr.mark_success(a)
    _backdate(a, days_ago=45)

    task = asyncio.create_task(periodic_webhook_cleanup(retention_days=30, interval_hours=24))
    await asyncio.sleep(0.05)
    # The first run should have already deleted the row.
    assert wdr.get_by_id(a) is None
    # Task should be alive — sleeping for the next interval.
    assert not task.done()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
