"""Tests for the diarization-review GET/POST routes (Issue #104, Stories 5.7 / 5.9).

GET /api/notebook/recordings/{id}/diarization-review
POST /api/notebook/recordings/{id}/diarization-review (action=open|complete)
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from fastapi import HTTPException
from server.api.routes import notebook
from server.core.diarization_review_lifecycle import on_transcription_complete
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
# GET — returns null status when no row, status string otherwise
# ──────────────────────────────────────────────────────────────────────────


def test_get_returns_null_status_when_no_row(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    resp = asyncio.run(notebook.get_diarization_review_state(1))
    assert resp.recording_id == 1
    assert resp.status is None
    assert resp.reviewed_turns_json is None


def test_get_returns_pending_status(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=True)
    resp = asyncio.run(notebook.get_diarization_review_state(1))
    assert resp.status == "pending"


def test_get_404_when_recording_missing(fresh_db: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook.get_diarization_review_state(999))
    assert exc.value.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# POST — action='open'
# ──────────────────────────────────────────────────────────────────────────


def test_post_open_transitions_pending_to_in_review(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=True)
    payload = notebook.DiarizationReviewSubmit(action="open")
    resp = asyncio.run(notebook.submit_diarization_review(1, payload))
    assert resp.status == "in_review"


def test_post_open_no_op_when_no_row(fresh_db: Path) -> None:
    """Story 5.6: opening when no review row exists is a silent no-op."""
    _seed_recording(fresh_db, 1)
    payload = notebook.DiarizationReviewSubmit(action="open")
    resp = asyncio.run(notebook.submit_diarization_review(1, payload))
    assert resp.status is None


# ──────────────────────────────────────────────────────────────────────────
# POST — action='complete' (Story 5.9 AC5)
# ──────────────────────────────────────────────────────────────────────────


def test_post_complete_persists_reviewed_turns_and_transitions(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=True)
    asyncio.run(
        notebook.submit_diarization_review(1, notebook.DiarizationReviewSubmit(action="open"))
    )

    reviewed_turns = [
        {"turn_index": 0, "decision": "accept", "speaker_id": "SPEAKER_00"},
        {"turn_index": 1, "decision": "skip", "speaker_id": "SPEAKER_01"},
    ]
    resp = asyncio.run(
        notebook.submit_diarization_review(
            1,
            notebook.DiarizationReviewSubmit(
                action="complete",
                reviewed_turns=reviewed_turns,
            ),
        )
    )
    assert resp.status == "completed"

    # reviewed_turns_json was persisted
    row = repo.get_review(1)
    assert row is not None
    parsed = json.loads(row["reviewed_turns_json"])
    assert parsed == sorted(reviewed_turns, key=lambda x: list(x.items()))


# ──────────────────────────────────────────────────────────────────────────
# Illegal transitions surface as 409
# ──────────────────────────────────────────────────────────────────────────


def test_post_complete_without_open_returns_409(fresh_db: Path) -> None:
    """Cannot 'complete' a review that is still pending (or has no row)."""
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=True)  # pending
    payload = notebook.DiarizationReviewSubmit(action="complete", reviewed_turns=[])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook.submit_diarization_review(1, payload))
    assert exc.value.status_code == 409


def test_post_invalid_action_returns_400(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    payload = notebook.DiarizationReviewSubmit(action="bogus")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook.submit_diarization_review(1, payload))
    assert exc.value.status_code == 400


def test_post_404_when_recording_missing(fresh_db: Path) -> None:
    payload = notebook.DiarizationReviewSubmit(action="open")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook.submit_diarization_review(999, payload))
    assert exc.value.status_code == 404


def test_complete_action_does_not_orphan_reviewed_turns_on_illegal_transition(
    fresh_db: Path,
) -> None:
    """Review feedback HIGH-1 — when 'complete' is invoked from a state
    that doesn't allow the transition (e.g. still pending, never opened),
    the lifecycle MUST raise BEFORE reviewed_turns_json is written.
    Otherwise a partial-write window leaves orphan JSON behind."""
    _seed_recording(fresh_db, 1)
    on_transcription_complete(1, has_low_confidence_turn=True)  # status = pending

    payload = notebook.DiarizationReviewSubmit(
        action="complete",
        reviewed_turns=[{"turn_index": 0, "decision": "accept", "speaker_id": "SPEAKER_00"}],
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook.submit_diarization_review(1, payload))
    assert exc.value.status_code == 409

    # Crucially: reviewed_turns_json must remain NULL because the
    # lifecycle transition raised before any JSON write occurred.
    row = repo.get_review(1)
    assert row is not None
    assert row["status"] == "pending"
    assert row["reviewed_turns_json"] is None
