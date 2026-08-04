"""Tests for the Markdown conversation export (GH-279).

Covers the pure generator (core/markdown_export.py) and the ``format=md``
branch of GET /api/notebook/recordings/{id}/export using the direct-call
route pattern from test_notebook_export_route.py.
"""

from __future__ import annotations

import importlib

import pytest
from server.api.routes import notebook
from server.core.markdown_export import format_markdown_timestamp, stream_markdown

# ── Helpers ───────────────────────────────────────────────────────────────────


def _render(recording: dict, segments: list[dict]) -> str:
    return "".join(stream_markdown(recording, iter(segments)))


async def _drain(response) -> str:
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


_RECORDING = {
    "id": 1,
    "title": "Friday Meeting - Part 2",
    "filename": "friday.mp3",
    "recorded_at": "2026-07-10T14:53:00",
    "duration_seconds": 120.0,
    "word_count": 12,
    "has_diarization": 1,
}


# ── format_markdown_timestamp ────────────────────────────────────────────────


class TestFormatMarkdownTimestamp:
    def test_zero_pads_minutes_and_seconds(self):
        assert format_markdown_timestamp(44.2) == "00:44"

    def test_minutes_roll_past_59_for_long_recordings(self):
        assert format_markdown_timestamp(3672.9) == "61:12"

    def test_zero(self):
        assert format_markdown_timestamp(0.0) == "00:00"

    def test_negative_clamps_to_zero(self):
        assert format_markdown_timestamp(-3.0) == "00:00"

    def test_non_numeric_defaults_to_zero(self):
        assert format_markdown_timestamp(None) == "00:00"  # type: ignore[arg-type]


# ── stream_markdown ──────────────────────────────────────────────────────────


class TestStreamMarkdown:
    def test_header_title_date_separator(self):
        out = _render(_RECORDING, [])
        assert out.startswith("# Friday Meeting - Part 2\n\n")
        assert "**Date:** July 10, 2026 at 02:53 PM\n\n" in out
        assert "---\n\n" in out

    def test_speaker_turn_line_format(self):
        segments = [
            {"speaker": "Speaker 3", "text": "Not enough memory.", "start_time": 44.2},
        ]
        out = _render(_RECORDING, segments)
        # Hard line break: two trailing spaces before the newline.
        assert "**Speaker 3** *[00:44]*: Not enough memory.  \n" in out

    def test_consecutive_same_speaker_segments_coalesce(self):
        segments = [
            {"speaker": "Speaker 1", "text": "Yes, I will let you decide.", "start_time": 48.0},
            {"speaker": "Speaker 1", "text": "Which one should go in.", "start_time": 49.5},
            {"speaker": "Speaker 2", "text": "Okay.", "start_time": 51.0},
        ]
        out = _render(_RECORDING, segments)
        assert (
            "**Speaker 1** *[00:48]*: Yes, I will let you decide. Which one should go in.  \n"
            in out
        )
        assert "**Speaker 2** *[00:51]*: Okay.  \n" in out
        # Only one Speaker 1 line — the two segments merged into one turn.
        assert out.count("**Speaker 1**") == 1

    def test_alternating_speakers_keep_separate_lines(self):
        segments = [
            {"speaker": "Speaker 1", "text": "One.", "start_time": 1.0},
            {"speaker": "Speaker 2", "text": "Two.", "start_time": 2.0},
            {"speaker": "Speaker 1", "text": "Three.", "start_time": 3.0},
        ]
        out = _render(_RECORDING, segments)
        assert out.count("**Speaker 1**") == 2
        assert out.count("**Speaker 2**") == 1

    def test_non_diarized_degrades_to_plain_paragraphs(self):
        segments = [
            {"speaker": None, "text": "Hello world.", "start_time": 0.0},
        ]
        out = _render({"title": "Note"}, segments)
        assert "# Note\n\n" in out
        assert "---\n\n" in out
        assert "Hello world.\n" in out
        assert "**" not in out.replace("**Date:**", "")
        assert "*[" not in out

    def test_missing_recorded_at_omits_date_line(self):
        out = _render({"title": "Note"}, [])
        assert "**Date:**" not in out

    def test_unparseable_recorded_at_falls_back_to_raw_string(self):
        out = _render({"title": "Note", "recorded_at": "sometime"}, [])
        assert "**Date:** sometime\n\n" in out

    def test_empty_text_segments_skipped(self):
        segments = [
            {"speaker": "Speaker 1", "text": "   ", "start_time": 1.0},
            {"speaker": "Speaker 2", "text": "Real text.", "start_time": 2.0},
        ]
        out = _render(_RECORDING, segments)
        assert "**Speaker 1**" not in out
        assert "**Speaker 2** *[00:02]*: Real text.  \n" in out

    def test_title_falls_back_to_filename_then_default(self):
        assert _render({"filename": "a.mp3"}, []).startswith("# a.mp3\n\n")
        assert _render({}, []).startswith("# Recording\n\n")

    def test_null_start_time_renders_zero_timestamp(self):
        segments = [{"speaker": "Speaker 1", "text": "Hi.", "start_time": None}]
        out = _render(_RECORDING, segments)
        assert "**Speaker 1** *[00:00]*: Hi.  \n" in out


# ── GET /recordings/{id}/export?format=md ────────────────────────────────────


def _patch_md_route_data(
    monkeypatch,
    recording: dict,
    segments: list[dict],
    aliases: dict[str, str] | None = None,
) -> None:
    db_module = importlib.import_module("server.database.database")
    alias_repo = importlib.import_module("server.database.alias_repository")
    monkeypatch.setattr(notebook, "get_recording", lambda recording_id: recording)
    monkeypatch.setattr(db_module, "iter_segments", lambda recording_id: iter(segments))
    monkeypatch.setattr(alias_repo, "alias_map", lambda recording_id: aliases or {})


@pytest.mark.asyncio
async def test_md_export_streams_markdown_with_headers(monkeypatch) -> None:
    segments = [
        {"speaker": "SPEAKER_00", "text": "Hello there.", "start_time": 0.5},
        {"speaker": "SPEAKER_01", "text": "Hi.", "start_time": 3.0},
    ]
    _patch_md_route_data(monkeypatch, _RECORDING, segments)

    response = await notebook.export_recording(1, format="md")

    assert response.status_code == 200
    assert response.media_type == "text/markdown; charset=utf-8"
    assert '.md"' in response.headers["Content-Disposition"]
    content = await _drain(response)
    assert content.startswith("# Friday Meeting - Part 2\n\n")
    # Raw diarization labels are substituted to first-appearance numbering.
    assert "**Speaker 1** *[00:00]*: Hello there.  \n" in content
    assert "**Speaker 2** *[00:03]*: Hi.  \n" in content


@pytest.mark.asyncio
async def test_md_export_applies_user_aliases(monkeypatch) -> None:
    segments = [
        {"speaker": "SPEAKER_00", "text": "Hello.", "start_time": 0.0},
        {"speaker": "SPEAKER_01", "text": "Hi.", "start_time": 2.0},
    ]
    _patch_md_route_data(
        monkeypatch,
        _RECORDING,
        segments,
        aliases={"SPEAKER_00": "Elena"},
    )

    response = await notebook.export_recording(1, format="md")

    content = await _drain(response)
    assert "**Elena** *[00:00]*: Hello.  \n" in content
    # Unaliased speakers keep first-appearance numbering.
    assert "**Speaker 1** *[00:02]*: Hi.  \n" in content


@pytest.mark.asyncio
async def test_md_export_allowed_for_pure_note(monkeypatch) -> None:
    """Unlike SRT/ASS, markdown must work for notes without diarization/words."""
    recording = {
        "id": 1,
        "title": "Pure note",
        "filename": "pure.mp3",
        "recorded_at": "2026-01-10T11:00:00",
        "duration_seconds": 42.0,
        "word_count": 0,
        "has_diarization": 0,
    }
    segments = [{"speaker": None, "text": "Just text.", "start_time": 0.0}]
    _patch_md_route_data(monkeypatch, recording, segments)

    response = await notebook.export_recording(1, format="md")

    assert response.status_code == 200
    content = await _drain(response)
    assert "Just text.\n" in content


@pytest.mark.asyncio
async def test_md_export_404_when_recording_missing(monkeypatch) -> None:
    from fastapi import HTTPException

    monkeypatch.setattr(notebook, "get_recording", lambda recording_id: None)

    with pytest.raises(HTTPException) as exc:
        await notebook.export_recording(999, format="md")
    assert exc.value.status_code == 404
