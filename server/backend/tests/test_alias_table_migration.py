"""Tests for migration 014 + recording_speaker_aliases schema (Issue #104, Story 4.1).

Covers AC1 (table + indexes), AC2 (FK CASCADE), AC3 (per-recording scope —
identity-level uniqueness is NOT enforced).
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


def _seed_recording(db_path: Path, recording_id: int) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO recordings (id, filename, filepath, duration_seconds, recorded_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                recording_id,
                f"r{recording_id}.wav",
                f"/tmp/r{recording_id}.wav",
                1.0,
                "2025-01-15T12:00:00Z",
            ),
        )
        conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# AC1 — schema
# ──────────────────────────────────────────────────────────────────────────


def test_alias_table_exists(fresh_db: Path) -> None:
    with sqlite3.connect(fresh_db) as conn:
        cols = {
            r[1] for r in conn.execute("PRAGMA table_info(recording_speaker_aliases)").fetchall()
        }
    expected = {"id", "recording_id", "speaker_id", "alias_name", "created_at", "updated_at"}
    assert expected.issubset(cols)


def test_alias_index_exists(fresh_db: Path) -> None:
    with sqlite3.connect(fresh_db) as conn:
        idx = {
            r[1]
            for r in conn.execute(
                "SELECT type, name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
    assert "idx_recording_speaker_aliases_recording_id" in idx


def test_unique_recording_speaker_constraint(fresh_db: Path) -> None:
    """UNIQUE(recording_id, speaker_id) enforced at DB layer."""
    _seed_recording(fresh_db, 1)
    with sqlite3.connect(fresh_db) as conn:
        conn.execute(
            "INSERT INTO recording_speaker_aliases "
            "(recording_id, speaker_id, alias_name) VALUES (?, ?, ?)",
            (1, "SPEAKER_00", "Elena"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO recording_speaker_aliases "
                "(recording_id, speaker_id, alias_name) VALUES (?, ?, ?)",
                (1, "SPEAKER_00", "Elena Duplicate"),
            )


# ──────────────────────────────────────────────────────────────────────────
# AC2 — FK enforcement (insertion with non-existent recording_id fails)
# ──────────────────────────────────────────────────────────────────────────


def test_fk_rejects_unknown_recording(fresh_db: Path) -> None:
    """FK constraint fires when recording_id has no parent row."""
    with sqlite3.connect(fresh_db) as conn:
        # PRAGMA foreign_keys must be ON for the FK to be enforced
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO recording_speaker_aliases "
                "(recording_id, speaker_id, alias_name) VALUES (?, ?, ?)",
                (999_999, "SPEAKER_00", "Ghost"),
            )


# ──────────────────────────────────────────────────────────────────────────
# AC3 — per-recording scope (no cross-recording uniqueness)
# ──────────────────────────────────────────────────────────────────────────


def test_same_alias_name_across_recordings_coexists(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    _seed_recording(fresh_db, 2)
    with sqlite3.connect(fresh_db) as conn:
        conn.execute(
            "INSERT INTO recording_speaker_aliases "
            "(recording_id, speaker_id, alias_name) VALUES (?, ?, ?)",
            (1, "SPEAKER_00", "Elena"),
        )
        conn.execute(
            "INSERT INTO recording_speaker_aliases "
            "(recording_id, speaker_id, alias_name) VALUES (?, ?, ?)",
            (2, "SPEAKER_00", "Elena"),
        )
        conn.commit()
        rows = conn.execute(
            "SELECT recording_id, alias_name FROM recording_speaker_aliases ORDER BY recording_id"
        ).fetchall()
    # Both rows persist — different (recording_id, speaker_id) pairs are independent.
    assert rows == [(1, "Elena"), (2, "Elena")]
