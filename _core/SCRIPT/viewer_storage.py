#!/usr/bin/env python3
"""
Viewer App Storage Module

This module provides functions to save longform recordings to the
Transcription Viewer app's database and storage, enabling them to appear
in the calendar view alongside imported recordings.
"""

import logging
import sqlite3
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

import numpy as np

# The Viewer app's data directory (relative to TranscriptionSuite root)
VIEWER_DATA_DIR = (
    Path(__file__).parent.parent.parent / "_app-transcription-viewer" / "backend" / "data"
)
VIEWER_AUDIO_DIR = VIEWER_DATA_DIR / "audio"
VIEWER_DB_PATH = VIEWER_DATA_DIR / "transcriptions.db"


def ensure_viewer_dirs() -> bool:
    """Ensure viewer app directories exist."""
    try:
        VIEWER_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        logging.error(f"Failed to create viewer directories: {e}")
        return False


def convert_audio_to_mp3(
    audio_data: np.ndarray,
    sample_rate: int = 16000,
    output_path: Path | str | None = None,
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
            output_path = VIEWER_AUDIO_DIR / f"longform_{timestamp}.mp3"
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
            import wave

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


def save_to_viewer_database(
    audio_path: Path,
    duration_seconds: float,
    transcription_text: str,
    word_timestamps: Optional[list[dict]] = None,
    diarization_segments: Optional[list[dict]] = None,
    recorded_at: Optional[datetime] = None,
) -> Optional[int]:
    """
    Save a recording to the viewer app's database.

    Args:
        audio_path: Path to the MP3 file
        duration_seconds: Duration in seconds
        transcription_text: Full transcription text
        word_timestamps: Optional list of word timing dicts
                        [{"word": "hello", "start": 0.0, "end": 0.5}, ...]
        diarization_segments: Optional list of speaker segments
                             [{"speaker": "SPEAKER_0", "start": 0.0, "end": 5.0, "text": "..."}, ...]
        recorded_at: Optional timestamp (defaults to now)

    Returns:
        Recording ID on success, None on error
    """
    if not VIEWER_DB_PATH.exists():
        logging.warning(
            f"Viewer database not found at {VIEWER_DB_PATH}. "
            "Start the viewer app first to initialize the database."
        )
        return None

    try:
        recorded_at = recorded_at or datetime.now()
        has_diarization = bool(diarization_segments and len(diarization_segments) > 0)

        # Connect to database
        conn = sqlite3.connect(VIEWER_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Insert recording
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

        # Prepare segments and words
        if diarization_segments:
            # Use diarization segments
            _insert_diarization_segments(
                cursor, recording_id, diarization_segments, word_timestamps
            )
        elif word_timestamps:
            # Create a single segment with all words
            _insert_single_segment(
                cursor,
                recording_id,
                transcription_text,
                duration_seconds,
                word_timestamps,
            )
        else:
            # Just insert the text as a single segment without word timings
            cursor.execute(
                """
                INSERT INTO segments 
                (recording_id, segment_index, text, start_time, end_time, speaker)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (recording_id, 0, transcription_text, 0.0, duration_seconds, None),
            )
            conn.commit()

        # Update word count
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
        logging.info(f"Recording saved to viewer database with ID: {recording_id}")
        return recording_id

    except Exception as e:
        logging.error(f"Error saving to viewer database: {e}", exc_info=True)
        return None


def _insert_single_segment(
    cursor: sqlite3.Cursor,
    recording_id: int,
    text: str,
    duration: float,
    word_timestamps: list[dict],
):
    """Insert a single segment with word timestamps."""
    # Get timing from words if available
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

    # Insert words
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


def _insert_diarization_segments(
    cursor: sqlite3.Cursor,
    recording_id: int,
    diarization_segments: list[dict],
    word_timestamps: Optional[list[dict]] = None,
):
    """Insert diarization segments with optional word timestamps."""
    # Create a mapping of word timestamps by time for fast lookup
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

        # Find words that fall within this segment's time range
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
    if not ensure_viewer_dirs():
        return None

    # Calculate duration
    duration_seconds = len(audio_data) / sample_rate if len(audio_data) > 0 else 0.0

    # Convert audio to MP3
    mp3_path = convert_audio_to_mp3(audio_data, sample_rate)
    if not mp3_path:
        logging.error("Failed to convert audio to MP3")
        return None

    # Save to database
    recording_id = save_to_viewer_database(
        audio_path=mp3_path,
        duration_seconds=duration_seconds,
        transcription_text=transcription_text,
        word_timestamps=word_timestamps,
        diarization_segments=diarization_segments,
    )

    return recording_id


def get_word_timestamps_from_audio(
    audio_data: np.ndarray,
    model: Any = None,
    language: Optional[str] = None,
) -> tuple[str, list[dict]]:
    """
    Transcribe audio with word-level timestamps using faster-whisper directly.

    This function is used when word_timestamps are needed but not already
    available (i.e., for longform recording when the main engine doesn't
    return word timestamps).

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
        # Use provided model or create a temporary one
        if model is None:
            logging.info("Loading faster-whisper model for word timestamps...")
            model = faster_whisper.WhisperModel(
                "large-v3",
                device="cuda",
                compute_type="float16",
            )

        # Transcribe with word timestamps
        segments, info = model.transcribe(
            audio_data,
            language=language,
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
        )

        # Collect text and word timestamps
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
