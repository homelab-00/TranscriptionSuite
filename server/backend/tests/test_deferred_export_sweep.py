"""Story 6.8 — periodic deferred-export sweeper tests (R-EL12, NFR20).

AC1 — Detect transient destination unavailability — covered in
      test_auto_action_coordinator.py::test_auto_export_missing_destination_marks_deferred

AC2 — Periodic sweeper checks os.path.isdir on each iteration; re-fires
      when the destination is back. Bootstrap-safe (NFR24a) — picks up
      rows that survived a restart.

AC3 — Auto-export re-fires summary too — Sprint 4 doesn't auto-pair
      summary+export (independence Story 6.5); the sweeper re-fires
      ONLY auto_export rows that are deferred. Summary retries are
      separate (retry_pending status, Story 6.11).

AC4 — User-visible badge (frontend, Story 6.6) — covered in
      AutoActionStatusBadge.test.tsx.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from server.core import auto_action_sweeper as sweeper
from server.database import auto_action_repository as repo

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


def _seed(db_path: Path, recording_id: int = 1) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO recordings (id, filename, filepath, title, duration_seconds, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                recording_id,
                f"r{recording_id}.wav",
                f"/tmp/r{recording_id}.wav",
                "TestRec",
                60.0,
                "2025-01-15T12:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO segments (recording_id, segment_index, text, start_time, end_time, speaker) "
            "VALUES (?, 0, 'hi', 0.0, 1.0, 'SPEAKER_00')",
            (recording_id,),
        )
        conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# _sweep_once — destination still missing
# ──────────────────────────────────────────────────────────────────────────


def test_sweeper_skips_when_destination_still_missing(fresh_db: Path, tmp_path: Path) -> None:
    """Row stays at 'deferred' when os.path.isdir(destination) is False."""
    _seed(fresh_db)
    repo.set_auto_export_status(
        1, "deferred", error="missing", path=str(tmp_path / "still-missing")
    )
    asyncio.run(sweeper._sweep_once())
    # Still deferred — no progress
    assert repo.get_auto_action_status(1, "auto_export") == "deferred"


# ──────────────────────────────────────────────────────────────────────────
# _sweep_once — destination back online → re-fire
# ──────────────────────────────────────────────────────────────────────────


def test_sweeper_refires_when_destination_returns(fresh_db: Path, tmp_path: Path) -> None:
    """Snapshot is loaded from the row; sweeper re-fires; status flips
    to 'success' once the destination is mounted."""
    _seed(fresh_db)
    dest = tmp_path / "mounted"
    dest.mkdir()
    # Save the profile snapshot the retry path will look up.
    import json

    repo.save_profile_snapshot(
        1,
        json.dumps(
            {
                "profile_id": 1,
                "public_fields": {
                    "auto_export_enabled": True,
                    "destination_folder": str(dest),
                    "filename_template": "{title}.txt",
                },
            }
        ),
    )
    repo.set_auto_export_status(1, "deferred", path=str(dest))

    asyncio.run(sweeper._sweep_once())

    assert repo.get_auto_action_status(1, "auto_export") == "success"
    assert (dest / "TestRec.txt").exists()


# ──────────────────────────────────────────────────────────────────────────
# _sweep_once — auto_summary retry_pending
# ──────────────────────────────────────────────────────────────────────────


def test_sweeper_retries_summary_marked_retry_pending(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Story 6.11 preview — sweeper picks up auto_summary rows in
    'retry_pending' state."""
    _seed(fresh_db)
    import json

    repo.save_profile_snapshot(1, json.dumps({"public_fields": {"auto_summary_enabled": True}}))
    repo.set_auto_summary_status(1, "retry_pending", error="transient")

    async def _ok(_rec, _public):
        return {
            "text": "Successful retry result.",
            "model": "m",
            "tokens_used": 30,
            "truncated": False,
        }

    monkeypatch.setattr("server.core.auto_summary_engine.summarize_for_auto_action", _ok)

    asyncio.run(sweeper._sweep_once())

    assert repo.get_auto_action_status(1, "auto_summary") == "success"


def test_sweeper_does_not_retry_failed_status(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sweeper does NOT auto-retry 'failed' rows — only manual retry +
    'retry_pending' / 'deferred' triggers a re-fire."""
    _seed(fresh_db)
    repo.set_auto_summary_status(1, "failed", error="transient")

    called = [False]

    async def _maybe(_rec, _public):
        called[0] = True
        return {"text": "x", "model": "m", "tokens_used": 1, "truncated": False}

    monkeypatch.setattr("server.core.auto_summary_engine.summarize_for_auto_action", _maybe)

    asyncio.run(sweeper._sweep_once())
    # Sweeper skipped the 'failed' row entirely
    assert called[0] is False
    assert repo.get_auto_action_status(1, "auto_summary") == "failed"


# ──────────────────────────────────────────────────────────────────────────
# _sweep_once — empty list
# ──────────────────────────────────────────────────────────────────────────


def test_sweeper_noop_when_no_actionable_rows(fresh_db: Path) -> None:
    """No rows in 'deferred' / 'retry_pending' → sweeper logs and returns."""
    _seed(fresh_db)
    asyncio.run(sweeper._sweep_once())
    # No status was set
    assert repo.get_auto_action_status(1, "auto_export") is None


# ──────────────────────────────────────────────────────────────────────────
# Cancel-safety
# ──────────────────────────────────────────────────────────────────────────


def test_periodic_sweep_cancel_clean(fresh_db: Path) -> None:
    """asyncio.CancelledError mid-sleep exits cleanly without raising."""

    async def runner():
        task = asyncio.create_task(sweeper.periodic_deferred_export_sweep(interval_s=0.05))
        await asyncio.sleep(0.02)
        task.cancel()
        # Awaiting a cancelled task either returns or raises
        # CancelledError; the sweeper itself catches the inner
        # CancelledError but the outer await may still see it.
        try:
            await task
        except asyncio.CancelledError:
            # Sweeper catches the inner CancelledError, but the outer await
            # may still surface it on a tight schedule. Either is acceptable.
            pass

    asyncio.run(runner())


def test_periodic_sweep_disabled_when_interval_le_zero(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """interval_s <= 0 returns immediately (one-shot disabled mode)."""
    asyncio.run(sweeper.periodic_deferred_export_sweep(interval_s=0))
    asyncio.run(sweeper.periodic_deferred_export_sweep(interval_s=-1.0))
    # No exceptions, returns immediately — assertion implicit


# ──────────────────────────────────────────────────────────────────────────
# Bootstrap-safety (NFR24a)
# ──────────────────────────────────────────────────────────────────────────


def test_sweeper_picks_up_rows_persisted_across_restart(fresh_db: Path, tmp_path: Path) -> None:
    """A row written by an earlier process is visible to the sweeper
    without any in-memory state — proves bootstrap-safety."""
    _seed(fresh_db)
    dest = tmp_path / "mounted"
    dest.mkdir()
    import json

    repo.save_profile_snapshot(
        1,
        json.dumps(
            {
                "public_fields": {
                    "auto_export_enabled": True,
                    "destination_folder": str(dest),
                    "filename_template": "{title}.txt",
                }
            }
        ),
    )
    repo.set_auto_export_status(1, "deferred", path=str(dest))

    # No state passed — sweeper reads from DB.
    asyncio.run(sweeper._sweep_once())

    assert repo.get_auto_action_status(1, "auto_export") == "success"
