"""Deferred-export sweeper (Issue #104, Story 6.8 / R-EL12 / NFR20).

Periodically scans rows where ``auto_export_status`` is ``deferred`` or
``retry_pending`` and re-fires the action when the destination becomes
available. Runs as a background asyncio.Task; canceled cleanly on
shutdown (CLAUDE.md project-context — never silent ``pass``).

Bootstrap-safe (NFR24a): on startup the sweeper picks up rows that
survived a restart — no in-memory state is required.

The sweeper interval is configurable via
``config.auto_actions.deferred_export_sweep_interval_s`` (default 30s in
production, much shorter in tests via fixture override).

Modeled on ``database/audio_cleanup.py::periodic_cleanup`` for the
async-loop scaffold + cancellation discipline.
"""

from __future__ import annotations

import asyncio
import logging
import os

from server.core.auto_action_coordinator import retry_auto_action_internal
from server.database import auto_action_repository as repo

logger = logging.getLogger(__name__)


DEFAULT_SWEEP_INTERVAL_S: float = 30.0


async def periodic_deferred_export_sweep(
    interval_s: float = DEFAULT_SWEEP_INTERVAL_S,
) -> None:
    """Run ``_sweep_once`` on a repeating schedule until cancelled.

    Never raises — exceptions inside a sweep are logged and the loop
    continues. ``asyncio.CancelledError`` exits cleanly.
    """
    if interval_s <= 0:
        logger.info("Periodic deferred-export sweep disabled (interval_s=%.3f)", interval_s)
        return

    logger.info("Periodic deferred-export sweep armed (every %.1fs)", interval_s)
    while True:
        try:
            await _sweep_once()
        except Exception:  # noqa: BLE001 — best-effort sweeper, never crash the loop
            logger.exception("deferred-export sweep iteration failed; will retry next interval")
        try:
            await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            logger.info("Periodic deferred-export sweep cancelled (shutdown)")
            return


async def _sweep_once() -> None:
    """One pass over actionable rows. Re-fires when destination is back."""
    rows = await asyncio.to_thread(repo.list_pending_auto_actions)
    if not rows:
        logger.debug("deferred-export sweep: no actionable rows")
        return
    logger.debug("deferred-export sweep: %d actionable row(s)", len(rows))

    for row in rows:
        rec_id = int(row["id"])
        export_status = row["auto_export_status"]
        summary_status = row["auto_summary_status"]

        # Auto-export: re-fire when destination is back.
        if export_status in {"deferred", "retry_pending"}:
            destination = row["auto_export_path"] or ""
            if destination and os.path.isdir(destination):
                logger.info(
                    "deferred-export sweep: re-firing auto_export for recording %d "
                    "(destination %s came back online)",
                    rec_id,
                    destination,
                )
                await retry_auto_action_internal(rec_id, "auto_export")

        # Auto-summary: re-fire on retry_pending (Story 6.11). 'failed'
        # rows are retried only via the user's manual retry — sweeper
        # never auto-retries 'failed' to avoid retry storms.
        if summary_status == "retry_pending":
            logger.info(
                "deferred-export sweep: re-firing auto_summary for recording %d (retry_pending)",
                rec_id,
            )
            await retry_auto_action_internal(rec_id, "auto_summary")
