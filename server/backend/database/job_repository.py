"""
Job repository for transcription durability (Wave 1).

Provides CRUD operations for the transcription_jobs table.
"""

import logging
from datetime import UTC, datetime

from server.logging import sanitize_log_value

from .database import get_connection
from .profile_repository import snapshot_profile_at_job_start

# Adapted from Scriberr (https://github.com/rishikanthc/Scriberr) — job model structure:
# id, status, audio_path, result, error_message, timestamps pattern.
# State machine: processing → completed | failed.

logger = logging.getLogger(__name__)


def create_job(
    job_id: str,
    source: str,
    client_name: str | None,
    language: str | None,
    task: str,
    translation_target: str | None,
    profile_id: int | None = None,
    audio_hash: str | None = None,
    normalized_audio_hash: str | None = None,
) -> None:
    """Insert a new job row with status='processing'. Called at transcription start.

    Uses INSERT OR IGNORE so duplicate calls are safe.

    When ``profile_id`` is provided, snapshots the profile via
    :func:`profile_repository.snapshot_profile_at_job_start` and writes the
    frozen JSON dump + schema version into the row (FR18). The snapshot is
    immutable for the lifetime of the job — concurrent profile edits cannot
    affect a running transcription. If the profile is deleted between
    selection and job-start, the snapshot helper returns ``None`` and we
    insert without snapshot fields rather than failing the job.

    When ``audio_hash`` is provided (Issue #104, Story 2.2), it is written
    atomically with the row insert. The dedup-check endpoint (Story 2.4)
    queries against this column. Hash is computed by the caller — see
    ``server.core.audio_utils.sha256_streaming``.

    When ``normalized_audio_hash`` is provided (Sprint 2 carve-out — Item 3),
    it is also written atomically. This second hash matches the same audio
    content across format re-encodes (MP3 vs WAV vs M4A). NULL when
    normalization (ffmpeg) fails — the row still participates in raw
    audio_hash dedup. See ``audio_utils.compute_normalized_pcm_hash``.
    """
    snapshot_json: str | None = None
    snapshot_schema_version: str | None = None
    if profile_id is not None:
        snapshot = snapshot_profile_at_job_start(profile_id)
        if snapshot is not None:
            snapshot_json, snapshot_schema_version = snapshot
        else:
            logger.warning(
                "create_job: profile_id=%d not found at snapshot time — "
                "inserting job without profile snapshot",
                profile_id,
            )

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO transcription_jobs
                (id, status, source, client_name, language, task,
                 translation_target, job_profile_snapshot, snapshot_schema_version,
                 audio_hash, normalized_audio_hash)
            VALUES (?, 'processing', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                source,
                client_name,
                language,
                task,
                translation_target,
                snapshot_json,
                snapshot_schema_version,
                audio_hash,
                normalized_audio_hash,
            ),
        )
        conn.commit()


def find_by_audio_hash(
    audio_hash: str,
    limit: int = 10,
    normalized_audio_hash: str | None = None,
) -> list[dict]:
    """Return prior jobs whose raw or normalized hash matches.

    Used by the dedup-check endpoint to find re-imports of the same audio
    content. Returns most-recent-first. Per FR4 / R-EL23, the query operates
    only on the local SQLite DB — no outbound calls.

    Args:
        audio_hash: SHA-256 over the raw upload bytes (Story 2.2). May be
            empty to match only on ``normalized_audio_hash``.
        limit: Maximum rows to return.
        normalized_audio_hash: Optional SHA-256 over the normalized PCM
            rendering (Sprint 2 Item 3). When provided, the query OR's
            against the second column too — a row that matches on EITHER
            hash is returned. NULL columns (legacy rows) never match.
    """
    has_raw = bool(audio_hash)
    has_norm = bool(normalized_audio_hash)
    if not has_raw and not has_norm:
        return []

    where_parts: list[str] = []
    params: list[object] = []
    if has_raw:
        where_parts.append("audio_hash = ?")
        params.append(audio_hash)
    if has_norm:
        where_parts.append("normalized_audio_hash = ?")
        params.append(normalized_audio_hash)
    where_clause = " OR ".join(where_parts)
    params.append(limit)

    with get_connection() as conn:
        cursor = conn.execute(
            f"""
            SELECT id, source, client_name, created_at, completed_at,
                   result_text, audio_hash, normalized_audio_hash
            FROM transcription_jobs
            WHERE {where_clause}
            ORDER BY COALESCE(completed_at, created_at) DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [dict(row) for row in cursor.fetchall()]


def save_result(
    job_id: str,
    result_text: str,
    result_json: str,
    result_language: str | None,
    duration_seconds: float | None,
) -> None:
    """Set status='completed', write result fields, set completed_at.

    MUST be called BEFORE delivering the result to the client.
    Logs an error and re-raises on DB failure.
    """
    completed_at = datetime.now(UTC).isoformat()
    try:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE transcription_jobs
                SET status = 'completed',
                    result_text = ?,
                    result_json = ?,
                    result_language = ?,
                    duration_seconds = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (
                    result_text,
                    result_json,
                    result_language,
                    duration_seconds,
                    completed_at,
                    job_id,
                ),
            )
            conn.commit()
    except Exception:
        logger.error("Failed to save result for job %s", sanitize_log_value(job_id), exc_info=True)
        raise


def mark_delivered(job_id: str) -> None:
    """Set delivered=1. Called AFTER successful WebSocket or HTTP delivery."""
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE transcription_jobs SET delivered = 1 WHERE id = ?",
                (job_id,),
            )
            conn.commit()
    except Exception:
        logger.warning(
            "Failed to mark job %s as delivered", sanitize_log_value(job_id), exc_info=True
        )


def mark_failed(job_id: str, error_message: str) -> None:
    """Set status='failed', write error_message."""
    try:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE transcription_jobs
                SET status = 'failed',
                    error_message = ?
                WHERE id = ?
                """,
                (error_message, job_id),
            )
            conn.commit()
    except Exception:
        logger.warning(
            "Failed to mark job %s as failed: %s",
            sanitize_log_value(job_id),
            sanitize_log_value(error_message),
            exc_info=True,
        )


def get_job(job_id: str) -> dict | None:
    """Return job row as dict, or None if not found."""
    with get_connection() as conn:
        # get_connection already sets conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM transcription_jobs WHERE id = ?",
            (job_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)


def get_recent_undelivered(client_name: str, limit: int = 5) -> list[dict]:
    """Return completed jobs where delivered=0 for this client, newest first.

    Ordered by completed_at (when the result was ready), not created_at (when
    the job started). This correctly surfaces retried jobs that completed recently
    even if their original creation time was long ago.
    completed_at uses isoformat() format — see save_result() for details.
    """
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM transcription_jobs
            WHERE client_name = ?
              AND status = 'completed'
              AND delivered = 0
            ORDER BY completed_at DESC
            LIMIT ?
            """,
            (client_name, limit),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def set_audio_path(job_id: str, audio_path: str) -> None:
    """Set audio_path field. Populated by Wave 2 before transcription starts."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE transcription_jobs SET audio_path = ? WHERE id = ?",
            (audio_path, job_id),
        )
        conn.commit()


def set_audio_hash(
    job_id: str,
    audio_hash: str,
    normalized_audio_hash: str | None = None,
) -> None:
    """Set audio_hash (and optionally normalized_audio_hash) on an existing row
    (Issue #104, Story 2.2 + Sprint 2 Item 3).

    Used for the ``/audio`` HTTP endpoint where ``create_job`` runs before
    the upload tempfile exists; the hash is computed post-save and patched
    in. The /import endpoint passes the hash directly to ``create_job`` and
    does not call this function.

    When ``normalized_audio_hash`` is provided, it is written in the same
    UPDATE so the row reaches a fully-hashed state atomically. Pass None
    to skip the second column (the existing audio-only callers pre-Item 3
    keep working unchanged).
    """
    with get_connection() as conn:
        if normalized_audio_hash is None:
            conn.execute(
                "UPDATE transcription_jobs SET audio_hash = ? WHERE id = ?",
                (audio_hash, job_id),
            )
        else:
            conn.execute(
                """
                UPDATE transcription_jobs
                SET audio_hash = ?, normalized_audio_hash = ?
                WHERE id = ?
                """,
                (audio_hash, normalized_audio_hash, job_id),
            )
        conn.commit()


def reset_for_retry(job_id: str) -> None:
    """Reset a job to 'processing' state so it can be re-transcribed.

    Clears result fields and error_message. The audio_path is preserved
    so the retry can read the same file. ``created_at`` is intentionally
    NOT overwritten — the orphan sweep's ``is_busy()`` guard (item 39)
    protects active retries, while preserving the original timestamp for
    audit trails.
    """
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE transcription_jobs
            SET status = 'processing',
                error_message = NULL,
                completed_at = NULL,
                result_text = NULL,
                result_json = NULL,
                delivered = 0
            WHERE id = ?
            """,
            (job_id,),
        )
        conn.commit()


def get_orphaned_jobs(timeout_minutes: int) -> list[dict]:
    """Return jobs stuck in 'processing' that were created before the timeout cutoff.

    Orphaned jobs are those that started processing but never completed — typically
    because the server crashed or was restarted mid-transcription.

    Only returns jobs where created_at < (now - timeout_minutes) to avoid falsely
    orphaning jobs that are legitimately in progress on a fresh boot.
    """
    from datetime import timedelta

    # Use strftime to match SQLite's CURRENT_TIMESTAMP format ("YYYY-MM-DD HH:MM:SS").
    # isoformat() produces "T" separator and "+00:00" suffix which sorts differently
    # than the space-separated SQLite default, causing the query to match all rows.
    cutoff = (datetime.now(UTC) - timedelta(minutes=timeout_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM transcription_jobs
            WHERE status = 'processing'
              AND created_at < ?
            ORDER BY created_at ASC
            """,
            (cutoff,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_jobs_for_cleanup(max_age_days: int, limit: int = 100) -> list[dict]:
    """Return completed+delivered jobs with audio_path older than max_age_days.

    Only returns rows where status='completed', delivered=1, audio_path is set,
    and completed_at is older than the cutoff. Used by the cleanup task to find
    audio files safe to delete.

    Note: completed_at is written by save_result() using isoformat() (T-separator,
    UTC offset), so the cutoff must also use isoformat() for correct lexicographic
    comparison. This differs from created_at (set by SQLite CURRENT_TIMESTAMP,
    space-separator) — do not use strftime() for this query.
    """
    from datetime import timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM transcription_jobs
            WHERE status = 'completed'
              AND delivered = 1
              AND audio_path IS NOT NULL
              AND completed_at < ?
            ORDER BY completed_at ASC
            LIMIT ?
            """,
            (cutoff, limit),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
