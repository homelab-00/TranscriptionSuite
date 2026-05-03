"""Migration 012 (audio_hash on recordings) tests (Issue #104, Sprint 2 Item 2).

Mirrors test_audio_hash_migration.py for transcription_jobs. Asserts:
  - migration 012 adds `audio_hash TEXT` to recordings
  - the covering index `idx_recordings_audio_hash` is created
  - existing rows retain NULL audio_hash (NFR21 non-destructiveness)
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


def test_recordings_audio_hash_column_exists(fresh_db: Path) -> None:
    with sqlite3.connect(fresh_db) as conn:
        cols = _column_names(conn, "recordings")
    assert "audio_hash" in cols


def test_recordings_audio_hash_index_exists(fresh_db: Path) -> None:
    with sqlite3.connect(fresh_db) as conn:
        indexes = _index_names(conn, "recordings")
    assert "idx_recordings_audio_hash" in indexes


def test_recordings_audio_hash_round_trips(fresh_db: Path) -> None:
    """Inserting + selecting the hash value preserves it byte-for-byte."""
    test_hash = "a" * 64  # SHA-256 hex is 64 chars
    with sqlite3.connect(fresh_db) as conn:
        conn.execute(
            """
            INSERT INTO recordings
                (filename, filepath, duration_seconds, recorded_at, audio_hash)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("file.mp3", "/tmp/file.mp3", 1.0, "2026-05-04T00:00:00", test_hash),
        )
        conn.commit()
        row = conn.execute(
            "SELECT audio_hash FROM recordings WHERE filepath = ?",
            ("/tmp/file.mp3",),
        ).fetchone()
    assert row is not None
    assert row[0] == test_hash


def test_legacy_recording_row_has_null_audio_hash(fresh_db: Path) -> None:
    """Recording inserted without audio_hash gets NULL (column is nullable)."""
    with sqlite3.connect(fresh_db) as conn:
        conn.execute(
            """
            INSERT INTO recordings
                (filename, filepath, duration_seconds, recorded_at)
            VALUES (?, ?, ?, ?)
            """,
            ("legacy.mp3", "/tmp/legacy.mp3", 1.0, "2026-05-04T00:00:00"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT audio_hash FROM recordings WHERE filepath = ?",
            ("/tmp/legacy.mp3",),
        ).fetchone()
    assert row is not None
    assert row[0] is None


def test_downgrade_raises_runtime_error() -> None:
    """The migration's downgrade() must refuse to roll back (NFR22).

    Migration filenames are digit-prefixed (`012_add_..._recordings.py`),
    which aren't valid Python identifiers — `importlib.import_module`
    accepts them as strings.
    """
    import importlib

    migration = importlib.import_module(
        "server.database.migrations.versions.012_add_audio_hash_to_recordings"
    )
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.downgrade()
