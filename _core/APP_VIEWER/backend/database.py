"""
SQLite database with FTS5 for full-text search of transcriptions.

Also includes utilities for saving longform recordings from the SCRIPT module.
"""

import logging
import sqlite3
import subprocess
import tempfile
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
from contextlib import contextmanager

import numpy as np

# Database file location
DATA_DIR = Path(__file__).parent / "data"
AUDIO_DIR = DATA_DIR / "audio"
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

        # Migration: Add summary column if it doesn't exist (for existing databases)
        cursor.execute("PRAGMA table_info(recordings)")
        columns = [col[1] for col in cursor.fetchall()]
        if "summary" not in columns:
            cursor.execute("ALTER TABLE recordings ADD COLUMN summary TEXT")

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


def update_recording_summary(recording_id: int, summary: Optional[str]) -> bool:
    """Update the AI summary for a recording"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE recordings SET summary = ? WHERE id = ?",
            (summary, recording_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_recording_summary(recording_id: int) -> Optional[str]:
    """Get the AI summary for a recording"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT summary FROM recordings WHERE id = ?", (recording_id,))
        row = cursor.fetchone()
        return row["summary"] if row else None


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


# =============================================================================
# Longform Recording Storage Functions (merged from viewer_storage.py)
# =============================================================================


def ensure_audio_dir() -> bool:
    """Ensure audio directory exists."""
    try:
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        logging.error(f"Failed to create audio directory: {e}")
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
        logging.warning("No audio data to convert")
        return None

    try:
        # Generate output path if not provided
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = AUDIO_DIR / f"longform_{timestamp}.mp3"
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
            logging.error(f"FFmpeg error: {result.stderr}")
            return None

        logging.info(f"Audio saved to MP3: {output_path}")
        return output_path

    except Exception as e:
        logging.error(f"Error converting audio to MP3: {e}", exc_info=True)
        return None


def _insert_single_segment_with_words(
    cursor: sqlite3.Cursor,
    recording_id: int,
    text: str,
    duration: float,
    word_timestamps: list[dict],
):
    """Insert a single segment with word timestamps (internal helper)."""
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
    cursor.connection.commit()


def _insert_diarization_segments_with_words(
    cursor: sqlite3.Cursor,
    recording_id: int,
    diarization_segments: list[dict],
    word_timestamps: Optional[list[dict]] = None,
):
    """Insert diarization segments with optional word timestamps (internal helper)."""
    word_map: list[dict] = word_timestamps or []

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

        if word_map:
            segment_words = [
                w
                for w in word_map
                if w.get("start", 0) >= start - 0.1 and w.get("end", 0) <= end + 0.1
            ]
            if segment_words:
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
                    for i, w in enumerate(segment_words)
                ]
                cursor.executemany(
                    """
                    INSERT INTO words 
                    (recording_id, segment_id, word_index, word, start_time, end_time, confidence)
                    VALUES (:recording_id, :segment_id, :word_index, :word, :start_time, :end_time, :confidence)
                    """,
                    words_batch,
                )
    cursor.connection.commit()


def save_longform_to_database(
    audio_path: Path,
    duration_seconds: float,
    transcription_text: str,
    word_timestamps: Optional[list[dict]] = None,
    diarization_segments: Optional[list[dict]] = None,
    recorded_at: Optional[datetime] = None,
) -> Optional[int]:
    """
    Save a longform recording to the database.

    Args:
        audio_path: Path to the MP3 file
        duration_seconds: Duration in seconds
        transcription_text: Full transcription text
        word_timestamps: Optional list of word timing dicts
        diarization_segments: Optional list of speaker segments
        recorded_at: Optional timestamp (defaults to now)

    Returns:
        Recording ID on success, None on error
    """
    if not DB_PATH.exists():
        logging.warning(
            f"Database not found at {DB_PATH}. "
            "Start the viewer app first to initialize the database."
        )
        return None

    try:
        recorded_at = recorded_at or datetime.now()
        has_diarization = bool(diarization_segments and len(diarization_segments) > 0)

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO recordings 
            (filename, filepath, duration_seconds, recorded_at, has_diarization)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                audio_path.name,
                str(audio_path),
                duration_seconds,
                recorded_at.isoformat(),
                int(has_diarization),
            ),
        )
        recording_id: int = cursor.lastrowid or 0
        conn.commit()

        if recording_id == 0:
            logging.error("Failed to insert recording into database")
            conn.close()
            return None

        if diarization_segments:
            _insert_diarization_segments_with_words(
                cursor, recording_id, diarization_segments, word_timestamps
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
            conn.commit()

        cursor.execute(
            """
            UPDATE recordings 
            SET word_count = (SELECT COUNT(*) FROM words WHERE recording_id = ?)
            WHERE id = ?
            """,
            (recording_id, recording_id),
        )
        conn.commit()
        conn.close()

        logging.info(f"Recording saved to database with ID: {recording_id}")
        return recording_id

    except Exception as e:
        logging.error(f"Error saving to database: {e}", exc_info=True)
        return None


def save_longform_recording(
    audio_data: np.ndarray,
    transcription_text: str,
    sample_rate: int = 16000,
    word_timestamps: Optional[list[dict]] = None,
    diarization_segments: Optional[list[dict]] = None,
) -> Optional[int]:
    """
    High-level function to save a longform recording to the viewer app.

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
        logging.error("Failed to convert audio to MP3")
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
) -> tuple[str, list[dict]]:
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
        logging.error("faster_whisper not available for word timestamp extraction")
        return "", []

    if audio_data is None or len(audio_data) == 0:
        return "", []

    try:
        if model is None:
            logging.info("Loading faster-whisper model for word timestamps...")
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
        logging.info(f"Word-level transcription complete: {len(all_words)} words")
        return full_text, all_words

    except Exception as e:
        logging.error(f"Error getting word timestamps: {e}", exc_info=True)
        return "", []
