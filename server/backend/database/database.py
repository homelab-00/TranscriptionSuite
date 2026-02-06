"""
SQLite database with FTS5 for full-text search of transcriptions.

Consolidated database layer for TranscriptionSuite server.
Handles:
- Recording metadata storage
- Segment and word storage with timestamps
- Full-text search with FTS5
- Conversation/chat history for LLM integration
"""

import logging
import os
import sqlite3
import subprocess
import tempfile
import wave
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Path to migrations directory
MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Default paths - can be overridden via environment or config
_data_dir: Optional[Path] = None
_db_path: Optional[Path] = None


def set_data_directory(path: Path) -> None:
    """Set the data directory for database and audio storage."""
    global _data_dir, _db_path
    _data_dir = path
    _db_path = path / "database" / "notebook.db"
    logger.info(f"Database data directory set to: {path}")


def get_data_dir() -> Path:
    """Get the data directory, creating if needed."""
    global _data_dir
    if _data_dir is None:
        # Check environment variable first
        env_data_dir = os.environ.get("DATA_DIR")
        if env_data_dir:
            _data_dir = Path(env_data_dir)
        else:
            # Default to project-relative path
            _data_dir = Path(__file__).parent.parent.parent / "data"

    _data_dir.mkdir(parents=True, exist_ok=True)
    return _data_dir


def get_db_path() -> Path:
    """Get database path, creating directories if needed."""
    global _db_path
    if _db_path is None:
        data_dir = get_data_dir()
        db_dir = data_dir / "database"
        db_dir.mkdir(parents=True, exist_ok=True)
        _db_path = db_dir / "notebook.db"
    return _db_path


def get_audio_dir() -> Path:
    """Get audio storage directory."""
    audio_dir = get_data_dir() / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Get a database connection with context manager.

    Connection is configured for multi-user safety:
    - 30 second timeout waiting for locks
    - 5 second busy timeout for retry on SQLITE_BUSY
    - Multi-thread support enabled
    """
    conn = sqlite3.connect(
        get_db_path(),
        timeout=30.0,  # Wait up to 30s for locks
        check_same_thread=False,  # Allow multi-thread access
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")  # 5s retry on SQLITE_BUSY
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_db_session() -> Generator[sqlite3.Connection, None, None]:
    """Alias for get_connection for API compatibility."""
    with get_connection() as conn:
        yield conn


def run_migrations() -> bool:
    """
    Run pending Alembic migrations.

    Returns:
        True if migrations ran successfully, False otherwise
    """
    try:
        from alembic import command
        from alembic.config import Config

        db_path = get_db_path()
        logger.info(f"Running database migrations for {db_path}")

        # Configure Alembic programmatically
        alembic_cfg = Config()
        alembic_cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

        # Upgrade to latest version
        command.upgrade(alembic_cfg, "head")

        logger.info("Database migrations completed successfully")
        return True

    except ImportError:
        logger.warning("Alembic not available - skipping migrations")
        return False
    except Exception as e:
        logger.error(f"Migration error: {e}", exc_info=True)
        return False


def _assert_schema_sanity(conn: sqlite3.Connection) -> None:
    """
    Validate that required tables/columns exist after migrations.

    Raises RuntimeError if the database schema is not compatible.
    """
    required_schema: dict[str, set[str]] = {
        "recordings": {
            "id",
            "filename",
            "filepath",
            "title",
            "duration_seconds",
            "recorded_at",
            "imported_at",
            "word_count",
            "has_diarization",
            "summary",
            "summary_model",
        },
        "segments": {
            "id",
            "recording_id",
            "segment_index",
            "speaker",
            "text",
            "start_time",
            "end_time",
        },
        "words": {
            "id",
            "recording_id",
            "segment_id",
            "word_index",
            "word",
            "start_time",
            "end_time",
            "confidence",
        },
        "conversations": {
            "id",
            "recording_id",
            "title",
            "created_at",
            "updated_at",
            "response_id",
        },
        "messages": {
            "id",
            "conversation_id",
            "role",
            "content",
            "created_at",
            "model",
            "tokens_used",
        },
    }
    required_virtual_tables = {"words_fts"}

    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}

    missing_tables = [name for name in required_schema if name not in tables]
    if missing_tables:
        raise RuntimeError(
            "Database schema validation failed; missing tables: "
            + ", ".join(sorted(missing_tables))
        )

    missing_virtual = [name for name in required_virtual_tables if name not in tables]
    if missing_virtual:
        raise RuntimeError(
            "Database schema validation failed; missing virtual tables: "
            + ", ".join(sorted(missing_virtual))
        )

    for table_name, required_columns in required_schema.items():
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in cursor.fetchall()}
        missing_columns = sorted(required_columns - existing_columns)
        if missing_columns:
            raise RuntimeError(
                f"Database schema validation failed; table '{table_name}' is missing "
                f"columns: {', '.join(missing_columns)}"
            )


def init_db() -> None:
    """Initialize database schema with FTS5 for word search.

    This function:
    1. Ensures the database directory exists
    2. Runs pending Alembic migrations
    3. Validates required schema objects exist
    4. Enables runtime SQLite pragmas (WAL, synchronous, FK)
    """
    logger.info(f"Initializing database at {get_db_path()}")

    # Migrations are required. Do not silently continue on failure.
    if not run_migrations():
        raise RuntimeError(
            "Database migration failed; refusing to start with potentially invalid schema"
        )

    with get_connection() as conn:
        _assert_schema_sanity(conn)

        cursor = conn.cursor()

        # Enable WAL mode for crash safety and concurrent access
        # WAL provides better concurrency and crash recovery than rollback journal
        cursor.execute("PRAGMA journal_mode=WAL")
        journal_mode = cursor.fetchone()[0]
        cursor.execute("PRAGMA synchronous=NORMAL")  # Good balance for WAL
        cursor.execute("PRAGMA foreign_keys=ON")  # Enforce FK constraints
        logger.info(f"Database initialized successfully (journal_mode={journal_mode})")


# =============================================================================
# Recording CRUD operations
# =============================================================================


class Recording:
    """Recording model class."""

    def __init__(self, data: Dict[str, Any]):
        self.id = data.get("id")
        self.filename = data.get("filename")
        self.filepath = data.get("filepath")
        self.title = data.get("title")
        self.duration_seconds = data.get("duration_seconds")
        self.recorded_at = data.get("recorded_at")
        self.imported_at = data.get("imported_at")
        self.word_count = data.get("word_count", 0)
        self.has_diarization = bool(data.get("has_diarization", 0))
        self.summary = data.get("summary")
        self.summary_model = data.get("summary_model")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "filename": self.filename,
            "filepath": self.filepath,
            "title": self.title,
            "duration_seconds": self.duration_seconds,
            "recorded_at": self.recorded_at,
            "imported_at": self.imported_at,
            "word_count": self.word_count,
            "has_diarization": self.has_diarization,
            "summary": self.summary,
            "summary_model": self.summary_model,
        }


def insert_recording(
    filename: str,
    filepath: str,
    duration_seconds: float,
    recorded_at: str,
    has_diarization: bool = False,
    title: Optional[str] = None,
) -> int:
    """Insert a new recording and return its ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        recording_title = title or filename
        cursor.execute(
            """
            INSERT INTO recordings (filename, filepath, title, duration_seconds, recorded_at, has_diarization)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                filename,
                filepath,
                recording_title,
                duration_seconds,
                recorded_at,
                int(has_diarization),
            ),
        )
        conn.commit()
        return cursor.lastrowid or 0


def get_recording(recording_id: int) -> Optional[Dict[str, Any]]:
    """Get a recording by ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_recordings() -> List[Dict[str, Any]]:
    """Get all recordings ordered by date."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM recordings ORDER BY recorded_at DESC")
        return [dict(row) for row in cursor.fetchall()]


def get_recordings_by_date_range(
    start_date: str, end_date: str
) -> List[Dict[str, Any]]:
    """Get recordings within a date range."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM recordings 
            WHERE date(recorded_at) BETWEEN date(?) AND date(?)
            ORDER BY recorded_at DESC
            """,
            (start_date, end_date),
        )
        return [dict(row) for row in cursor.fetchall()]


def delete_recording(recording_id: int) -> bool:
    """Delete a recording and all associated data."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
        conn.commit()
        return cursor.rowcount > 0


def update_recording_summary(
    recording_id: int,
    summary: Optional[str],
    summary_model: Optional[str] = None,
) -> bool:
    """Update the summary for a recording."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE recordings SET summary = ?, summary_model = ? WHERE id = ?",
            (summary, summary_model if summary else None, recording_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def update_recording_title(recording_id: int, title: str) -> bool:
    """Update the title for a recording."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE recordings SET title = ? WHERE id = ?",
            (title, recording_id),
        )
        conn.commit()
        return cursor.rowcount > 0


# =============================================================================
# Segment and Word operations
# =============================================================================


def insert_segment(
    recording_id: int,
    segment_index: int,
    text: str,
    start_time: float,
    end_time: float,
    speaker: Optional[str] = None,
) -> int:
    """Insert a segment and return its ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO segments (recording_id, segment_index, speaker, text, start_time, end_time)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (recording_id, segment_index, speaker, text, start_time, end_time),
        )
        conn.commit()
        return cursor.lastrowid or 0


def insert_word(
    recording_id: int,
    segment_id: int,
    word_index: int,
    word: str,
    start_time: float,
    end_time: float,
    confidence: Optional[float] = None,
) -> int:
    """Insert a word and return its ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO words (recording_id, segment_id, word_index, word, start_time, end_time, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recording_id,
                segment_id,
                word_index,
                word,
                start_time,
                end_time,
                confidence,
            ),
        )
        conn.commit()
        return cursor.lastrowid or 0


def insert_words_batch(words: List[Dict[str, Any]]) -> None:
    """Insert multiple words in a batch for efficiency."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany(
            """
            INSERT INTO words (recording_id, segment_id, word_index, word, start_time, end_time, confidence)
            VALUES (:recording_id, :segment_id, :word_index, :word, :start_time, :end_time, :confidence)
            """,
            words,
        )
        conn.commit()


def update_recording_word_count(recording_id: int) -> None:
    """Update the word count for a recording."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE recordings 
            SET word_count = (SELECT COUNT(*) FROM words WHERE recording_id = ?)
            WHERE id = ?
            """,
            (recording_id, recording_id),
        )
        conn.commit()


def get_segments(recording_id: int) -> List[Dict[str, Any]]:
    """Get all segments for a recording."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM segments WHERE recording_id = ? ORDER BY segment_index",
            (recording_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_words(recording_id: int) -> List[Dict[str, Any]]:
    """Get all words for a recording."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM words WHERE recording_id = ? ORDER BY start_time",
            (recording_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


# =============================================================================
# Search operations
# =============================================================================


def search_words(query: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Search words using FTS5."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT w.*, r.filename, r.title, r.recorded_at,
                   s.speaker, s.text AS context
            FROM words w
            JOIN words_fts ON w.id = words_fts.rowid
            JOIN recordings r ON w.recording_id = r.id
            LEFT JOIN segments s ON w.segment_id = s.id
            WHERE words_fts MATCH ?
            ORDER BY r.recorded_at DESC
            LIMIT ?
            """,
            (query, limit),
        )
        return [dict(row) for row in cursor.fetchall()]


def search_words_by_date_range(
    query: str,
    start_date: Optional[str],
    end_date: Optional[str],
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Search words using FTS5, optionally filtered by recording date."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT w.*, r.filename, r.title, r.recorded_at,
                   s.speaker, s.text AS context
            FROM words w
            JOIN words_fts ON w.id = words_fts.rowid
            JOIN recordings r ON w.recording_id = r.id
            LEFT JOIN segments s ON w.segment_id = s.id
            WHERE words_fts MATCH ?
              AND (? IS NULL OR date(r.recorded_at) >= date(?))
              AND (? IS NULL OR date(r.recorded_at) <= date(?))
            ORDER BY r.recorded_at DESC
            LIMIT ?
            """,
            (query, start_date, start_date, end_date, end_date, limit),
        )
        return [dict(row) for row in cursor.fetchall()]


def search_recording_metadata(
    query: str,
    start_date: Optional[str],
    end_date: Optional[str],
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Search recordings by filename/title/summary."""
    like_query = f"%{query}%"
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id AS recording_id, filename, title, recorded_at
            FROM recordings
            WHERE (filename LIKE ? OR title LIKE ?)
              AND (? IS NULL OR date(recorded_at) >= date(?))
              AND (? IS NULL OR date(recorded_at) <= date(?))
            ORDER BY recorded_at DESC
            LIMIT ?
            """,
            (like_query, like_query, start_date, start_date, end_date, end_date, limit),
        )
        filename_matches = [dict(row) for row in cursor.fetchall()]

        cursor.execute(
            """
            SELECT id AS recording_id, filename, title, recorded_at, summary
            FROM recordings
            WHERE summary IS NOT NULL
              AND summary != ''
              AND summary LIKE ?
              AND (? IS NULL OR date(recorded_at) >= date(?))
              AND (? IS NULL OR date(recorded_at) <= date(?))
            ORDER BY recorded_at DESC
            LIMIT ?
            """,
            (like_query, start_date, start_date, end_date, end_date, limit),
        )
        summary_matches = [dict(row) for row in cursor.fetchall()]

    return filename_matches + summary_matches


def search_recordings(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Search recordings by word content."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT r.*
            FROM recordings r
            JOIN words w ON r.id = w.recording_id
            JOIN words_fts ON w.id = words_fts.rowid
            WHERE words_fts MATCH ?
            ORDER BY r.recorded_at DESC
            LIMIT ?
            """,
            (query, limit),
        )
        return [dict(row) for row in cursor.fetchall()]


# =============================================================================
# Conversation operations (for LLM chat)
# =============================================================================


def create_conversation(recording_id: int, title: str = "New Chat") -> int:
    """Create a new conversation for a recording."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO conversations (recording_id, title)
            VALUES (?, ?)
            """,
            (recording_id, title),
        )
        conn.commit()
        return cursor.lastrowid or 0


def get_conversations(recording_id: int) -> List[Dict[str, Any]]:
    """Get all conversations for a recording."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM conversations 
            WHERE recording_id = ? 
            ORDER BY updated_at DESC
            """,
            (recording_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def add_message(
    conversation_id: int,
    role: str,
    content: str,
    model: Optional[str] = None,
    tokens_used: Optional[int] = None,
) -> int:
    """Add a message to a conversation."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO messages (conversation_id, role, content, model, tokens_used)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, role, content, model, tokens_used),
        )
        # Update conversation timestamp
        cursor.execute(
            "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (conversation_id,),
        )
        conn.commit()
        return cursor.lastrowid or 0


def get_messages(conversation_id: int) -> List[Dict[str, Any]]:
    """Get all messages in a conversation."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM messages 
            WHERE conversation_id = ? 
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def delete_conversation(conversation_id: int) -> bool:
    """Delete a conversation and all its messages."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        conn.commit()
        return cursor.rowcount > 0


def get_conversation(conversation_id: int) -> Optional[Dict[str, Any]]:
    """Get a conversation by ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def update_conversation_title(conversation_id: int, title: str) -> bool:
    """Update a conversation's title."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE conversations 
            SET title = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (title, conversation_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def update_conversation_response_id(
    conversation_id: int, response_id: Optional[str]
) -> bool:
    """Update a conversation's LM Studio response_id for stateful sessions."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE conversations 
            SET response_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (response_id, conversation_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_conversation_with_messages(conversation_id: int) -> Optional[Dict[str, Any]]:
    """Get a conversation with all its messages."""
    conversation = get_conversation(conversation_id)
    if conversation:
        conversation["messages"] = get_messages(conversation_id)
    return conversation


def delete_message(message_id: int) -> bool:
    """Delete a specific message."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.commit()
        return cursor.rowcount > 0


# =============================================================================
# Extended Recording operations
# =============================================================================


def get_recordings_for_month(year: int, month: int) -> List[Dict[str, Any]]:
    """Get recordings for a specific month."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM recordings 
            WHERE strftime('%Y', recorded_at) = ? AND strftime('%m', recorded_at) = ?
            ORDER BY recorded_at DESC
            """,
            (str(year), f"{month:02d}"),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_recordings_for_hour(date_str: str, hour: int) -> List[Dict[str, Any]]:
    """Get recordings for a specific date and hour, ordered by recorded_at."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM recordings 
            WHERE date(recorded_at) = date(?)
            AND CAST(strftime('%H', recorded_at) AS INTEGER) = ?
            ORDER BY recorded_at ASC
            """,
            (date_str, hour),
        )
        return [dict(row) for row in cursor.fetchall()]


def update_recording_date(recording_id: int, recorded_at: str) -> bool:
    """Update the recorded_at timestamp for a recording."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE recordings SET recorded_at = ? WHERE id = ?",
            (recorded_at, recording_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def check_time_slot_overlap(
    start_time: datetime,
    duration_seconds: float,
    exclude_recording_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Check if a recording would overlap with existing recordings.

    Args:
        start_time: Proposed start time for the new recording
        duration_seconds: Duration of the new recording in seconds
        exclude_recording_id: Optional recording ID to exclude (for updates)

    Returns:
        Dict with overlap info if conflict exists, None if no overlap
    """
    end_time = start_time.timestamp() + duration_seconds

    with get_connection() as conn:
        cursor = conn.cursor()

        # Find any recording that overlaps with the proposed time range
        # Overlap exists when: existing_start < new_end AND existing_end > new_start
        query = """
            SELECT id, filename, title, recorded_at, duration_seconds,
                   datetime(recorded_at, '+' || CAST(duration_seconds AS TEXT) || ' seconds') as end_at
            FROM recordings
            WHERE datetime(recorded_at) < datetime(?, 'unixepoch')
              AND datetime(recorded_at, '+' || CAST(duration_seconds AS TEXT) || ' seconds') > datetime(?, 'unixepoch')
        """
        params: List[Any] = [end_time, start_time.timestamp()]

        if exclude_recording_id:
            query += " AND id != ?"
            params.append(exclude_recording_id)

        query += " ORDER BY recorded_at ASC LIMIT 1"

        cursor.execute(query, params)
        row = cursor.fetchone()

        if row:
            return dict(row)
        return None


def get_next_available_start_time(
    target_date: str,
    hour: int,
) -> Optional[datetime]:
    """
    Get the next available start time for a given hour slot.

    If recordings exist in the slot, returns the next minute after the last
    recording ends. If the slot is full (would overflow to next hour),
    returns None.

    Args:
        target_date: Date string in YYYY-MM-DD format
        hour: Hour (0-23)

    Returns:
        datetime of next available start, or None if slot is full
    """
    # Get all recordings that START in this hour
    recordings = get_recordings_for_hour(target_date, hour)

    if not recordings:
        # No recordings in this hour, start at the beginning
        return datetime.fromisoformat(f"{target_date}T{hour:02d}:00:00")

    # Find the recording with the latest end time
    latest_end_timestamp = 0.0
    for rec in recordings:
        rec_start = datetime.fromisoformat(rec["recorded_at"].replace("Z", "+00:00"))
        rec_end_timestamp = rec_start.timestamp() + rec["duration_seconds"]
        if rec_end_timestamp > latest_end_timestamp:
            latest_end_timestamp = rec_end_timestamp

    # Also check recordings from PREVIOUS hours that might extend into this hour
    # by checking if any recording's end time falls within this hour
    with get_connection() as conn:
        cursor = conn.cursor()
        # Find recordings that end within this hour but started before it
        hour_start = datetime.fromisoformat(f"{target_date}T{hour:02d}:00:00")
        hour_end = datetime.fromisoformat(f"{target_date}T{hour:02d}:59:59")

        cursor.execute(
            """
            SELECT recorded_at, duration_seconds
            FROM recordings
            WHERE date(recorded_at) = date(?)
              AND CAST(strftime('%H', recorded_at) AS INTEGER) < ?
              AND datetime(recorded_at, '+' || CAST(duration_seconds AS TEXT) || ' seconds') > datetime(?)
            """,
            (target_date, hour, hour_start.isoformat()),
        )

        for row in cursor.fetchall():
            rec_start = datetime.fromisoformat(
                row["recorded_at"].replace("Z", "+00:00")
            )
            rec_end_timestamp = rec_start.timestamp() + row["duration_seconds"]
            if rec_end_timestamp > latest_end_timestamp:
                latest_end_timestamp = rec_end_timestamp

    if latest_end_timestamp == 0.0:
        # No recordings affect this hour
        return datetime.fromisoformat(f"{target_date}T{hour:02d}:00:00")

    # Round up to the next full minute
    latest_end = datetime.fromtimestamp(latest_end_timestamp)
    if latest_end.second > 0 or latest_end.microsecond > 0:
        # Round up to next minute
        next_start = latest_end.replace(second=0, microsecond=0)
        next_start = datetime.fromtimestamp(next_start.timestamp() + 60)
    else:
        next_start = latest_end

    # Check if next_start is still within this hour
    hour_boundary = (
        datetime.fromisoformat(f"{target_date}T{hour + 1:02d}:00:00")
        if hour < 23
        else datetime.fromisoformat(f"{target_date}T23:59:59")
    )

    if next_start >= hour_boundary:
        # Slot is full
        return None

    return next_start


def get_time_slot_info(target_date: str, hour: int) -> Dict[str, Any]:
    """
    Get information about a time slot including available time and existing recordings.

    Args:
        target_date: Date string in YYYY-MM-DD format
        hour: Hour (0-23)

    Returns:
        Dict with:
        - recordings: List of recordings in this slot
        - next_available: Next available start time (or None if full)
        - total_duration: Total duration of recordings in seconds
        - available_seconds: Remaining seconds available in the slot
    """
    recordings = get_recordings_for_hour(target_date, hour)
    next_available = get_next_available_start_time(target_date, hour)

    total_duration = sum(rec["duration_seconds"] for rec in recordings)

    # Calculate available time
    hour_start = datetime.fromisoformat(f"{target_date}T{hour:02d}:00:00")
    if next_available:
        used_seconds = (next_available - hour_start).total_seconds()
    else:
        used_seconds = 3600  # Full hour used

    available_seconds = max(0, 3600 - used_seconds)

    return {
        "recordings": recordings,
        "next_available": next_available.isoformat() if next_available else None,
        "total_duration": total_duration,
        "available_seconds": available_seconds,
        "is_full": next_available is None,
    }


def get_recording_summary(recording_id: int) -> Optional[str]:
    """Get the AI summary for a recording."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT summary FROM recordings WHERE id = ?", (recording_id,))
        row = cursor.fetchone()
        return row["summary"] if row else None


def get_transcription(recording_id: int) -> Dict[str, Any]:
    """Get full transcription with segments and words."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Get segments
        cursor.execute(
            "SELECT * FROM segments WHERE recording_id = ? ORDER BY segment_index",
            (recording_id,),
        )
        segments = [dict(row) for row in cursor.fetchall()]

        # Get all words for all segments in a single query using JOIN
        segment_ids = [seg["id"] for seg in segments]
        if segment_ids:
            # Use placeholders for IN clause
            placeholders = ",".join("?" * len(segment_ids))
            cursor.execute(
                f"""
                SELECT 
                    w.segment_id,
                    w.word,
                    w.start_time,
                    w.end_time,
                    w.confidence
                FROM words w
                WHERE w.segment_id IN ({placeholders})
                ORDER BY w.segment_id, w.word_index
                """,
                segment_ids,
            )

            # Group words by segment_id
            words_by_segment = {}
            for row in cursor.fetchall():
                segment_id = row["segment_id"]
                if segment_id not in words_by_segment:
                    words_by_segment[segment_id] = []
                words_by_segment[segment_id].append(
                    {
                        "word": row["word"],
                        "start": row["start_time"],
                        "end": row["end_time"],
                        "confidence": row["confidence"],
                    }
                )

            # Attach words to segments
            for segment in segments:
                segment["words"] = words_by_segment.get(segment["id"], [])
        else:
            # No segments, no words
            for segment in segments:
                segment["words"] = []

        return {
            "recording_id": recording_id,
            "segments": [
                {
                    "speaker": seg.get("speaker"),
                    "text": seg["text"],
                    "start": seg["start_time"],
                    "end": seg["end_time"],
                    "words": seg["words"],
                }
                for seg in segments
            ],
        }


# =============================================================================
# Enhanced Search operations
# =============================================================================


def search_words_enhanced(
    query: str,
    fuzzy: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Search for words in transcriptions using FTS5, plus filenames and summaries.
    Returns matching words with context (surrounding words, recording info).
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        results: List[Dict[str, Any]] = []

        # 1. Search in words using FTS5
        if fuzzy:
            fts_query = f"{query}*"
        else:
            fts_query = f'"{query}"'

        sql = """
            SELECT 
                w.id,
                w.recording_id,
                w.segment_id,
                w.word,
                w.start_time,
                w.end_time,
                r.filename,
                r.recorded_at,
                s.speaker,
                'word' as match_type
            FROM words_fts fts
            JOIN words w ON fts.rowid = w.id
            JOIN recordings r ON w.recording_id = r.id
            JOIN segments s ON w.segment_id = s.id
            WHERE words_fts MATCH ?
        """
        params: List[Any] = [fts_query]

        if start_date:
            sql += " AND date(r.recorded_at) >= date(?)"
            params.append(start_date)
        if end_date:
            sql += " AND date(r.recorded_at) <= date(?)"
            params.append(end_date)

        sql += " ORDER BY r.recorded_at DESC, w.start_time LIMIT ?"
        params.append(limit)

        cursor.execute(sql, params)

        for row in cursor.fetchall():
            result = dict(row)

            # Get context (surrounding words)
            cursor.execute(
                """
                SELECT word, start_time, end_time 
                FROM words 
                WHERE segment_id = ? 
                AND word_index BETWEEN 
                    (SELECT word_index FROM words WHERE id = ?) - 5 
                    AND (SELECT word_index FROM words WHERE id = ?) + 5
                ORDER BY word_index
                """,
                (result["segment_id"], result["id"], result["id"]),
            )

            context_words = [dict(r) for r in cursor.fetchall()]
            result["context"] = " ".join(w["word"] for w in context_words)
            result["context_words"] = context_words
            results.append(result)

        # 2. Search in filenames
        like_pattern = f"%{query}%"
        filename_sql = """
            SELECT 
                r.id as recording_id,
                r.filename,
                r.recorded_at,
                r.summary
            FROM recordings r
            WHERE LOWER(r.filename) LIKE LOWER(?)
        """
        filename_params: List[Any] = [like_pattern]

        if start_date:
            filename_sql += " AND date(r.recorded_at) >= date(?)"
            filename_params.append(start_date)
        if end_date:
            filename_sql += " AND date(r.recorded_at) <= date(?)"
            filename_params.append(end_date)

        filename_sql += " ORDER BY r.recorded_at DESC LIMIT ?"
        filename_params.append(limit)

        cursor.execute(filename_sql, filename_params)

        for row in cursor.fetchall():
            rec_id = row["recording_id"]
            if not any(
                r.get("recording_id") == rec_id and r.get("match_type") == "filename"
                for r in results
            ):
                results.append(
                    {
                        "id": None,
                        "recording_id": rec_id,
                        "segment_id": None,
                        "word": row["filename"],
                        "start_time": 0.0,
                        "end_time": 0.0,
                        "filename": row["filename"],
                        "recorded_at": row["recorded_at"],
                        "speaker": None,
                        "context": f"Filename match: {row['filename']}",
                        "context_words": [],
                        "match_type": "filename",
                    }
                )

        # 3. Search in summaries
        summary_sql = """
            SELECT 
                r.id as recording_id,
                r.filename,
                r.recorded_at,
                r.summary
            FROM recordings r
            WHERE r.summary IS NOT NULL AND LOWER(r.summary) LIKE LOWER(?)
        """
        summary_params: List[Any] = [like_pattern]

        if start_date:
            summary_sql += " AND date(r.recorded_at) >= date(?)"
            summary_params.append(start_date)
        if end_date:
            summary_sql += " AND date(r.recorded_at) <= date(?)"
            summary_params.append(end_date)

        summary_sql += " ORDER BY r.recorded_at DESC LIMIT ?"
        summary_params.append(limit)

        cursor.execute(summary_sql, summary_params)

        for row in cursor.fetchall():
            rec_id = row["recording_id"]
            if not any(
                r.get("recording_id") == rec_id and r.get("match_type") == "summary"
                for r in results
            ):
                summary = row["summary"] or ""
                query_lower = query.lower()
                summary_lower = summary.lower()
                match_pos = summary_lower.find(query_lower)
                if match_pos >= 0:
                    start = max(0, match_pos - 50)
                    end = min(len(summary), match_pos + len(query) + 50)
                    snippet = summary[start:end]
                    if start > 0:
                        snippet = "..." + snippet
                    if end < len(summary):
                        snippet = snippet + "..."
                else:
                    snippet = summary[:100] + ("..." if len(summary) > 100 else "")

                results.append(
                    {
                        "id": None,
                        "recording_id": rec_id,
                        "segment_id": None,
                        "word": query,
                        "start_time": 0.0,
                        "end_time": 0.0,
                        "filename": row["filename"],
                        "recorded_at": row["recorded_at"],
                        "speaker": None,
                        "context": f"Summary match: {snippet}",
                        "context_words": [],
                        "match_type": "summary",
                    }
                )

        return results[:limit]


# =============================================================================
# Longform Recording Storage Functions
# =============================================================================


def ensure_audio_dir() -> bool:
    """Ensure audio directory exists."""
    try:
        get_audio_dir()
        return True
    except Exception as e:
        logger.error(f"Failed to create audio directory: {e}")
        return False


def convert_audio_to_mp3(
    audio_data: np.ndarray,
    sample_rate: int = 16000,
    output_path: Optional[Path] = None,
) -> Optional[Path]:
    """
    Convert numpy audio array to MP3 file.

    Args:
        audio_data: NumPy array of audio samples (float32, mono)
        sample_rate: Sample rate of the audio (default 16000)
        output_path: Optional output path for MP3 file

    Returns:
        Path to the generated MP3 file, or None on error
    """
    if audio_data is None or len(audio_data) == 0:
        logger.warning("No audio data to convert")
        return None

    try:
        # Generate output path if not provided
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = get_audio_dir() / f"longform_{timestamp}.mp3"
        else:
            output_path = Path(output_path)

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write raw audio to a temporary WAV file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
            tmp_wav_path = tmp_wav.name

            # Convert float32 [-1.0, 1.0] to int16
            audio_int16 = (audio_data * 32767).astype(np.int16)

            # Write WAV header and data
            with wave.open(tmp_wav_path, "wb") as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(audio_int16.tobytes())

        # Convert to MP3 using ffmpeg
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i",
            tmp_wav_path,
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "2",  # High quality VBR
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        # Clean up temporary file
        Path(tmp_wav_path).unlink(missing_ok=True)

        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            return None

        logger.info(f"Audio saved to MP3: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Error converting audio to MP3: {e}", exc_info=True)
        return None


def _insert_single_segment_with_words(
    cursor: sqlite3.Cursor,
    recording_id: int,
    text: str,
    duration: float,
    word_timestamps: List[Dict[str, Any]],
) -> None:
    """Insert a single segment with word timestamps (internal helper).

    Note: This function does NOT commit - caller is responsible for transaction management.
    """
    start_time = word_timestamps[0].get("start", 0.0) if word_timestamps else 0.0
    end_time = word_timestamps[-1].get("end", duration) if word_timestamps else duration

    cursor.execute(
        """
        INSERT INTO segments
        (recording_id, segment_index, text, start_time, end_time, speaker)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (recording_id, 0, text, start_time, end_time, None),
    )
    segment_id = cursor.lastrowid

    if word_timestamps:
        words_batch = [
            {
                "recording_id": recording_id,
                "segment_id": segment_id,
                "word_index": i,
                "word": w.get("word", ""),
                "start_time": w.get("start", 0.0),
                "end_time": w.get("end", 0.0),
                "confidence": w.get("confidence"),
            }
            for i, w in enumerate(word_timestamps)
        ]
        cursor.executemany(
            """
            INSERT INTO words
            (recording_id, segment_id, word_index, word, start_time, end_time, confidence)
            VALUES (:recording_id, :segment_id, :word_index, :word, :start_time, :end_time, :confidence)
            """,
            words_batch,
        )


def _insert_diarization_segments_with_words(
    cursor: sqlite3.Cursor,
    recording_id: int,
    diarization_segments: List[Dict[str, Any]],
    alignment_words: Optional[List[Dict[str, Any]]] = None,
    save_words: bool = True,
) -> None:
    """Insert diarization segments with optional word timestamps (internal helper).

    Args:
        cursor: Database cursor
        recording_id: ID of the recording
        diarization_segments: List of speaker segments
        alignment_words: Optional word timestamps for aligning text with speaker segments
        save_words: Whether to save individual words to the database (vs just using them for segment text)

    Note: This function does NOT commit - caller is responsible for transaction management.
    """
    word_map: List[Dict[str, Any]] = alignment_words or []

    inserted_segments: List[Dict[str, Any]] = []

    for seg_idx, segment in enumerate(diarization_segments):
        speaker = segment.get("speaker")
        text = segment.get("text", "")
        start = segment.get("start", 0.0)
        end = segment.get("end", 0.0)

        cursor.execute(
            """
            INSERT INTO segments 
            (recording_id, segment_index, text, start_time, end_time, speaker)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (recording_id, seg_idx, text, start, end, speaker),
        )
        segment_id = cursor.lastrowid

        inserted_segments.append(
            {
                "segment_id": segment_id,
                "start": float(start or 0.0),
                "end": float(end or 0.0),
            }
        )

    if word_map and inserted_segments:
        words_by_segment_id: Dict[int, List[Dict[str, Any]]] = {
            int(seg["segment_id"]): [] for seg in inserted_segments
        }

        for w in word_map:
            w_start = float(w.get("start", w.get("start_time", 0.0)) or 0.0)
            w_end = float(w.get("end", w.get("end_time", w_start)) or w_start)
            w_mid = (w_start + w_end) / 2.0

            best_segment_id: Optional[int] = None
            best_overlap: float = 0.0
            best_distance: Optional[float] = None

            for seg in inserted_segments:
                seg_start = float(seg.get("start", 0.0))
                seg_end = float(seg.get("end", 0.0))

                overlap = max(0.0, min(w_end, seg_end) - max(w_start, seg_start))
                if overlap > 0.0:
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_segment_id = int(seg["segment_id"])
                    continue

                if best_overlap > 0.0:
                    continue

                if seg_start <= w_mid <= seg_end:
                    distance = 0.0
                elif w_mid < seg_start:
                    distance = seg_start - w_mid
                else:
                    distance = w_mid - seg_end

                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best_segment_id = int(seg["segment_id"])

            if best_segment_id is not None:
                words_by_segment_id[best_segment_id].append(w)

        for segment_id, segment_words in words_by_segment_id.items():
            if not segment_words:
                continue

            segment_words_sorted = sorted(
                segment_words,
                key=lambda x: float(x.get("start", x.get("start_time", 0.0)) or 0.0),
            )

            # Build segment text from words (always needed)
            segment_text = " ".join(
                [str(w.get("word", "")).strip() for w in segment_words_sorted]
            ).strip()
            cursor.execute(
                "UPDATE segments SET text = ? WHERE id = ?",
                (segment_text, segment_id),
            )

            # Only save individual words to database if requested
            if save_words:
                words_batch = [
                    {
                        "recording_id": recording_id,
                        "segment_id": segment_id,
                        "word_index": i,
                        "word": w.get("word", ""),
                        "start_time": float(
                            w.get("start", w.get("start_time", 0.0)) or 0.0
                        ),
                        "end_time": float(
                            w.get(
                                "end",
                                w.get(
                                    "end_time",
                                    w.get("start", w.get("start_time", 0.0)),
                                ),
                            )
                            or 0.0
                        ),
                        "confidence": w.get("confidence"),
                    }
                    for i, w in enumerate(segment_words_sorted)
                ]

                cursor.executemany(
                    """
                    INSERT INTO words
                    (recording_id, segment_id, word_index, word, start_time, end_time, confidence)
                    VALUES (:recording_id, :segment_id, :word_index, :word, :start_time, :end_time, :confidence)
                    """,
                    words_batch,
                )


def save_longform_to_database(
    audio_path: Path,
    duration_seconds: float,
    transcription_text: str,
    word_timestamps: Optional[List[Dict[str, Any]]] = None,
    diarization_segments: Optional[List[Dict[str, Any]]] = None,
    recorded_at: Optional[datetime] = None,
) -> Optional[int]:
    """
    Save a longform recording to the database atomically.

    All inserts (recording, segments, words) are wrapped in a single transaction.
    If any step fails, the entire operation is rolled back to prevent partial data.

    Args:
        audio_path: Path to the MP3 file
        duration_seconds: Duration in seconds
        transcription_text: Full transcription text
        word_timestamps: Optional list of word timing dicts
            (automatically provided when diarization is enabled for text alignment)
        diarization_segments: Optional list of speaker segments
        recorded_at: Optional timestamp (defaults to now)

    Returns:
        Recording ID on success, None on error
    """
    db_path = get_db_path()
    if not db_path.exists():
        logger.warning(
            f"Database not found at {db_path}. "
            "Start the server first to initialize the database."
        )
        return None

    conn = None
    try:
        recorded_at = recorded_at or datetime.now()
        has_diarization = bool(diarization_segments and len(diarization_segments) > 0)

        conn = sqlite3.connect(
            db_path,
            timeout=30.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Begin explicit transaction for atomicity
        # IMMEDIATE mode acquires write lock immediately, preventing conflicts
        cursor.execute("BEGIN IMMEDIATE")

        try:
            # Insert recording
            cursor.execute(
                """
                INSERT INTO recordings
                (filename, filepath, title, duration_seconds, recorded_at, has_diarization)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    audio_path.name,
                    str(audio_path),
                    audio_path.stem,
                    duration_seconds,
                    recorded_at.isoformat(),
                    int(has_diarization),
                ),
            )
            recording_id: int = cursor.lastrowid or 0

            if recording_id == 0:
                raise ValueError("Failed to insert recording - no lastrowid")

            # Insert segments and words (no intermediate commits)
            if diarization_segments:
                # Diarization requires word timestamps for text alignment
                # Words are always saved when diarization is enabled
                _insert_diarization_segments_with_words(
                    cursor,
                    recording_id,
                    diarization_segments,
                    alignment_words=word_timestamps,
                    save_words=True,
                )
            elif word_timestamps:
                _insert_single_segment_with_words(
                    cursor,
                    recording_id,
                    transcription_text,
                    duration_seconds,
                    word_timestamps,
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO segments
                    (recording_id, segment_index, text, start_time, end_time, speaker)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (recording_id, 0, transcription_text, 0.0, duration_seconds, None),
                )

            # Update word count
            cursor.execute(
                """
                UPDATE recordings
                SET word_count = (SELECT COUNT(*) FROM words WHERE recording_id = ?)
                WHERE id = ?
                """,
                (recording_id, recording_id),
            )

            # Commit entire transaction atomically
            conn.commit()
            logger.info(f"Recording saved to database with ID: {recording_id}")
            return recording_id

        except Exception:
            # Rollback on any error within the transaction
            conn.rollback()
            raise

    except Exception as e:
        logger.error(f"Error saving to database: {e}", exc_info=True)
        return None

    finally:
        if conn:
            conn.close()


def save_longform_recording(
    audio_data: np.ndarray,
    transcription_text: str,
    sample_rate: int = 16000,
    word_timestamps: Optional[List[Dict[str, Any]]] = None,
    diarization_segments: Optional[List[Dict[str, Any]]] = None,
) -> Optional[int]:
    """
    High-level function to save a longform recording.

    Args:
        audio_data: NumPy array of audio samples (float32, mono)
        transcription_text: Full transcription text
        sample_rate: Sample rate of the audio (default 16000)
        word_timestamps: Optional list of word timing dicts
        diarization_segments: Optional list of speaker segments

    Returns:
        Recording ID on success, None on error
    """
    if not ensure_audio_dir():
        return None

    duration_seconds = len(audio_data) / sample_rate if len(audio_data) > 0 else 0.0

    mp3_path = convert_audio_to_mp3(audio_data, sample_rate)
    if not mp3_path:
        logger.error("Failed to convert audio to MP3")
        return None

    return save_longform_to_database(
        audio_path=mp3_path,
        duration_seconds=duration_seconds,
        transcription_text=transcription_text,
        word_timestamps=word_timestamps,
        diarization_segments=diarization_segments,
    )


def get_word_timestamps_from_audio(
    audio_data: np.ndarray,
    model: Any = None,
    language: Optional[str] = None,
) -> tuple:
    """
    Transcribe audio with word-level timestamps using faster-whisper directly.

    Args:
        audio_data: NumPy array of audio samples (float32, mono, 16kHz)
        model: Optional pre-loaded faster_whisper model
        language: Optional language code

    Returns:
        Tuple of (transcription_text, word_timestamps_list)
    """
    try:
        import faster_whisper
    except ImportError:
        logger.error("faster_whisper not available for word timestamp extraction")
        return "", []

    if audio_data is None or len(audio_data) == 0:
        return "", []

    try:
        if model is None:
            logger.info("Loading faster-whisper model for word timestamps...")
            model = faster_whisper.WhisperModel(
                "large-v3",
                device="cuda",
                compute_type="float16",
            )

        segments, info = model.transcribe(
            audio_data,
            language=language,
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
        )

        full_text_parts = []
        all_words = []

        for segment in segments:
            full_text_parts.append(segment.text.strip())
            if hasattr(segment, "words") and segment.words:
                for word in segment.words:
                    all_words.append(
                        {
                            "word": word.word.strip(),
                            "start": word.start,
                            "end": word.end,
                            "confidence": getattr(word, "probability", None),
                        }
                    )

        full_text = " ".join(full_text_parts)
        logger.info(f"Word-level transcription complete: {len(all_words)} words")
        return full_text, all_words

    except Exception as e:
        logger.error(f"Error getting word timestamps: {e}", exc_info=True)
        return "", []
