"""Migration 013 (normalized_audio_hash) tests
(Issue #104, Sprint 2 carve-out — Item 3).

Asserts that:
  - migration 013 adds `normalized_audio_hash TEXT` to BOTH transcription_jobs
    and recordings
  - the covering indexes are created on each table
  - existing rows retain NULL normalized_audio_hash (NFR21 non-destructiveness)
  - downgrade raises RuntimeError (forward-only per NFR22)
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


def _column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _index_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA index_list({table})").fetchall()
    return {r[1] for r in rows}


def test_normalized_hash_column_on_transcription_jobs(fresh_db: Path) -> None:
    with sqlite3.connect(fresh_db) as conn:
        cols = _column_names(conn, "transcription_jobs")
    assert "normalized_audio_hash" in cols


def test_normalized_hash_column_on_recordings(fresh_db: Path) -> None:
    with sqlite3.connect(fresh_db) as conn:
        cols = _column_names(conn, "recordings")
    assert "normalized_audio_hash" in cols


def test_normalized_hash_index_on_transcription_jobs(fresh_db: Path) -> None:
    with sqlite3.connect(fresh_db) as conn:
        indexes = _index_names(conn, "transcription_jobs")
    assert "idx_transcription_jobs_normalized_audio_hash" in indexes


def test_normalized_hash_index_on_recordings(fresh_db: Path) -> None:
    with sqlite3.connect(fresh_db) as conn:
        indexes = _index_names(conn, "recordings")
    assert "idx_recordings_normalized_audio_hash" in indexes


def test_legacy_rows_have_null_normalized_hash(fresh_db: Path) -> None:
    """A row inserted without specifying normalized_audio_hash gets NULL."""
    with sqlite3.connect(fresh_db) as conn:
        conn.execute(
            "INSERT INTO transcription_jobs (id, status, source) VALUES (?, 'completed', 'http')",
            ("legacy-job-norm",),
        )
        conn.execute(
            """
            INSERT INTO recordings (filename, filepath, duration_seconds, recorded_at)
            VALUES (?, ?, ?, ?)
            """,
            ("leg.mp3", "/tmp/leg.mp3", 1.0, "2026-05-04T00:00:00"),
        )
        conn.commit()
        job_row = conn.execute(
            "SELECT normalized_audio_hash FROM transcription_jobs WHERE id = ?",
            ("legacy-job-norm",),
        ).fetchone()
        rec_row = conn.execute(
            "SELECT normalized_audio_hash FROM recordings WHERE filepath = ?",
            ("/tmp/leg.mp3",),
        ).fetchone()
    assert job_row is not None and job_row[0] is None
    assert rec_row is not None and rec_row[0] is None


def test_downgrade_raises_runtime_error() -> None:
    """The migration's downgrade() must refuse to roll back (NFR22)."""
    import importlib

    migration = importlib.import_module(
        "server.database.migrations.versions.013_add_normalized_audio_hash"
    )
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.downgrade()
