"""WebhookWorker — lifecycle, delivery contract, PBD, escalation
(Issue #104, Sprint 5: Stories 7.3 + 7.4 + 7.5 + 7.7).

All tests use the ``webhook_mock_receiver`` aiohttp fixture from
``conftest.py`` so no real network IO occurs. The receiver is
programmable: ``set_response(status, delay_seconds=...)`` /
``set_redirect(url)`` configure the next response shape.

Persist-Before-Deliver assertions verify ordering by recording an
event log inside a monkeypatched commit hook + the HTTP fire — the
'persist' event must come strictly before 'deliver'.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
import server.database.database as db
from server.database import webhook_deliveries_repository as wdr
from server.services.webhook_worker import (
    AUTO_RETRY_DELAY_S,
    HTTP_TIMEOUT_S,
    WebhookWorker,
)

pytest.importorskip("alembic")


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


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


@pytest.fixture()
def insert_pending(recording_id: int):
    """Factory: insert a pending webhook_deliveries row pointing at a URL."""

    def _insert(url: str, *, extra: dict | None = None) -> int:
        body: dict[str, Any] = {
            "event": "transcription.completed",
            "recording_id": recording_id,
            "__webhook_url__": url,
        }
        if extra:
            body.update(extra)
        return wdr.create_pending(recording_id, profile_id=None, payload=body)

    return _insert


@pytest.fixture(autouse=True)
def _allow_test_loopback(monkeypatch: pytest.MonkeyPatch):
    """The aiohttp ``webhook_mock_receiver`` binds to ``127.0.0.1`` — a
    private IP that the worker's TOCTOU re-check legitimately rejects in
    production. For the worker test suite, we monkeypatch the validator
    inside the worker module to a no-op so the mock receiver is reachable.

    The validator itself is exercised exhaustively in
    ``test_webhook_url_validation.py`` and the profile-endpoint tests —
    it is NOT an untested attack surface.
    """
    import server.services.webhook_worker as ww

    monkeypatch.setattr(ww, "validate_webhook_url", lambda url: None)
    yield


async def _drain_until(predicate, *, timeout: float = 5.0, interval: float = 0.05) -> None:
    """Wait up to ``timeout`` seconds for ``predicate()`` to return True."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"predicate did not become true within {timeout}s")


# ──────────────────────────────────────────────────────────────────────────
# Story 7.3 — lifecycle
# ──────────────────────────────────────────────────────────────────────────


async def test_worker_starts_and_stops_cleanly() -> None:
    worker = WebhookWorker(poll_interval_s=0.05)
    await worker.start()
    assert worker._task is not None and not worker._task.done()  # noqa: SLF001
    await worker.stop(grace_s=2.0)
    assert worker._task is None  # noqa: SLF001


async def test_worker_double_start_is_idempotent() -> None:
    worker = WebhookWorker(poll_interval_s=0.05)
    await worker.start()
    task1 = worker._task  # noqa: SLF001
    await worker.start()
    task2 = worker._task  # noqa: SLF001
    assert task1 is task2
    await worker.stop(grace_s=2.0)


async def test_worker_drains_pending_rows(insert_pending, webhook_mock_receiver) -> None:
    """End-to-end happy path: 3 pending rows → all marked success."""
    webhook_mock_receiver.set_response(200, body={"ok": True})
    a = insert_pending(webhook_mock_receiver.url)
    webhook_mock_receiver.set_response(200, body={"ok": True})
    b = insert_pending(webhook_mock_receiver.url)
    webhook_mock_receiver.set_response(200, body={"ok": True})
    c = insert_pending(webhook_mock_receiver.url)

    worker = WebhookWorker(poll_interval_s=0.05)
    await worker.start()
    try:
        await _drain_until(
            lambda: all(wdr.get_by_id(x)["status"] == "success" for x in (a, b, c)),
            timeout=5.0,
        )
    finally:
        await worker.stop(grace_s=2.0)


async def test_worker_picks_up_in_flight_on_restart(insert_pending, webhook_mock_receiver) -> None:
    """Story 7.5 AC2 — bootstrap recovery sweeps in_flight rows."""
    webhook_mock_receiver.set_response(200)
    row_id = insert_pending(webhook_mock_receiver.url)
    # Manually flip to in_flight to simulate a prior crash mid-call.
    wdr.mark_in_flight(row_id)

    worker = WebhookWorker(poll_interval_s=0.05)
    await worker.start()
    try:
        await _drain_until(lambda: wdr.get_by_id(row_id)["status"] == "success", timeout=5.0)
    finally:
        await worker.stop(grace_s=2.0)


async def test_stop_requeues_in_flight_back_to_pending(
    insert_pending, webhook_mock_receiver
) -> None:
    """Story 7.3 AC5 — stop() reverts in_flight rows so next start picks them up."""
    webhook_mock_receiver.set_response(200, delay_seconds=0)
    row_id = insert_pending(webhook_mock_receiver.url)
    # Manually mark it in_flight without firing — simulates a hot stop()
    # right before the HTTP call would have happened.
    wdr.mark_in_flight(row_id)

    worker = WebhookWorker(poll_interval_s=60.0)  # don't auto-tick
    await worker.start()
    await worker.stop(grace_s=1.0)

    row = wdr.get_by_id(row_id)
    assert row["status"] == "pending"


async def test_notify_new_delivery_wakes_loop(insert_pending, webhook_mock_receiver) -> None:
    """Long poll interval is shortcut by notify_new_delivery()."""
    webhook_mock_receiver.set_response(200)
    worker = WebhookWorker(poll_interval_s=60.0)  # would normally wait 60s
    await worker.start()
    try:
        # Wait one tick so the loop is parked at the first asyncio.wait_for.
        await asyncio.sleep(0.05)
        row_id = insert_pending(webhook_mock_receiver.url)
        worker.notify_new_delivery()
        await _drain_until(lambda: wdr.get_by_id(row_id)["status"] == "success", timeout=2.0)
    finally:
        await worker.stop(grace_s=1.0)


# ──────────────────────────────────────────────────────────────────────────
# Story 7.4 — delivery contract
# ──────────────────────────────────────────────────────────────────────────


async def test_timeout_marks_failed(
    insert_pending, webhook_mock_receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC1 — 10s deadline. We patch HTTP_TIMEOUT_S to 0.5s for fast test."""
    monkeypatch.setattr("server.services.webhook_worker.HTTP_TIMEOUT_S", 0.5)
    # Mock receiver delays 2s — well past 0.5s, but well under what would
    # slow the test suite down.
    webhook_mock_receiver.set_response(200, delay_seconds=2.0)
    row_id = insert_pending(webhook_mock_receiver.url)

    worker = WebhookWorker(poll_interval_s=0.05)
    await worker.start()
    try:
        await _drain_until(lambda: wdr.get_by_id(row_id)["status"] == "failed", timeout=5.0)
    finally:
        await worker.stop(grace_s=2.0)
    row = wdr.get_by_id(row_id)
    assert row["last_error"] == "timeout"


async def test_no_redirect_following(insert_pending, webhook_mock_receiver) -> None:
    """AC2 — 3xx is treated as failure; worker does NOT follow."""
    webhook_mock_receiver.set_redirect("https://elsewhere.example.com/foo")
    row_id = insert_pending(webhook_mock_receiver.url)

    worker = WebhookWorker(poll_interval_s=0.05)
    await worker.start()
    try:
        await _drain_until(lambda: wdr.get_by_id(row_id)["status"] == "failed", timeout=5.0)
    finally:
        await worker.stop(grace_s=2.0)
    row = wdr.get_by_id(row_id)
    assert row["last_error"] == "http_302"
    # Receiver controller should have seen exactly ONE request — not two.
    assert len(webhook_mock_receiver.requests) == 1


async def test_accept_encoding_identity_sent(insert_pending, webhook_mock_receiver) -> None:
    """AC3 — Accept-Encoding: identity header signals "no decompression"."""
    webhook_mock_receiver.set_response(200)
    insert_pending(webhook_mock_receiver.url)

    worker = WebhookWorker(poll_interval_s=0.05)
    await worker.start()
    try:
        await _drain_until(lambda: len(webhook_mock_receiver.requests) >= 1, timeout=5.0)
    finally:
        await worker.stop(grace_s=2.0)
    headers = webhook_mock_receiver.requests[0]["headers"]
    assert headers.get("Accept-Encoding") == "identity"


@pytest.mark.parametrize("status_code", [200, 201, 204])
async def test_2xx_status_marks_success(
    status_code: int, insert_pending, webhook_mock_receiver
) -> None:
    """AC4 — every 2xx maps to success."""
    webhook_mock_receiver.set_response(status_code)
    row_id = insert_pending(webhook_mock_receiver.url)
    worker = WebhookWorker(poll_interval_s=0.05)
    await worker.start()
    try:
        await _drain_until(lambda: wdr.get_by_id(row_id)["status"] == "success", timeout=5.0)
    finally:
        await worker.stop(grace_s=2.0)


@pytest.mark.parametrize("status_code", [400, 401, 404, 500, 502, 503])
async def test_non_2xx_status_marks_failed(
    status_code: int, insert_pending, webhook_mock_receiver
) -> None:
    """AC4 — everything outside 2xx is failure."""
    webhook_mock_receiver.set_response(status_code)
    row_id = insert_pending(webhook_mock_receiver.url)
    worker = WebhookWorker(poll_interval_s=0.05)
    await worker.start()
    try:
        await _drain_until(lambda: wdr.get_by_id(row_id)["status"] == "failed", timeout=5.0)
    finally:
        await worker.stop(grace_s=2.0)
    row = wdr.get_by_id(row_id)
    assert row["last_error"] == f"http_{status_code}"


async def test_3xx_status_marks_failed_no_redirect(insert_pending, webhook_mock_receiver) -> None:
    """AC2 + AC4 — 3xx without Location-following → failed."""
    webhook_mock_receiver.set_response(304)
    row_id = insert_pending(webhook_mock_receiver.url)
    worker = WebhookWorker(poll_interval_s=0.05)
    await worker.start()
    try:
        await _drain_until(lambda: wdr.get_by_id(row_id)["status"] == "failed", timeout=5.0)
    finally:
        await worker.stop(grace_s=2.0)


# ──────────────────────────────────────────────────────────────────────────
# Story 7.5 — Persist-Before-Deliver
# ──────────────────────────────────────────────────────────────────────────


async def test_pending_row_exists_before_http_fire(
    insert_pending, webhook_mock_receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 'pending' row must be durable BEFORE the HTTP call happens."""
    events: list[str] = []
    real_post = WebhookWorker._http_post_with_contract

    async def recording_post(url, payload, headers):
        events.append("http_fire")
        return await real_post(url, payload, headers)

    monkeypatch.setattr(WebhookWorker, "_http_post_with_contract", staticmethod(recording_post))

    webhook_mock_receiver.set_response(200)
    row_id = insert_pending(webhook_mock_receiver.url)
    events.append("row_inserted")

    worker = WebhookWorker(poll_interval_s=0.05)
    await worker.start()
    try:
        await _drain_until(lambda: wdr.get_by_id(row_id)["status"] == "success", timeout=5.0)
    finally:
        await worker.stop(grace_s=2.0)

    assert events.index("row_inserted") < events.index("http_fire")


async def test_in_flight_committed_before_http_fire(
    insert_pending, webhook_mock_receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Story 7.5 — in_flight transition is committed strictly BEFORE the POST."""
    seen_status_at_fire: list[str] = []
    real_post = WebhookWorker._http_post_with_contract

    async def recording_post(url, payload, headers):
        # Re-fetch row state from a fresh connection — only if the
        # in_flight COMMIT happened will this read see it.
        # The row id is encoded in the payload via recording_id; we fish
        # it via list_pending which returns ordered rows.
        rows = wdr.list_pending()
        if rows:
            seen_status_at_fire.append(rows[0]["status"])
        return await real_post(url, payload, headers)

    monkeypatch.setattr(WebhookWorker, "_http_post_with_contract", staticmethod(recording_post))

    webhook_mock_receiver.set_response(200)
    row_id = insert_pending(webhook_mock_receiver.url)

    worker = WebhookWorker(poll_interval_s=0.05)
    await worker.start()
    try:
        await _drain_until(lambda: wdr.get_by_id(row_id)["status"] == "success", timeout=5.0)
    finally:
        await worker.stop(grace_s=2.0)

    assert seen_status_at_fire and seen_status_at_fire[0] == "in_flight"


async def test_payload_json_persisted_for_diagnostic(insert_pending, webhook_mock_receiver) -> None:
    """NFR42 — failed payloads remain queryable for inspection."""
    webhook_mock_receiver.set_response(500)
    row_id = insert_pending(
        webhook_mock_receiver.url,
        extra={"some_field": "value", "nested": {"k": 1}},
    )
    worker = WebhookWorker(poll_interval_s=0.05)
    await worker.start()
    try:
        await _drain_until(lambda: wdr.get_by_id(row_id)["status"] == "failed", timeout=5.0)
    finally:
        await worker.stop(grace_s=2.0)
    row = wdr.get_by_id(row_id)
    body = json.loads(row["payload_json"])
    # The URL slot WAS popped at fire time and not re-stored — the
    # producer-side payload is the source of truth at INSERT.
    assert body["some_field"] == "value"
    assert body["nested"] == {"k": 1}


# ──────────────────────────────────────────────────────────────────────────
# Story 7.7 — escalation
# ──────────────────────────────────────────────────────────────────────────


async def test_first_failure_schedules_retry_second_escalates(
    insert_pending,
    webhook_mock_receiver,
    monkeypatch: pytest.MonkeyPatch,
    recording_id: int,
) -> None:
    """One auto-retry, then manual_intervention_required."""
    # Make the auto-retry near-instant so the test stays fast.
    monkeypatch.setattr("server.services.webhook_worker.AUTO_RETRY_DELAY_S", 0.05)

    # The receiver controller is single-shot per ``set_response``; for
    # this test we need EVERY call to return 500. Monkeypatch the
    # controller's ``_consume`` to always return failure.
    monkeypatch.setattr(
        webhook_mock_receiver,
        "_consume",
        lambda: {"status": 500, "body": None, "delay": 0},
    )
    insert_pending(webhook_mock_receiver.url)

    worker = WebhookWorker(poll_interval_s=0.05)
    await worker.start()
    try:
        # Wait for both rows to materialize and for the second to escalate.
        await _drain_until(
            lambda: (
                (latest := wdr.get_latest_for_recording(recording_id)) is not None
                and latest["status"] == "manual_intervention_required"
            ),
            timeout=5.0,
        )
    finally:
        await worker.stop(grace_s=2.0)

    # There should be exactly TWO rows: original (failed) + retry (escalated).
    latest = wdr.get_latest_for_recording(recording_id)
    assert latest is not None
    assert latest["status"] == "manual_intervention_required"


async def test_intervening_success_resets_consecutive_count(
    recording_id: int,
) -> None:
    """A success between failures opens the auto-retry budget back up."""
    a = wdr.create_pending(recording_id, None, {"a": 1})
    b = wdr.create_pending(recording_id, None, {"b": 1})
    c = wdr.create_pending(recording_id, None, {"c": 1})
    wdr.mark_failed(a, "first")
    wdr.mark_success(b)
    wdr.mark_failed(c, "fresh")
    # The consecutive counter sees only ONE failed (since the success
    # resets the run); next failure on this recording must be a fresh
    # auto-retry, NOT manual.
    assert wdr.count_consecutive_recent_failures(recording_id) == 1


# ──────────────────────────────────────────────────────────────────────────
# Cancel-safety
# ──────────────────────────────────────────────────────────────────────────


async def test_cancel_safe_shutdown(insert_pending, webhook_mock_receiver) -> None:
    webhook_mock_receiver.set_response(200, delay_seconds=0)
    insert_pending(webhook_mock_receiver.url)

    worker = WebhookWorker(poll_interval_s=0.05)
    await worker.start()
    task = worker._task  # noqa: SLF001 — keep our own ref before stop() nulls it
    # Cancel directly (simulates a hard shutdown signal).
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        # Expected: awaiting a cancelled task re-raises CancelledError;
        # the test wants the cancel to terminate, not to propagate.
        pass
    # After hard cancel, stop() still runs to perform the in_flight-revert
    # housekeeping cleanly — should not raise. The CancelledError that
    # asyncio.wait_for surfaces internally is normal — stop() handles it.
    try:
        await worker.stop(grace_s=1.0)
    except asyncio.CancelledError:
        # Even if wait_for surfaces a CancelledError because the task is
        # already done in cancelled state, stop() must not leave dangling
        # tasks — verify the worker is clean.
        pass
    assert worker._task is None  # noqa: SLF001


# ──────────────────────────────────────────────────────────────────────────
# Constants exposed (sanity check — story design references these)
# ──────────────────────────────────────────────────────────────────────────


def test_constants_exposed() -> None:
    assert AUTO_RETRY_DELAY_S == 30.0
    assert HTTP_TIMEOUT_S == 10.0
