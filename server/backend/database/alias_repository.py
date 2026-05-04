"""Speaker-alias repository (Issue #104, Story 4.2).

CRUD over the ``recording_speaker_aliases`` table created by migration
014. Read-time substitution lives in ``server/backend/core/alias_substitution.py``
(Stories 4.4 / 5.1 / 5.2 / 5.3); this module provides only the
data primitives.

All writes commit before returning (Persist-Before-Deliver, NFR16).

Verbatim guarantee (R-EL3): alias_name is stored EXACTLY as the caller
supplies it — no NFC normalization, no truncation, no lower-casing.
The only sanitization is the route-layer ``.strip()`` which removes
surrounding whitespace (whitespace is never part of a speaker name).
SQLite TEXT columns preserve arbitrary Unicode bytes, so the round-trip
is byte-stable.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from server.database.database import get_connection

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def list_aliases(recording_id: int) -> list[dict[str, Any]]:
    """Return alias rows for ``recording_id`` ordered by speaker_id.

    Empty list when no aliases exist (callers MUST treat empty as
    "no aliases" — never as 404 — per Story 4.2 AC1).

    If the ``recording_speaker_aliases`` table doesn't exist (e.g. an
    older test fixture that doesn't run migration 014), we return an
    empty list rather than raising — semantically consistent with
    "no aliases". Production runs always have the table because
    ``init_db()`` stamps to migration head.
    """
    import sqlite3

    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT speaker_id, alias_name
                FROM recording_speaker_aliases
                WHERE recording_id = ?
                ORDER BY speaker_id
                """,
                (recording_id,),
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            logger.debug("recording_speaker_aliases table missing — returning empty alias list")
            return []
        raise
    return [dict(row) for row in rows]


def replace_aliases(recording_id: int, aliases: list[dict[str, str]]) -> None:
    """Full-replace upsert.

    For each entry in ``aliases`` (``{"speaker_id": ..., "alias_name": ...}``)
    insert or update the row. Any pre-existing row for
    ``recording_id`` whose ``speaker_id`` is NOT in the incoming
    payload is DELETED — this is the Story 4.2 AC2 "full-replace
    semantics" requirement.

    Single transaction; commit before returning (NFR16).
    """
    now = _now_iso()
    incoming_ids = [a["speaker_id"] for a in aliases]
    with get_connection() as conn:
        if incoming_ids:
            placeholders = ",".join("?" * len(incoming_ids))
            conn.execute(
                f"DELETE FROM recording_speaker_aliases "
                f"WHERE recording_id = ? AND speaker_id NOT IN ({placeholders})",
                (recording_id, *incoming_ids),
            )
        else:
            conn.execute(
                "DELETE FROM recording_speaker_aliases WHERE recording_id = ?",
                (recording_id,),
            )
        for entry in aliases:
            conn.execute(
                """
                INSERT INTO recording_speaker_aliases
                    (recording_id, speaker_id, alias_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(recording_id, speaker_id) DO UPDATE SET
                    alias_name = excluded.alias_name,
                    updated_at = excluded.updated_at
                """,
                (recording_id, entry["speaker_id"], entry["alias_name"], now, now),
            )
        conn.commit()


def alias_map(recording_id: int) -> dict[str, str]:
    """Return ``{speaker_id: alias_name}`` for the recording.

    Convenience for read-time substitution callers (Stories 5.1 / 5.2 /
    5.3 / 5.5) who don't need the full row metadata.
    """
    return {row["speaker_id"]: row["alias_name"] for row in list_aliases(recording_id)}
