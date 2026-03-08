"""Tests for database/database.py — CRUD, FTS, cascading deletes, pagination.

Phase 4 of the testing roadmap.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import server.database.database as db

# ---------------------------------------------------------------------------
# Schema bootstrap (mirrors the Alembic migrations without requiring alembic)
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

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT 'New Chat',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    response_id TEXT,
    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    model TEXT,
    tokens_used INTEGER,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_recordings_date ON recordings(recorded_at);
CREATE INDEX IF NOT EXISTS idx_words_recording ON words(recording_id);
CREATE INDEX IF NOT EXISTS idx_words_time ON words(start_time);
CREATE INDEX IF NOT EXISTS idx_segments_recording ON segments(recording_id);
CREATE INDEX IF NOT EXISTS idx_conversations_recording ON conversations(recording_id);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);

PRAGMA foreign_keys = ON;
"""


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the database module at a fresh SQLite file under tmp_path.

    Sets up the full schema (tables + FTS + triggers) and resets module
    globals so every test starts from a clean database.
    """
    import sqlite3

    data_dir = tmp_path / "data"
    db_dir = data_dir / "database"
    db_dir.mkdir(parents=True)

    db_path = db_dir / "notebook.db"

    # Create the schema
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA_SQL)
    conn.close()

    # Redirect the module-level globals
    monkeypatch.setattr(db, "_data_dir", data_dir)
    monkeypatch.setattr(db, "_db_path", db_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_sample_recording(
    filename: str = "test.mp3",
    filepath: str = "/audio/test.mp3",
    duration: float = 10.0,
    recorded_at: str = "2025-06-15T10:00:00",
    has_diarization: bool = False,
    title: str | None = None,
) -> int:
    return db.insert_recording(
        filename=filename,
        filepath=filepath,
        duration_seconds=duration,
        recorded_at=recorded_at,
        has_diarization=has_diarization,
        title=title,
    )


# ===================================================================
# Recording CRUD
# ===================================================================


class TestInsertRecording:
    def test_returns_positive_id(self) -> None:
        rid = _insert_sample_recording()

        assert rid > 0

    def test_title_defaults_to_filename(self) -> None:
        rid = _insert_sample_recording(filename="meeting.mp3")

        rec = db.get_recording(rid)
        assert rec is not None
        assert rec["title"] == "meeting.mp3"

    def test_explicit_title_overrides_default(self) -> None:
        rid = _insert_sample_recording(title="Weekly standup")

        rec = db.get_recording(rid)
        assert rec is not None
        assert rec["title"] == "Weekly standup"


class TestGetRecording:
    def test_returns_none_for_missing_id(self) -> None:
        assert db.get_recording(9999) is None

    def test_round_trips_all_fields(self) -> None:
        rid = _insert_sample_recording(
            filename="call.mp3",
            filepath="/audio/call.mp3",
            duration=42.5,
            recorded_at="2025-06-15T14:30:00",
            has_diarization=True,
            title="Client call",
        )

        rec = db.get_recording(rid)
        assert rec is not None
        assert rec["filename"] == "call.mp3"
        assert rec["filepath"] == "/audio/call.mp3"
        assert rec["duration_seconds"] == 42.5
        assert rec["has_diarization"] == 1
        assert rec["title"] == "Client call"


class TestGetAllRecordings:
    def test_empty_database(self) -> None:
        assert db.get_all_recordings() == []

    def test_returns_newest_first(self) -> None:
        _insert_sample_recording(filepath="/a1.mp3", recorded_at="2025-06-01T08:00:00")
        _insert_sample_recording(filepath="/a2.mp3", recorded_at="2025-06-15T08:00:00")

        recs = db.get_all_recordings()

        assert len(recs) == 2
        assert recs[0]["filepath"] == "/a2.mp3"
        assert recs[1]["filepath"] == "/a1.mp3"


class TestGetRecordingsByDateRange:
    def test_filters_by_date(self) -> None:
        _insert_sample_recording(filepath="/jan.mp3", recorded_at="2025-01-15T10:00:00")
        _insert_sample_recording(filepath="/jun.mp3", recorded_at="2025-06-15T10:00:00")
        _insert_sample_recording(filepath="/dec.mp3", recorded_at="2025-12-15T10:00:00")

        results = db.get_recordings_by_date_range("2025-06-01", "2025-06-30")

        assert len(results) == 1
        assert results[0]["filepath"] == "/jun.mp3"


class TestDeleteRecording:
    def test_returns_true_when_found(self) -> None:
        rid = _insert_sample_recording()

        assert db.delete_recording(rid) is True
        assert db.get_recording(rid) is None

    def test_returns_false_for_missing_id(self) -> None:
        assert db.delete_recording(9999) is False

    def test_cascades_to_segments_and_words(self) -> None:
        rid = _insert_sample_recording()
        sid = db.insert_segment(rid, 0, "hello world", 0.0, 1.0)
        db.insert_word(rid, sid, 0, "hello", 0.0, 0.5, 0.9)
        db.insert_word(rid, sid, 1, "world", 0.5, 1.0, 0.8)

        db.delete_recording(rid)

        assert db.get_segments(rid) == []
        assert db.get_words(rid) == []

    def test_cascades_to_conversations_and_messages(self) -> None:
        rid = _insert_sample_recording()
        cid = db.create_conversation(rid, "Chat")
        db.add_message(cid, "user", "hello")

        db.delete_recording(rid)

        assert db.get_conversations(rid) == []
        assert db.get_messages(cid) == []


class TestUpdateRecordingSummary:
    def test_sets_summary_and_model(self) -> None:
        rid = _insert_sample_recording()

        db.update_recording_summary(rid, "A nice summary", "gpt-4")

        rec = db.get_recording(rid)
        assert rec is not None
        assert rec["summary"] == "A nice summary"
        assert rec["summary_model"] == "gpt-4"

    def test_clears_summary(self) -> None:
        rid = _insert_sample_recording()
        db.update_recording_summary(rid, "temp", "model")

        db.update_recording_summary(rid, None)

        rec = db.get_recording(rid)
        assert rec is not None
        assert rec["summary"] is None
        assert rec["summary_model"] is None

    def test_returns_false_for_missing_id(self) -> None:
        assert db.update_recording_summary(9999, "x") is False


class TestUpdateRecordingTitle:
    def test_changes_title(self) -> None:
        rid = _insert_sample_recording(title="Old")

        assert db.update_recording_title(rid, "New") is True

        rec = db.get_recording(rid)
        assert rec is not None
        assert rec["title"] == "New"


# ===================================================================
# Segment and Word operations
# ===================================================================


class TestSegmentCRUD:
    def test_insert_and_retrieve(self) -> None:
        rid = _insert_sample_recording()
        sid = db.insert_segment(rid, 0, "first segment", 0.0, 5.0, speaker="SPEAKER_00")

        segs = db.get_segments(rid)

        assert len(segs) == 1
        assert segs[0]["id"] == sid
        assert segs[0]["text"] == "first segment"
        assert segs[0]["speaker"] == "SPEAKER_00"
        assert segs[0]["start_time"] == 0.0
        assert segs[0]["end_time"] == 5.0

    def test_ordered_by_segment_index(self) -> None:
        rid = _insert_sample_recording()
        db.insert_segment(rid, 1, "second", 5.0, 10.0)
        db.insert_segment(rid, 0, "first", 0.0, 5.0)

        segs = db.get_segments(rid)

        assert [s["segment_index"] for s in segs] == [0, 1]


class TestWordCRUD:
    def test_insert_and_retrieve(self) -> None:
        rid = _insert_sample_recording()
        sid = db.insert_segment(rid, 0, "hello world", 0.0, 1.0)
        wid = db.insert_word(rid, sid, 0, "hello", 0.0, 0.5, 0.95)

        words = db.get_words(rid)

        assert len(words) == 1
        assert words[0]["id"] == wid
        assert words[0]["word"] == "hello"
        assert words[0]["confidence"] == 0.95

    def test_ordered_by_start_time(self) -> None:
        rid = _insert_sample_recording()
        sid = db.insert_segment(rid, 0, "hello world", 0.0, 1.0)
        db.insert_word(rid, sid, 1, "world", 0.5, 1.0)
        db.insert_word(rid, sid, 0, "hello", 0.0, 0.5)

        words = db.get_words(rid)

        assert [w["word"] for w in words] == ["hello", "world"]


class TestInsertWordsBatch:
    def test_batch_insert_multiple_words(self) -> None:
        rid = _insert_sample_recording()
        sid = db.insert_segment(rid, 0, "hello beautiful world", 0.0, 1.5)

        batch = [
            {
                "recording_id": rid,
                "segment_id": sid,
                "word_index": 0,
                "word": "hello",
                "start_time": 0.0,
                "end_time": 0.3,
                "confidence": 0.9,
            },
            {
                "recording_id": rid,
                "segment_id": sid,
                "word_index": 1,
                "word": "beautiful",
                "start_time": 0.3,
                "end_time": 0.8,
                "confidence": 0.85,
            },
            {
                "recording_id": rid,
                "segment_id": sid,
                "word_index": 2,
                "word": "world",
                "start_time": 0.8,
                "end_time": 1.2,
                "confidence": 0.95,
            },
        ]
        db.insert_words_batch(batch)

        words = db.get_words(rid)

        assert len(words) == 3
        assert [w["word"] for w in words] == ["hello", "beautiful", "world"]


class TestUpdateRecordingWordCount:
    def test_counts_words_correctly(self) -> None:
        rid = _insert_sample_recording()
        sid = db.insert_segment(rid, 0, "a b c", 0.0, 1.0)
        for i, w in enumerate(["a", "b", "c"]):
            db.insert_word(rid, sid, i, w, i * 0.3, (i + 1) * 0.3)

        db.update_recording_word_count(rid)

        rec = db.get_recording(rid)
        assert rec is not None
        assert rec["word_count"] == 3


# ===================================================================
# FTS search
# ===================================================================


class TestSearchWords:
    def test_fts_matches_inserted_word(self) -> None:
        rid = _insert_sample_recording()
        sid = db.insert_segment(rid, 0, "quantum physics", 0.0, 2.0)
        db.insert_word(rid, sid, 0, "quantum", 0.0, 1.0)
        db.insert_word(rid, sid, 1, "physics", 1.0, 2.0)

        results = db.search_words("quantum")

        assert len(results) >= 1
        assert any(r["word"] == "quantum" for r in results)

    def test_no_match_returns_empty(self) -> None:
        rid = _insert_sample_recording()
        sid = db.insert_segment(rid, 0, "hello", 0.0, 1.0)
        db.insert_word(rid, sid, 0, "hello", 0.0, 1.0)

        results = db.search_words("zzzznonexistent")

        assert results == []

    def test_fts_respects_limit(self) -> None:
        rid = _insert_sample_recording()
        sid = db.insert_segment(rid, 0, "word " * 10, 0.0, 10.0)
        for i in range(10):
            db.insert_word(rid, sid, i, "word", i * 1.0, (i + 1) * 1.0)

        results = db.search_words("word", limit=3)

        assert len(results) <= 3


class TestSearchWordsByDateRange:
    def test_filters_by_date(self) -> None:
        r1 = _insert_sample_recording(filepath="/jan.mp3", recorded_at="2025-01-15T10:00:00")
        s1 = db.insert_segment(r1, 0, "alpha", 0.0, 1.0)
        db.insert_word(r1, s1, 0, "alpha", 0.0, 1.0)

        r2 = _insert_sample_recording(filepath="/jun.mp3", recorded_at="2025-06-15T10:00:00")
        s2 = db.insert_segment(r2, 0, "alpha", 0.0, 1.0)
        db.insert_word(r2, s2, 0, "alpha", 0.0, 1.0)

        results = db.search_words_by_date_range(
            "alpha", start_date="2025-06-01", end_date="2025-06-30"
        )

        assert len(results) == 1
        assert results[0]["recording_id"] == r2


class TestSearchRecordingMetadata:
    def test_matches_filename(self) -> None:
        _insert_sample_recording(filename="meeting_notes.mp3", filepath="/meeting_notes.mp3")

        results = db.search_recording_metadata("meeting", None, None)

        assert len(results) >= 1
        assert any(r["filename"] == "meeting_notes.mp3" for r in results)

    def test_matches_summary(self) -> None:
        rid = _insert_sample_recording(filepath="/sum.mp3")
        db.update_recording_summary(rid, "Discussed quarterly revenue targets")

        results = db.search_recording_metadata("revenue", None, None)

        assert len(results) >= 1


class TestSearchRecordings:
    def test_finds_recording_by_word_content(self) -> None:
        rid = _insert_sample_recording(filepath="/find_me.mp3")
        sid = db.insert_segment(rid, 0, "supercalifragilistic", 0.0, 2.0)
        db.insert_word(rid, sid, 0, "supercalifragilistic", 0.0, 2.0)

        results = db.search_recordings("supercalifragilistic")

        assert len(results) == 1
        assert results[0]["id"] == rid


# ===================================================================
# Conversation / Message CRUD
# ===================================================================


class TestConversationCRUD:
    def test_create_and_retrieve(self) -> None:
        rid = _insert_sample_recording()
        cid = db.create_conversation(rid, "Test Chat")

        convs = db.get_conversations(rid)

        assert len(convs) == 1
        assert convs[0]["id"] == cid
        assert convs[0]["title"] == "Test Chat"

    def test_get_conversation_by_id(self) -> None:
        rid = _insert_sample_recording()
        cid = db.create_conversation(rid, "My Chat")

        conv = db.get_conversation(cid)

        assert conv is not None
        assert conv["title"] == "My Chat"

    def test_get_conversation_returns_none_for_missing(self) -> None:
        assert db.get_conversation(9999) is None

    def test_update_title(self) -> None:
        rid = _insert_sample_recording()
        cid = db.create_conversation(rid, "Old Title")

        db.update_conversation_title(cid, "New Title")
        conv = db.get_conversation(cid)

        assert conv is not None
        assert conv["title"] == "New Title"

    def test_update_response_id(self) -> None:
        rid = _insert_sample_recording()
        cid = db.create_conversation(rid)

        db.update_conversation_response_id(cid, "resp-123")
        conv = db.get_conversation(cid)

        assert conv is not None
        assert conv["response_id"] == "resp-123"

    def test_delete_conversation(self) -> None:
        rid = _insert_sample_recording()
        cid = db.create_conversation(rid)

        assert db.delete_conversation(cid) is True
        assert db.get_conversation(cid) is None

    def test_delete_missing_conversation(self) -> None:
        assert db.delete_conversation(9999) is False


class TestMessageCRUD:
    def test_add_and_retrieve(self) -> None:
        rid = _insert_sample_recording()
        cid = db.create_conversation(rid)
        mid = db.add_message(cid, "user", "Hello!", model="gpt-4", tokens_used=5)

        msgs = db.get_messages(cid)

        assert len(msgs) == 1
        assert msgs[0]["id"] == mid
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello!"
        assert msgs[0]["model"] == "gpt-4"
        assert msgs[0]["tokens_used"] == 5

    def test_messages_ordered_by_created_at(self) -> None:
        rid = _insert_sample_recording()
        cid = db.create_conversation(rid)
        db.add_message(cid, "user", "first")
        db.add_message(cid, "assistant", "second")

        msgs = db.get_messages(cid)

        assert [m["content"] for m in msgs] == ["first", "second"]

    def test_delete_message(self) -> None:
        rid = _insert_sample_recording()
        cid = db.create_conversation(rid)
        mid = db.add_message(cid, "user", "gone")

        assert db.delete_message(mid) is True
        assert db.get_messages(cid) == []

    def test_delete_missing_message(self) -> None:
        assert db.delete_message(9999) is False

    def test_conversation_cascades_to_messages(self) -> None:
        rid = _insert_sample_recording()
        cid = db.create_conversation(rid)
        db.add_message(cid, "user", "msg1")
        db.add_message(cid, "assistant", "msg2")

        db.delete_conversation(cid)

        assert db.get_messages(cid) == []


class TestGetConversationWithMessages:
    def test_returns_conversation_with_messages(self) -> None:
        rid = _insert_sample_recording()
        cid = db.create_conversation(rid, "Full Chat")
        db.add_message(cid, "user", "question")
        db.add_message(cid, "assistant", "answer")

        result = db.get_conversation_with_messages(cid)

        assert result is not None
        assert result["title"] == "Full Chat"
        assert len(result["messages"]) == 2

    def test_returns_none_for_missing(self) -> None:
        assert db.get_conversation_with_messages(9999) is None


# ===================================================================
# Unicode handling
# ===================================================================


class TestUnicodeHandling:
    def test_unicode_in_segment_text(self) -> None:
        rid = _insert_sample_recording(filepath="/uni.mp3")
        db.insert_segment(rid, 0, "日本語テスト 🎙️", 0.0, 1.0)

        segs = db.get_segments(rid)

        assert segs[0]["text"] == "日本語テスト 🎙️"

    def test_unicode_in_word(self) -> None:
        rid = _insert_sample_recording(filepath="/uni2.mp3")
        sid = db.insert_segment(rid, 0, "café", 0.0, 1.0)
        db.insert_word(rid, sid, 0, "café", 0.0, 1.0)

        words = db.get_words(rid)

        assert words[0]["word"] == "café"

    def test_unicode_fts_search(self) -> None:
        rid = _insert_sample_recording(filepath="/uni3.mp3")
        sid = db.insert_segment(rid, 0, "Ökologie", 0.0, 1.0)
        db.insert_word(rid, sid, 0, "Ökologie", 0.0, 1.0)

        results = db.search_words("Ökologie")

        assert len(results) >= 1

    def test_unicode_in_conversation(self) -> None:
        rid = _insert_sample_recording()
        cid = db.create_conversation(rid, "对话标题")
        db.add_message(cid, "user", "你好世界")

        conv = db.get_conversation(cid)
        msgs = db.get_messages(cid)

        assert conv is not None
        assert conv["title"] == "对话标题"
        assert msgs[0]["content"] == "你好世界"


# ===================================================================
# Extended recording operations
# ===================================================================


class TestGetRecordingsForMonth:
    def test_returns_matching_month(self) -> None:
        _insert_sample_recording(filepath="/m1.mp3", recorded_at="2025-03-10T09:00:00")
        _insert_sample_recording(filepath="/m2.mp3", recorded_at="2025-04-10T09:00:00")

        results = db.get_recordings_for_month(2025, 3)

        assert len(results) == 1
        assert results[0]["filepath"] == "/m1.mp3"


class TestGetRecordingsForHour:
    def test_returns_matching_hour(self) -> None:
        _insert_sample_recording(filepath="/h1.mp3", recorded_at="2025-06-15T14:30:00")
        _insert_sample_recording(filepath="/h2.mp3", recorded_at="2025-06-15T15:30:00")

        results = db.get_recordings_for_hour("2025-06-15", 14)

        assert len(results) == 1
        assert results[0]["filepath"] == "/h1.mp3"


class TestUpdateRecordingDate:
    def test_changes_recorded_at(self) -> None:
        rid = _insert_sample_recording(recorded_at="2025-01-01T00:00:00")

        db.update_recording_date(rid, "2025-12-31T23:59:59")

        rec = db.get_recording(rid)
        assert rec is not None
        assert "2025-12-31" in rec["recorded_at"]


class TestGetTranscription:
    def test_returns_segments_with_words(self) -> None:
        rid = _insert_sample_recording()
        sid = db.insert_segment(rid, 0, "hello world", 0.0, 2.0, speaker="A")
        db.insert_word(rid, sid, 0, "hello", 0.0, 1.0, 0.9)
        db.insert_word(rid, sid, 1, "world", 1.0, 2.0, 0.8)

        result = db.get_transcription(rid)

        assert result["recording_id"] == rid
        assert len(result["segments"]) == 1

        seg = result["segments"][0]
        assert seg["speaker"] == "A"
        assert seg["text"] == "hello world"
        assert len(seg["words"]) == 2
        assert seg["words"][0]["word"] == "hello"
        assert seg["words"][1]["word"] == "world"

    def test_empty_recording_returns_no_segments(self) -> None:
        rid = _insert_sample_recording()

        result = db.get_transcription(rid)

        assert result["segments"] == []


class TestRecordingModel:
    def test_to_dict_round_trip(self) -> None:
        data = {
            "id": 1,
            "filename": "test.mp3",
            "filepath": "/test.mp3",
            "title": "Test",
            "duration_seconds": 10.0,
            "recorded_at": "2025-06-15T10:00:00",
            "imported_at": "2025-06-15T10:00:01",
            "word_count": 5,
            "has_diarization": 1,
            "summary": "A summary",
            "summary_model": "gpt-4",
            "transcription_backend": "whisper",
        }
        rec = db.Recording(data)
        d = rec.to_dict()

        assert d["id"] == 1
        assert d["filename"] == "test.mp3"
        assert d["has_diarization"] is True
        assert d["transcription_backend"] == "whisper"

    def test_defaults_for_missing_keys(self) -> None:
        rec = db.Recording({})

        assert rec.id is None
        assert rec.word_count == 0
        assert rec.has_diarization is False


class TestGetRecordingSummary:
    def test_returns_summary(self) -> None:
        rid = _insert_sample_recording()
        db.update_recording_summary(rid, "Key points here")

        assert db.get_recording_summary(rid) == "Key points here"

    def test_returns_none_for_missing(self) -> None:
        assert db.get_recording_summary(9999) is None
