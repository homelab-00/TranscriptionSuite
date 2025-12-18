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
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)

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
    """Get a database connection with context manager."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_db_session() -> Generator[sqlite3.Connection, None, None]:
    """Alias for get_connection for API compatibility."""
    with get_connection() as conn:
        yield conn


def init_db() -> None:
    """Initialize database schema with FTS5 for word search."""
    logger.info(f"Initializing database at {get_db_path()}")

    with get_connection() as conn:
        cursor = conn.cursor()

        # Main recordings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recordings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                filepath TEXT NOT NULL UNIQUE,
                duration_seconds REAL NOT NULL,
                recorded_at TIMESTAMP NOT NULL,
                imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                word_count INTEGER DEFAULT 0,
                has_diarization INTEGER DEFAULT 0,
                summary TEXT
            )
        """)

        # Segments table (for speaker turns or time-based segments)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id INTEGER NOT NULL,
                segment_index INTEGER NOT NULL,
                speaker TEXT,
                text TEXT NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL,
                FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
            )
        """)

        # Words table with timing information
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id INTEGER NOT NULL,
                segment_id INTEGER NOT NULL,
                word_index INTEGER NOT NULL,
                word TEXT NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL,
                confidence REAL,
                FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE,
                FOREIGN KEY (segment_id) REFERENCES segments(id) ON DELETE CASCADE
            )
        """)

        # FTS5 virtual table for full-text search
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS words_fts USING fts5(
                word,
                content='words',
                content_rowid='id',
                tokenize='unicode61'
            )
        """)

        # Triggers to keep FTS in sync
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS words_ai AFTER INSERT ON words BEGIN
                INSERT INTO words_fts(rowid, word) VALUES (new.id, new.word);
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS words_ad AFTER DELETE ON words BEGIN
                INSERT INTO words_fts(words_fts, rowid, word) VALUES('delete', old.id, old.word);
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS words_au AFTER UPDATE ON words BEGIN
                INSERT INTO words_fts(words_fts, rowid, word) VALUES('delete', old.id, old.word);
                INSERT INTO words_fts(rowid, word) VALUES (new.id, new.word);
            END
        """)

        # Indexes for common queries
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_recordings_date ON recordings(recorded_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_words_recording ON words(recording_id)"
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_words_time ON words(start_time)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_segments_recording ON segments(recording_id)"
        )

        # Migration: Add summary column if it doesn't exist
        cursor.execute("PRAGMA table_info(recordings)")
        columns = [col[1] for col in cursor.fetchall()]
        if "summary" not in columns:
            cursor.execute("ALTER TABLE recordings ADD COLUMN summary TEXT")

        # Conversations table - each recording can have multiple conversations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT 'New Chat',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
            )
        """)

        # Messages table - each conversation has multiple messages
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tokens_used INTEGER,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
        """)

        # Indexes for conversation queries
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_recording ON conversations(recording_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)"
        )

        conn.commit()
        logger.info("Database initialized successfully")


# =============================================================================
# Recording CRUD operations
# =============================================================================


class Recording:
    """Recording model class."""

    def __init__(self, data: Dict[str, Any]):
        self.id = data.get("id")
        self.filename = data.get("filename")
        self.filepath = data.get("filepath")
        self.duration_seconds = data.get("duration_seconds")
        self.recorded_at = data.get("recorded_at")
        self.imported_at = data.get("imported_at")
        self.word_count = data.get("word_count", 0)
        self.has_diarization = bool(data.get("has_diarization", 0))
        self.summary = data.get("summary")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "filename": self.filename,
            "filepath": self.filepath,
            "duration_seconds": self.duration_seconds,
            "recorded_at": self.recorded_at,
            "imported_at": self.imported_at,
            "word_count": self.word_count,
            "has_diarization": self.has_diarization,
            "summary": self.summary,
        }


def insert_recording(
    filename: str,
    filepath: str,
    duration_seconds: float,
    recorded_at: str,
    has_diarization: bool = False,
) -> int:
    """Insert a new recording and return its ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO recordings (filename, filepath, duration_seconds, recorded_at, has_diarization)
            VALUES (?, ?, ?, ?, ?)
            """,
            (filename, filepath, duration_seconds, recorded_at, int(has_diarization)),
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


def get_recordings_by_date_range(start_date: str, end_date: str) -> List[Dict[str, Any]]:
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


def update_recording_summary(recording_id: int, summary: str) -> bool:
    """Update the summary for a recording."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE recordings SET summary = ? WHERE id = ?",
            (summary, recording_id),
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
            SELECT w.*, r.filename, r.recorded_at
            FROM words w
            JOIN words_fts ON w.id = words_fts.rowid
            JOIN recordings r ON w.recording_id = r.id
            WHERE words_fts MATCH ?
            ORDER BY r.recorded_at DESC
            LIMIT ?
            """,
            (query, limit),
        )
        return [dict(row) for row in cursor.fetchall()]


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
    tokens_used: Optional[int] = None,
) -> int:
    """Add a message to a conversation."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO messages (conversation_id, role, content, tokens_used)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, role, content, tokens_used),
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
