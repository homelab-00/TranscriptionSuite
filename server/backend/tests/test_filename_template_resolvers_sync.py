"""Resolver-sync test (Issue #104, Story 3.3).

Asserts that the TypeScript resolver registry in
``dashboard/src/utils/filenameTemplate.ts`` matches the Python registry in
``server/backend/core/filename_template.py`` exactly.

This is a CI lint — drift is silently broken behavior (the live preview
would render placeholders the server rejects, or vice versa).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from server.core.filename_template import PLACEHOLDER_RESOLVERS

# Resolve the dashboard file relative to the repo root. The backend's
# pytest is run from server/backend/, so we walk up two levels.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_TS_PATH = _REPO_ROOT / "dashboard" / "src" / "utils" / "filenameTemplate.ts"


def _ts_resolver_keys() -> set[str]:
    """Parse the TS RESOLVERS dict and return its keys.

    The TS file uses the shape:
        export const RESOLVERS: Record<string, (r: SampleRecording) => string> = {
          date: (r) => r.date,
          ...
        };

    The type annotation contains a `=>` arrow, so a naive `[^=]*` regex
    won't span the assignment. We anchor on the `= {` opening and walk
    line-by-line until the closing `};`.
    """
    src = _TS_PATH.read_text(encoding="utf-8")

    # Find the line containing `RESOLVERS` and the `= {` opening.
    lines = src.splitlines()
    start_idx: int | None = None
    for i, line in enumerate(lines):
        if "export const RESOLVERS" in line and "= {" in line:
            start_idx = i + 1
            break
    if start_idx is None:
        pytest.fail("Could not locate the RESOLVERS dict in filenameTemplate.ts")

    keys: set[str] = set()
    for line in lines[start_idx:]:
        if line.strip().startswith("}"):
            break
        # Match `  identifier: ...` ignoring leading whitespace + comments
        line_match = re.match(r"\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", line)
        if line_match:
            keys.add(line_match.group(1))
    return keys


def test_resolver_keys_match_python_and_typescript() -> None:
    """The two registries must declare the SAME placeholder names."""
    python_keys = set(PLACEHOLDER_RESOLVERS.keys())
    ts_keys = _ts_resolver_keys()
    assert python_keys == ts_keys, (
        f"Resolver drift detected:\n"
        f"  Python only: {python_keys - ts_keys}\n"
        f"  TypeScript only: {ts_keys - python_keys}\n"
        f"Update both files to keep the live preview in lockstep with "
        f"server-side validation."
    )


def test_ts_file_exists() -> None:
    """Sanity check — guard against repo restructuring."""
    assert _TS_PATH.exists(), f"Expected TS file at {_TS_PATH}"
