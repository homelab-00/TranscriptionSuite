"""Auto-action status repository (Issue #104, Stories 6.2/6.3/6.6/6.8/6.9/6.11).

CRUD over the auto-action status columns added to ``recordings`` by
migration 015. The repository is the single layer that knows the column
names — the coordinator (``server.core.auto_action_coordinator``) and the
retry endpoint call only these helpers.

All writes commit before returning (Persist-Before-Deliver, NFR16).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from server.database.database import get_connection

logger = logging.getLogger(__name__)


ActionType = Literal["auto_summary", "auto_export"]

# Status enum (TEXT column, validated here — no CHECK constraint per project policy).
VALID_AUTO_SUMMARY_STATUSES: frozenset[str] = frozenset(
    {
        "pending",
        "in_progress",
        "success",
        "summary_empty",
        "summary_truncated",
        "held",
        "retry_pending",
        "failed",
        "manual_intervention_required",
    }
)
VALID_AUTO_EXPORT_STATUSES: frozenset[str] = frozenset(
    {
        "pending",
        "in_progress",
        "success",
        "deferred",
        "retry_pending",
        "failed",
        "manual_intervention_required",
    }
)


class InvalidAutoActionStatusError(ValueError):
    def __init__(self, action_type: str, received: str) -> None:
        super().__init__(
            f"invalid {action_type} status: received={received!r}; "
            f"valid={sorted(_valid_statuses_for(action_type))}"
        )
        self.action_type = action_type
        self.received = received


class InvalidActionTypeError(ValueError):
    def __init__(self, received: str) -> None:
        super().__init__(
            f"unknown action_type: received={received!r}; valid=['auto_summary', 'auto_export']"
        )
        self.received = received


def _valid_statuses_for(action_type: str) -> frozenset[str]:
    if action_type == "auto_summary":
        return VALID_AUTO_SUMMARY_STATUSES
    if action_type == "auto_export":
        return VALID_AUTO_EXPORT_STATUSES
    raise InvalidActionTypeError(action_type)


def _columns_for(action_type: str) -> tuple[str, str, str, str]:
    """Return (status_col, error_col, attempts_col, completed_at_col)."""
    if action_type == "auto_summary":
        return (
            "auto_summary_status",
            "auto_summary_error",
            "auto_summary_attempts",
            "auto_summary_completed_at",
        )
    if action_type == "auto_export":
        return (
            "auto_export_status",
            "auto_export_error",
            "auto_export_attempts",
            "auto_export_completed_at",
        )
    raise InvalidActionTypeError(action_type)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ──────────────────────────────────────────────────────────────────────────
# Reads
# ──────────────────────────────────────────────────────────────────────────


def get_auto_action_status(recording_id: int, action_type: str) -> str | None:
    status_col, _, _, _ = _columns_for(action_type)
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT {status_col} FROM recordings WHERE id = ?",  # noqa: S608 — column name is internal
            (recording_id,),
        ).fetchone()
    return row[status_col] if row is not None else None


def get_auto_action_attempts(recording_id: int, action_type: str) -> int:
    _, _, attempts_col, _ = _columns_for(action_type)
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT {attempts_col} FROM recordings WHERE id = ?",  # noqa: S608
            (recording_id,),
        ).fetchone()
    if row is None:
        return 0
    value = row[attempts_col]
    return int(value) if value is not None else 0


def get_auto_action_state(recording_id: int) -> dict | None:
    """Return all auto-action columns for a recording, or None if missing."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id,
                   auto_summary_status, auto_summary_error,
                   auto_summary_attempts, auto_summary_completed_at,
                   auto_export_status, auto_export_error,
                   auto_export_attempts, auto_export_path,
                   auto_export_completed_at,
                   auto_action_profile_snapshot
            FROM recordings WHERE id = ?
            """,
            (recording_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def save_profile_snapshot(recording_id: int, snapshot_json: str) -> None:
    """Persist the profile snapshot used at auto-action time.

    Read by ``retry_auto_action_internal`` and by the deferred-export
    sweeper. Stored as JSON text — no schema enforcement at the DB layer.
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE recordings SET auto_action_profile_snapshot = ? WHERE id = ?",
            (snapshot_json, recording_id),
        )
        conn.commit()


def get_profile_snapshot(recording_id: int) -> dict | None:
    """Read back the profile snapshot. Returns None if missing or invalid JSON."""
    import json

    with get_connection() as conn:
        row = conn.execute(
            "SELECT auto_action_profile_snapshot FROM recordings WHERE id = ?",
            (recording_id,),
        ).fetchone()
    if row is None or row["auto_action_profile_snapshot"] is None:
        return None
    try:
        return json.loads(row["auto_action_profile_snapshot"])
    except (ValueError, TypeError):
        return None


def list_pending_auto_actions() -> list[sqlite3.Row]:
    """Sweeper query — every row with any non-terminal auto-action state.

    Returns rows where either auto_summary_status or auto_export_status is
    in ``{deferred, retry_pending}`` — the sweeper's actionable subset.
    """
    actionable = ("deferred", "retry_pending")
    placeholders = ",".join("?" * len(actionable))
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, auto_summary_status, auto_export_status, auto_export_path
            FROM recordings
            WHERE auto_summary_status IN ({placeholders})
               OR auto_export_status IN ({placeholders})
            """,
            (*actionable, *actionable),
        ).fetchall()
    return list(rows)


# ──────────────────────────────────────────────────────────────────────────
# Writes — generic
# ──────────────────────────────────────────────────────────────────────────


def set_auto_action_status(
    recording_id: int,
    action_type: str,
    status: str | None,
    *,
    error: str | None = None,
    path: str | None = None,
) -> None:
    """Update status (+ optional error / path) on a recording.

    `status=None` clears the column (used after a successful retry to
    reset to "no auto-action in flight"). Otherwise the status is
    validated against the per-action enum.

    `path` is meaningful only for auto_export — silently ignored for
    auto_summary.
    """
    if status is not None and status not in _valid_statuses_for(action_type):
        raise InvalidAutoActionStatusError(action_type, status)
    status_col, error_col, _, completed_col = _columns_for(action_type)

    sets: list[str] = [f"{status_col} = ?", f"{error_col} = ?"]
    params: list[object] = [status, error]

    # completed_at gets a timestamp on terminal-success states only —
    # other transitions leave it untouched (so retries don't move it backward).
    if status == "success":
        sets.append(f"{completed_col} = ?")
        params.append(_now_iso())

    if action_type == "auto_export" and path is not None:
        sets.append("auto_export_path = ?")
        params.append(path)

    params.append(recording_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE recordings SET {', '.join(sets)} WHERE id = ?",  # noqa: S608
            tuple(params),
        )
        conn.commit()


def increment_auto_action_attempts(recording_id: int, action_type: str) -> None:
    _, _, attempts_col, _ = _columns_for(action_type)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE recordings SET {attempts_col} = COALESCE({attempts_col}, 0) + 1 "  # noqa: S608
            f"WHERE id = ?",
            (recording_id,),
        )
        conn.commit()


def reset_auto_action_attempts(recording_id: int, action_type: str) -> None:
    _, _, attempts_col, _ = _columns_for(action_type)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE recordings SET {attempts_col} = 0 WHERE id = ?",  # noqa: S608
            (recording_id,),
        )
        conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# Writes — specialized convenience wrappers
# ──────────────────────────────────────────────────────────────────────────


def set_auto_summary_status(
    recording_id: int, status: str | None, *, error: str | None = None
) -> None:
    set_auto_action_status(recording_id, "auto_summary", status, error=error)


def set_auto_export_status(
    recording_id: int,
    status: str | None,
    *,
    error: str | None = None,
    path: str | None = None,
) -> None:
    set_auto_action_status(recording_id, "auto_export", status, error=error, path=path)


__all__: Sequence[str] = (
    "ActionType",
    "VALID_AUTO_SUMMARY_STATUSES",
    "VALID_AUTO_EXPORT_STATUSES",
    "InvalidAutoActionStatusError",
    "InvalidActionTypeError",
    "get_auto_action_status",
    "get_auto_action_attempts",
    "get_auto_action_state",
    "get_profile_snapshot",
    "list_pending_auto_actions",
    "save_profile_snapshot",
    "set_auto_action_status",
    "set_auto_summary_status",
    "set_auto_export_status",
    "increment_auto_action_attempts",
    "reset_auto_action_attempts",
)
