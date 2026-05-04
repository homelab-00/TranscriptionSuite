"""Auto-action independence + partial-success tests (Issue #104, Story 6.5).

Story 6.5 says auto-summary and auto-export must be independent:

  AC1: Summary failure does not block export — export still runs and
       writes the transcript file.
  AC2: Export failure does not block summary — summary still saves to
       the recording.

Both surfaces show TWO independent badges (Story 6.6) — Story 6.5 is
the underlying-data assertion.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import server.database.database as db
from server.core import auto_action_coordinator as coord
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


def _seed_recording(db_path: Path, recording_id: int = 1) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO recordings (id, filename, filepath, title, duration_seconds, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (recording_id, "r.wav", "/tmp/r.wav", "RecTitle", 60.0, "2025-01-15T12:00:00Z"),
        )
        conn.execute(
            "INSERT INTO segments (recording_id, segment_index, text, start_time, end_time, speaker) "
            "VALUES (?, 0, 'hi', 0.0, 1.0, 'SPEAKER_00')",
            (recording_id,),
        )
        conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# AC1 — summary failure does NOT block export
# ──────────────────────────────────────────────────────────────────────────


def test_summary_failure_does_not_block_export(
    fresh_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM unreachable + auto_export enabled → export still runs.

    Outcome: auto_summary_status='failed', auto_export_status='success'.
    """
    _seed_recording(fresh_db)

    from server.core.auto_summary_engine import AutoSummaryError

    async def _summary_fails(_rec_id: int, _public: Mapping[str, Any]) -> dict:
        raise AutoSummaryError("LLM unreachable")

    monkeypatch.setattr("server.core.auto_summary_engine.summarize_for_auto_action", _summary_fails)

    dest = tmp_path / "exports"
    dest.mkdir()
    snapshot = {
        "profile_id": 1,
        "public_fields": {
            "auto_summary_enabled": True,
            "auto_export_enabled": True,
            "destination_folder": str(dest),
            "filename_template": "{title}.txt",
        },
    }

    asyncio.run(coord.trigger_auto_actions(1, snapshot))

    # Summary failed
    assert repo.get_auto_action_status(1, "auto_summary") == "failed"
    # Export succeeded — independence proven
    assert repo.get_auto_action_status(1, "auto_export") == "success"
    assert (dest / "RecTitle.txt").exists()


# ──────────────────────────────────────────────────────────────────────────
# AC2 — export failure does NOT block summary
# ──────────────────────────────────────────────────────────────────────────


def test_export_failure_does_not_block_summary(
    fresh_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Destination unmounted + auto_summary enabled → summary still saves
    to recordings.summary; export goes to 'deferred'.

    Outcome: auto_summary_status='success', auto_export_status='deferred'.
    """
    _seed_recording(fresh_db)

    async def _summary_ok(_rec_id: int, _public: Mapping[str, Any]) -> dict:
        return {
            "text": "Successful summary content here.",
            "model": "test-model",
            "tokens_used": 30,
            "truncated": False,
        }

    monkeypatch.setattr("server.core.auto_summary_engine.summarize_for_auto_action", _summary_ok)

    snapshot = {
        "profile_id": 1,
        "public_fields": {
            "auto_summary_enabled": True,
            "auto_export_enabled": True,
            "destination_folder": str(tmp_path / "does-not-exist"),
            "filename_template": "{title}.txt",
        },
    }

    asyncio.run(coord.trigger_auto_actions(1, snapshot))

    # Summary succeeded and persisted to recording
    assert repo.get_auto_action_status(1, "auto_summary") == "success"
    assert db.get_recording_summary(1) == "Successful summary content here."
    # Export deferred — independence proven
    assert repo.get_auto_action_status(1, "auto_export") == "deferred"


# ──────────────────────────────────────────────────────────────────────────
# Both can fail independently — each gets its own status
# ──────────────────────────────────────────────────────────────────────────


def test_both_fail_independently_two_distinct_statuses(
    fresh_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM down AND destination missing → two distinct failure states.

    Recording has TWO badges: ⚠ summary failed (red), ⚠ export deferred (amber).
    """
    _seed_recording(fresh_db)

    from server.core.auto_summary_engine import AutoSummaryError

    async def _summary_fails(_rec_id: int, _public: Mapping[str, Any]) -> dict:
        raise AutoSummaryError("LLM unreachable")

    monkeypatch.setattr("server.core.auto_summary_engine.summarize_for_auto_action", _summary_fails)

    snapshot = {
        "profile_id": 1,
        "public_fields": {
            "auto_summary_enabled": True,
            "auto_export_enabled": True,
            "destination_folder": str(tmp_path / "does-not-exist"),
            "filename_template": "{title}.txt",
        },
    }

    asyncio.run(coord.trigger_auto_actions(1, snapshot))

    state = repo.get_auto_action_state(1)
    # Two independent failure states — neither badge is the other's status
    assert state["auto_summary_status"] == "failed"
    assert state["auto_export_status"] == "deferred"
    # Errors are also independent
    assert "LLM unreachable" in (state["auto_summary_error"] or "")
    assert "destination not available" in (state["auto_export_error"] or "")


# ──────────────────────────────────────────────────────────────────────────
# Both succeed — happy path also independent
# ──────────────────────────────────────────────────────────────────────────


def test_both_succeed_two_distinct_success_statuses(
    fresh_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanity check: happy path leaves both at status='success'."""
    _seed_recording(fresh_db)

    async def _summary_ok(_rec_id: int, _public: Mapping[str, Any]) -> dict:
        return {
            "text": "Both succeeded.",
            "model": "m",
            "tokens_used": 10,
            "truncated": False,
        }

    monkeypatch.setattr("server.core.auto_summary_engine.summarize_for_auto_action", _summary_ok)

    dest = tmp_path / "exports"
    dest.mkdir()
    snapshot = {
        "profile_id": 1,
        "public_fields": {
            "auto_summary_enabled": True,
            "auto_export_enabled": True,
            "destination_folder": str(dest),
            "filename_template": "{title}.txt",
        },
    }

    asyncio.run(coord.trigger_auto_actions(1, snapshot))

    assert repo.get_auto_action_status(1, "auto_summary") == "success"
    assert repo.get_auto_action_status(1, "auto_export") == "success"


# ──────────────────────────────────────────────────────────────────────────
# Concurrency — summary and export run in parallel (not sequential)
# ──────────────────────────────────────────────────────────────────────────


def test_summary_and_export_run_concurrently(
    fresh_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both tasks should be in flight simultaneously — coordinator uses
    independent asyncio.Tasks, not sequential awaits.

    We measure: the slower task's start time should be < the faster
    task's end time (overlap proven).
    """
    _seed_recording(fresh_db)
    timings: dict[str, float] = {}

    import time as _time

    async def _slow_summary(_rec_id: int, _public: Mapping[str, Any]) -> dict:
        timings["summary_start"] = _time.monotonic()
        await asyncio.sleep(0.2)  # simulate slow LLM
        timings["summary_end"] = _time.monotonic()
        return {
            "text": "Done after 200ms.",
            "model": "m",
            "tokens_used": 5,
            "truncated": False,
        }

    monkeypatch.setattr("server.core.auto_summary_engine.summarize_for_auto_action", _slow_summary)

    # Wrap _write_atomic to record export timing. _write_atomic runs
    # inside a worker thread (via asyncio.to_thread), so we use
    # time.monotonic() instead of asyncio.get_event_loop().time() —
    # there's no running event loop in the worker thread.
    original_write = coord._write_atomic

    def timed_write(target: Path, content: str) -> None:
        timings.setdefault("export_start", _time.monotonic())
        original_write(target, content)
        timings["export_end"] = _time.monotonic()

    monkeypatch.setattr(coord, "_write_atomic", timed_write)

    dest = tmp_path / "exports"
    dest.mkdir()
    snapshot = {
        "profile_id": 1,
        "public_fields": {
            "auto_summary_enabled": True,
            "auto_export_enabled": True,
            "destination_folder": str(dest),
            "filename_template": "{title}.txt",
        },
    }

    asyncio.run(coord.trigger_auto_actions(1, snapshot))

    # Export should have started before summary finished — proves concurrency.
    assert timings["export_start"] < timings["summary_end"], (
        f"Tasks ran sequentially; timings={timings}"
    )
