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
    assert response.headers["Content-Disposition"].endswith('_export.txt"')
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
    segments = [
        {"segment_index": 0, "text": "plain", "start_time": 0.0, "end_time": 1.0}
    ]
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
        assert response.headers["Content-Disposition"].endswith('_export.srt"')
    else:
        assert "[Events]" in output
        assert response.headers["Content-Disposition"].endswith('_export.ass"')


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
