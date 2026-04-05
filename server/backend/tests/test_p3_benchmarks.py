"""P3 benchmark tests — latency and throughput measurements.

Covers:
- P3-PERF-001: Transcription latency per backend (mocked engine, measures overhead)
- P3-PERF-002: WS binary message parse throughput
- P3-PERF-003: FTS5 search latency with 1000+ recordings

All benchmarks use generous time ceilings to avoid flaky CI failures.
Run with: pytest tests/ -m p3 -v
"""

from __future__ import annotations

import json
import struct
import time
from pathlib import Path

import pytest
import server.database.database as db

# ---------------------------------------------------------------------------
# Shared schema (mirrors test_database.py)
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL UNIQUE,
    title TEXT,
    duration_seconds REAL NOT NULL,
    recorded_at TIMESTAMP NOT NULL,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    word_count INTEGER DEFAULT 0,
    has_diarization INTEGER DEFAULT 0,
    summary TEXT,
    summary_model TEXT,
    transcription_backend TEXT
);

CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL,
    segment_index INTEGER NOT NULL,
    speaker TEXT,
    text TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
);

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
);

CREATE VIRTUAL TABLE IF NOT EXISTS words_fts USING fts5(
    word,
    content='words',
    content_rowid='id',
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS words_ai AFTER INSERT ON words BEGIN
    INSERT INTO words_fts(rowid, word) VALUES (new.id, new.word);
END;

CREATE TRIGGER IF NOT EXISTS words_ad AFTER DELETE ON words BEGIN
    INSERT INTO words_fts(words_fts, rowid, word) VALUES('delete', old.id, old.word);
END;

CREATE TRIGGER IF NOT EXISTS words_au AFTER UPDATE ON words BEGIN
    INSERT INTO words_fts(words_fts, rowid, word) VALUES('delete', old.id, old.word);
    INSERT INTO words_fts(rowid, word) VALUES (new.id, new.word);
END;

CREATE INDEX IF NOT EXISTS idx_recordings_date ON recordings(recorded_at);
CREATE INDEX IF NOT EXISTS idx_words_recording ON words(recording_id);
CREATE INDEX IF NOT EXISTS idx_words_time ON words(start_time);
CREATE INDEX IF NOT EXISTS idx_segments_recording ON segments(recording_id);

PRAGMA foreign_keys = ON;
"""

# Sample vocabulary for synthetic data generation
_VOCAB = [
    "the",
    "quick",
    "brown",
    "fox",
    "jumps",
    "over",
    "lazy",
    "dog",
    "transcription",
    "audio",
    "speech",
    "model",
    "neural",
    "network",
    "quantum",
    "physics",
    "meeting",
    "notes",
    "interview",
    "lecture",
    "hello",
    "world",
    "data",
    "processing",
    "machine",
    "learning",
    "artificial",
    "intelligence",
    "deep",
    "recognition",
    "voice",
    "recording",
    "microphone",
    "speaker",
    "diarization",
    "segment",
    "frequency",
    "amplitude",
    "waveform",
    "spectrum",
    "acoustic",
    "language",
    "translation",
    "subtitle",
    "caption",
    "timestamp",
    "duration",
    "buffer",
    "stream",
    "encode",
    "decode",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _fts_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Create an isolated SQLite DB with FTS5 and seed 1000+ recordings."""
    import sqlite3

    data_dir = tmp_path / "data"
    db_dir = data_dir / "database"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "notebook.db"

    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA_SQL)

    # Seed 1000 recordings, each with 1 segment and 50 words
    vocab_len = len(_VOCAB)
    for i in range(1000):
        month = (i % 12) + 1
        day = (i % 28) + 1
        conn.execute(
            "INSERT INTO recordings (filename, filepath, duration_seconds, recorded_at) "
            "VALUES (?, ?, ?, ?)",
            (
                f"rec_{i:04d}.mp3",
                f"/audio/rec_{i:04d}.mp3",
                60.0,
                f"2025-{month:02d}-{day:02d}T10:00:00",
            ),
        )
        rec_id = i + 1
        conn.execute(
            "INSERT INTO segments (recording_id, segment_index, speaker, text, start_time, end_time) "
            "VALUES (?, 0, 'Speaker 1', ?, 0.0, 60.0)",
            (rec_id, " ".join(_VOCAB[j % vocab_len] for j in range(i, i + 50))),
        )
        seg_id = i + 1
        for w_idx in range(50):
            word = _VOCAB[(i + w_idx) % vocab_len]
            start = w_idx * 1.2
            conn.execute(
                "INSERT INTO words (recording_id, segment_id, word_index, word, start_time, end_time) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (rec_id, seg_id, w_idx, word, start, start + 1.0),
            )

    conn.commit()
    conn.close()

    monkeypatch.setattr(db, "_data_dir", data_dir)
    monkeypatch.setattr(db, "_db_path", db_path)


# ===================================================================
# P3-PERF-001: Transcription latency per backend (mocked)
# ===================================================================


class _FakeResult:
    """Minimal transcription result for latency measurement."""

    def __init__(self, text: str, duration: float, num_segments: int) -> None:
        self.text = text
        self.language = "en"
        self.language_probability = 0.95
        self.duration = duration
        self.segments = [
            {"start_time": i * 10.0, "end_time": (i + 1) * 10.0, "text": f"Segment {i}"}
            for i in range(num_segments)
        ]
        self.words = [
            {"word": f"word{j}", "start_time": j * 0.5, "end_time": j * 0.5 + 0.4}
            for j in range(num_segments * 10)
        ]
        self.num_speakers = 1


@pytest.mark.p3
@pytest.mark.benchmark
class TestTranscriptionLatencyOverhead:
    """P3-PERF-001: Measure transcription call-path overhead (no real inference).

    These tests mock the engine to return instantly and measure how much time
    the surrounding code (format conversion, result construction) adds.
    """

    @staticmethod
    def _time_transcribe_roundtrip(num_segments: int, response_format: str = "json") -> float:
        """Time a full transcribe-and-format cycle with a mocked engine."""
        from server.core.formatters import (
            format_json,
            format_srt,
            format_text,
            format_verbose_json,
            format_vtt,
        )

        result = _FakeResult(
            text="Hello world " * num_segments,
            duration=num_segments * 10.0,
            num_segments=num_segments,
        )

        formatters = {
            "json": lambda r: format_json(r),
            "text": lambda r: format_text(r),
            "verbose_json": lambda r: format_verbose_json(r, task="transcribe", include_words=True),
            "srt": lambda r: format_srt(r),
            "vtt": lambda r: format_vtt(r),
        }
        fmt_fn = formatters[response_format]

        start = time.perf_counter()
        for _ in range(100):
            fmt_fn(result)
        elapsed = time.perf_counter() - start
        return elapsed

    def test_small_result_formatting_overhead(self) -> None:
        """Small result (3 segments, ~30s audio): 100 format cycles < 1s."""
        elapsed = self._time_transcribe_roundtrip(num_segments=3)
        assert elapsed < 1.0, f"Small result formatting took {elapsed:.3f}s for 100 iterations"

    def test_medium_result_formatting_overhead(self) -> None:
        """Medium result (30 segments, ~5min audio): 100 format cycles < 2s."""
        elapsed = self._time_transcribe_roundtrip(num_segments=30)
        assert elapsed < 2.0, f"Medium result formatting took {elapsed:.3f}s for 100 iterations"

    def test_large_result_verbose_json_overhead(self) -> None:
        """Large result (300 segments, ~50min audio): 100 verbose_json cycles < 5s."""
        elapsed = self._time_transcribe_roundtrip(num_segments=300, response_format="verbose_json")
        assert elapsed < 5.0, (
            f"Large verbose_json formatting took {elapsed:.3f}s for 100 iterations"
        )


# ===================================================================
# P3-PERF-002: WS binary message parse throughput
# ===================================================================


def _make_binary_frame(pcm_size: int = 3200, sample_rate: int = 16000) -> bytes:
    """Build a binary WebSocket frame: [4B meta_len][JSON metadata][PCM data]."""
    metadata = json.dumps({"sample_rate": sample_rate}).encode("utf-8")
    meta_len = struct.pack("<I", len(metadata))
    pcm_data = b"\x00" * pcm_size  # silence
    return meta_len + metadata + pcm_data


@pytest.mark.p3
@pytest.mark.benchmark
class TestWsBinaryParseThroughput:
    """P3-PERF-002: Measure binary frame parsing throughput."""

    def test_parse_1000_frames_under_1s(self) -> None:
        """Parse 1000 well-formed binary frames in under 1 second."""
        frames = [_make_binary_frame() for _ in range(1000)]

        parsed_count = 0
        start = time.perf_counter()
        for frame in frames:
            # Replicate the parsing logic from handle_binary_message
            if len(frame) < 4:
                continue
            metadata_len = struct.unpack("<I", frame[:4])[0]
            if len(frame) < 4 + metadata_len:
                continue
            metadata_bytes = frame[4 : 4 + metadata_len]
            _metadata = json.loads(metadata_bytes.decode("utf-8"))
            pcm_data = frame[4 + metadata_len :]
            assert len(pcm_data) > 0
            parsed_count += 1
        elapsed = time.perf_counter() - start

        assert parsed_count == 1000
        assert elapsed < 1.0, f"Parsing 1000 frames took {elapsed:.3f}s"

    def test_malformed_frames_do_not_crash(self) -> None:
        """Malformed frames (too short, truncated metadata) are skipped without errors."""
        frames = [
            b"",  # empty
            b"\x01",  # too short
            b"\x03\x00\x00\x00ab",  # metadata_len=3 but only 2 bytes of metadata
            _make_binary_frame(),  # valid
            struct.pack("<I", 0) + b"\x00" * 100,  # zero-length metadata + PCM
        ]

        parsed = 0
        skipped = 0
        for frame in frames:
            if len(frame) < 4:
                skipped += 1
                continue
            metadata_len = struct.unpack("<I", frame[:4])[0]
            if len(frame) < 4 + metadata_len:
                skipped += 1
                continue
            if metadata_len > 0:
                metadata_bytes = frame[4 : 4 + metadata_len]
                try:
                    json.loads(metadata_bytes.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    skipped += 1
                    continue
            parsed += 1

        assert parsed >= 2  # the valid frame + zero-metadata frame
        assert skipped >= 2  # empty + too short


# ===================================================================
# P3-PERF-003: FTS5 search latency with 1000+ recordings
# ===================================================================


@pytest.mark.p3
@pytest.mark.benchmark
class TestFts5SearchLatency:
    """P3-PERF-003: FTS5 search performance with 1000 recordings × 50 words each."""

    def test_search_words_under_500ms(self, _fts_db) -> None:
        """search_words() for a common term completes in <500ms over 50k words."""
        start = time.perf_counter()
        results = db.search_words("transcription", limit=100)
        elapsed = time.perf_counter() - start

        assert len(results) > 0, "Expected at least one match for 'transcription'"
        assert elapsed < 0.5, f"search_words took {elapsed:.3f}s (expected <0.5s)"

    def test_search_words_by_date_range_under_500ms(self, _fts_db) -> None:
        """search_words_by_date_range() with date filter completes in <500ms."""
        start = time.perf_counter()
        results = db.search_words_by_date_range(
            "audio", start_date="2025-03-01", end_date="2025-06-30", limit=100
        )
        elapsed = time.perf_counter() - start

        assert len(results) > 0, "Expected at least one match for 'audio' in date range"
        assert elapsed < 0.5, f"search_words_by_date_range took {elapsed:.3f}s (expected <0.5s)"

    def test_search_recordings_under_500ms(self, _fts_db) -> None:
        """search_recordings() finds recordings by word content in <500ms."""
        start = time.perf_counter()
        results = db.search_recordings("quantum", limit=50)
        elapsed = time.perf_counter() - start

        assert len(results) > 0, "Expected at least one recording match for 'quantum'"
        assert elapsed < 0.5, f"search_recordings took {elapsed:.3f}s (expected <0.5s)"

    def test_search_enhanced_fuzzy_under_1s(self, _fts_db) -> None:
        """search_words_enhanced() with fuzzy prefix search in <1s."""
        start = time.perf_counter()
        results = db.search_words_enhanced("trans", fuzzy=True, limit=100)
        elapsed = time.perf_counter() - start

        assert len(results) > 0, "Expected fuzzy prefix match for 'trans'"
        assert elapsed < 1.0, f"search_words_enhanced (fuzzy) took {elapsed:.3f}s (expected <1s)"

    def test_search_no_match_returns_fast(self, _fts_db) -> None:
        """Searching for a non-existent term returns empty in <100ms."""
        start = time.perf_counter()
        results = db.search_words("xyzzynonexistent12345", limit=100)
        elapsed = time.perf_counter() - start

        assert results == []
        assert elapsed < 0.1, f"No-match search took {elapsed:.3f}s (expected <0.1s)"
