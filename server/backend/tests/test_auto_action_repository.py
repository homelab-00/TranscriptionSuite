"""Repository tests for auto_action_repository (Issue #104, Stories 6.2-6.11).

Covers:
  - status validation (per-action enum)
  - attempts increment / reset
  - Persist-Before-Deliver: every write commits before returning
  - list_pending_auto_actions sweeper query
  - per-action specialization (auto_summary vs auto_export)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
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
# Status validation
# ──────────────────────────────────────────────────────────────────────────


def test_invalid_action_type_raises(fresh_db: Path) -> None:
    with pytest.raises(repo.InvalidActionTypeError):
        repo.set_auto_action_status(1, "auto_lol", "pending")


def test_invalid_status_for_auto_summary_raises(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    # 'deferred' is valid for auto_export but not auto_summary
    with pytest.raises(repo.InvalidAutoActionStatusError):
        repo.set_auto_summary_status(1, "deferred")


def test_invalid_status_for_auto_export_raises(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    # 'summary_empty' is valid for auto_summary but not auto_export
    with pytest.raises(repo.InvalidAutoActionStatusError):
        repo.set_auto_export_status(1, "summary_empty")


def test_status_none_clears_column(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    repo.set_auto_summary_status(1, "in_progress")
    assert repo.get_auto_action_status(1, "auto_summary") == "in_progress"
    repo.set_auto_summary_status(1, None)
    assert repo.get_auto_action_status(1, "auto_summary") is None


# ──────────────────────────────────────────────────────────────────────────
# Reads
# ──────────────────────────────────────────────────────────────────────────


def test_get_status_missing_recording_returns_none(fresh_db: Path) -> None:
    assert repo.get_auto_action_status(99, "auto_summary") is None


def test_get_attempts_default_zero(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    assert repo.get_auto_action_attempts(1, "auto_summary") == 0
    assert repo.get_auto_action_attempts(1, "auto_export") == 0


# ──────────────────────────────────────────────────────────────────────────
# Writes — happy path
# ──────────────────────────────────────────────────────────────────────────


def test_set_auto_summary_success_marks_completed_at(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    repo.set_auto_summary_status(1, "success")
    state = repo.get_auto_action_state(1)
    assert state is not None
    assert state["auto_summary_status"] == "success"
    assert state["auto_summary_completed_at"] is not None  # success sets timestamp


def test_set_auto_summary_in_progress_does_not_set_completed_at(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    repo.set_auto_summary_status(1, "in_progress")
    state = repo.get_auto_action_state(1)
    assert state is not None
    assert state["auto_summary_completed_at"] is None


def test_set_auto_export_persists_path(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    repo.set_auto_export_status(1, "deferred", path="/mnt/usb/drive")
    state = repo.get_auto_action_state(1)
    assert state["auto_export_status"] == "deferred"
    assert state["auto_export_path"] == "/mnt/usb/drive"


def test_set_status_with_error_persists_error_text(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    repo.set_auto_summary_status(1, "failed", error="LLM unreachable")
    state = repo.get_auto_action_state(1)
    assert state["auto_summary_error"] == "LLM unreachable"


# ──────────────────────────────────────────────────────────────────────────
# Attempts increment / reset
# ──────────────────────────────────────────────────────────────────────────


def test_increment_attempts(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    repo.increment_auto_action_attempts(1, "auto_summary")
    assert repo.get_auto_action_attempts(1, "auto_summary") == 1
    repo.increment_auto_action_attempts(1, "auto_summary")
    assert repo.get_auto_action_attempts(1, "auto_summary") == 2


def test_reset_attempts(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    repo.increment_auto_action_attempts(1, "auto_export")
    repo.increment_auto_action_attempts(1, "auto_export")
    assert repo.get_auto_action_attempts(1, "auto_export") == 2
    repo.reset_auto_action_attempts(1, "auto_export")
    assert repo.get_auto_action_attempts(1, "auto_export") == 0


def test_increment_attempts_for_one_action_does_not_affect_other(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    repo.increment_auto_action_attempts(1, "auto_summary")
    assert repo.get_auto_action_attempts(1, "auto_summary") == 1
    assert repo.get_auto_action_attempts(1, "auto_export") == 0


# ──────────────────────────────────────────────────────────────────────────
# Sweeper query
# ──────────────────────────────────────────────────────────────────────────


def test_list_pending_includes_deferred_export(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    _seed_recording(fresh_db, 2)
    _seed_recording(fresh_db, 3)
    repo.set_auto_export_status(1, "deferred", path="/mnt/usb")
    repo.set_auto_export_status(2, "success")  # excluded
    repo.set_auto_summary_status(3, "retry_pending")  # included
    rows = repo.list_pending_auto_actions()
    ids = {row["id"] for row in rows}
    assert ids == {1, 3}


def test_list_pending_skips_terminal_states(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    _seed_recording(fresh_db, 2)
    repo.set_auto_summary_status(1, "manual_intervention_required")
    repo.set_auto_export_status(2, "manual_intervention_required")
    rows = repo.list_pending_auto_actions()
    assert rows == []


# ──────────────────────────────────────────────────────────────────────────
# Persist-Before-Deliver — write commits before returning (NFR16)
# ──────────────────────────────────────────────────────────────────────────


def test_set_status_commits_before_returning(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wrap get_connection so we can track commit() calls — assert
    commit() is invoked at least once on the path that updates the row.

    sqlite3.Connection is a built-in C type and can't be monkeypatched
    directly; we substitute the connection factory with a wrapping
    Connection subclass that records commits.
    """
    _seed_recording(fresh_db, 1)

    commits: list[str] = []

    class TrackingConnection(sqlite3.Connection):
        def commit(self) -> None:
            commits.append("commit")
            super().commit()

    db_path = fresh_db
    real_get_connection = repo.get_connection  # type: ignore[attr-defined]

    def fake_get_connection():
        conn = sqlite3.connect(db_path, factory=TrackingConnection)
        conn.row_factory = sqlite3.Row
        return conn

    # Patch the symbol the repository imported.
    monkeypatch.setattr(
        "server.database.auto_action_repository.get_connection", fake_get_connection
    )
    repo.set_auto_summary_status(1, "in_progress")
    assert commits, "commit() never invoked — Persist-Before-Deliver violated"

    # Reset patch + verify the row actually persisted via real connection.
    monkeypatch.setattr(
        "server.database.auto_action_repository.get_connection", real_get_connection
    )
    assert repo.get_auto_action_status(1, "auto_summary") == "in_progress"
