"""Sync test — Python and TypeScript confidence-bucket constants agree.

UX-DR3 declares one set of thresholds (high ≥0.8, medium ≥0.6, low <0.6)
that BOTH the backend (`server.core.diarization_confidence`) and the
dashboard (`dashboard/src/utils/confidenceBuckets.ts`) must implement
identically. This test catches drift where one side is updated and
the other forgotten.
"""

from __future__ import annotations

import re
from pathlib import Path

from server.core import diarization_confidence as py_module

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TS_FILE = _REPO_ROOT / "dashboard" / "src" / "utils" / "confidenceBuckets.ts"


def _extract_const(text: str, name: str) -> float:
    """Pull `export const NAME = <number>;` out of TS source."""
    pattern = rf"export const {re.escape(name)} = ([0-9.]+);"
    m = re.search(pattern, text)
    assert m is not None, f"could not find `export const {name}` in TS file"
    return float(m.group(1))


def test_typescript_module_exists() -> None:
    assert _TS_FILE.exists()


def test_high_threshold_matches() -> None:
    text = _TS_FILE.read_text(encoding="utf-8")
    ts_value = _extract_const(text, "HIGH_CONFIDENCE_THRESHOLD")
    assert ts_value == py_module.HIGH_CONFIDENCE_THRESHOLD, (
        f"TS HIGH_CONFIDENCE_THRESHOLD={ts_value} but Python={py_module.HIGH_CONFIDENCE_THRESHOLD} — "
        "UX-DR3 buckets have drifted across the language boundary."
    )


def test_low_threshold_matches() -> None:
    text = _TS_FILE.read_text(encoding="utf-8")
    ts_value = _extract_const(text, "LOW_CONFIDENCE_THRESHOLD")
    assert ts_value == py_module.LOW_CONFIDENCE_THRESHOLD, (
        f"TS LOW_CONFIDENCE_THRESHOLD={ts_value} but Python={py_module.LOW_CONFIDENCE_THRESHOLD} — "
        "UX-DR3 buckets have drifted across the language boundary."
    )


def test_typescript_exports_bucketFor() -> None:
    text = _TS_FILE.read_text(encoding="utf-8")
    assert "export function bucketFor(" in text
