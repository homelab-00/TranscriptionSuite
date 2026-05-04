"""Confidence-threshold filter for the review view (Issue #104, Story 5.9 AC1).

Pure function — no I/O — so the linearity benchmark
(``tests/test_review_filter_linearity.py``) measures only the
filter cost. The filter is also exercised on the dashboard side
via ``dashboard/src/utils/diarizationReviewFilter.ts``.

Filter modes (mirror UX-DR3 buckets):
  - ``bottom_5``  — bottom 5% by confidence (sorted ascending,
                    take ceil(N * 0.05) entries)
  - ``below_60``  — confidence < 0.6 (low bucket)
  - ``below_80``  — confidence < 0.8 (low + medium)
  - ``all``       — every uncertain turn (currently equivalent to
                    ``below_80`` since high-bucket turns don't
                    appear in the review view at all)
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def filter_low_confidence(
    turns: Sequence[dict[str, Any]],
    *,
    mode: str = "below_60",
) -> list[dict[str, Any]]:
    """Return the turns matching the requested filter mode.

    ``turns`` items must have a numeric ``confidence`` field. Items
    are returned in stable order (preserving input order for the
    ``below_*`` and ``all`` modes; ascending-by-confidence for
    ``bottom_5``).
    """
    if mode == "all":
        return [t for t in turns if "confidence" in t]
    if mode == "below_60":
        return [t for t in turns if t.get("confidence", 1.0) < 0.6]
    if mode == "below_80":
        return [t for t in turns if t.get("confidence", 1.0) < 0.8]
    if mode == "bottom_5":
        sorted_turns = sorted(turns, key=lambda t: t.get("confidence", 1.0))
        n = len(sorted_turns)
        if n == 0:
            return []
        k = max(1, math.ceil(n * 0.05))
        return sorted_turns[:k]
    raise ValueError(f"unknown filter mode: {mode!r}")
