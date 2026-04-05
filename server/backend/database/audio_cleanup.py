"""
Audio cleanup module for transcription durability (Wave 2).

Deletes raw audio files for completed+delivered transcription jobs that are
older than the configured retention window. The job DB row is always kept —
it records that a transcription happened. Only the audio file is removed.

Never deletes audio for failed or undelivered jobs.
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

    from .job_repository import get_jobs_for_cleanup

    try:
        jobs = await asyncio.to_thread(get_jobs_for_cleanup, max_age_days)
    except Exception as exc:
        logger.error("Audio cleanup: failed to query expired jobs: %s", exc)
        return

    if not jobs:
        logger.debug(
            "Audio cleanup: no expired recordings found (older than %d days)", max_age_days
        )
        return

    deleted = 0
    skipped = 0
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

    logger.info(
        "Audio cleanup complete: %d file(s) deleted, %d skipped (retention=%d days, dir=%s)",
        deleted,
        skipped,
        max_age_days,
        recordings_dir,
    )
