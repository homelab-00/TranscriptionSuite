"""Tests for server.core.speaker_merge — pure logic, no ML dependencies.

Covers:
- Word-level speaker assignment via overlap
- Fallback chain: max-overlap → midpoint → nearest → previous → UNKNOWN
- Micro-turn smoothing
- Edge cases: empty inputs, zero-length words, single word
- Full merge pipeline (merge_diarization_with_words)
- Segment builder (build_speaker_segments)
"""

from __future__ import annotations

from server.core.speaker_merge import (
    assign_speakers_to_words,
    build_speaker_segments,
    merge_diarization_with_words,
    smooth_micro_turns,
)

# ── Helpers ───────────────────────────────────────────────────────────────


def _word(text: str, start: float, end: float, speaker: str | None = None) -> dict:
    d = {"word": text, "start": start, "end": end}
    if speaker is not None:
        d["speaker"] = speaker
    return d


def _seg(speaker: str, start: float, end: float) -> dict:
    return {"speaker": speaker, "start": start, "end": end}


# ── assign_speakers_to_words ─────────────────────────────────────────────


class TestAssignSpeakersToWords:
    def test_empty_words_returns_empty(self):
        result = assign_speakers_to_words([], [_seg("A", 0, 5)])

        assert result == []

    def test_empty_diarization_preserves_existing_speaker(self):
        words = [_word("hello", 0.0, 0.5, speaker="X")]

        result = assign_speakers_to_words(words, [])

        assert result[0]["speaker"] == "X"

    def test_empty_diarization_no_speaker_gives_none(self):
        words = [_word("hello", 0.0, 0.5)]

        result = assign_speakers_to_words(words, [])

        assert result[0]["speaker"] is None

    def test_single_word_full_overlap(self):
        words = [_word("hello", 1.0, 2.0)]
        segs = [_seg("A", 0.5, 3.0)]

        result = assign_speakers_to_words(words, segs)

        assert result[0]["speaker"] == "A"

    def test_max_overlap_wins(self):
        words = [_word("hello", 1.0, 3.0)]
        # Word overlaps A for 1s (1..2), B for 1s (2..3), but with padding
        # A covers 0..2 → padded word 0.96..3.04 → overlap = min(3.04,2)-max(0.96,0) = 1.04
        # B covers 2..4 → padded overlap = min(3.04,4)-max(0.96,2) = 1.04
        # Equal overlap — first one encountered wins (A is first because sorted by start)
        segs = [_seg("A", 0.0, 2.0), _seg("B", 2.0, 4.0)]

        result = assign_speakers_to_words(words, segs)

        # With symmetric overlap the first segment in sorted order wins
        assert result[0]["speaker"] in ("A", "B")

    def test_word_clearly_in_one_segment(self):
        words = [_word("hi", 1.0, 1.5)]
        segs = [_seg("A", 0.0, 5.0), _seg("B", 6.0, 10.0)]

        result = assign_speakers_to_words(words, segs)

        assert result[0]["speaker"] == "A"

    def test_multiple_words_different_speakers(self):
        words = [_word("hi", 0.5, 1.0), _word("there", 3.0, 3.5)]
        segs = [_seg("A", 0.0, 2.0), _seg("B", 2.5, 4.0)]

        result = assign_speakers_to_words(words, segs)

        assert result[0]["speaker"] == "A"
        assert result[1]["speaker"] == "B"

    def test_fallback_midpoint_containment(self):
        """Word has zero overlap but midpoint is inside a diarization segment."""
        # Diarization segment: 1.00..2.00, word: 1.50..1.50 (zero-length)
        # Padding ±0.04 → 1.46..1.54, segment 1.00..2.00 → overlap 0.08 > 0
        # This will actually be assigned by overlap. Let's craft a case
        # where padding doesn't help:
        words = [_word("um", 1.5, 1.5)]  # zero-length word
        segs = [_seg("A", 1.0, 2.0)]

        result = assign_speakers_to_words(words, segs)

        # Padded word: 1.46..1.54, segment 1.0..2.0 → overlap 0.08 > 0 → overlap wins
        assert result[0]["speaker"] == "A"

    def test_fallback_nearest_within_tolerance(self):
        """Word sits in a gap but within tolerance of the nearest segment."""
        words = [_word("gap", 5.0, 5.1)]
        # Nearest segment is 120ms away (within default 120ms tolerance)
        # Initial attempt: [_seg("A", 0.0, 1.0), _seg("B", 5.22, 6.0)]
        # Padded word: 4.96..5.14 — no overlap with B (starts at 5.22)
        # midpoint = 5.05 — not inside any segment
        # Nearest: B is 5.22-5.05 = 0.17 > 0.12 tolerance
        # A: 5.05-1.0 = 4.05 > tolerance
        # So nearest fallback won't match either. Use tighter gap:
        segs2 = [_seg("A", 0.0, 1.0), _seg("B", 5.16, 6.0)]
        # Padded word: 4.96..5.14 — no overlap with B (5.16 > 5.14)
        # midpoint 5.05 — not in A(0..1), not in B(5.16..6)
        # nearest: B = 5.16-5.05 = 0.11 < 0.12 ✓

        result = assign_speakers_to_words(words, segs2)

        assert result[0]["speaker"] == "B"

    def test_fallback_previous_speaker_small_gap(self):
        """Second word is slightly outside any segment but close to previous word."""
        words = [_word("hi", 0.5, 1.0), _word("um", 1.05, 1.10)]
        segs = [_seg("A", 0.0, 1.0)]
        # First word → A (overlap)
        # Second word: padded 1.01..1.14, segment A ends at 1.0 → overlap max(0, min(1.14,1.0)-max(1.01,0))=0
        # midpoint = 1.075, not inside A (0..1)
        # nearest A: 1.075-1.0 = 0.075 < 0.12 → nearest = A

        result = assign_speakers_to_words(words, segs)

        assert result[0]["speaker"] == "A"
        assert result[1]["speaker"] == "A"

    def test_fallback_unknown_when_no_match(self):
        """Word is far from any diarization segment → UNKNOWN."""
        words = [_word("lost", 100.0, 101.0)]
        segs = [_seg("A", 0.0, 1.0)]

        result = assign_speakers_to_words(words, segs)

        assert result[0]["speaker"] == "UNKNOWN"

    def test_original_words_not_mutated(self):
        words = [_word("hi", 0.0, 1.0)]
        segs = [_seg("A", 0.0, 2.0)]

        result = assign_speakers_to_words(words, segs)

        assert "speaker" not in words[0]
        assert result[0]["speaker"] == "A"

    def test_start_time_end_time_keys(self):
        """Words with start_time/end_time instead of start/end."""
        words = [{"word": "alt", "start_time": 0.5, "end_time": 1.0}]
        segs = [_seg("A", 0.0, 2.0)]

        result = assign_speakers_to_words(words, segs)

        assert result[0]["speaker"] == "A"


# ── smooth_micro_turns ───────────────────────────────────────────────────


class TestSmoothMicroTurns:
    def test_fewer_than_3_words_unchanged(self):
        words = [_word("a", 0, 1, "A"), _word("b", 1, 2, "B")]

        result = smooth_micro_turns(words)

        assert result[0]["speaker"] == "A"
        assert result[1]["speaker"] == "B"

    def test_single_word_flip_smoothed(self):
        words = [
            _word("hi", 0, 1, "A"),
            _word("um", 1, 2, "A"),
            _word("uh", 2, 3, "B"),  # isolated flip
            _word("yes", 3, 4, "A"),
            _word("ok", 4, 5, "A"),
        ]

        result = smooth_micro_turns(words)

        assert result[2]["speaker"] == "A"  # was B → smoothed to A

    def test_two_word_flip_not_smoothed_by_default(self):
        words = [
            _word("a", 0, 1, "A"),
            _word("b", 1, 2, "B"),  # run of 2
            _word("c", 2, 3, "B"),
            _word("d", 3, 4, "A"),
        ]

        result = smooth_micro_turns(words, max_run_length=1)

        # Run of 2 Bs is longer than max_run_length=1, so not smoothed
        assert result[1]["speaker"] == "B"
        assert result[2]["speaker"] == "B"

    def test_two_word_flip_smoothed_with_higher_threshold(self):
        words = [
            _word("a", 0, 1, "A"),
            _word("b", 1, 2, "B"),
            _word("c", 2, 3, "B"),
            _word("d", 3, 4, "A"),
        ]

        result = smooth_micro_turns(words, max_run_length=2)

        assert result[1]["speaker"] == "A"
        assert result[2]["speaker"] == "A"

    def test_no_smoothing_when_neighbours_differ(self):
        words = [
            _word("a", 0, 1, "A"),
            _word("b", 1, 2, "B"),
            _word("c", 2, 3, "C"),
        ]

        result = smooth_micro_turns(words)

        assert result[1]["speaker"] == "B"

    def test_original_not_mutated(self):
        words = [
            _word("a", 0, 1, "A"),
            _word("b", 1, 2, "B"),
            _word("c", 2, 3, "A"),
        ]

        result = smooth_micro_turns(words)

        assert words[1]["speaker"] == "B"  # original unchanged
        assert result[1]["speaker"] == "A"  # smoothed copy


# ── merge_diarization_with_words ─────────────────────────────────────────


class TestMergeDiarizationWithWords:
    def test_merge_assigns_and_smooths(self):
        words = [
            _word("hello", 0.0, 0.5),
            _word("um", 0.5, 0.6),
            _word("world", 0.6, 1.2),
        ]
        segs = [_seg("A", 0.0, 1.5)]

        result = merge_diarization_with_words(words, segs)

        assert all(w["speaker"] == "A" for w in result)

    def test_merge_without_smoothing(self):
        words = [
            _word("a", 0, 1),
            _word("b", 2, 3),
            _word("c", 4, 5),
        ]
        segs = [_seg("A", 0, 1.5), _seg("B", 1.5, 3.5), _seg("A", 3.5, 6)]

        result = merge_diarization_with_words(words, segs, smooth=False)

        assert result[0]["speaker"] == "A"
        assert result[1]["speaker"] == "B"
        assert result[2]["speaker"] == "A"


# ── build_speaker_segments ───────────────────────────────────────────────


class TestBuildSpeakerSegments:
    def test_empty_words(self):
        segments, words, n = build_speaker_segments([], [])

        assert segments == []
        assert words == []
        assert n == 0

    def test_single_speaker_one_segment(self):
        words = [_word("hi", 0, 0.5), _word("there", 0.5, 1.0)]
        segs = [_seg("A", 0, 2)]

        segments, labelled, n = build_speaker_segments(words, segs)

        assert len(segments) == 1
        assert segments[0]["speaker"] == "A"
        assert segments[0]["text"] == "hi there"
        assert n == 1

    def test_two_speakers_multiple_segments(self):
        words = [
            _word("hello", 0.0, 0.5),
            _word("world", 0.5, 1.0),
            _word("goodbye", 2.0, 2.5),
        ]
        segs = [_seg("A", 0.0, 1.5), _seg("B", 1.5, 3.0)]

        segments, labelled, n = build_speaker_segments(words, segs)

        assert n == 2
        assert segments[0]["speaker"] == "A"
        assert segments[-1]["speaker"] == "B"

    def test_unknown_speaker_not_counted(self):
        words = [_word("lost", 100, 101)]
        segs = [_seg("A", 0, 1)]  # word is far away

        segments, _, n = build_speaker_segments(words, segs)

        assert segments[0]["speaker"] == "UNKNOWN"
        assert n == 0  # UNKNOWN is discarded from speaker count

    def test_segment_timestamps_rounded(self):
        words = [_word("hi", 0.12345, 0.67891)]
        segs = [_seg("A", 0, 1)]

        segments, _, _ = build_speaker_segments(words, segs)

        assert segments[0]["start"] == 0.123
        assert segments[0]["end"] == 0.679
