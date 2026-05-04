"""Lifespan-wiring tests for the deferred-export sweeper (Issue #104, Sprint 4 no. 1).

The sweeper itself is unit-tested in test_deferred_export_sweep.py. What this
file proves is that ``server.api.main.lifespan`` actually wires it: the task
is created on startup, the configured interval is honored, and cancellation
on shutdown is clean.

Two layers:

1. Static source assertions — catch refactors that accidentally drop the
   wiring without exercising the heavy lifespan startup path (CUDA probe,
   model manager, DB migrations, etc.).
2. A lightweight functional test that schedules ``periodic_deferred_export_sweep``
   exactly as the lifespan does (``asyncio.create_task`` with the configured
   interval) and asserts a deferred row flips to ``success`` automatically —
   proving the loop runs and is interruptible.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from server.core import auto_action_sweeper as sweeper
from server.database import auto_action_repository as repo

pytest.importorskip("alembic")


# ─── Static source assertions ───────────────────────────────────────────────


def test_lifespan_schedules_periodic_deferred_export_sweep() -> None:
    """``main.lifespan`` must reference the sweeper and config key by name."""
    from server.api import main as main_mod

    src = inspect.getsource(main_mod.lifespan)
    assert "periodic_deferred_export_sweep" in src, (
        "lifespan does not import/schedule the deferred-export sweeper"
    )
    assert "deferred_export_sweep_interval_s" in src, (
        "lifespan does not read the deferred_export_sweep_interval_s config key"
    )


def test_lifespan_cancels_deferred_export_sweep_on_shutdown() -> None:
    """``main.lifespan`` must cancel and await the sweeper task on shutdown."""
    from server.api import main as main_mod

    src = inspect.getsource(main_mod.lifespan)
    assert "_deferred_export_sweep_task" in src, "lifespan does not store the sweeper task handle"
    # The cancel + await pair lives in the shutdown half of the generator.
    assert "_deferred_export_sweep_task.cancel()" in src, (
        "lifespan does not cancel the sweeper task on shutdown"
    )


# ─── Functional test: scheduled task flips deferred → success ───────────────


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


def _seed_recording(db_path: Path, recording_id: int = 1) -> None:
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


def test_scheduled_sweeper_task_flips_deferred_row_to_success(
    fresh_db: Path, tmp_path: Path
) -> None:
    """Mirror the lifespan wiring shape: schedule the sweeper as an
    asyncio.Task with a tiny interval; insert a deferred row whose
    destination is already mounted; assert the row flips to 'success'
    within a few sweep iterations and that cancellation on shutdown is
    clean."""
    _seed_recording(fresh_db)
    dest = tmp_path / "mounted"
    dest.mkdir()

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

    async def runner() -> None:
        task = asyncio.create_task(sweeper.periodic_deferred_export_sweep(interval_s=0.05))
        try:
            # Wait for at least one sweep iteration to land. Up to ~1s budget.
            for _ in range(20):
                await asyncio.sleep(0.05)
                if repo.get_auto_action_status(1, "auto_export") == "success":
                    break
            assert repo.get_auto_action_status(1, "auto_export") == "success"
            assert (dest / "TestRec.txt").exists()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # Awaiting a cancelled task may re-raise CancelledError;
                # we asked for cancellation, so swallow it.
                pass

    asyncio.run(runner())
