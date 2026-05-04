"""WebhookWorker — singleton background dispatcher for webhook deliveries.

(Issue #104, Sprint 5: Stories 7.3 + 7.4 + 7.5 + 7.6 + 7.7)

The worker is the single delivery surface for every row in
``webhook_deliveries``. Producers (auto-action coordinator, retry
endpoint) only INSERT rows at status='pending'; the worker handles the
HTTP fire, the status transitions, and the retry escalation.

This split is deliberate:

  * Crash-recovered rows go through the SAME path as fresh ones — no
    "first call vs retry call" code duplication. The bootstrap sweep
    just calls ``list_pending`` which returns both 'pending' and
    'in_flight' (the latter recovered from a process death mid-call).

  * Producers do not block on HTTP — the worker decouples the
    completion path from external endpoint latency.

Lifecycle (Story 7.3 AC2):

  * ``await worker.start()``  in FastAPI lifespan startup
  * ``await worker.stop(grace_s=30.0)``  in lifespan shutdown — drains
    in-flight, then reverts any leftover 'in_flight' rows back to
    'pending' so the next start picks them up.

Delivery contract (Story 7.4 / FR45 / NFR5 / NFR11 / NFR12 / R-EL26):

  * 10s total timeout
  * No redirect following
  * No response-body decompression
  * 2xx → success; everything else → failed
  * Body bytes are read but never inflated; only ``status_code`` is
    consulted

Persist-Before-Deliver (Story 7.5 / NFR16 / NFR17 / R-EL33):

  * Row exists at status='pending' BEFORE the worker dequeues it
  * Status flips to 'in_flight' (committed) BEFORE the HTTP fire
  * Status flips to 'success'/'failed' AFTER the response (committed)

Escalation (Story 7.7 AC2 / R-EL18):

  * First failure → schedule a 30s-delayed re-INSERT into pending
  * Second consecutive failure on the SAME recording → status flips to
    ``manual_intervention_required`` instead of being re-queued
  * A 'success' between failures resets the consecutive counter

The worker is a single-instance-per-process. The deployment is
single-container Docker so this is sufficient; if the deployment ever
fans out to multiple replicas, an advisory-lock or claim-token column
would be needed to prevent two workers from racing on the same row.
That's documented as an out-of-sprint observation in
``sprint-5-design.md`` §6.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from server.core.webhook_url_validation import (
    WebhookUrlValidationError,
    validate_webhook_url,
)
from server.database import webhook_deliveries_repository as wdr

logger = logging.getLogger(__name__)


# Auto-retry budget (Story 7.7 AC2 — mirrors Story 6.11 escalation policy).
# First failure schedules ONE delayed retry (30s) then escalates if the
# retry also fails. Counted across rows since each attempt is a fresh row.
MAX_AUTO_RETRIES: int = 1
AUTO_RETRY_DELAY_S: float = 30.0

# Worker tick — how often the queue is drained when there is no incoming
# work signal. Producer notify_new_delivery() shortcuts this for fresh
# events; the timeout floor caps the maximum latency of a sweeper-style
# recovery (e.g. an in_flight row left behind after a crash).
DEFAULT_POLL_INTERVAL_S: float = 5.0

# Per-call HTTP deadline (Story 7.4 AC1 / FR45 / NFR5 / R-EL26).
HTTP_TIMEOUT_S: float = 10.0


class WebhookWorker:
    """Singleton worker — start once at app startup, stop once at shutdown.

    Tests can construct their own instance and call ``start``/``stop``
    directly — there is no hidden global state inside an instance.
    The module-level ``get_worker()`` is just a convenience for the
    lifespan + producer code; tests that want isolation should NOT
    use it.
    """

    def __init__(self, *, poll_interval_s: float = DEFAULT_POLL_INTERVAL_S) -> None:
        self._poll_interval = poll_interval_s
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._wake_event: asyncio.Event | None = None
        # Tasks created from inside the worker (delayed-retry sleeps).
        # We keep a reference so they can be cancelled on stop() — but
        # they are also cancel-safe individually.
        self._retry_tasks: set[asyncio.Task] = set()

    # ──────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        # Lazily construct events here so they bind to the running loop.
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._task = asyncio.create_task(self._run())
        logger.info("WebhookWorker started (poll=%.1fs)", self._poll_interval)

    async def stop(self, grace_s: float = 30.0) -> None:
        if self._task is None:
            return
        assert self._stop_event is not None and self._wake_event is not None
        self._stop_event.set()
        self._wake_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=grace_s)
        except TimeoutError:
            logger.warning("WebhookWorker stop timed out (%.1fs); cancelling", grace_s)
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.debug("WebhookWorker task cancelled after timeout")
        except asyncio.CancelledError:
            # The task was cancelled before stop() was invoked — that's
            # a valid shutdown sequence (e.g. hard-cancel followed by
            # cleanup). Treat it the same as a clean exit.
            logger.debug("WebhookWorker stop saw pre-cancelled task; proceeding to housekeeping")
        finally:
            # Cancel any pending delayed-retry tasks. These are cancel-safe;
            # the row stays at 'failed' / 'manual_intervention_required'
            # depending on what was already committed.
            for task in list(self._retry_tasks):
                if not task.done():
                    task.cancel()
            self._retry_tasks.clear()
            self._task = None
            self._stop_event = None
            self._wake_event = None
            # Story 7.3 AC5 — sweep any 'in_flight' rows back to 'pending'
            # so the next process start picks them up cleanly. Without
            # this, a row that was in flight when stop() was called could
            # stay marked in_flight indefinitely (the bootstrap sweep
            # would still rescue it via list_pending, but explicit
            # requeue avoids the ambiguity).
            #
            # ``asyncio.shield`` protects the revert against cancellation
            # of stop() itself — e.g., the lifespan task is being torn
            # down hard. Without shield, a CancelledError during the
            # ``asyncio.to_thread`` await would silently skip the revert
            # and the row would stay 'in_flight' until the next bootstrap
            # sweep rescued it.
            try:
                reverted = await asyncio.shield(asyncio.to_thread(wdr.requeue_in_flight_to_pending))
                if reverted:
                    logger.info(
                        "WebhookWorker.stop: reverted %d in_flight row(s) → pending",
                        reverted,
                    )
            except asyncio.CancelledError:
                # Shield can still surface CancelledError if the awaiter
                # was cancelled before the inner task started. Bootstrap
                # sweep will rescue any in_flight rows on next start —
                # documented invariant — so we treat this as best-effort.
                logger.debug("WebhookWorker.stop: revert cancelled; bootstrap sweep will rescue")
                raise
            except Exception:
                logger.exception("requeue_in_flight_to_pending failed during stop")

    def notify_new_delivery(self) -> None:
        """Producer hook — called by the coordinator / retry endpoint after
        ``create_pending``. Wakes the worker's poll loop immediately so the
        new row goes out without waiting for the next tick.

        Safe to call when the worker is not running (no-op).
        """
        if self._wake_event is not None:
            self._wake_event.set()

    # ──────────────────────────────────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        assert self._stop_event is not None and self._wake_event is not None
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception:
                logger.exception("WebhookWorker tick failed; will retry next interval")
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=self._poll_interval)
                self._wake_event.clear()
            except TimeoutError:
                # Expected: no wake_event during the poll interval — fall through
                # to the next iteration so the queue is drained on schedule.
                pass
            except asyncio.CancelledError:
                logger.debug("WebhookWorker run cancelled (shutdown)")
                return

    async def _tick(self) -> None:
        """Drain everything currently 'pending' or 'in_flight'."""
        rows = await asyncio.to_thread(wdr.list_pending)
        for row in rows:
            if self._stop_event is not None and self._stop_event.is_set():
                return
            try:
                await self._deliver_one(row)
            except Exception:
                # Defensive — _deliver_one handles its own failures, but
                # one bad row must not stop the queue.
                logger.exception(
                    "WebhookWorker _deliver_one raised on row %s",
                    row["id"],
                )

    # ──────────────────────────────────────────────────────────────────────
    # Single-row delivery (Persist-Before-Deliver discipline + contract)
    # ──────────────────────────────────────────────────────────────────────

    async def _deliver_one(self, row: Any) -> None:
        row_id: int = row["id"]
        recording_id: int = row["recording_id"]

        try:
            payload = json.loads(row["payload_json"])
        except Exception:
            # Stored payload is corrupted — terminal; cannot recover.
            logger.exception("webhook row %d has unparsable payload_json; marking failed", row_id)
            await asyncio.to_thread(wdr.mark_failed, row_id, "payload_json_unparsable")
            return

        url = self._extract_url_from_payload(payload, row_id)
        if url is None:
            await asyncio.to_thread(wdr.mark_failed, row_id, "no_url_in_payload")
            return

        # TOCTOU re-check (Story 7.2 AC3) — a hostname's A record can
        # change between profile-save and delivery. Re-resolve.
        try:
            validate_webhook_url(url)
        except WebhookUrlValidationError as exc:
            logger.warning(
                "webhook URL validation failed at delivery time: row=%d code=%s",
                row_id,
                exc.code,
            )
            await self._handle_failure(row_id, recording_id, f"url_validation_failed: {exc.code}")
            return

        # Persist-Before-Deliver — the in_flight transition commits BEFORE
        # the HTTP call. A crash here leaves the row at in_flight; the
        # bootstrap sweep on next start re-runs this same path (which
        # will call mark_in_flight again — idempotent — and re-fire).
        await asyncio.to_thread(wdr.mark_in_flight, row_id)

        # Build outgoing headers — the auth token (if any) lives in the
        # payload-time-frozen ``__auth_header__`` slot if the producer
        # baked one in. We strip it from the JSON body before POSTing
        # so the receiver doesn't see a duplicate.
        auth_header = payload.pop("__auth_header__", None)
        outgoing: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",  # NFR12 — no decompression
        }
        if isinstance(auth_header, str) and auth_header:
            outgoing["Authorization"] = auth_header

        # The HTTP fire (Story 7.4)
        try:
            status_code = await self._http_post_with_contract(url, payload, outgoing)
        except httpx.TimeoutException:
            await self._handle_failure(row_id, recording_id, "timeout")
            return
        except httpx.RequestError as exc:
            await self._handle_failure(row_id, recording_id, f"transport: {type(exc).__name__}")
            return
        except Exception as exc:
            # Defensive — anything httpx might raise that we missed.
            logger.exception("unexpected error during webhook fire")
            await self._handle_failure(row_id, recording_id, f"unexpected: {type(exc).__name__}")
            return

        if 200 <= status_code < 300:
            await asyncio.to_thread(wdr.mark_success, row_id)
            logger.info(
                "webhook delivered: row=%d recording=%d status=%d",
                row_id,
                recording_id,
                status_code,
            )
        else:
            # 3xx is treated as failure (Story 7.4 AC2 — no redirect-following).
            # 4xx and 5xx all map to failed; receiver-side retries are out
            # of scope for v1 (no Idempotency-Key header).
            await self._handle_failure(row_id, recording_id, f"http_{status_code}")

    @staticmethod
    def _extract_url_from_payload(payload: Any, row_id: int) -> str | None:
        """The producer stores ``__webhook_url__`` alongside the public body.

        Storing the URL inside the payload (rather than reading it from
        the live profile at fire-time) is a deliberate "no drift" choice:
        if the user edits the profile between INSERT and fire, the
        original URL still goes out. Same for the auth header. Both are
        stripped from the body before POST so the receiver only sees
        the public payload.
        """
        if not isinstance(payload, dict):
            logger.warning(
                "webhook row %d payload is not a dict (type=%s)",
                row_id,
                type(payload).__name__,
            )
            return None
        url = payload.pop("__webhook_url__", None)
        return url if isinstance(url, str) and url else None

    @staticmethod
    async def _http_post_with_contract(url: str, payload: dict, headers: dict[str, str]) -> int:
        """POST under the security contract. Returns status_code only.

        The body is OPAQUE (FR45 AC4) — never parsed, decoded, or
        decompressed. ``Accept-Encoding: identity`` tells the server
        not to compress the response, but even if it does anyway, we
        only access ``response.status_code``.
        """
        timeout = httpx.Timeout(HTTP_TIMEOUT_S)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.post(url, json=payload, headers=headers)
            return response.status_code

    # ──────────────────────────────────────────────────────────────────────
    # Failure / escalation (Story 7.7 AC2)
    # ──────────────────────────────────────────────────────────────────────

    async def _handle_failure(self, row_id: int, recording_id: int, error: str) -> None:
        """Two-strikes escalation: count consecutive recent failures for
        this recording. If we're at the budget already, mark the row
        terminal (manual_intervention_required); otherwise mark it
        failed and schedule a delayed re-queue.
        """
        consecutive = await asyncio.to_thread(wdr.count_consecutive_recent_failures, recording_id)
        # The current row hasn't yet been marked failed, so `consecutive`
        # represents the count BEFORE this attempt. Once we mark this
        # one failed, the new count is `consecutive + 1`. We escalate
        # when `consecutive >= MAX_AUTO_RETRIES` (i.e. one prior failure
        # already used the auto-retry budget).
        if consecutive >= MAX_AUTO_RETRIES:
            await asyncio.to_thread(wdr.mark_manual_intervention, row_id, error)
            logger.warning(
                "webhook escalated to manual_intervention_required: "
                "recording=%d consecutive_failures=%d row=%d error=%s",
                recording_id,
                consecutive + 1,
                row_id,
                error,
            )
            return
        await asyncio.to_thread(wdr.mark_failed, row_id, error)
        logger.info(
            "webhook attempt failed: recording=%d row=%d error=%s (scheduling auto-retry in %.1fs)",
            recording_id,
            row_id,
            error,
            AUTO_RETRY_DELAY_S,
        )
        task = asyncio.create_task(self._delayed_requeue(recording_id, AUTO_RETRY_DELAY_S))
        self._retry_tasks.add(task)
        task.add_done_callback(self._retry_tasks.discard)

    async def _delayed_requeue(self, recording_id: int, delay_s: float) -> None:
        """Sleep, then INSERT a fresh pending row from the failed payload.

        Cancel-safe: if cancelled mid-sleep (server shutdown), no row is
        inserted and the user can manual-retry via the badge later. The
        already-failed row stays at 'failed' so the badge surfaces it.
        """
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            return
        try:
            new_id = await asyncio.to_thread(wdr.requeue_failed_row, recording_id)
            if new_id is not None:
                logger.info(
                    "webhook auto-retry queued: recording=%d new_row=%d",
                    recording_id,
                    new_id,
                )
                self.notify_new_delivery()
        except Exception:
            logger.exception("delayed_requeue failed for recording=%d", recording_id)


# ──────────────────────────────────────────────────────────────────────────
# Module-level singleton accessor (used by lifespan + producer)
# ──────────────────────────────────────────────────────────────────────────

_instance: WebhookWorker | None = None


def get_worker() -> WebhookWorker:
    """Return the process-wide singleton worker (creating on first call).

    The lifespan handler calls ``await get_worker().start()`` once;
    producers call ``get_worker().notify_new_delivery()`` after INSERT.
    Tests should construct their own ``WebhookWorker(...)`` instance
    instead of calling this — using the singleton makes test isolation
    fragile.
    """
    global _instance
    if _instance is None:
        _instance = WebhookWorker()
    return _instance


def _reset_singleton_for_test() -> None:
    """Test helper — drops the cached singleton. Use only from tests."""
    global _instance
    _instance = None


__all__ = (
    "MAX_AUTO_RETRIES",
    "AUTO_RETRY_DELAY_S",
    "DEFAULT_POLL_INTERVAL_S",
    "HTTP_TIMEOUT_S",
    "WebhookWorker",
    "get_worker",
)
