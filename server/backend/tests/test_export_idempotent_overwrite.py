"""Story 6.10 — idempotent re-export semantics tests.

AC1: Same path overwrites in-place via os.replace; no .1/.2 suffix accumulation
AC2: Concurrent retry collision — atomic write semantics ensure last writer
     wins; never half-written file
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

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


def _seed(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO recordings (id, filename, filepath, title, duration_seconds, recorded_at) "
            "VALUES (1, 'r.wav', '/tmp/r.wav', 'TestRec', 60.0, '2025-01-15T12:00:00Z')"
        )
        conn.execute(
            "INSERT INTO segments (recording_id, segment_index, text, start_time, end_time, speaker) "
            "VALUES (1, 0, 'hello world', 0.0, 1.0, 'SPEAKER_00')"
        )
        conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# AC1 — same path overwrites; no suffix accumulation
# ──────────────────────────────────────────────────────────────────────────


def test_re_export_overwrites_in_place_no_suffix(fresh_db: Path, tmp_path: Path) -> None:
    """Run auto-export twice; only ONE file at the path; no .1/.2 suffix."""
    _seed(fresh_db)
    dest = tmp_path / "exports"
    dest.mkdir()
    public = {
        "auto_export_enabled": True,
        "destination_folder": str(dest),
        "filename_template": "{title}.txt",
    }

    asyncio.run(coord._run_auto_export(1, public))
    first_files = sorted(p.name for p in dest.iterdir())
    assert first_files == ["TestRec.txt"]

    # Mutate the recording (e.g. user updated title) — re-fire export
    db.update_recording_summary(1, "Now there's a summary too.", "test-model")
    asyncio.run(coord._run_auto_export(1, public))
    second_files = sorted(p.name for p in dest.iterdir())
    # Transcript file overwritten in place; summary file added
    assert second_files == ["TestRec.txt", "TestRec.txt.summary.txt"]
    # No accumulation — no .1 / .2
    assert not (dest / "TestRec.1.txt").exists()
    assert not (dest / "TestRec.txt.1").exists()


def test_atomic_write_no_tmp_leftover_on_success(tmp_path: Path) -> None:
    """Story 6.10 — _write_atomic uses .tmp sibling + os.replace; no .tmp left."""
    target = tmp_path / "out.txt"
    coord._write_atomic(target, "first")
    coord._write_atomic(target, "second")
    coord._write_atomic(target, "third")
    assert target.read_text() == "third"
    # Only one file at the target; no .tmp leftover
    siblings = sorted(p.name for p in tmp_path.iterdir())
    assert siblings == ["out.txt"]


# ──────────────────────────────────────────────────────────────────────────
# AC2 — concurrent retry collision
# ──────────────────────────────────────────────────────────────────────────


def test_concurrent_retry_atomicity(tmp_path: Path) -> None:
    """Two concurrent _write_atomic calls — file content matches ONE of the
    inputs exactly (no half-written / interleaved bytes).

    On POSIX, os.replace is atomic — the kernel-level rename guarantees
    we never see a half-finished file at the target path.
    """
    target = tmp_path / "shared.txt"
    content_a = "A" * 4096
    content_b = "B" * 4096

    async def runner() -> None:
        await asyncio.gather(
            asyncio.to_thread(coord._write_atomic, target, content_a),
            asyncio.to_thread(coord._write_atomic, target, content_b),
        )

    asyncio.run(runner())

    final = target.read_text()
    # Last writer wins — content matches one of the two inputs in entirety
    assert final == content_a or final == content_b
    # File size matches exactly — no truncation, no partial write
    assert target.stat().st_size == len(content_a)


def test_concurrent_retry_summary_and_transcript_ok(fresh_db: Path, tmp_path: Path) -> None:
    """Two retries fire back-to-back on the SAME recording: both succeed,
    and the resulting files are well-formed (transcript + summary)."""
    _seed(fresh_db)
    db.update_recording_summary(1, "Summary text.", "test-model")
    dest = tmp_path / "exports"
    dest.mkdir()
    public = {
        "auto_export_enabled": True,
        "destination_folder": str(dest),
        "filename_template": "{title}.txt",
    }

    async def runner() -> None:
        await asyncio.gather(
            coord._run_auto_export(1, public),
            coord._run_auto_export(1, public),
        )

    asyncio.run(runner())

    # Both files exist with valid content
    transcript = dest / "TestRec.txt"
    summary = dest / "TestRec.txt.summary.txt"
    assert transcript.exists()
    assert summary.exists()
    assert summary.read_text() == "Summary text."
    # Final status is success (last writer wins)
    assert repo.get_auto_action_status(1, "auto_export") == "success"
