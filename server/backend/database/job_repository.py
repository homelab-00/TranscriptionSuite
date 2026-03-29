"""
Job repository for transcription durability (Wave 1).

Provides CRUD operations for the transcription_jobs table.
"""

import logging
from datetime import UTC, datetime

from .database import get_connection

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
) -> None:
    """Insert a new job row with status='processing'. Called at transcription start.

    Uses INSERT OR IGNORE so duplicate calls are safe.
    """
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO transcription_jobs
                (id, status, source, client_name, language, task, translation_target)
            VALUES (?, 'processing', ?, ?, ?, ?, ?)
            """,
            (job_id, source, client_name, language, task, translation_target),
        )
        conn.commit()


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
        logger.error("Failed to save result for job %s", job_id, exc_info=True)
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
        logger.warning("Failed to mark job %s as delivered", job_id, exc_info=True)


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
        logger.warning("Failed to mark job %s as failed: %s", job_id, error_message, exc_info=True)


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
    """Return completed jobs where delivered=0 for this client, newest first."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM transcription_jobs
            WHERE client_name = ?
              AND status = 'completed'
              AND delivered = 0
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (client_name, limit),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def set_audio_path(job_id: str, audio_path: str) -> None:
    """Set audio_path field. Stub for Wave 2 use."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE transcription_jobs SET audio_path = ? WHERE id = ?",
            (audio_path, job_id),
        )
        conn.commit()
