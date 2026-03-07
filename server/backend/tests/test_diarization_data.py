"""Tests for diarization data classes — pure logic, no ML dependencies.

Covers:
- ``DiarizationSegment.duration`` property
- ``DiarizationSegment.to_dict()`` rounding behaviour
- ``DiarizationResult.get_speaker_at()`` lookups (hit, miss, boundary)
- ``DiarizationResult.to_dict()`` serialisation
- ``DiarizationResult.num_speakers`` tracking
- Edge cases: zero-length segment, adjacent segments, empty result
"""

from __future__ import annotations

import pytest
from server.core.diarization_engine import DiarizationResult, DiarizationSegment

# ── DiarizationSegment ────────────────────────────────────────────────────


class TestDiarizationSegment:
    def test_duration_simple(self):
        seg = DiarizationSegment(start=1.0, end=3.0, speaker="SPEAKER_00")

        assert seg.duration == 2.0

    def test_duration_zero_length(self):
        seg = DiarizationSegment(start=5.0, end=5.0, speaker="SPEAKER_00")

        assert seg.duration == 0.0

    def test_duration_fractional(self):
        seg = DiarizationSegment(start=0.123, end=1.456, speaker="SPEAKER_01")

        assert seg.duration == pytest.approx(1.333, abs=1e-6)

    def test_to_dict_rounds_to_three_decimals(self):
        seg = DiarizationSegment(start=1.12345, end=2.67891, speaker="SPEAKER_00")

        d = seg.to_dict()

        assert d["start"] == 1.123
        assert d["end"] == 2.679
        assert d["duration"] == round(2.67891 - 1.12345, 3)

    def test_to_dict_includes_speaker(self):
        seg = DiarizationSegment(start=0.0, end=1.0, speaker="SPEAKER_02")

        d = seg.to_dict()

        assert d["speaker"] == "SPEAKER_02"

    def test_to_dict_keys(self):
        seg = DiarizationSegment(start=0.0, end=1.0, speaker="SPEAKER_00")

        d = seg.to_dict()

        assert set(d.keys()) == {"start", "end", "speaker", "duration"}

    def test_attributes_directly_accessible(self):
        seg = DiarizationSegment(start=1.5, end=3.5, speaker="SPEAKER_01")

        assert seg.start == 1.5
        assert seg.end == 3.5
        assert seg.speaker == "SPEAKER_01"


# ── DiarizationResult ────────────────────────────────────────────────────


class TestDiarizationResult:
    @pytest.fixture()
    def two_speaker_result(self) -> DiarizationResult:
        """A result with two speakers and three segments."""
        return DiarizationResult(
            segments=[
                DiarizationSegment(0.0, 2.5, "SPEAKER_00"),
                DiarizationSegment(2.5, 5.0, "SPEAKER_01"),
                DiarizationSegment(5.0, 8.0, "SPEAKER_00"),
            ],
            num_speakers=2,
        )

    # -- get_speaker_at --

    def test_get_speaker_at_start_of_segment(self, two_speaker_result: DiarizationResult):
        assert two_speaker_result.get_speaker_at(0.0) == "SPEAKER_00"

    def test_get_speaker_at_middle_of_segment(self, two_speaker_result: DiarizationResult):
        assert two_speaker_result.get_speaker_at(3.5) == "SPEAKER_01"

    def test_get_speaker_at_end_of_segment(self, two_speaker_result: DiarizationResult):
        assert two_speaker_result.get_speaker_at(2.5) is not None

    def test_get_speaker_at_boundary_returns_first_match(
        self, two_speaker_result: DiarizationResult
    ):
        """At boundary 2.5, both seg[0].end and seg[1].start match — first wins."""
        speaker = two_speaker_result.get_speaker_at(2.5)

        assert speaker == "SPEAKER_00"

    def test_get_speaker_at_gap_returns_none(self):
        result = DiarizationResult(
            segments=[
                DiarizationSegment(0.0, 1.0, "SPEAKER_00"),
                DiarizationSegment(3.0, 4.0, "SPEAKER_01"),
            ],
            num_speakers=2,
        )

        assert result.get_speaker_at(2.0) is None

    def test_get_speaker_at_before_all_segments(self, two_speaker_result: DiarizationResult):
        assert two_speaker_result.get_speaker_at(-1.0) is None

    def test_get_speaker_at_after_all_segments(self, two_speaker_result: DiarizationResult):
        assert two_speaker_result.get_speaker_at(100.0) is None

    # -- to_dict --

    def test_to_dict_structure(self, two_speaker_result: DiarizationResult):
        d = two_speaker_result.to_dict()

        assert set(d.keys()) == {"segments", "num_speakers"}
        assert d["num_speakers"] == 2
        assert len(d["segments"]) == 3

    def test_to_dict_segment_roundtrip(self):
        seg = DiarizationSegment(1.111, 2.222, "SPEAKER_00")
        result = DiarizationResult(segments=[seg], num_speakers=1)

        d = result.to_dict()

        assert d["segments"][0] == seg.to_dict()

    # -- num_speakers --

    def test_num_speakers(self, two_speaker_result: DiarizationResult):
        assert two_speaker_result.num_speakers == 2

    # -- Edge cases --

    def test_empty_result(self):
        result = DiarizationResult(segments=[], num_speakers=0)

        assert result.get_speaker_at(0.0) is None
        assert result.to_dict() == {"segments": [], "num_speakers": 0}

    def test_single_segment_result(self):
        result = DiarizationResult(
            segments=[DiarizationSegment(0.0, 10.0, "SPEAKER_00")],
            num_speakers=1,
        )

        assert result.get_speaker_at(5.0) == "SPEAKER_00"
        assert result.num_speakers == 1
