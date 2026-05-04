"""Story 6.9 — idempotent retry endpoint tests.

AC1: POST endpoint accepts {action_type} and re-fires when status is failed/
     deferred/summary_empty/summary_truncated; returns 202 + retry_initiated.
AC2: Idempotent on success — returns 200 + already_complete; NO re-execution.
AC3: Persist-Before-Deliver — covered by commit C matrix.

Manual retry button (frontend AC) — covered by AutoActionStatusBadge tests.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from fastapi import HTTPException
from fastapi.responses import Response
from server.api.routes import notebook as notebook_route
from server.database import auto_action_repository as repo

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


def _seed(db_path: Path, recording_id: int = 1) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO recordings (id, filename, filepath, title, duration_seconds, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                recording_id,
                "r.wav",
                "/tmp/r.wav",
                "T",
                60.0,
                "2025-01-15T12:00:00Z",
            ),
        )
        conn.commit()


def _call_retry(recording_id: int, action_type: str) -> notebook_route.AutoActionRetryResponse:
    """Direct-call helper for the retry endpoint per CLAUDE.md test pattern."""
    payload = notebook_route.AutoActionRetryRequest(action_type=action_type)
    response_obj = Response()
    return asyncio.run(
        notebook_route.retry_auto_action(recording_id, payload, response_obj)
    ), response_obj


# ──────────────────────────────────────────────────────────────────────────
# AC1 — happy path retry
# ──────────────────────────────────────────────────────────────────────────


def test_retry_on_failed_returns_202(fresh_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(fresh_db)
    repo.set_auto_summary_status(1, "failed", error="prior failure")

    # Don't actually run the coordinator — patch retry_auto_action_internal
    # so we don't need a real LLM.
    fired = [False]

    async def _fake_retry(_rec_id: int, _action_type: str) -> None:
        fired[0] = True

    monkeypatch.setattr(
        "server.core.auto_action_coordinator.retry_auto_action_internal",
        _fake_retry,
    )

    result, http_response = _call_retry(1, "auto_summary")
    assert result.status == "retry_initiated"
    assert http_response.status_code == 202
    # Status reset to 'pending' before dispatch
    assert repo.get_auto_action_status(1, "auto_summary") == "pending"


def test_retry_on_deferred_returns_202(fresh_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(fresh_db)
    repo.set_auto_export_status(1, "deferred", path="/mnt/usb")

    async def _fake_retry(_rec_id: int, _action_type: str) -> None:
        pass

    monkeypatch.setattr(
        "server.core.auto_action_coordinator.retry_auto_action_internal",
        _fake_retry,
    )

    result, http_response = _call_retry(1, "auto_export")
    assert result.status == "retry_initiated"
    assert http_response.status_code == 202


def test_retry_on_summary_empty_returns_202(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(fresh_db)
    repo.set_auto_summary_status(1, "summary_empty")

    async def _fake_retry(_rec_id: int, _action_type: str) -> None:
        pass

    monkeypatch.setattr(
        "server.core.auto_action_coordinator.retry_auto_action_internal",
        _fake_retry,
    )

    result, http_response = _call_retry(1, "auto_summary")
    assert result.status == "retry_initiated"
    assert http_response.status_code == 202


def test_retry_on_summary_truncated_returns_202(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(fresh_db)
    repo.set_auto_summary_status(1, "summary_truncated")

    async def _fake_retry(_rec_id: int, _action_type: str) -> None:
        pass

    monkeypatch.setattr(
        "server.core.auto_action_coordinator.retry_auto_action_internal",
        _fake_retry,
    )

    result, _http_response = _call_retry(1, "auto_summary")
    assert result.status == "retry_initiated"


# ──────────────────────────────────────────────────────────────────────────
# AC2 — idempotent on success — Story 6.9 / R-EL27
# ──────────────────────────────────────────────────────────────────────────


def test_retry_on_success_returns_already_complete_no_re_execution(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Idempotent — calling retry on a successful action returns 200 +
    already_complete and does NOT re-fire the coordinator."""
    _seed(fresh_db)
    repo.set_auto_summary_status(1, "success")

    fired = [False]

    async def _should_not_fire(_rec_id: int, _action_type: str) -> None:
        fired[0] = True

    monkeypatch.setattr(
        "server.core.auto_action_coordinator.retry_auto_action_internal",
        _should_not_fire,
    )

    result, http_response = _call_retry(1, "auto_summary")
    assert result.status == "already_complete"
    assert http_response.status_code == 200
    assert fired[0] is False  # NO re-execution
    # Status untouched
    assert repo.get_auto_action_status(1, "auto_summary") == "success"


# ──────────────────────────────────────────────────────────────────────────
# AC — already in-flight
# ──────────────────────────────────────────────────────────────────────────


def test_retry_on_in_progress_returns_already_in_progress(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrent click while a retry is in flight → no double-fire."""
    _seed(fresh_db)
    repo.set_auto_summary_status(1, "in_progress")

    fired = [False]

    async def _should_not_fire(_rec_id: int, _action_type: str) -> None:
        fired[0] = True

    monkeypatch.setattr(
        "server.core.auto_action_coordinator.retry_auto_action_internal",
        _should_not_fire,
    )

    result, http_response = _call_retry(1, "auto_summary")
    assert result.status == "already_in_progress"
    assert http_response.status_code == 200
    assert fired[0] is False
    assert repo.get_auto_action_status(1, "auto_summary") == "in_progress"


# ──────────────────────────────────────────────────────────────────────────
# Manual retry resets attempts (Story 6.11 → R-EL18)
# ──────────────────────────────────────────────────────────────────────────


def test_retry_resets_attempts_counter(fresh_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """User-initiated retry resets attempts so escalation budget is fresh."""
    _seed(fresh_db)
    repo.set_auto_summary_status(1, "failed")
    repo.increment_auto_action_attempts(1, "auto_summary")
    repo.increment_auto_action_attempts(1, "auto_summary")
    assert repo.get_auto_action_attempts(1, "auto_summary") == 2

    async def _fake_retry(_rec_id: int, _action_type: str) -> None:
        pass

    monkeypatch.setattr(
        "server.core.auto_action_coordinator.retry_auto_action_internal",
        _fake_retry,
    )

    _call_retry(1, "auto_summary")
    assert repo.get_auto_action_attempts(1, "auto_summary") == 0


# ──────────────────────────────────────────────────────────────────────────
# 404 + 400
# ──────────────────────────────────────────────────────────────────────────


def test_retry_404_on_unknown_recording(fresh_db: Path) -> None:
    payload = notebook_route.AutoActionRetryRequest(action_type="auto_summary")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook_route.retry_auto_action(99999, payload, Response()))
    assert exc.value.status_code == 404


def test_retry_400_on_unknown_action_type() -> None:
    """Pydantic validator rejects bad action_type at construction time."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        notebook_route.AutoActionRetryRequest(action_type="auto_lol")
