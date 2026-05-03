"""Profile repository for the Audio Notebook QoL pack (Issue #104, Story 1.2).

Parameterised SQL CRUD over the `profiles` table created by migration 008.

Two key design constraints:
  - public_fields_json holds settings safely returned by the API (FR10).
  - private_field_refs_json holds keychain-reference IDs only — NEVER
    plaintext values (FR11, R-EL22). The keychain layer (Story 1.7) is
    responsible for translating an ID like 'profile.123.webhook_token'
    into its concrete secret at use-site.

Persist-Before-Deliver (NFR16): every write commits before returning.

Concurrent-edit semantics: last-write-wins via UPDATE on `updated_at`
(NFR46). Stale-cache discovery is the frontend's responsibility — see
Story 1.6.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from server.database.database import get_connection

logger = logging.getLogger(__name__)


SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1.0"})


class UnsupportedSchemaVersionError(ValueError):
    """Raised when a write specifies a schema_version not in
    SUPPORTED_SCHEMA_VERSIONS (FR16, R-EL30, NFR13)."""

    def __init__(self, received: str) -> None:
        super().__init__(
            f"unsupported_schema_version: received={received!r}, "
            f"supported={sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )
        self.received = received


def _now_iso() -> str:
    """ISO-8601 UTC timestamp. Honours `frozen_clock` in tests."""
    return datetime.now(UTC).isoformat()


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a sqlite3.Row to a dict with public_fields parsed
    and private_field_refs parsed but NEVER returned to the caller —
    callers that want only the public projection use ``to_public_dict``.
    """
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "schema_version": row["schema_version"],
        "public_fields": json.loads(row["public_fields_json"]),
        "private_field_refs": json.loads(row["private_field_refs_json"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def to_public_dict(record: dict[str, Any]) -> dict[str, Any]:
    """Strip private_field_refs from a record. Used by API response builders
    to enforce FR11 — private fields never travel over the wire."""
    return {k: v for k, v in record.items() if k != "private_field_refs"}


def list_profiles() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM profiles ORDER BY name COLLATE NOCASE").fetchall()
    return [_row_to_dict(row) for row in rows]


def get_profile(profile_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


def create_profile(
    *,
    name: str,
    description: str | None,
    schema_version: str,
    public_fields: dict[str, Any],
    private_field_refs: dict[str, str] | None = None,
) -> int:
    """Insert and commit. Returns new row id."""
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchemaVersionError(schema_version)
    now = _now_iso()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO profiles
                (name, description, schema_version,
                 public_fields_json, private_field_refs_json,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                description,
                schema_version,
                json.dumps(public_fields, sort_keys=True),
                json.dumps(private_field_refs or {}, sort_keys=True),
                now,
                now,
            ),
        )
        conn.commit()
        # Persist-Before-Deliver: commit returns BEFORE we hand back the id.
        return int(cur.lastrowid or 0)


def update_profile(
    profile_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    schema_version: str | None = None,
    public_fields: dict[str, Any] | None = None,
    private_field_refs: dict[str, str] | None = None,
) -> bool:
    """Update fields that were passed (None = leave alone).

    Returns True if a row was actually updated; False if no row matched.

    Last-write-wins semantics (NFR46): no optimistic locking on
    `updated_at`. The frontend reconciles via stale-cache discovery.
    """
    if schema_version is not None and schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchemaVersionError(schema_version)

    sets: list[str] = []
    params: list[Any] = []
    if name is not None:
        sets.append("name = ?")
        params.append(name)
    if description is not None:
        sets.append("description = ?")
        params.append(description)
    if schema_version is not None:
        sets.append("schema_version = ?")
        params.append(schema_version)
    if public_fields is not None:
        sets.append("public_fields_json = ?")
        params.append(json.dumps(public_fields, sort_keys=True))
    if private_field_refs is not None:
        sets.append("private_field_refs_json = ?")
        params.append(json.dumps(private_field_refs, sort_keys=True))

    if not sets:
        return False  # nothing to do; caller likely passed an empty payload

    sets.append("updated_at = ?")
    params.append(_now_iso())
    params.append(profile_id)

    with get_connection() as conn:
        cur = conn.execute(
            f"UPDATE profiles SET {', '.join(sets)} WHERE id = ?",  # noqa: S608
            tuple(params),
        )
        conn.commit()
        return cur.rowcount > 0


def delete_profile(profile_id: int) -> bool:
    """Delete a profile row. Returns True if a row was removed."""
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM profiles WHERE id = ?",
            (profile_id,),
        )
        conn.commit()
        return cur.rowcount > 0


# ──────────────────────────────────────────────────────────────────────────
# Story 1.3 — Snapshot helper
# ──────────────────────────────────────────────────────────────────────────


def snapshot_profile_at_job_start(profile_id: int) -> tuple[str, str] | None:
    """Return ``(snapshot_json, schema_version)`` for a profile, or ``None``
    if the profile has been deleted between selection and job-start.

    The snapshot intentionally OMITS ``private_field_refs`` — those are
    pointers to keychain entries, not values, and are re-resolved at
    use-site by the worker. ADR-003 + ADR-005 reasoning.
    """
    profile = get_profile(profile_id)
    if profile is None:
        logger.warning("snapshot_profile_at_job_start: profile %d not found", profile_id)
        return None
    snapshot = {
        "id": profile["id"],
        "name": profile["name"],
        "schema_version": profile["schema_version"],
        "public_fields": profile["public_fields"],
    }
    return json.dumps(snapshot, sort_keys=True), profile["schema_version"]
