"""ADR-009 lifecycle state machine tests (Issue #104, Story 5.6).

Covers all transitions, illegal-transition rejection, predicate
correctness, and persistence-across-restart (NFR23, R-EL19).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from server.core.diarization_review_lifecycle import (
    IllegalReviewTransitionError,
    auto_summary_is_held,
    banner_visible,
    current_status,
    on_auto_summary_fired,
    on_review_view_opened,
    on_run_summary_now_clicked,
    on_transcription_complete,
)
from server.database import diarization_review_repository as repo

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
            (recording_id, "x.wav", "/tmp/x.wav", 1.0, "2025-01-15T12:00:00Z"),
        )
        conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# AC1 — initial pending insert (gated on has_low_confidence_turn)
# ──────────────────────────────────────────────────────────────────────────


def test_no_row_when_no_low_confidence_turn(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=False)
    assert current_status(1) is None  # no row


def test_pending_row_inserted_when_low_confidence_present(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=True)
    assert current_status(1) == "pending"


# ──────────────────────────────────────────────────────────────────────────
# AC2 — lifecycle transitions
# ──────────────────────────────────────────────────────────────────────────


def test_full_happy_path(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=True)
    assert current_status(1) == "pending"

    moved = on_review_view_opened(1)
    assert moved is True
    assert current_status(1) == "in_review"

    on_run_summary_now_clicked(1)
    assert current_status(1) == "completed"

    on_auto_summary_fired(1)
    assert current_status(1) == "released"


def test_review_view_opened_idempotent_when_in_review(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=True)
    on_review_view_opened(1)
    # Second open is a no-op
    moved = on_review_view_opened(1)
    assert moved is False
    assert current_status(1) == "in_review"


def test_review_view_opened_no_op_when_no_row(fresh_db: Path) -> None:
    """When transcription completed without low-conf turns, the view-open
    trigger does NOT spawn a row out of nowhere."""
    _seed_recording(fresh_db, 1)
    moved = on_review_view_opened(1)
    assert moved is False
    assert current_status(1) is None


# ──────────────────────────────────────────────────────────────────────────
# Illegal transitions raise
# ──────────────────────────────────────────────────────────────────────────


def test_skip_pending_raises(fresh_db: Path) -> None:
    """Cannot go directly None → in_review (must pass through pending)."""
    _seed_recording(fresh_db, 1)
    with pytest.raises(IllegalReviewTransitionError):
        on_run_summary_now_clicked(1)  # None → completed forbidden


def test_pending_to_completed_raises(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=True)
    with pytest.raises(IllegalReviewTransitionError):
        on_run_summary_now_clicked(1)  # pending → completed forbidden


def test_in_review_to_released_raises(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=True)
    on_review_view_opened(1)
    with pytest.raises(IllegalReviewTransitionError):
        on_auto_summary_fired(1)  # in_review → released forbidden


def test_released_is_terminal(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=True)
    on_review_view_opened(1)
    on_run_summary_now_clicked(1)
    on_auto_summary_fired(1)
    # No further transitions allowed
    with pytest.raises(IllegalReviewTransitionError):
        on_auto_summary_fired(1)


# ──────────────────────────────────────────────────────────────────────────
# AC3 / AC4 — predicates
# ──────────────────────────────────────────────────────────────────────────


def test_banner_visible_predicate(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    # No row → no banner
    assert banner_visible(1) is False

    on_transcription_complete(1, has_low_confidence_turn=True)
    assert banner_visible(1) is True  # pending

    on_review_view_opened(1)
    assert banner_visible(1) is True  # in_review

    on_run_summary_now_clicked(1)
    assert banner_visible(1) is False  # completed

    on_auto_summary_fired(1)
    assert banner_visible(1) is False  # released


def test_auto_summary_held_predicate(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    # No row → not held
    assert auto_summary_is_held(1) is False

    on_transcription_complete(1, has_low_confidence_turn=True)
    assert auto_summary_is_held(1) is True  # pending

    on_review_view_opened(1)
    assert auto_summary_is_held(1) is True  # in_review

    on_run_summary_now_clicked(1)
    assert auto_summary_is_held(1) is True  # completed (still HELD until release)

    on_auto_summary_fired(1)
    assert auto_summary_is_held(1) is False  # released


# ──────────────────────────────────────────────────────────────────────────
# AC5 — persistence across "restart" (re-read after closing connection)
# ──────────────────────────────────────────────────────────────────────────


def test_state_survives_restart(fresh_db: Path) -> None:
    """Insert pending → "restart" (close/open new connection) → state preserved.

    Sprint 1 Story 1.9 already proves migration durability; this test
    exercises the lifecycle module's interaction with that durability."""
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=True)
    on_review_view_opened(1)
    assert current_status(1) == "in_review"

    # Force re-open by reading via direct sqlite3 connection
    with sqlite3.connect(fresh_db) as conn:
        row = conn.execute(
            "SELECT status FROM recording_diarization_review WHERE recording_id = 1"
        ).fetchone()
    assert row is not None
    assert row[0] == "in_review"


# ──────────────────────────────────────────────────────────────────────────
# AC6 — Persist-Before-Deliver
# ──────────────────────────────────────────────────────────────────────────


def test_state_visible_in_external_connection_after_each_transition(
    fresh_db: Path,
) -> None:
    """Each trigger commits before returning — confirmed by reading from
    a separate sqlite3 connection between calls."""
    _seed_recording(fresh_db, 1)

    on_transcription_complete(1, has_low_confidence_turn=True)
    with sqlite3.connect(fresh_db) as conn:
        row = conn.execute(
            "SELECT status FROM recording_diarization_review WHERE recording_id=1"
        ).fetchone()
    assert row[0] == "pending"

    on_review_view_opened(1)
    with sqlite3.connect(fresh_db) as conn:
        row = conn.execute(
            "SELECT status FROM recording_diarization_review WHERE recording_id=1"
        ).fetchone()
    assert row[0] == "in_review"


# ──────────────────────────────────────────────────────────────────────────
# Story 5.8 — fake auto-summary consumer end-to-end
# ──────────────────────────────────────────────────────────────────────────


def _fake_auto_summary_consumer(recording_id: int) -> str:
    """Pretends to be Sprint 4 Story 6.2 auto-summary lifecycle.

    The actual auto-summary lifecycle hook will import
    ``auto_summary_is_held`` from this module and use the same logic.
    """
    if auto_summary_is_held(recording_id):
        return "HELD"
    return "FIRED"


def test_held_when_pending(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=True)
    assert _fake_auto_summary_consumer(1) == "HELD"


def test_fires_after_release(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=True)
    on_review_view_opened(1)
    on_run_summary_now_clicked(1)
    on_auto_summary_fired(1)
    assert _fake_auto_summary_consumer(1) == "FIRED"


def test_not_held_when_no_low_confidence(fresh_db: Path) -> None:
    """Story 5.8 AC1 corollary — no low-conf turns → no HOLD predicate, fires immediately."""
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=False)
    assert _fake_auto_summary_consumer(1) == "FIRED"


# ──────────────────────────────────────────────────────────────────────────
# Sanity — repo state matches lifecycle state at all times
# ──────────────────────────────────────────────────────────────────────────


def test_repo_state_matches_lifecycle(fresh_db: Path) -> None:
    """The lifecycle never goes out of band with the repository — both
    paths report the same status after each transition."""
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=True)
    assert repo.get_review(1)["status"] == current_status(1) == "pending"
    on_review_view_opened(1)
    assert repo.get_review(1)["status"] == current_status(1) == "in_review"
