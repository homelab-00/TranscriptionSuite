"""Webhook delivery row persistence (Issue #104, Story 7.1).

CRUD over the ``webhook_deliveries`` table created by migration 016. The
repository is the single layer that knows the column names — the
``WebhookWorker`` service (`server.services.webhook_worker`) and the
auto-action coordinator (`server.core.auto_action_coordinator`) call only
these helpers.

All writes commit before returning (Persist-Before-Deliver, NFR16). The
worker's drain loop counts on the ``status`` column being durably
visible across processes — anything less than ``COMMIT`` defeats
crash-recovery (Story 7.5 AC2).

The 1:N (recording → many deliveries) shape is intentional: each retry
is a fresh row so the failure history remains queryable for diagnostics
(NFR42). Sprint 4's auto-action columns were 1:1; this is deliberately
different because retries here are distinct events.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Mapping
from typing import Any

from server.database.database import get_connection

logger = logging.getLogger(__name__)


VALID_STATUSES: frozenset[str] = frozenset(
    {
        "pending",
        "in_flight",
        "success",
        "failed",
        "manual_intervention_required",
    }
)


class InvalidWebhookStatusError(ValueError):
    """Raised when a caller asks for a status not in ``VALID_STATUSES``."""

    def __init__(self, received: str) -> None:
        super().__init__(
            f"invalid webhook status: received={received!r}; valid={sorted(VALID_STATUSES)}"
        )
        self.received = received


def _check_status(status: str) -> None:
    if status not in VALID_STATUSES:
        raise InvalidWebhookStatusError(status)


# ──────────────────────────────────────────────────────────────────────────
# Producer-side helpers (called by coordinator + retry endpoint)
# ──────────────────────────────────────────────────────────────────────────


def create_pending(
    recording_id: int,
    profile_id: int | None,
    payload: Mapping[str, Any],
) -> int:
    """INSERT a fresh row at ``status='pending'`` with the full payload.

    Commits before returning. Returns the new row's id so the caller
    (the WebhookWorker later) can address it directly. The payload is
    serialized to JSON now — at delivery time the worker uses this
    exact body, so a profile edit between INSERT and fire does NOT
    silently change what got POSTed (no-drift property).
    """
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO webhook_deliveries "
            "(recording_id, profile_id, status, payload_json) "
            "VALUES (?, ?, 'pending', ?)",
            (recording_id, profile_id, body),
        )
        conn.commit()
        row_id = cur.lastrowid
    if row_id is None:
        # SQLite always returns lastrowid for INSERT into rowid tables, so
        # this is purely a type-narrowing safety net for callers.
        raise RuntimeError("INSERT did not return a lastrowid")
    return row_id


# ──────────────────────────────────────────────────────────────────────────
# Worker-side state transitions
# ──────────────────────────────────────────────────────────────────────────


def mark_in_flight(row_id: int) -> None:
    """UPDATE status='in_flight' (committed before HTTP fire — PBD)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE webhook_deliveries SET status = 'in_flight' WHERE id = ?",
            (row_id,),
        )
        conn.commit()


def mark_success(row_id: int) -> None:
    """UPDATE status='success', last_attempted_at=NOW (committed)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE webhook_deliveries "
            "SET status = 'success', last_attempted_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (row_id,),
        )
        conn.commit()


def mark_failed(row_id: int, error: str) -> None:
    """UPDATE status='failed', attempt_count++, last_error, last_attempted_at."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE webhook_deliveries "
            "SET status = 'failed', "
            "    attempt_count = attempt_count + 1, "
            "    last_error = ?, "
            "    last_attempted_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (error, row_id),
        )
        conn.commit()


def mark_manual_intervention(row_id: int, error: str) -> None:
    """Story 7.7 AC2 — auto-retry budget exhausted. Same shape as mark_failed
    but with the terminal status and a final attempt_count increment."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE webhook_deliveries "
            "SET status = 'manual_intervention_required', "
            "    attempt_count = attempt_count + 1, "
            "    last_error = ?, "
            "    last_attempted_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (error, row_id),
        )
        conn.commit()


def requeue_in_flight_to_pending() -> int:
    """Story 7.3 AC5 — on shutdown, revert any 'in_flight' rows so the next
    start picks them up. Returns the count of rows reverted.

    The worker calls this from its ``stop()`` method. Without it, an
    in-flight row could stay in that state across restarts and only be
    rescued by the bootstrap sweep (which DOES drain in_flight per
    ``list_pending``) — but explicit requeue avoids the ambiguity of a
    stale 'in_flight' marker in the table.
    """
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE webhook_deliveries SET status = 'pending' WHERE status = 'in_flight'"
        )
        conn.commit()
        return cur.rowcount


# ──────────────────────────────────────────────────────────────────────────
# Read-side queries
# ──────────────────────────────────────────────────────────────────────────


def list_pending() -> list[sqlite3.Row]:
    """Worker drain query — every row in 'pending' or 'in_flight'.

    'in_flight' is included so the bootstrap sweep recovers attempts
    that were mid-call when the prior process died (Story 7.5 AC2).

    Ordered by id ASC (insertion order) so older attempts go out first
    under sustained load.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, recording_id, profile_id, status, attempt_count, "
            "       last_error, created_at, last_attempted_at, payload_json "
            "FROM webhook_deliveries "
            "WHERE status IN ('pending', 'in_flight') "
            "ORDER BY id ASC"
        ).fetchall()
    return list(rows)


def get_by_id(row_id: int) -> sqlite3.Row | None:
    """Fetch one row by primary key. Used by tests + admin debugging."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, recording_id, profile_id, status, attempt_count, "
            "       last_error, created_at, last_attempted_at, payload_json "
            "FROM webhook_deliveries WHERE id = ?",
            (row_id,),
        ).fetchone()
    return row


def get_latest_for_recording(recording_id: int) -> sqlite3.Row | None:
    """Most recent attempt for a recording — newest id wins.

    Used by:
      - the retry endpoint to enforce idempotency on 'success' (Story 7.7
        AC1 → R-EL27 "no re-execution on success")
      - the dashboard's per-recording status badge (Story 7.7 frontend
        wiring; the badge reads this row's status / last_error).
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, recording_id, profile_id, status, attempt_count, "
            "       last_error, created_at, last_attempted_at, payload_json "
            "FROM webhook_deliveries "
            "WHERE recording_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (recording_id,),
        ).fetchone()
    return row


def count_consecutive_recent_failures(recording_id: int) -> int:
    """Count failed rows since the most recent terminal non-failed row.

    Used by the worker's escalation logic (Story 7.7 AC2 — one auto-retry
    then manual). Returns the number of ``failed`` rows that have
    accumulated since the last ``success`` or ``manual_intervention_required``
    row (those reset the counter — a successful delivery means the
    receiver came back online; manual_intervention is a human boundary).

    In-progress states (``pending`` and ``in_flight``) are SKIPPED rather
    than treated as boundaries — at the moment the worker calls this
    function, the row currently being delivered is at ``in_flight`` and
    we want to count the failures that came BEFORE it. Without this
    skip, the most-recent in-flight row would prematurely break the
    loop and the function would always return 0 mid-delivery.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT status FROM webhook_deliveries WHERE recording_id = ? ORDER BY id DESC",
            (recording_id,),
        ).fetchall()
    consecutive = 0
    for r in rows:
        status = r["status"]
        if status in ("pending", "in_flight"):
            # In-progress — not a boundary, not counted; skip and look
            # at the next-older row.
            continue
        if status == "failed":
            consecutive += 1
        else:
            # success / manual_intervention_required — boundary.
            break
    return consecutive


# ──────────────────────────────────────────────────────────────────────────
# Retention cleanup (Story 7.7 AC3 / NFR40)
# ──────────────────────────────────────────────────────────────────────────


def cleanup_older_than(retention_days: int) -> int:
    """Delete success / manual_intervention_required rows older than N days.

    Returns the number of rows deleted.

    Never deletes:
      - 'pending' / 'in_flight' — actionable, the worker is responsible.
      - 'failed' — could still be retried by the user; queryable for diag.

    The age check uses ``created_at`` not ``last_attempted_at`` so a row
    that was retried right at the cutoff is still removed if its original
    creation predated the window. Documented intent: "30 days from when
    the receiver missed the event," not "30 days from when we last tried."
    """
    if retention_days <= 0:
        logger.info("webhook cleanup skipped (retention_days=%d — keeping forever)", retention_days)
        return 0
    # SQLite's datetime modifier accepts a string like "-30 days" — pass
    # it as a parameter (rather than f-string interpolation) so the query
    # is parameterized end-to-end. The ``int()`` cast is defense-in-depth;
    # ``retention_days`` only ever flows in from config.yaml today.
    days_modifier = f"-{int(retention_days)} days"
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM webhook_deliveries "
            "WHERE status IN ('success', 'manual_intervention_required') "
            "AND created_at < datetime('now', ?)",
            (days_modifier,),
        )
        conn.commit()
        return cur.rowcount


def requeue_failed_row(recording_id: int) -> int | None:
    """Story 7.7 AC2 — 30s-delayed auto-retry path. Take the most recent
    'failed' row's payload and INSERT a fresh 'pending' row.

    Returns the new row id, or None if no failed row exists for that
    recording (defensive — caller has already proven recently-failed).
    """
    with get_connection() as conn:
        latest = conn.execute(
            "SELECT profile_id, payload_json FROM webhook_deliveries "
            "WHERE recording_id = ? AND status = 'failed' "
            "ORDER BY id DESC LIMIT 1",
            (recording_id,),
        ).fetchone()
        if latest is None:
            return None
        cur = conn.execute(
            "INSERT INTO webhook_deliveries "
            "(recording_id, profile_id, status, payload_json) "
            "VALUES (?, ?, 'pending', ?)",
            (recording_id, latest["profile_id"], latest["payload_json"]),
        )
        conn.commit()
        return cur.lastrowid


__all__ = (
    "VALID_STATUSES",
    "InvalidWebhookStatusError",
    "create_pending",
    "mark_in_flight",
    "mark_success",
    "mark_failed",
    "mark_manual_intervention",
    "requeue_in_flight_to_pending",
    "list_pending",
    "get_by_id",
    "get_latest_for_recording",
    "count_consecutive_recent_failures",
    "cleanup_older_than",
    "requeue_failed_row",
)
