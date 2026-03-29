"""
Audio cleanup module for transcription durability (Wave 2).

Deletes raw audio files for completed+delivered transcription jobs that are
older than the configured retention window. The job DB row is always kept —
it records that a transcription happened. Only the audio file is removed.

Never deletes audio for failed or undelivered jobs.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


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
        jobs = get_jobs_for_cleanup(max_age_days)
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
