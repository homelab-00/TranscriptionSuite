"""FK cascade verification for recording_speaker_aliases (Issue #104, Story 4.5).

When a parent ``recordings`` row is deleted, the FK ON DELETE CASCADE
constraint added in migration 014 must remove every alias row whose
``recording_id`` matches the deleted parent.

AC1: cascade goes 3 → 0 after delete.
AC2: cascade survives DB dump/restore (the constraint is encoded at the
schema level, not at app code level — same pattern as
test_diarization_review_state_survives_restore from Sprint 1).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from server.database import alias_repository
from server.database.database import delete_recording

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
# AC1 — happy path cascade
# ──────────────────────────────────────────────────────────────────────────


def test_alias_rows_cascade_when_recording_deleted(fresh_db: Path) -> None:
    """3 alias rows → delete recording → 0 alias rows (Story 4.5 AC1)."""
    _seed_recording(fresh_db, 1)
    alias_repository.replace_aliases(
        1,
        [
            {"speaker_id": "SPEAKER_00", "alias_name": "Elena"},
            {"speaker_id": "SPEAKER_01", "alias_name": "Marco"},
            {"speaker_id": "SPEAKER_02", "alias_name": "Sami"},
        ],
    )
    assert len(alias_repository.list_aliases(1)) == 3

    assert delete_recording(1) is True

    # Cascade fired — no alias rows remain
    assert alias_repository.list_aliases(1) == []
    # Direct row count just to be sure
    with sqlite3.connect(fresh_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM recording_speaker_aliases WHERE recording_id = ?",
            (1,),
        ).fetchone()[0]
    assert count == 0


def test_cascade_only_affects_deleted_recording(fresh_db: Path) -> None:
    """Deleting recording 1 must NOT remove aliases for recording 2."""
    _seed_recording(fresh_db, 1)
    _seed_recording(fresh_db, 2)
    alias_repository.replace_aliases(1, [{"speaker_id": "SPEAKER_00", "alias_name": "Elena"}])
    alias_repository.replace_aliases(2, [{"speaker_id": "SPEAKER_00", "alias_name": "Marco"}])
    assert len(alias_repository.list_aliases(1)) == 1
    assert len(alias_repository.list_aliases(2)) == 1

    delete_recording(1)

    assert alias_repository.list_aliases(1) == []
    # Recording 2's alias must remain untouched
    assert alias_repository.list_aliases(2) == [{"speaker_id": "SPEAKER_00", "alias_name": "Marco"}]


# ──────────────────────────────────────────────────────────────────────────
# AC2 — cascade survives DB dump/restore
# ──────────────────────────────────────────────────────────────────────────


def test_cascade_survives_db_restore(fresh_db: Path) -> None:
    """Schema-level FK is preserved across schema/data round-trip — Story 4.5 AC2.

    iterdump() chokes on FTS5 virtual tables (words_fts), so the round
    trip is performed by extracting just the schema for the two tables
    we care about (recordings + recording_speaker_aliases) plus their
    data, then restoring into an in-memory DB. The CASCADE constraint
    is encoded in the CREATE TABLE statement itself, so this is the
    real test surface — full-DB iterdump fidelity is unrelated.
    """
    _seed_recording(fresh_db, 7)
    alias_repository.replace_aliases(
        7,
        [
            {"speaker_id": "SPEAKER_00", "alias_name": "Elena"},
            {"speaker_id": "SPEAKER_01", "alias_name": "Marco"},
        ],
    )

    # Pull schema for the two tables of interest
    with sqlite3.connect(fresh_db) as src:
        schemas: list[str] = []
        for tbl in ("recordings", "recording_speaker_aliases"):
            row = src.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (tbl,),
            ).fetchone()
            assert row is not None, f"missing schema for {tbl}"
            schemas.append(row[0] + ";")
        # Plus rows
        recordings_rows = src.execute("SELECT * FROM recordings WHERE id = 7").fetchall()
        alias_rows = src.execute(
            "SELECT recording_id, speaker_id, alias_name FROM recording_speaker_aliases "
            "WHERE recording_id = 7"
        ).fetchall()

    restored = sqlite3.connect(":memory:")
    restored.execute("PRAGMA foreign_keys = ON")
    for stmt in schemas:
        restored.execute(stmt)
    # Re-insert the parent then children (FK ordering)
    placeholders = ",".join("?" * len(recordings_rows[0]))
    restored.executemany(f"INSERT INTO recordings VALUES ({placeholders})", recordings_rows)
    restored.executemany(
        "INSERT INTO recording_speaker_aliases (recording_id, speaker_id, alias_name) "
        "VALUES (?, ?, ?)",
        alias_rows,
    )
    restored.commit()

    # Confirm rows survived
    rows = restored.execute(
        "SELECT COUNT(*) FROM recording_speaker_aliases WHERE recording_id = 7"
    ).fetchone()[0]
    assert rows == 2

    # Trigger cascade in the restored DB
    restored.execute("DELETE FROM recordings WHERE id = ?", (7,))
    restored.commit()

    rows_after = restored.execute(
        "SELECT COUNT(*) FROM recording_speaker_aliases WHERE recording_id = 7"
    ).fetchone()[0]
    restored.close()
    assert rows_after == 0, (
        "FK CASCADE was not preserved across DB schema/data restore — "
        "schema-level constraint is broken."
    )
