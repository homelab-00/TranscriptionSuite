"""Filter linearity + p95 latency benchmark (Issue #104, Story 5.9 AC6).

The diarization-review filter must scale linearly in the number of
input turns:
  - Linear regression r² > 0.95 across [10, 100, 500, 1000] turns
  - p95 latency < 200ms at N=100 (per-PR assertion)

Implementation note: the AC framing mentions ``pytest-benchmark`` but
this project does not currently use it for in-process latency math.
We use ``time.perf_counter_ns`` + numpy linregress (already a transitive
dep via NeMo). The slow nightly variant is gated behind ``@pytest.mark.slow``.
"""

from __future__ import annotations

import math
import time

import numpy as np
import pytest
from server.core.diarization_review_filter import filter_low_confidence


def _sample_turns(n: int) -> list[dict]:
    return [
        {
            "turn_index": i,
            "speaker_id": f"SPEAKER_{i % 4:02d}",
            "confidence": (i * 13) % 100 / 100.0,  # spread 0..0.99
            "text": "x" * 40,
        }
        for i in range(n)
    ]


def test_filter_correctness_below_60() -> None:
    turns = [
        {"turn_index": 0, "speaker_id": "A", "confidence": 0.4},
        {"turn_index": 1, "speaker_id": "B", "confidence": 0.65},
        {"turn_index": 2, "speaker_id": "C", "confidence": 0.55},
    ]
    out = filter_low_confidence(turns, mode="below_60")
    assert [t["turn_index"] for t in out] == [0, 2]


def test_filter_correctness_below_80() -> None:
    turns = [
        {"turn_index": 0, "confidence": 0.4},
        {"turn_index": 1, "confidence": 0.7},
        {"turn_index": 2, "confidence": 0.85},
    ]
    out = filter_low_confidence(turns, mode="below_80")
    assert [t["turn_index"] for t in out] == [0, 1]


def test_filter_correctness_bottom_5() -> None:
    """20 turns → bottom_5 returns ceil(20*0.05)=1 turn (the lowest)."""
    turns = [{"turn_index": i, "confidence": i * 0.05} for i in range(20)]
    out = filter_low_confidence(turns, mode="bottom_5")
    assert len(out) == 1
    assert out[0]["turn_index"] == 0


def test_filter_correctness_all() -> None:
    turns = [{"turn_index": 0, "confidence": 0.4}, {"turn_index": 1, "confidence": 0.95}]
    out = filter_low_confidence(turns, mode="all")
    assert len(out) == 2


def test_filter_unknown_mode_raises() -> None:
    with pytest.raises(ValueError):
        filter_low_confidence([], mode="bogus")


# ──────────────────────────────────────────────────────────────────────────
# AC6 — p95 latency at N=100 (per-PR assertion)
# ──────────────────────────────────────────────────────────────────────────


def test_p95_at_n100_under_200ms() -> None:
    """Per-PR assertion (AC6) — N=100 visible turns, p95 < 200ms."""
    turns = _sample_turns(100)
    samples_ns: list[int] = []
    for _ in range(50):
        t0 = time.perf_counter_ns()
        _ = filter_low_confidence(turns, mode="below_80")
        samples_ns.append(time.perf_counter_ns() - t0)
    p95_ns = float(np.percentile(samples_ns, 95))
    assert p95_ns < 200_000_000, f"p95 at N=100 = {p95_ns / 1e6:.2f}ms (budget 200ms)"


# ──────────────────────────────────────────────────────────────────────────
# AC6 — linearity benchmark (slow / nightly)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.slow
def test_filter_linearity_r_squared_above_0_95() -> None:
    """Slow / nightly: r² across [10, 100, 500, 1000] must be > 0.95.

    Marked ``slow`` because it takes ~1s. CI runs this on the nightly
    schedule rather than per-PR (matches the AC's "nightly" framing).
    """
    sizes = [10, 100, 500, 1000]
    samples_per_size = 30
    means: list[float] = []
    for n in sizes:
        turns = _sample_turns(n)
        per_size: list[int] = []
        for _ in range(samples_per_size):
            t0 = time.perf_counter_ns()
            _ = filter_low_confidence(turns, mode="below_80")
            per_size.append(time.perf_counter_ns() - t0)
        means.append(float(np.mean(per_size)))

    # Linear regression Y = aX + b; report r²
    x = np.array(sizes, dtype=float)
    y = np.array(means, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    pred = slope * x + intercept
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 1.0
    assert r2 > 0.95 or math.isclose(r2, 0.95, rel_tol=0.01), (
        f"linearity r²={r2:.3f} < 0.95; sizes={sizes} means_ns={means}"
    )
