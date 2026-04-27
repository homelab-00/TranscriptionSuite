"""Tests for notebook export route format and capability gating."""

import pytest
from fastapi import HTTPException
from server.api.routes import notebook


def _patch_notebook_data(
    monkeypatch,
    recording: dict,
    segments: list[dict],
    words: list[dict],
) -> None:
    monkeypatch.setattr(notebook, "get_recording", lambda recording_id: recording)
    monkeypatch.setattr(notebook, "get_segments", lambda recording_id: segments)
    monkeypatch.setattr(notebook, "get_words", lambda recording_id: words)


@pytest.mark.asyncio
async def test_pure_note_txt_export_allowed(monkeypatch) -> None:
    recording = {
        "id": 1,
        "title": "Pure note",
        "filename": "pure_note.mp3",
        "recorded_at": "2026-01-10T11:00:00",
        "duration_seconds": 42.0,
        "word_count": 8,
        "has_diarization": 0,
        "summary": None,
    }
    segments = [
        {
            "segment_index": 0,
            "text": "This is pure transcription.",
            "start_time": 0.0,
            "end_time": 42.0,
            "speaker": None,
        }
    ]
    _patch_notebook_data(monkeypatch, recording, segments, words=[])

    response = await notebook.export_recording(1, format="txt")

    assert response.status_code == 200
    # Issue #106: Content-Disposition now carries both an ASCII fallback and a
    # UTF-8 RFC 6266 form, so the legacy filename="..." chunk is a substring
    # rather than the entire trailing slice of the header.
    assert '_export.txt"' in response.headers["Content-Disposition"]
    assert "TRANSCRIPTION EXPORT" in response.body.decode("utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["srt", "ass"])
async def test_pure_note_subtitle_export_rejected(monkeypatch, fmt: str) -> None:
    recording = {
        "id": 1,
        "title": "Pure note",
        "filename": "pure_note.mp3",
        "recorded_at": "2026-01-10T11:00:00",
        "duration_seconds": 42.0,
        "word_count": 8,
        "has_diarization": 0,
    }
    segments = [{"segment_index": 0, "text": "plain", "start_time": 0.0, "end_time": 1.0}]
    _patch_notebook_data(monkeypatch, recording, segments, words=[])

    with pytest.raises(HTTPException) as exc:
        await notebook.export_recording(1, format=fmt)

    assert exc.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["srt", "ass"])
async def test_timestamp_capable_note_subtitle_export_allowed(
    monkeypatch,
    fmt: str,
) -> None:
    recording = {
        "id": 2,
        "title": "Timestamp note",
        "filename": "timestamp_note.mp3",
        "recorded_at": "2026-01-10T12:00:00",
        "duration_seconds": 10.0,
        "word_count": 3,
        "has_diarization": 0,
    }
    segments = [
        {
            "id": 100,
            "segment_index": 0,
            "speaker": None,
            "text": "one two three",
            "start_time": 0.0,
            "end_time": 1.5,
        }
    ]
    words = [
        {"segment_id": 100, "word": "one", "start_time": 0.0, "end_time": 0.4},
        {"segment_id": 100, "word": "two", "start_time": 0.5, "end_time": 0.9},
        {"segment_id": 100, "word": "three", "start_time": 1.0, "end_time": 1.4},
    ]
    _patch_notebook_data(monkeypatch, recording, segments, words=words)

    response = await notebook.export_recording(2, format=fmt)
    output = response.body.decode("utf-8")

    assert response.status_code == 200
    if fmt == "srt":
        assert "-->" in output
        assert '_export.srt"' in response.headers["Content-Disposition"]
    else:
        assert "[Events]" in output
        assert '_export.ass"' in response.headers["Content-Disposition"]


@pytest.mark.asyncio
async def test_timestamp_capable_note_txt_export_rejected(monkeypatch) -> None:
    recording = {
        "id": 2,
        "title": "Timestamp note",
        "filename": "timestamp_note.mp3",
        "recorded_at": "2026-01-10T12:00:00",
        "duration_seconds": 10.0,
        "word_count": 3,
        "has_diarization": 0,
    }
    segments = [
        {
            "id": 100,
            "segment_index": 0,
            "speaker": None,
            "text": "one two three",
            "start_time": 0.0,
            "end_time": 1.5,
        }
    ]
    words = [{"segment_id": 100, "word": "one", "start_time": 0.0, "end_time": 0.4}]
    _patch_notebook_data(monkeypatch, recording, segments, words=words)

    with pytest.raises(HTTPException) as exc:
        await notebook.export_recording(2, format="txt")

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_json_export_rejected_for_any_note() -> None:
    with pytest.raises(HTTPException) as exc:
        await notebook.export_recording(999, format="json")

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_export_with_greek_title_uses_rfc5987(monkeypatch) -> None:
    """Issue #106: export Content-Disposition must survive non-ASCII titles."""
    recording = {
        "id": 3,
        "title": "Συνομιλία",
        "filename": "synomilia.mp3",
        "recorded_at": "2026-01-10T11:00:00",
        "duration_seconds": 12.0,
        "word_count": 4,
        "has_diarization": 0,
        "summary": None,
    }
    segments = [
        {
            "segment_index": 0,
            "text": "γειά σου κόσμε",
            "start_time": 0.0,
            "end_time": 12.0,
            "speaker": None,
        }
    ]
    _patch_notebook_data(monkeypatch, recording, segments, words=[])

    response = await notebook.export_recording(3, format="txt")

    assert response.status_code == 200
    cd = response.headers["Content-Disposition"]
    # ASCII fallback: 'Συνομιλία' (9 letters) → 9 '?' chars, then '_export.txt'.
    assert 'filename="?????????_export.txt"' in cd
    # UTF-8 form preserves the Greek title via percent-encoding.
    assert "filename*=UTF-8''" in cd
    assert "%CE%A3" in cd  # leading 'Σ' percent-encoded
    # Header must round-trip through Latin-1 — Uvicorn's encoding requirement.
    cd.encode("latin-1")


# Issue #98 regression coverage: NULL numeric columns and unexpected exceptions
# must NOT bubble up as FastAPI's generic "Internal server error" 500.


@pytest.mark.asyncio
async def test_pure_note_txt_export_handles_null_duration(monkeypatch) -> None:
    """recording.duration_seconds is NULL — must not crash arithmetic in TXT path."""
    recording = {
        "id": 1,
        "title": "Null duration note",
        "filename": "null_duration.mp3",
        "recorded_at": "2026-01-10T11:00:00",
        "duration_seconds": None,  # <-- the bug trigger
        "word_count": None,
        "has_diarization": 0,
        "summary": None,
    }
    segments = [
        {"segment_index": 0, "text": "hello", "start_time": 0.0, "end_time": 1.0, "speaker": None}
    ]
    _patch_notebook_data(monkeypatch, recording, segments, words=[])

    response = await notebook.export_recording(1, format="txt")

    assert response.status_code == 200
    body = response.body.decode("utf-8")
    assert "Duration: 0 seconds" in body
    assert "Word Count: 0" in body
    assert "TRANSCRIPTION EXPORT" in body


@pytest.mark.asyncio
async def test_pure_note_txt_export_handles_null_segment_start_time(monkeypatch) -> None:
    """segment.start_time is NULL — must render `[00:00]` and stay 200."""
    recording = {
        "id": 1,
        "title": "Null start note",
        "filename": "null_start.mp3",
        "recorded_at": "2026-01-10T11:00:00",
        "duration_seconds": 30.0,
        "word_count": 2,
        "has_diarization": 0,
    }
    segments = [
        {
            "segment_index": 0,
            "text": "first segment",
            "start_time": None,
            "end_time": None,
            "speaker": None,
        },
        {
            "segment_index": 1,
            "text": "second segment",
            "start_time": 5.0,
            "end_time": 10.0,
            "speaker": None,
        },
    ]
    _patch_notebook_data(monkeypatch, recording, segments, words=[])

    response = await notebook.export_recording(1, format="txt")

    assert response.status_code == 200
    body = response.body.decode("utf-8")
    assert "[00:00] first segment" in body
    assert "[00:05] second segment" in body


@pytest.mark.asyncio
async def test_pure_note_txt_export_handles_combined_nulls(monkeypatch) -> None:
    """Combination of NULL duration + NULL start_time + missing recorded_at — must stay 200."""
    recording = {
        "id": 1,
        "title": None,  # falls back to filename
        "filename": "combined_nulls.mp3",
        "recorded_at": None,
        "duration_seconds": None,
        "word_count": None,
        "has_diarization": 0,
    }
    segments = [
        {
            "segment_index": 0,
            "text": "only segment",
            "start_time": None,
            "end_time": None,
            "speaker": None,
        }
    ]
    _patch_notebook_data(monkeypatch, recording, segments, words=[])

    response = await notebook.export_recording(1, format="txt")

    assert response.status_code == 200
    body = response.body.decode("utf-8")
    assert "Duration: 0 seconds" in body
    assert "[00:00] only segment" in body


@pytest.mark.asyncio
async def test_export_unexpected_exception_returns_concrete_detail(monkeypatch) -> None:
    """Unhandled errors must surface as 500 with a concrete detail, NOT FastAPI's
    generic 'Internal server error' (Issue #98)."""

    def boom(_recording_id: int) -> dict:
        raise RuntimeError("simulated db corruption")

    monkeypatch.setattr(notebook, "get_recording", boom)

    with pytest.raises(HTTPException) as exc:
        await notebook.export_recording(1, format="txt")

    assert exc.value.status_code == 500
    assert "RuntimeError" in exc.value.detail
    assert "simulated db corruption" in exc.value.detail
    # The whole point: the user no longer sees the opaque generic envelope.
    assert exc.value.detail != "Internal server error"
