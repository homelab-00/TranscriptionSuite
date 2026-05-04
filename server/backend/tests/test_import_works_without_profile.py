"""Regression test: import flow does NOT require a profile (Issue #104, Story 2.3).

Anna's J1 Lurker happy path mandates that a fresh installation with no
profiles defined can still import audio. This test pins the contract that
``create_job`` accepts ``profile_id=None`` and produces a usable durability
row — the snapshot columns stay NULL, ``audio_hash`` is still writeable, and
the row's status enters ``'processing'`` exactly as the worker expects.

Why a repository-level test (and not a full HTTP test): the route handler
already wraps ``create_job`` and the route is exercised by other suites; the
critical regression we're guarding against is the repository contract
silently flipping to require a profile (a subtle bug that an HTTP test
would also catch but takes 100× longer to run).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import server.database.database as db
from server.database.job_repository import create_job, get_job


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


def test_import_works_without_profile(fresh_db: Path) -> None:
    """A fresh install with NO profiles defined still permits import.

    The combined contract:
      - profile_id is optional (default None)
      - audio_hash can be set independently
      - the row enters status='processing' (the worker handshake)
      - snapshot columns are NULL (no profile to snapshot)
    """
    create_job(
        job_id="import-anna-j1",
        source="file_import",
        client_name=None,
        language=None,
        task="transcribe",
        translation_target=None,
        # Notably absent: profile_id — exactly the J1 happy-path
        audio_hash="d" * 64,
    )
    row = get_job("import-anna-j1")
    assert row is not None
    assert row["status"] == "processing"
    assert row["audio_hash"] == "d" * 64
    # No profile selected → no snapshot
    assert row["job_profile_snapshot"] is None
    assert row["snapshot_schema_version"] is None
