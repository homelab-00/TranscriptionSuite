"""Per-turn diarization confidence (Issue #104, Story 5.4).

The current schema stores word-level confidence on ``words.confidence``.
Per-turn confidence is DERIVED at API time as the arithmetic mean of
the segment's word-confidence values (NULL words excluded). When a
segment has zero usable word-confidence values, the turn is omitted
from the API response (Story 5.4 AC2 — "older runs" graceful fallback;
the dashboard treats missing turns as "no chip rendering").

UX-DR3 buckets (mirror in ``dashboard/src/utils/confidenceBuckets.ts``):
  - high   ≥ 0.80      — no chip rendered
  - medium 0.60–0.80   — neutral chip
  - low    < 0.60      — amber chip + flagged for review

The thresholds are mirrored verbatim across Python and TypeScript;
the sync test in
``server/backend/tests/test_confidence_buckets_sync.py`` catches drift.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# UX-DR3 thresholds (PRD §922-968).
HIGH_CONFIDENCE_THRESHOLD = 0.8
LOW_CONFIDENCE_THRESHOLD = 0.6


def bucket_for(confidence: float) -> str:
    """Return ``'high'`` / ``'medium'`` / ``'low'`` per UX-DR3."""
    if confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return "high"
    if confidence >= LOW_CONFIDENCE_THRESHOLD:
        return "medium"
    return "low"


def per_turn_confidence(
    segments: Iterable[Mapping[str, Any]],
    words: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate word-level confidence into per-turn confidence.

    Returns a list of ``{turn_index, speaker_id, confidence}`` dicts
    in segment_index order. Segments without usable word-confidence
    values are silently omitted (Story 5.4 AC2 fallback).
    """
    by_segment: dict[int, list[float]] = {}
    for w in words:
        seg_id = w.get("segment_id")
        c = w.get("confidence")
        if seg_id is None or c is None:
            continue
        try:
            cf = float(c)
        except (TypeError, ValueError):
            continue
        try:
            seg_id_int = int(seg_id)
        except (TypeError, ValueError):
            continue
        by_segment.setdefault(seg_id_int, []).append(cf)

    out: list[dict[str, Any]] = []
    for seg in segments:
        seg_id = seg.get("id")
        if seg_id is None:
            continue
        try:
            seg_id_int = int(seg_id)
        except (TypeError, ValueError):
            continue
        scores = by_segment.get(seg_id_int)
        if not scores:
            continue
        out.append(
            {
                "turn_index": int(seg.get("segment_index", 0) or 0),
                "speaker_id": seg.get("speaker"),
                "confidence": round(sum(scores) / len(scores), 4),
            }
        )
    return out
