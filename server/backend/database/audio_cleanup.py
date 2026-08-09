"""
Audio cleanup module for transcription durability (Wave 2) and session
ephemeral retention (2026-08-09 spec).

For non-session jobs (e.g. source='audio_upload'): deletes only the raw audio
file of completed+delivered jobs older than the retention window — the DB row
is kept as a record that a transcription happened.

For session-source jobs ('websocket', 'file_import'): the backstop passes also
delete the DB ROW — the Session tab is ephemeral, and rows here only survive
their immediate post-delivery purge after a crash. Aged failed file_import
rows (which never have audio, so nothing is retryable) are purged too.

Never deletes audio for failed or undelivered jobs, and never touches failed
mic ('websocket') rows — their WAV is what makes /retry possible.
"""

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def periodic_cleanup(
    recordings_dir: str, max_age_days: int, interval_hours: int = 24
) -> None:
    """Run cleanup_old_recordings on a repeating schedule.

    First run executes immediately (preserving startup cleanup behavior).
    Subsequent runs repeat every *interval_hours*.  If *interval_hours* <= 0,
    runs once and returns (backwards-compatible one-shot mode).

    Designed to be launched via ``asyncio.create_task`` and cancelled on
    shutdown via ``task.cancel()``.
    """
    # Always run once immediately
    try:
        await cleanup_old_recordings(recordings_dir, max_age_days)
    except Exception:
        logger.exception("Initial audio cleanup failed — periodic retries will continue")

    if interval_hours <= 0:
        logger.info("Periodic audio cleanup disabled (interval_hours=%d)", interval_hours)
        return

    interval_seconds = interval_hours * 3600
    logger.info(
        "Periodic audio cleanup armed (every %dh, retention=%dd)", interval_hours, max_age_days
    )

    while True:
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("Periodic audio cleanup cancelled (shutdown)")
            return
        try:
            await cleanup_old_recordings(recordings_dir, max_age_days)
        except Exception:
            logger.exception("Periodic audio cleanup failed — will retry next interval")


async def cleanup_old_recordings(recordings_dir: str, max_age_days: int) -> None:
    """Delete audio files for completed+delivered jobs older than max_age_days.

    Args:
        recordings_dir: Directory where audio files are stored (for logging only —
            actual paths come from the audio_path column in the DB).
        max_age_days: Retention window in days. Pass 0 to skip cleanup entirely
            (keep forever).
    """
    if max_age_days <= 0:
        logger.info(
            "Audio cleanup skipped (audio_retention_days=%d — keeping forever)", max_age_days
        )
        return

    from .job_repository import (
        delete_job,
        get_jobs_for_cleanup,
        get_purgeable_session_jobs,
        get_stale_failed_imports,
    )

    deleted = 0
    skipped = 0
    try:
        jobs = await asyncio.to_thread(get_jobs_for_cleanup, max_age_days)
    except Exception as exc:
        logger.error("Audio cleanup: failed to query expired jobs: %s", exc)
        jobs = []

    if not jobs:
        logger.debug(
            "Audio cleanup: no expired recordings found (older than %d days)", max_age_days
        )

    for job in jobs:
        audio_path = job.get("audio_path")
        if not audio_path:
            continue
        try:
            Path(audio_path).unlink(missing_ok=True)
            deleted += 1
            logger.debug("Deleted expired audio: %s (job %.8s)", audio_path, job["id"])
        except Exception as exc:
            logger.warning("Failed to delete audio file %s: %s", audio_path, exc)
            skipped += 1

    # Session ephemeral retention backstops. Immediate purge normally removes
    # session rows at delivery time; these passes only catch crash-window
    # stragglers and failed imports whose client never polled the error.
    purged_rows = 0
    try:
        stragglers = await asyncio.to_thread(get_purgeable_session_jobs, max_age_days)
        stale_imports = await asyncio.to_thread(get_stale_failed_imports, max_age_days)
        for job in [*stragglers, *stale_imports]:
            await asyncio.to_thread(delete_job, job["id"])
            purged_rows += 1
    except Exception:
        logger.exception("Audio cleanup: session-row backstop purge failed")

    logger.info(
        "Audio cleanup complete: %d file(s) deleted, %d skipped, %d session row(s) purged "
        "(retention=%d days, dir=%s)",
        deleted,
        skipped,
        purged_rows,
        max_age_days,
        recordings_dir,
    )


async def purge_legacy_session_rows() -> None:
    """One-time startup migration for session ephemeral retention.

    Purges rows accumulated under the old lifecycle: bare /import dedup
    anchors (the rows behind the duplicate dialog) and already-delivered
    session rows. Anything failed or undelivered with content is untouched.
    Safe to run every startup — once drained it finds nothing.
    """
    from .job_repository import delete_job, get_legacy_session_rows

    total = 0
    while True:
        try:
            rows = await asyncio.to_thread(get_legacy_session_rows)
        except Exception:
            logger.exception("Legacy session-row purge: query failed")
            return
        if not rows:
            break
        for row in rows:
            await asyncio.to_thread(delete_job, row["id"])
        total += len(rows)
        if len(rows) < 1000:  # last page
            break
    if total:
        logger.info("Legacy session-row purge: %d row(s) removed", total)
