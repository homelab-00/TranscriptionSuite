"""Migration non-destructiveness regression tests (Issue #104, Story 1.2 + 1.3).

Asserts that:
  - migration 008 creates the profiles table without modifying existing rows
  - migration 009 adds two nullable columns to transcription_jobs without
    modifying existing rows
  - both migrations are idempotent (re-running upgrade is safe)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import server.database.database as db

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


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _row_count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608


# ──────────────────────────────────────────────────────────────────────────
# AC1.2 / AC1.3 — basic schema assertions
# ──────────────────────────────────────────────────────────────────────────


def test_profiles_table_exists_with_expected_columns(fresh_db: Path) -> None:
    with sqlite3.connect(fresh_db) as conn:
        assert _table_exists(conn, "profiles")
        cols = _column_names(conn, "profiles")
    expected = {
        "id",
        "name",
        "description",
        "schema_version",
        "public_fields_json",
        "private_field_refs_json",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(set(cols))


def test_transcription_jobs_has_snapshot_columns(fresh_db: Path) -> None:
    with sqlite3.connect(fresh_db) as conn:
        cols = _column_names(conn, "transcription_jobs")
    assert "job_profile_snapshot" in cols
    assert "snapshot_schema_version" in cols


# ──────────────────────────────────────────────────────────────────────────
# AC1.2 / AC1.3 AC2 — non-destructiveness
# ──────────────────────────────────────────────────────────────────────────


def test_existing_recordings_preserved_through_migrations(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre-populate recordings + a transcription_jobs row, then re-run init_db()
    (which re-applies migrations idempotently) and assert nothing changed.

    `recordings` table is created by migration 001; `transcription_jobs` by 006.
    """
    with sqlite3.connect(fresh_db) as conn:
        # Insert a recordings row using only required columns inferred from schema
        conn.execute(
            "INSERT INTO recordings (filename, filepath, duration_seconds, recorded_at) "
            "VALUES (?, ?, ?, ?)",
            ("test.wav", "/tmp/test.wav", 12.34, "2025-01-15T12:00:00Z"),
        )
        conn.execute(
            "INSERT INTO transcription_jobs (id, status, source) VALUES (?, 'completed', 'http')",
            ("job-abc",),
        )
        conn.commit()

    pre_recordings = _read_all(fresh_db, "recordings")
    pre_jobs = _read_all(fresh_db, "transcription_jobs")

    # Re-run init_db (idempotent): every migration's `IF NOT EXISTS` / column-check
    # guard should make this a no-op for existing data.
    db.init_db()

    post_recordings = _read_all(fresh_db, "recordings")
    post_jobs = _read_all(fresh_db, "transcription_jobs")

    assert post_recordings == pre_recordings
    # transcription_jobs row preserved; new snapshot columns are NULL
    assert len(post_jobs) == len(pre_jobs)
    job_post = post_jobs[0]
    assert job_post["id"] == "job-abc"
    # AC1.3 AC1: nullable for legacy rows
    assert job_post["job_profile_snapshot"] is None
    assert job_post["snapshot_schema_version"] is None


def test_migration_idempotent(fresh_db: Path) -> None:
    """Re-running init_db() must succeed without raising or duplicating rows."""
    db.init_db()  # second call
    db.init_db()  # third call
    with sqlite3.connect(fresh_db) as conn:
        # alembic_version table should still hold a single head revision
        rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    assert len(rows) == 1
    # Head advances with each sprint; accept any current-or-later revision.
    # 009 = Stories 1.2/1.3, 010 = Story 1.9, 011 = Story 2.1, 012 = Sprint 2 Item 2.
    assert rows[0][0] in {"009", "010", "011", "012"}


def _read_all(db_path: Path, table: str) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()  # noqa: S608
        return [dict(r) for r in rows]
