"""Tests for the speaker-labelled plain-text formatter (GH-258)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from server.core.formatters import format_speaker_text


@dataclass
class _FakeResult:
    """Minimal stand-in for TranscriptionResult (avoids the ML import chain)."""

    text: str = ""
    language: str | None = None
    language_probability: float = 0.0
    duration: float = 0.0
    segments: list[dict[str, Any]] = field(default_factory=list)
    words: list[dict[str, Any]] = field(default_factory=list)
    num_speakers: int = 0


def _result(segments, text="flat fallback text"):
    return _FakeResult(text=text, segments=segments)


def test_alternating_speakers_become_labelled_paragraphs():
    result = _result(
        [
            {"text": "Good morning.", "speaker": "SPEAKER_00"},
            {"text": "Morning.", "speaker": "SPEAKER_01"},
        ]
    )

    assert format_speaker_text(result) == "SPEAKER_00: Good morning.\n\nSPEAKER_01: Morning."


def test_consecutive_same_speaker_segments_coalesce_into_one_paragraph():
    result = _result(
        [
            {"text": "Good morning.", "speaker": "SPEAKER_00"},
            {"text": "Let us begin.", "speaker": "SPEAKER_00"},
            {"text": "Ready.", "speaker": "SPEAKER_01"},
        ]
    )

    assert format_speaker_text(result) == (
        "SPEAKER_00: Good morning. Let us begin.\n\nSPEAKER_01: Ready."
    )


def test_returns_flat_text_when_no_segment_carries_a_speaker():
    result = _result([{"text": "Just dictation."}, {"text": "No speakers here."}])

    assert format_speaker_text(result) == "flat fallback text"


def test_returns_flat_text_when_there_are_no_segments():
    assert format_speaker_text(_result([])) == "flat fallback text"


def test_unknown_sentinel_yields_an_unlabelled_paragraph():
    result = _result(
        [
            {"text": "Attributed line.", "speaker": "SPEAKER_00"},
            {"text": "Unattributable line.", "speaker": "UNKNOWN"},
        ]
    )

    assert format_speaker_text(result) == "SPEAKER_00: Attributed line.\n\nUnattributable line."


def test_blank_and_whitespace_segments_are_skipped():
    result = _result(
        [
            {"text": "Real line.", "speaker": "SPEAKER_00"},
            {"text": "   ", "speaker": "SPEAKER_01"},
            {"text": "", "speaker": "SPEAKER_01"},
            {"text": "Second real line.", "speaker": "SPEAKER_00"},
        ]
    )

    # The blank SPEAKER_01 segments are dropped before the speaker is read, so
    # the two SPEAKER_00 turns coalesce. Breaking the run on an invisible turn
    # would emit two consecutive paragraphs both labelled SPEAKER_00 with
    # nothing between them, which reads as a rendering bug.
    assert format_speaker_text(result) == "SPEAKER_00: Real line. Second real line."


def test_missing_text_key_is_tolerated():
    result = _result([{"speaker": "SPEAKER_00"}, {"text": "Present.", "speaker": "SPEAKER_00"}])

    assert format_speaker_text(result) == "SPEAKER_00: Present."
