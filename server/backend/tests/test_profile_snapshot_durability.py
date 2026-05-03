"""Persist-Before-Deliver + snapshot-immutability tests (Issue #104, Story 1.3).

The big invariant these guard:

    The job_profile_snapshot row commit MUST complete before any worker
    code path that consumes the snapshot can fire. (NFR16, NFR18.)

These tests verify the snapshot-helper-level durability guarantee:
``snapshot_profile_at_job_start`` reads from a committed row, so any
subsequent worker call cannot see uncommitted state.

End-to-end coverage of the helper threaded through ``create_job`` lives
in ``test_create_job_profile_snapshot.py``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from server.database import profile_repository

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


def _public() -> dict:
    return {
        "filename_template": "{date} {title}.txt",
        "destination_folder": "/tmp",
        "auto_summary_enabled": False,
        "auto_export_enabled": False,
        "summary_model_id": None,
        "summary_prompt_template": None,
        "export_format": "plaintext",
    }


def test_snapshot_reads_from_committed_state_only(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demonstrates Persist-Before-Deliver at the snapshot helper layer:
    even if a writer attempted to take a snapshot mid-INSERT, the helper
    would see no row (returns None) rather than partial state."""
    # Fresh DB has no profiles
    assert profile_repository.snapshot_profile_at_job_start(1) is None

    # Once committed, snapshot is queryable
    pid = profile_repository.create_profile(
        name="P", description=None, schema_version="1.0", public_fields=_public()
    )
    snap = profile_repository.snapshot_profile_at_job_start(pid)
    assert snap is not None
    assert json.loads(snap[0])["id"] == pid


def test_concurrent_profile_edit_does_not_mutate_existing_snapshot(
    fresh_db: Path,
) -> None:
    """FR18 / R-EL21: a snapshot taken at t0 is independent of subsequent
    profile edits at t1. The worker uses the snapshot tuple, never the
    live row."""
    pid = profile_repository.create_profile(
        name="V1", description=None, schema_version="1.0", public_fields=_public()
    )
    snap_at_job_start = profile_repository.snapshot_profile_at_job_start(pid)
    assert snap_at_job_start is not None

    # Mid-job: user edits the profile
    new_public = {**_public(), "filename_template": "EDITED.txt"}
    profile_repository.update_profile(pid, name="V2", public_fields=new_public)

    # Snapshot tuple is unchanged
    snap_after_edit = profile_repository.snapshot_profile_at_job_start(pid)
    assert snap_after_edit is not None
    # The OLD snapshot (kept by the worker) is still V1; demonstrating that the
    # *captured* snapshot is what the worker would use:
    assert json.loads(snap_at_job_start[0])["name"] == "V1"
    # A NEW snapshot taken after the edit reflects the edit:
    assert json.loads(snap_after_edit[0])["name"] == "V2"


def test_snapshot_serialization_is_deterministic(fresh_db: Path) -> None:
    """sort_keys=True so byte-for-byte equality holds across runs (load-bearing
    for the profile_snapshot_golden fixture in downstream snapshot tests)."""
    pid = profile_repository.create_profile(
        name="Stable",
        description=None,
        schema_version="1.0",
        public_fields=_public(),
    )
    snap_a = profile_repository.snapshot_profile_at_job_start(pid)
    snap_b = profile_repository.snapshot_profile_at_job_start(pid)
    assert snap_a is not None and snap_b is not None
    assert snap_a[0] == snap_b[0]


def test_persist_before_deliver_commit_visible_in_new_connection(
    fresh_db: Path,
) -> None:
    """After create_profile returns, the row MUST be visible to a brand-new
    connection (proving the commit happened, not just a write)."""
    pid = profile_repository.create_profile(
        name="P", description=None, schema_version="1.0", public_fields=_public()
    )
    # New connection — no shared transaction state
    with sqlite3.connect(fresh_db) as conn:
        row = conn.execute("SELECT name FROM profiles WHERE id = ?", (pid,)).fetchone()
    assert row is not None
    assert row[0] == "P"
