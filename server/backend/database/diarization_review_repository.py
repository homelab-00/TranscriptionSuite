"""Diarization-review state repository (Issue #104, Story 1.9 — ADR-009).

CRUD over the ``recording_diarization_review`` table created by migration
010. Lifecycle state-machine consumption (with transition validation,
banner triggers, auto-summary HOLD coordination) lives in Story 5.6
(Sprint 3) — this module provides only the data primitives that machine
will consume.

All writes commit before returning (Persist-Before-Deliver, NFR16).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from server.database.database import get_connection

logger = logging.getLogger(__name__)


VALID_STATUSES: frozenset[str] = frozenset({"pending", "in_review", "completed", "released"})


class InvalidReviewStatusError(ValueError):
    """Raised when a status outside :data:`VALID_STATUSES` is supplied."""

    def __init__(self, received: str) -> None:
        super().__init__(
            f"invalid review status: received={received!r}, valid={sorted(VALID_STATUSES)}"
        )
        self.received = received


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def create_review(recording_id: int, status: str = "pending") -> None:
    """Insert a new review row for ``recording_id`` with the given status."""
    if status not in VALID_STATUSES:
        raise InvalidReviewStatusError(status)
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO recording_diarization_review
                (recording_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (recording_id, status, now, now),
        )
        conn.commit()


def get_review(recording_id: int) -> dict | None:
    """Return the review row as a dict, or None if no row exists."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM recording_diarization_review WHERE recording_id = ?",
            (recording_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def update_status(recording_id: int, new_status: str) -> bool:
    """Update only the status column. Returns True if a row was updated.

    Lifecycle transition validation (e.g. completed→released allowed,
    released→pending forbidden) is intentionally NOT enforced here —
    that belongs to the Story 5.6 state machine. The CHECK constraint
    in migration 010 still rejects invalid status names at the DB layer.
    """
    if new_status not in VALID_STATUSES:
        raise InvalidReviewStatusError(new_status)
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE recording_diarization_review
            SET status = ?, updated_at = ?
            WHERE recording_id = ?
            """,
            (new_status, _now_iso(), recording_id),
        )
        conn.commit()
        return cur.rowcount > 0


def update_reviewed_turns(recording_id: int, turns_json: str) -> bool:
    """Update the ``reviewed_turns_json`` payload. Returns True if updated.

    Caller is responsible for serialising — the column stores raw JSON text.
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE recording_diarization_review
            SET reviewed_turns_json = ?, updated_at = ?
            WHERE recording_id = ?
            """,
            (turns_json, _now_iso(), recording_id),
        )
        conn.commit()
        return cur.rowcount > 0
