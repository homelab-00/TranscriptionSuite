"""Periodic webhook_deliveries retention cleanup (Issue #104, Story 7.7 AC3 / NFR40).

Mirrors :func:`server.database.audio_cleanup.periodic_cleanup` exactly:

  * First run executes immediately (preserving startup-cleanup behavior).
  * Subsequent runs repeat every ``interval_hours``.
  * If ``interval_hours <= 0``, runs once and returns (one-shot mode).

Designed to be launched via ``asyncio.create_task`` and cancelled on
shutdown via ``task.cancel()`` — the ``CancelledError`` exit drops
through cleanly without a stray exception.
"""

from __future__ import annotations

import asyncio
import logging

from server.database import webhook_deliveries_repository as wdr

logger = logging.getLogger(__name__)


async def periodic_webhook_cleanup(retention_days: int, interval_hours: int = 24) -> None:
    """Drop ``success`` / ``manual_intervention_required`` rows older than N days.

    Pending / in_flight / failed rows are NEVER cleaned (the worker
    is responsible for those, and failed rows remain queryable for
    diagnostic until a manual retry succeeds or escalates).
    """
    try:
        deleted = await asyncio.to_thread(wdr.cleanup_older_than, retention_days)
        if deleted:
            logger.info(
                "Initial webhook cleanup: deleted %d row(s) older than %dd",
                deleted,
                retention_days,
            )
    except Exception:
        logger.exception("Initial webhook cleanup failed — periodic retries will continue")

    if interval_hours <= 0:
        logger.info("Periodic webhook cleanup disabled (interval_hours=%d)", interval_hours)
        return

    interval_seconds = interval_hours * 3600
    logger.info(
        "Periodic webhook cleanup armed (every %dh, retention=%dd)",
        interval_hours,
        retention_days,
    )

    while True:
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("Periodic webhook cleanup cancelled (shutdown)")
            return
        try:
            deleted = await asyncio.to_thread(wdr.cleanup_older_than, retention_days)
            if deleted:
                logger.info("Periodic webhook cleanup: deleted %d row(s)", deleted)
        except Exception:
            logger.exception("Periodic webhook cleanup failed — will retry next interval")


__all__ = ("periodic_webhook_cleanup",)
