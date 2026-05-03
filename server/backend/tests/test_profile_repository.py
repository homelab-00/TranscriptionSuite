"""Tests for server.database.profile_repository (Issue #104, Story 1.2 + 1.3).

Uses a tmp_path-backed SQLite via ``set_data_directory()`` + ``init_db()``
so migrations run against a fresh DB for each test.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from server.database import profile_repository
from server.database.profile_repository import (
    SUPPORTED_SCHEMA_VERSIONS,
    UnsupportedSchemaVersionError,
)

pytest.importorskip("alembic")


@pytest.fixture()
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialise a fresh tmp_path-backed SQLite DB with all migrations applied."""
    data_dir = tmp_path / "data"
    (data_dir / "database").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setattr(db, "_data_dir", None)
    monkeypatch.setattr(db, "_db_path", None)
    db.set_data_directory(data_dir)
    db.init_db()
    return db.get_db_path()


# ──────────────────────────────────────────────────────────────────────────
# Story 1.2 — basic CRUD
# ──────────────────────────────────────────────────────────────────────────


def _minimal_public_fields() -> dict:
    return {
        "filename_template": "{date} {title}.txt",
        "destination_folder": "/tmp/dest",
        "auto_summary_enabled": False,
        "auto_export_enabled": False,
        "summary_model_id": None,
        "summary_prompt_template": None,
        "export_format": "plaintext",
    }


def test_create_profile_persists_and_returns_id(fresh_db: Path) -> None:
    pid = profile_repository.create_profile(
        name="Default",
        description="The default profile",
        schema_version="1.0",
        public_fields=_minimal_public_fields(),
    )
    assert pid > 0

    record = profile_repository.get_profile(pid)
    assert record is not None
    assert record["name"] == "Default"
    assert record["schema_version"] == "1.0"
    assert record["public_fields"]["filename_template"] == "{date} {title}.txt"


def test_create_persist_before_deliver_commits_first(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Persist-Before-Deliver invariant (NFR16): the SQLite commit MUST
    happen before ``create_profile`` returns the new id.

    ``sqlite3.Connection`` is a C immutable type so we cannot monkeypatch
    ``commit`` on it directly. Instead we wrap the ``get_connection``
    context-manager exposed by ``profile_repository`` so the test sees
    every commit call in order and can assert it occurred before
    ``create_profile`` returned.
    """
    call_order: list[str] = []
    real_get_connection = profile_repository.get_connection

    from contextlib import contextmanager

    class _CommitTrackingConn:
        """Lightweight proxy: forwards everything to the wrapped conn,
        records commit() calls. ``sqlite3.Connection`` is a C immutable
        type so an instance attribute can't be overridden — proxy is the
        only portable approach."""

        def __init__(self, real_conn):
            self._real = real_conn

        def commit(self):
            call_order.append("commit")
            return self._real.commit()

        def __getattr__(self, name):
            return getattr(self._real, name)

    @contextmanager
    def tracking_get_connection():
        with real_get_connection() as conn:
            yield _CommitTrackingConn(conn)

    monkeypatch.setattr(profile_repository, "get_connection", tracking_get_connection)

    pid = profile_repository.create_profile(
        name="P1",
        description=None,
        schema_version="1.0",
        public_fields=_minimal_public_fields(),
    )
    call_order.append("returned")

    assert "commit" in call_order, "create_profile did not call commit() at all"
    assert call_order.index("commit") < call_order.index("returned"), (
        f"Persist-Before-Deliver violated: {call_order}"
    )
    # Sanity: row is queryable from a brand-new connection (commit really happened)
    with sqlite3.connect(fresh_db) as conn:
        row = conn.execute("SELECT id FROM profiles WHERE id = ?", (pid,)).fetchone()
    assert row is not None


def test_get_profile_returns_none_for_missing(fresh_db: Path) -> None:
    assert profile_repository.get_profile(99999) is None


def test_update_profile_changes_fields_and_updated_at(fresh_db: Path) -> None:
    pid = profile_repository.create_profile(
        name="Original",
        description=None,
        schema_version="1.0",
        public_fields=_minimal_public_fields(),
    )
    before = profile_repository.get_profile(pid)
    assert before is not None

    updated = profile_repository.update_profile(pid, name="Renamed")
    assert updated is True

    after = profile_repository.get_profile(pid)
    assert after is not None
    assert after["name"] == "Renamed"
    # updated_at moves forward (or at least is not earlier — clock granularity safe)
    assert after["updated_at"] >= before["updated_at"]


def test_update_profile_returns_false_when_missing(fresh_db: Path) -> None:
    assert profile_repository.update_profile(99999, name="X") is False


def test_delete_profile_removes_row(fresh_db: Path) -> None:
    pid = profile_repository.create_profile(
        name="ToDelete",
        description=None,
        schema_version="1.0",
        public_fields=_minimal_public_fields(),
    )
    assert profile_repository.delete_profile(pid) is True
    assert profile_repository.get_profile(pid) is None
    assert profile_repository.delete_profile(pid) is False


def test_list_profiles_orders_by_name(fresh_db: Path) -> None:
    for name in ("zulu", "alpha", "mike"):
        profile_repository.create_profile(
            name=name,
            description=None,
            schema_version="1.0",
            public_fields=_minimal_public_fields(),
        )
    names = [p["name"] for p in profile_repository.list_profiles()]
    assert names == ["alpha", "mike", "zulu"]


def test_create_with_unsupported_schema_version_raises(fresh_db: Path) -> None:
    with pytest.raises(UnsupportedSchemaVersionError) as exc:
        profile_repository.create_profile(
            name="P",
            description=None,
            schema_version="99.0",
            public_fields=_minimal_public_fields(),
        )
    assert exc.value.received == "99.0"
    assert "1.0" in str(exc.value)


def test_update_with_unsupported_schema_version_raises(fresh_db: Path) -> None:
    pid = profile_repository.create_profile(
        name="P",
        description=None,
        schema_version="1.0",
        public_fields=_minimal_public_fields(),
    )
    with pytest.raises(UnsupportedSchemaVersionError):
        profile_repository.update_profile(pid, schema_version="2.5")


def test_to_public_dict_strips_private_field_refs(fresh_db: Path) -> None:
    pid = profile_repository.create_profile(
        name="HasPrivate",
        description=None,
        schema_version="1.0",
        public_fields=_minimal_public_fields(),
        private_field_refs={"webhook_token": "profile.42.webhook_token"},
    )
    record = profile_repository.get_profile(pid)
    assert record is not None
    assert record["private_field_refs"] == {"webhook_token": "profile.42.webhook_token"}
    public = profile_repository.to_public_dict(record)
    assert "private_field_refs" not in public


def test_supported_schema_versions_constant() -> None:
    """Pin the catalogue so adding a version is an intentional act with a test bump."""
    assert SUPPORTED_SCHEMA_VERSIONS == frozenset({"1.0"})


# ──────────────────────────────────────────────────────────────────────────
# Story 1.3 — snapshot helper
# ──────────────────────────────────────────────────────────────────────────


def test_snapshot_profile_at_job_start_returns_public_only(fresh_db: Path) -> None:
    pid = profile_repository.create_profile(
        name="Snap",
        description="snap me",
        schema_version="1.0",
        public_fields=_minimal_public_fields(),
        private_field_refs={"webhook_token": "profile.X.webhook_token"},
    )
    result = profile_repository.snapshot_profile_at_job_start(pid)
    assert result is not None
    snapshot_json, version = result
    assert version == "1.0"
    snapshot = json.loads(snapshot_json)
    # Public + identity, no private refs
    assert snapshot["id"] == pid
    assert snapshot["name"] == "Snap"
    assert snapshot["schema_version"] == "1.0"
    assert snapshot["public_fields"]["filename_template"] == "{date} {title}.txt"
    assert "private_field_refs" not in snapshot


def test_snapshot_profile_returns_none_when_missing(fresh_db: Path) -> None:
    assert profile_repository.snapshot_profile_at_job_start(99999) is None


def test_snapshot_uses_frozen_clock_for_determinism(fresh_db: Path, frozen_clock) -> None:
    """The snapshot itself does not embed a timestamp, but the surrounding
    DB row carries created_at / updated_at — when frozen_clock is active,
    those are deterministic, which is what downstream snapshot-equality
    tests rely on."""
    pid = profile_repository.create_profile(
        name="FrozenP",
        description=None,
        schema_version="1.0",
        public_fields=_minimal_public_fields(),
    )
    record = profile_repository.get_profile(pid)
    assert record is not None
    # Anchor: 2025-01-15T12:00:00Z is the frozen_clock default
    assert record["created_at"].startswith("2025-01-15T12:00:00")


def test_snapshot_immutable_under_concurrent_edit(fresh_db: Path) -> None:
    """The snapshot serialises profile state at the moment it's taken;
    later edits do NOT mutate the snapshot tuple. (FR18, R-EL21.)"""
    pid = profile_repository.create_profile(
        name="V1",
        description=None,
        schema_version="1.0",
        public_fields=_minimal_public_fields(),
    )
    snap_before = profile_repository.snapshot_profile_at_job_start(pid)
    assert snap_before is not None

    new_public = {**_minimal_public_fields(), "filename_template": "EDITED.txt"}
    profile_repository.update_profile(pid, name="V2", public_fields=new_public)

    # snap_before is a tuple — Python immutability — still has v1 state
    snap_before_json = json.loads(snap_before[0])
    assert snap_before_json["name"] == "V1"
    assert snap_before_json["public_fields"]["filename_template"] == "{date} {title}.txt"

    # A NEW snapshot taken now reflects the edit
    snap_after = profile_repository.snapshot_profile_at_job_start(pid)
    assert snap_after is not None
    snap_after_json = json.loads(snap_after[0])
    assert snap_after_json["name"] == "V2"
    assert snap_after_json["public_fields"]["filename_template"] == "EDITED.txt"
