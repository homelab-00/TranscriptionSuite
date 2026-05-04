"""Migration 016 — webhook_deliveries table (Issue #104, Story 7.1).

Verifies the table exists with the right column set, the CHECK constraint
on status is enforced, the partial indexes are created, and the foreign-key
cascade behavior matches the design (CASCADE on recording, SET NULL on
profile).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import server.database.database as db

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


def _open(path: Path) -> sqlite3.Connection:
    """Open a raw connection with FK enforcement on (matches get_connection)."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


# ──────────────────────────────────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────────────────────────────────


def test_webhook_deliveries_table_exists(fresh_db: Path) -> None:
    with _open(fresh_db) as conn:
        cols = {r[1]: r for r in conn.execute("PRAGMA table_info(webhook_deliveries)").fetchall()}
    expected = {
        "id",
        "recording_id",
        "profile_id",
        "status",
        "attempt_count",
        "last_error",
        "created_at",
        "last_attempted_at",
        "payload_json",
    }
    assert expected.issubset(cols), f"missing columns: {expected - cols.keys()}"


def test_status_check_constraint_rejects_invalid(fresh_db: Path) -> None:
    """AC1 — CHECK (status IN (...)) blocks the obvious typo."""
    with _open(fresh_db) as conn:
        # Need a recording first since recording_id has a NOT NULL FK.
        conn.execute(
            "INSERT INTO recordings (filename, filepath, title, duration_seconds, recorded_at) "
            "VALUES ('a.wav', '/tmp/a.wav', 'a', 1.0, '2026-05-04T00:00:00')"
        )
        rec_id = conn.execute("SELECT id FROM recordings").fetchone()["id"]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO webhook_deliveries "
                "(recording_id, status, payload_json) VALUES (?, ?, ?)",
                (rec_id, "bogus", "{}"),
            )


def test_partial_status_index_exists(fresh_db: Path) -> None:
    with _open(fresh_db) as conn:
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='index' AND tbl_name='webhook_deliveries'"
        ).fetchall()
    names = {r["name"] for r in rows}
    assert "idx_webhook_deliveries_status" in names
    # Confirm it really IS partial (covers worker drain query only).
    sql_for_status_idx = next(
        r["sql"] for r in rows if r["name"] == "idx_webhook_deliveries_status"
    )
    assert "WHERE" in sql_for_status_idx.upper()
    assert "pending" in sql_for_status_idx.lower()
    assert "in_flight" in sql_for_status_idx.lower()


def test_recording_index_exists(fresh_db: Path) -> None:
    with _open(fresh_db) as conn:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='webhook_deliveries'"
            ).fetchall()
        }
    assert "idx_webhook_deliveries_recording" in names


# ──────────────────────────────────────────────────────────────────────────
# Foreign-key cascade behavior
# ──────────────────────────────────────────────────────────────────────────


def test_cascade_delete_on_recording_removes_deliveries(fresh_db: Path) -> None:
    """ON DELETE CASCADE: deleting the recording removes its delivery rows."""
    with _open(fresh_db) as conn:
        conn.execute(
            "INSERT INTO recordings (filename, filepath, title, duration_seconds, recorded_at) "
            "VALUES ('a.wav', '/tmp/a.wav', 'a', 1.0, '2026-05-04T00:00:00')"
        )
        rec_id = conn.execute("SELECT id FROM recordings").fetchone()["id"]
        conn.execute(
            "INSERT INTO webhook_deliveries "
            "(recording_id, status, payload_json) VALUES (?, 'pending', '{}')",
            (rec_id,),
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0] == 1

        conn.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0] == 0


def test_set_null_on_profile_delete(fresh_db: Path) -> None:
    """ON DELETE SET NULL: deleting the profile leaves the delivery row but nulls profile_id."""
    with _open(fresh_db) as conn:
        conn.execute(
            "INSERT INTO recordings (filename, filepath, title, duration_seconds, recorded_at) "
            "VALUES ('a.wav', '/tmp/a.wav', 'a', 1.0, '2026-05-04T00:00:00')"
        )
        rec_id = conn.execute("SELECT id FROM recordings").fetchone()["id"]
        conn.execute(
            "INSERT INTO profiles (name, schema_version, public_fields_json, private_field_refs_json) "
            "VALUES ('p1', '1.0', '{}', '{}')"
        )
        prof_id = conn.execute("SELECT id FROM profiles").fetchone()["id"]
        conn.execute(
            "INSERT INTO webhook_deliveries "
            "(recording_id, profile_id, status, payload_json) "
            "VALUES (?, ?, 'pending', '{}')",
            (rec_id, prof_id),
        )
        conn.commit()

        conn.execute("DELETE FROM profiles WHERE id = ?", (prof_id,))
        conn.commit()
        row = conn.execute("SELECT recording_id, profile_id FROM webhook_deliveries").fetchone()
        assert row is not None, "delivery row should NOT cascade-delete with profile"
        assert row["recording_id"] == rec_id
        assert row["profile_id"] is None


# ──────────────────────────────────────────────────────────────────────────
# Forward-only invariant
# ──────────────────────────────────────────────────────────────────────────


def test_downgrade_raises_runtime_error() -> None:
    """NFR22 — forward-only migration policy.

    File name leads with a digit so we go via importlib (Python's
    `import` statement won't accept ``016_*`` as a module identifier).
    """
    import importlib

    mod = importlib.import_module("server.database.migrations.versions.016_add_webhook_deliveries")
    with pytest.raises(RuntimeError, match="forward-only"):
        mod.downgrade()
