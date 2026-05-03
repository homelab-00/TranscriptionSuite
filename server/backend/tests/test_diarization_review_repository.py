"""Tests for migration 010 + diarization_review_repository (Issue #104, Story 1.9)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from server.database import diarization_review_repository as repo
from server.database.diarization_review_repository import (
    VALID_STATUSES,
    InvalidReviewStatusError,
)

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
    """Insert a minimal recordings row so the FK reference resolves."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO recordings (id, filename, filepath, duration_seconds, recorded_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (recording_id, "x.wav", "/tmp/x.wav", 1.0, "2025-01-15T12:00:00Z"),
        )
        conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# Migration AC1 — schema
# ──────────────────────────────────────────────────────────────────────────


def test_table_exists_with_expected_columns(fresh_db: Path) -> None:
    with sqlite3.connect(fresh_db) as conn:
        cols = {
            r[1] for r in conn.execute("PRAGMA table_info(recording_diarization_review)").fetchall()
        }
    expected = {"recording_id", "status", "reviewed_turns_json", "created_at", "updated_at"}
    assert expected.issubset(cols)


def test_status_check_constraint_rejects_unknown_value(fresh_db: Path) -> None:
    """The DB-layer CHECK constraint backs up the Python-side validation."""
    _seed_recording(fresh_db, 1)
    with sqlite3.connect(fresh_db) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO recording_diarization_review (recording_id, status) VALUES (?, ?)",
                (1, "made_up_status"),
            )


# ──────────────────────────────────────────────────────────────────────────
# AC2 — restore-survival smoke test
# ──────────────────────────────────────────────────────────────────────────


def test_diarization_review_state_survives_restore(fresh_db: Path) -> None:
    """NFR23 — DB dump/restore round-trip preserves review-state rows."""
    _seed_recording(fresh_db, 42)
    repo.create_review(42, status="in_review")

    # Round-trip via iterdump → fresh in-memory DB
    with sqlite3.connect(fresh_db) as src:
        dump_lines = list(src.iterdump())

    sql_text = "\n".join(dump_lines)
    restored = sqlite3.connect(":memory:")
    restored.executescript(sql_text)

    row = restored.execute(
        "SELECT status FROM recording_diarization_review WHERE recording_id = ?",
        (42,),
    ).fetchone()
    restored.close()
    assert row is not None
    assert row[0] == "in_review"


# ──────────────────────────────────────────────────────────────────────────
# AC3 — repository CRUD
# ──────────────────────────────────────────────────────────────────────────


def test_create_and_get_review(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 7)
    repo.create_review(7, status="pending")
    fetched = repo.get_review(7)
    assert fetched is not None
    assert fetched["recording_id"] == 7
    assert fetched["status"] == "pending"


def test_get_review_returns_none_when_absent(fresh_db: Path) -> None:
    assert repo.get_review(999) is None


def test_create_with_invalid_status_raises(fresh_db: Path) -> None:
    with pytest.raises(InvalidReviewStatusError):
        repo.create_review(1, status="not_a_status")


def test_update_status_changes_value(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 11)
    repo.create_review(11, status="pending")
    assert repo.update_status(11, "in_review") is True
    assert repo.get_review(11)["status"] == "in_review"


def test_update_status_returns_false_when_missing(fresh_db: Path) -> None:
    assert repo.update_status(999, "completed") is False


def test_update_status_with_invalid_status_raises(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 12)
    repo.create_review(12, status="pending")
    with pytest.raises(InvalidReviewStatusError):
        repo.update_status(12, "garbage")


def test_update_reviewed_turns_persists_blob(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 13)
    repo.create_review(13, status="in_review")
    assert repo.update_reviewed_turns(13, '[{"turn_id": 1, "speaker": "Alice"}]') is True
    fetched = repo.get_review(13)
    assert fetched["reviewed_turns_json"] == '[{"turn_id": 1, "speaker": "Alice"}]'


def test_lifecycle_transitions_not_enforced_by_repo(fresh_db: Path) -> None:
    """Story 5.6 owns the state-machine. The repository accepts any
    valid status name regardless of source state — this freedom is the
    explicit design contract."""
    _seed_recording(fresh_db, 14)
    repo.create_review(14, status="released")
    # released → pending would be forbidden by the state machine, but the
    # repo says yes (Story 5.6 will say no when it lands)
    assert repo.update_status(14, "pending") is True


def test_valid_statuses_constant() -> None:
    """Pin the catalogue so a future addition requires an intentional bump."""
    assert VALID_STATUSES == frozenset({"pending", "in_review", "completed", "released"})
