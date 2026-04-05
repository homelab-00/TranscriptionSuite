"""Tests for Audio Notebook CRUD routes.

[P2] Covers P2-ROUTE-001: list, detail, delete, title update, calendar, export.

Follows the direct-call pattern: import the route module, monkeypatch the
database functions it imports at module level, call handlers directly via
asyncio.run(), assert on returned responses or HTTPException.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from server.api.routes import notebook

# ── Helpers ──────────────────────────────────────────────────────────────────


def _recording(
    recording_id: int = 1,
    *,
    title: str = "Test Recording",
    filepath: str = "/data/audio/test.wav",
    has_diarization: bool = False,
    word_count: int = 0,
    duration_seconds: float = 120.0,
) -> dict:
    """Minimal recording dict matching the database schema."""
    return {
        "id": recording_id,
        "filename": "test.wav",
        "filepath": filepath,
        "title": title,
        "duration_seconds": duration_seconds,
        "recorded_at": "2026-04-01 10:00:00",
        "imported_at": None,
        "word_count": word_count,
        "has_diarization": has_diarization,
        "summary": None,
        "summary_model": None,
        "transcription_backend": "whisper",
    }


def _segment(seg_id: int = 1, text: str = "Hello world") -> dict:
    return {
        "id": seg_id,
        "recording_id": 1,
        "text": text,
        "start_time": 0.0,
        "end_time": 5.0,
        "speaker": None,
    }


def _word(word: str = "Hello", start: float = 0.0, end: float = 0.5) -> dict:
    return {
        "word": word,
        "start_time": start,
        "end_time": end,
        "confidence": 0.95,
        "segment_id": 1,
    }


# ── P2-ROUTE-001: Notebook CRUD ─────────────────────────────────────────────


@pytest.mark.p2
class TestP2Route001ListRecordings:
    """[P2] GET /api/notebook/recordings — list recordings."""

    def test_list_returns_all_recordings(self, monkeypatch):
        recs = [_recording(1), _recording(2, title="Second")]
        monkeypatch.setattr(notebook, "get_all_recordings", lambda: recs)

        # Pass explicit None to bypass FastAPI Query() defaults which are truthy objects
        result = asyncio.run(notebook.list_recordings(start_date=None, end_date=None))

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["title"] == "Second"


@pytest.mark.p2
class TestP2Route001ListRecordingsAsymmetricDates:
    """[P2] Asymmetric date params: only start_date or only end_date provided."""

    def test_only_start_date_returns_all_recordings(self, monkeypatch):
        """When start_date is provided but end_date is None, the handler
        ignores the date filter and returns all recordings."""
        recs = [_recording(1), _recording(2, title="Second")]
        monkeypatch.setattr(notebook, "get_all_recordings", lambda: recs)
        # get_recordings_by_date_range should NOT be called
        monkeypatch.setattr(
            notebook,
            "get_recordings_by_date_range",
            lambda _s, _e: pytest.fail("should not filter by date range"),
        )

        result = asyncio.run(notebook.list_recordings(start_date="2026-01-01", end_date=None))

        assert len(result) == 2

    def test_only_end_date_returns_all_recordings(self, monkeypatch):
        """When end_date is provided but start_date is None, the handler
        ignores the date filter and returns all recordings."""
        recs = [_recording(1)]
        monkeypatch.setattr(notebook, "get_all_recordings", lambda: recs)
        monkeypatch.setattr(
            notebook,
            "get_recordings_by_date_range",
            lambda _s, _e: pytest.fail("should not filter by date range"),
        )

        result = asyncio.run(notebook.list_recordings(start_date=None, end_date="2026-12-31"))

        assert len(result) == 1


@pytest.mark.p2
class TestP2Route001RecordingDetail:
    """[P2] GET /api/notebook/recordings/{id} — recording detail."""

    def test_detail_returns_recording_with_segments_and_words(self, monkeypatch):
        rec = _recording(1)
        segs = [_segment(1, "Hello world")]
        words = [_word("Hello"), _word("world", 0.5, 1.0)]

        monkeypatch.setattr(notebook, "get_recording", lambda _id: rec)
        monkeypatch.setattr(notebook, "get_segments", lambda _id: segs)
        monkeypatch.setattr(notebook, "get_words", lambda _id: words)

        result = asyncio.run(notebook.get_recording_detail(1))

        assert result["id"] == 1
        assert result["title"] == "Test Recording"
        assert len(result["segments"]) == 1
        assert len(result["words"]) == 2

    def test_detail_404_when_not_found(self, monkeypatch):
        monkeypatch.setattr(notebook, "get_recording", lambda _id: None)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(notebook.get_recording_detail(999))
        assert exc.value.status_code == 404


@pytest.mark.p2
class TestP2Route001DeleteRecording:
    """[P2] DELETE /api/notebook/recordings/{id} — remove recording."""

    def test_delete_returns_status(self, monkeypatch, tmp_path):
        audio = tmp_path / "test.wav"
        audio.write_bytes(b"RIFF")
        rec = _recording(1, filepath=str(audio))
        monkeypatch.setattr(notebook, "get_recording", lambda _id: rec)
        monkeypatch.setattr(notebook, "delete_recording", lambda _id: True)

        result = asyncio.run(notebook.remove_recording(1))

        assert result["status"] == "deleted"
        assert result["id"] == "1"

    def test_delete_404_when_not_found(self, monkeypatch):
        monkeypatch.setattr(notebook, "get_recording", lambda _id: None)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(notebook.remove_recording(999))
        assert exc.value.status_code == 404


@pytest.mark.p2
class TestP2Route001UpdateTitle:
    """[P2] PATCH /api/notebook/recordings/{id}/title — update title."""

    def test_update_title_success(self, monkeypatch):
        rec = _recording(1)
        monkeypatch.setattr(notebook, "get_recording", lambda _id: rec)
        monkeypatch.setattr(notebook, "update_recording_title", lambda _id, _t: True)

        body = notebook.TitleUpdate(title="New Title")
        result = asyncio.run(notebook.update_title_patch(1, body))

        assert result["status"] == "updated"
        assert result["title"] == "New Title"

    def test_update_title_400_on_empty(self, monkeypatch):
        rec = _recording(1)
        monkeypatch.setattr(notebook, "get_recording", lambda _id: rec)

        body = notebook.TitleUpdate(title="   ")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(notebook.update_title_patch(1, body))
        assert exc.value.status_code == 400
        assert "empty" in exc.value.detail.lower()


@pytest.mark.p2
class TestP2Route001Calendar:
    """[P2] GET /api/notebook/calendar — calendar data."""

    def test_calendar_returns_grouped_days(self, monkeypatch):
        recs = [
            {**_recording(1), "recorded_at": "2026-04-01 10:00:00"},
            {**_recording(2), "recorded_at": "2026-04-01 14:00:00"},
            {**_recording(3), "recorded_at": "2026-04-15 09:00:00"},
        ]
        monkeypatch.setattr(notebook, "get_recordings_by_date_range", lambda _s, _e: recs)

        result = asyncio.run(notebook.get_calendar_data(year=2026, month=4))

        assert result["year"] == 2026
        assert result["month"] == 4
        assert result["total_recordings"] == 3
        assert len(result["days"]["2026-04-01"]) == 2
        assert len(result["days"]["2026-04-15"]) == 1


@pytest.mark.p2
class TestP2Route001Export:
    """[P2] GET /api/notebook/recordings/{id}/export — export recording."""

    def test_export_txt_returns_content(self, monkeypatch):
        rec = _recording(1, has_diarization=False, word_count=0)
        segs = [_segment(1, "Hello world")]

        monkeypatch.setattr(notebook, "get_recording", lambda _id: rec)
        monkeypatch.setattr(notebook, "get_segments", lambda _id: segs)
        monkeypatch.setattr(notebook, "get_words", lambda _id: [])

        result = asyncio.run(notebook.export_recording(1, format="txt"))

        # Response is a fastapi Response with body content
        body = result.body.decode("utf-8") if hasattr(result.body, "decode") else str(result.body)
        assert "TRANSCRIPTION EXPORT" in body
        assert "Hello world" in body

    def test_export_400_on_unsupported_format(self, monkeypatch):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(notebook.export_recording(1, format="pdf"))
        assert exc.value.status_code == 400
        assert "Unsupported" in exc.value.detail
