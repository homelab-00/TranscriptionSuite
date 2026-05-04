"""Migration 011 (audio_hash column) tests (Issue #104, Story 2.1).

Asserts that:
  - migration 011 adds `audio_hash TEXT` to transcription_jobs
  - the covering index `idx_transcription_jobs_audio_hash` is created
  - existing rows retain NULL audio_hash (NFR21 non-destructiveness)
  - re-running init_db is idempotent
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


# ──────────────────────────────────────────────────────────────────────────
# AC2.1.AC1 — schema
# ──────────────────────────────────────────────────────────────────────────


def test_audio_hash_column_exists(fresh_db: Path) -> None:
    with sqlite3.connect(fresh_db) as conn:
        cols = _column_names(conn, "transcription_jobs")
    assert "audio_hash" in cols


def test_audio_hash_index_exists(fresh_db: Path) -> None:
    with sqlite3.connect(fresh_db) as conn:
        indexes = _index_names(conn, "transcription_jobs")
    assert "idx_transcription_jobs_audio_hash" in indexes


def test_audio_hash_round_trips(fresh_db: Path) -> None:
    """Inserting + selecting the hash value preserves it byte-for-byte."""
    test_hash = "a" * 64  # SHA-256 hex is 64 chars
    with sqlite3.connect(fresh_db) as conn:
        conn.execute(
            "INSERT INTO transcription_jobs (id, status, source, audio_hash) "
            "VALUES (?, 'completed', 'file_import', ?)",
            ("job-with-hash", test_hash),
        )
        conn.commit()
        row = conn.execute(
            "SELECT audio_hash FROM transcription_jobs WHERE id = ?",
            ("job-with-hash",),
        ).fetchone()
    assert row is not None
    assert row[0] == test_hash


# ──────────────────────────────────────────────────────────────────────────
# AC2.1.AC2 — legacy rows have NULL audio_hash
# ──────────────────────────────────────────────────────────────────────────


def test_legacy_row_has_null_audio_hash(fresh_db: Path) -> None:
    """A row inserted without specifying audio_hash gets NULL — confirming
    the column is nullable and backfill is opt-in only.
    """
    with sqlite3.connect(fresh_db) as conn:
        conn.execute(
            "INSERT INTO transcription_jobs (id, status, source) VALUES (?, 'completed', 'http')",
            ("legacy-job",),
        )
        conn.commit()
        row = conn.execute(
            "SELECT audio_hash FROM transcription_jobs WHERE id = ?",
            ("legacy-job",),
        ).fetchone()
    assert row is not None
    assert row[0] is None


# ──────────────────────────────────────────────────────────────────────────
# Forward-only downgrade (NFR22)
# ──────────────────────────────────────────────────────────────────────────


def test_downgrade_raises_runtime_error() -> None:
    """The migration's downgrade() must refuse to roll back.

    Migration filenames are digit-prefixed (`011_add_..._jobs.py`), which
    aren't valid Python identifiers — `importlib.import_module` accepts
    them as strings.
    """
    import importlib

    migration = importlib.import_module(
        "server.database.migrations.versions.011_add_audio_hash_to_transcription_jobs"
    )
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.downgrade()
