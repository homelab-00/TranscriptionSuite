"""Per-turn diarization confidence tests (Issue #104, Story 5.4).

Covers the helper (`server.core.diarization_confidence.per_turn_confidence`)
and the route (`GET /api/notebook/recordings/{id}/diarization-confidence`).
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from server.api.routes import notebook
from server.core.diarization_confidence import (
    HIGH_CONFIDENCE_THRESHOLD,
    LOW_CONFIDENCE_THRESHOLD,
    bucket_for,
    per_turn_confidence,
)

# ──────────────────────────────────────────────────────────────────────────
# bucket_for — UX-DR3 thresholds
# ──────────────────────────────────────────────────────────────────────────


def test_bucket_high_at_and_above_threshold() -> None:
    assert bucket_for(HIGH_CONFIDENCE_THRESHOLD) == "high"
    assert bucket_for(0.95) == "high"
    assert bucket_for(1.0) == "high"


def test_bucket_medium_in_range() -> None:
    assert bucket_for(LOW_CONFIDENCE_THRESHOLD) == "medium"
    assert bucket_for(0.79) == "medium"


def test_bucket_low_below_threshold() -> None:
    assert bucket_for(0.0) == "low"
    assert bucket_for(0.59) == "low"
    assert bucket_for(LOW_CONFIDENCE_THRESHOLD - 0.01) == "low"


# ──────────────────────────────────────────────────────────────────────────
# per_turn_confidence — aggregation
# ──────────────────────────────────────────────────────────────────────────


def _seg(seg_id: int, idx: int, speaker: str = "SPEAKER_00") -> dict:
    return {"id": seg_id, "segment_index": idx, "speaker": speaker, "text": "x"}


def _word(seg_id: int, conf: float | None) -> dict:
    return {"segment_id": seg_id, "confidence": conf}


def test_returns_empty_for_empty_inputs() -> None:
    assert per_turn_confidence([], []) == []


def test_aggregates_word_confidence_as_mean() -> None:
    segs = [_seg(1, 0), _seg(2, 1)]
    words = [_word(1, 0.9), _word(1, 0.7), _word(2, 0.5)]
    out = per_turn_confidence(segs, words)
    assert out == [
        {"turn_index": 0, "speaker_id": "SPEAKER_00", "confidence": 0.8},
        {"turn_index": 1, "speaker_id": "SPEAKER_00", "confidence": 0.5},
    ]


def test_skips_words_with_null_confidence() -> None:
    segs = [_seg(1, 0)]
    words = [_word(1, 0.9), _word(1, None), _word(1, 0.7)]
    out = per_turn_confidence(segs, words)
    assert out == [{"turn_index": 0, "speaker_id": "SPEAKER_00", "confidence": 0.8}]


def test_omits_segments_with_no_usable_words() -> None:
    """Story 5.4 AC2 — empty fallback per turn (older runs)."""
    segs = [_seg(1, 0), _seg(2, 1)]
    # Only seg 1 has a usable word
    words = [_word(1, 0.9), _word(2, None)]
    out = per_turn_confidence(segs, words)
    assert out == [{"turn_index": 0, "speaker_id": "SPEAKER_00", "confidence": 0.9}]


def test_returns_empty_when_no_words_at_all() -> None:
    """Story 5.4 AC2 — empty list for a recording with no word data."""
    segs = [_seg(1, 0), _seg(2, 1)]
    out = per_turn_confidence(segs, words=[])
    assert out == []


def test_handles_invalid_confidence_strings() -> None:
    """Numeric coercion failures are silently skipped."""
    segs = [_seg(1, 0)]
    words = [_word(1, "not-a-number"), _word(1, 0.5)]  # type: ignore[arg-type]
    out = per_turn_confidence(segs, words)
    assert out == [{"turn_index": 0, "speaker_id": "SPEAKER_00", "confidence": 0.5}]


def test_rounding_to_4_decimal_places() -> None:
    segs = [_seg(1, 0)]
    words = [_word(1, 0.123456789)]
    out = per_turn_confidence(segs, words)
    assert out[0]["confidence"] == 0.1235


# ──────────────────────────────────────────────────────────────────────────
# Route handler
# ──────────────────────────────────────────────────────────────────────────


def test_route_returns_404_when_recording_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notebook, "get_recording", lambda _id: None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook.get_diarization_confidence(999))
    assert exc.value.status_code == 404


def test_route_returns_empty_turns_for_recording_without_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notebook, "get_recording", lambda _id: {"id": 1})
    monkeypatch.setattr(notebook, "get_segments", lambda _id: [_seg(1, 0)])
    monkeypatch.setattr(notebook, "get_words", lambda _id: [])
    resp = asyncio.run(notebook.get_diarization_confidence(1))
    assert resp.recording_id == 1
    assert resp.turns == []


def test_route_returns_aggregated_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notebook, "get_recording", lambda _id: {"id": 1})
    segs = [_seg(1, 0, "SPEAKER_00"), _seg(2, 1, "SPEAKER_01")]
    words = [_word(1, 0.9), _word(1, 0.7), _word(2, 0.4)]
    monkeypatch.setattr(notebook, "get_segments", lambda _id: segs)
    monkeypatch.setattr(notebook, "get_words", lambda _id: words)
    resp = asyncio.run(notebook.get_diarization_confidence(1))
    assert resp.recording_id == 1
    assert len(resp.turns) == 2
    assert resp.turns[0].speaker_id == "SPEAKER_00"
    assert resp.turns[0].confidence == 0.8
    assert resp.turns[1].speaker_id == "SPEAKER_01"
    assert resp.turns[1].confidence == 0.4
