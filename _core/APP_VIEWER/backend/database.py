"""
SQLite database with FTS5 for full-text search of transcriptions
"""

import sqlite3
from pathlib import Path
from typing import Optional, Any
from contextlib import contextmanager

# Database file location
DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "transcriptions.db"


def get_db_path() -> Path:
    """Get database path, creating data directory if needed"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DB_PATH


@contextmanager
def get_connection():
    """Get a database connection with context manager"""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """Initialize database schema with FTS5 for word search"""
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
                has_diarization INTEGER DEFAULT 0
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
        # Using content sync to automatically keep in sync with words table
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

        conn.commit()


def insert_recording(
    filename: str,
    filepath: str,
    duration_seconds: float,
    recorded_at: str,
    has_diarization: bool = False,
) -> int:
    """Insert a new recording and return its ID"""
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


def insert_segment(
    recording_id: int,
    segment_index: int,
    text: str,
    start_time: float,
    end_time: float,
    speaker: Optional[str] = None,
) -> int:
    """Insert a segment and return its ID"""
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
):
    """Insert a word"""
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


def insert_words_batch(words: list[dict]):
    """Insert multiple words in a batch for efficiency"""
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


def update_recording_word_count(recording_id: int):
    """Update the word count for a recording"""
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


def get_recording(recording_id: int) -> Optional[dict]:
    """Get a recording by ID"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_recordings() -> list[dict]:
    """Get all recordings"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM recordings ORDER BY recorded_at DESC")
        return [dict(row) for row in cursor.fetchall()]


def get_recordings_by_date_range(start_date: str, end_date: str) -> list[dict]:
    """Get recordings within a date range"""
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


def get_recordings_for_month(year: int, month: int) -> list[dict]:
    """Get recordings for a specific month"""
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


def get_transcription(recording_id: int) -> dict:
    """Get full transcription with segments and words"""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Get segments
        cursor.execute(
            """
            SELECT * FROM segments WHERE recording_id = ? ORDER BY segment_index
        """,
            (recording_id,),
        )
        segments = [dict(row) for row in cursor.fetchall()]

        # Get words for each segment
        for segment in segments:
            cursor.execute(
                """
                SELECT word, start_time, end_time, confidence 
                FROM words 
                WHERE segment_id = ? 
                ORDER BY word_index
            """,
                (segment["id"],),
            )
            segment["words"] = [
                {
                    "word": row["word"],
                    "start": row["start_time"],
                    "end": row["end_time"],
                    "confidence": row["confidence"],
                }
                for row in cursor.fetchall()
            ]

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


def search_words(
    query: str,
    fuzzy: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """
    Search for words in transcriptions using FTS5
    Returns matching words with context (surrounding words, recording info)
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # Build FTS query
        if fuzzy:
            # Use prefix matching for fuzzy search
            fts_query = f"{query}*"
        else:
            fts_query = f'"{query}"'

        # Base query joining FTS results with word and recording info
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
                s.speaker
            FROM words_fts fts
            JOIN words w ON fts.rowid = w.id
            JOIN recordings r ON w.recording_id = r.id
            JOIN segments s ON w.segment_id = s.id
            WHERE words_fts MATCH ?
        """
        params: list[Any] = [fts_query]

        # Add date filtering
        if start_date:
            sql += " AND date(r.recorded_at) >= date(?)"
            params.append(start_date)
        if end_date:
            sql += " AND date(r.recorded_at) <= date(?)"
            params.append(end_date)

        sql += " ORDER BY r.recorded_at DESC, w.start_time LIMIT ?"
        params.append(limit)

        cursor.execute(sql, params)

        results = []
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

        return results


def delete_recording(recording_id: int) -> bool:
    """Delete a recording and all associated data"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
        conn.commit()
        return cursor.rowcount > 0


def update_recording_date(recording_id: int, recorded_at: str) -> bool:
    """Update the recorded_at timestamp for a recording"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE recordings SET recorded_at = ? WHERE id = ?",
            (recorded_at, recording_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_recordings_for_hour(date_str: str, hour: int) -> list[dict]:
    """Get recordings for a specific date and hour, ordered by recorded_at"""
    with get_connection() as conn:
        cursor = conn.cursor()
        # Match recordings where the hour matches and date matches
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
