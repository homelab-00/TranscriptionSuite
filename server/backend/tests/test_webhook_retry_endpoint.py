"""Webhook retry via the auto-actions/retry endpoint (Issue #104, Story 7.7 AC1).

Sprint 4's idempotent retry endpoint at
``POST /api/notebook/recordings/{id}/auto-actions/retry`` now accepts
``action_type="webhook"`` (Sprint 5 extension). The webhook branch:

  * Returns 200 + ``already_complete`` if the latest delivery row is success.
  * Returns 200 + ``already_in_progress`` if pending/in_flight.
  * Returns 400 + ``no_webhook_configured`` if the recording's snapshot
    has no webhook_url.
  * Returns 202 + ``retry_initiated`` and re-fires via _run_webhook_dispatch.

The dispatcher is mocked here — the worker pipeline is covered by
``tests/test_webhook_worker.py``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import server.database.database as db
from fastapi import HTTPException
from fastapi.responses import Response
from server.api.routes import notebook as notebook_route
from server.database import auto_action_repository as aar
from server.database import webhook_deliveries_repository as wdr

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


@pytest.fixture()
def recording_id(fresh_db: Path) -> int:
    return db.insert_recording(
        filename="r.wav",
        filepath="/tmp/r.wav",
        duration_seconds=1.0,
        recorded_at="2026-05-04T00:00:00",
    )


def _seed_snapshot(recording_id: int, webhook_url: str = "https://hooks.example.com/x") -> None:
    """Save a profile snapshot with a webhook_url so the retry endpoint
    can re-fire from the original profile context (no drift)."""
    snapshot = {
        "name": "test",
        "public_fields": {
            "webhook_url": webhook_url,
            "webhook_include_transcript_text": False,
        },
    }
    aar.save_profile_snapshot(recording_id, json.dumps(snapshot))


def _call_retry(recording_id: int, action_type: str = "webhook"):
    payload = notebook_route.AutoActionRetryRequest(action_type=action_type)
    response_obj = Response()
    result = asyncio.run(notebook_route.retry_auto_action(recording_id, payload, response_obj))
    return result, response_obj


# ──────────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────────


def test_retry_with_no_prior_delivery_returns_202(
    recording_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No prior delivery row → fresh dispatch."""
    _seed_snapshot(recording_id)

    fired: list = []

    async def _fake_dispatch(rid: int, public: dict) -> None:
        fired.append((rid, public))

    monkeypatch.setattr(
        "server.core.auto_action_coordinator._run_webhook_dispatch",
        _fake_dispatch,
    )

    result, http_response = _call_retry(recording_id)
    assert result.status == "retry_initiated"
    assert http_response.status_code == 202
    # Give the spawned task one tick to run.
    asyncio.run(asyncio.sleep(0.05))
    assert fired and fired[0][0] == recording_id


def test_retry_after_failed_returns_202(recording_id: int, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_snapshot(recording_id)
    a = wdr.create_pending(recording_id, None, {"x": 1})
    wdr.mark_failed(a, "prior")

    async def _fake_dispatch(rid: int, public: dict) -> None:
        pass

    monkeypatch.setattr(
        "server.core.auto_action_coordinator._run_webhook_dispatch",
        _fake_dispatch,
    )

    result, http_response = _call_retry(recording_id)
    assert result.status == "retry_initiated"
    assert http_response.status_code == 202


def test_retry_after_manual_intervention_returns_202(
    recording_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_snapshot(recording_id)
    a = wdr.create_pending(recording_id, None, {})
    wdr.mark_manual_intervention(a, "exhausted")

    async def _fake_dispatch(rid: int, public: dict) -> None:
        pass

    monkeypatch.setattr(
        "server.core.auto_action_coordinator._run_webhook_dispatch",
        _fake_dispatch,
    )

    result, http_response = _call_retry(recording_id)
    assert result.status == "retry_initiated"
    assert http_response.status_code == 202


# ──────────────────────────────────────────────────────────────────────────
# Idempotency on success / in-flight (Story 7.7 AC1 → R-EL27)
# ──────────────────────────────────────────────────────────────────────────


def test_retry_after_success_returns_already_complete(
    recording_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_snapshot(recording_id)
    a = wdr.create_pending(recording_id, None, {})
    wdr.mark_success(a)

    fired: list = []

    async def _fake_dispatch(rid: int, public: dict) -> None:
        fired.append((rid, public))

    monkeypatch.setattr(
        "server.core.auto_action_coordinator._run_webhook_dispatch",
        _fake_dispatch,
    )

    result, http_response = _call_retry(recording_id)
    assert result.status == "already_complete"
    assert http_response.status_code == 200
    asyncio.run(asyncio.sleep(0.05))
    assert fired == [], "no fresh dispatch should occur on already-complete"


def test_retry_during_pending_returns_already_in_progress(
    recording_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_snapshot(recording_id)
    wdr.create_pending(recording_id, None, {})  # row stays at pending

    fired: list = []

    async def _fake_dispatch(rid: int, public: dict) -> None:
        fired.append((rid, public))

    monkeypatch.setattr(
        "server.core.auto_action_coordinator._run_webhook_dispatch",
        _fake_dispatch,
    )

    result, http_response = _call_retry(recording_id)
    assert result.status == "already_in_progress"
    assert http_response.status_code == 200
    asyncio.run(asyncio.sleep(0.05))
    assert fired == []


def test_retry_during_in_flight_returns_already_in_progress(
    recording_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_snapshot(recording_id)
    a = wdr.create_pending(recording_id, None, {})
    wdr.mark_in_flight(a)

    fired: list = []

    async def _fake_dispatch(rid: int, public: dict) -> None:
        fired.append((rid, public))

    monkeypatch.setattr(
        "server.core.auto_action_coordinator._run_webhook_dispatch",
        _fake_dispatch,
    )

    result, http_response = _call_retry(recording_id)
    assert result.status == "already_in_progress"
    assert http_response.status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# Failure modes
# ──────────────────────────────────────────────────────────────────────────


def test_retry_with_no_webhook_configured_returns_400(
    recording_id: int,
) -> None:
    """Snapshot has no webhook_url — endpoint refuses to fire blind."""
    snapshot = {"name": "noop", "public_fields": {}}
    aar.save_profile_snapshot(recording_id, json.dumps(snapshot))
    payload = notebook_route.AutoActionRetryRequest(action_type="webhook")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook_route.retry_auto_action(recording_id, payload, Response()))
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "no_webhook_configured"


def test_retry_unknown_action_type_rejected_at_validation() -> None:
    """Pydantic surfaces unknown action_type as ValidationError at construct time."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        notebook_route.AutoActionRetryRequest(action_type="bogus")
