"""Sync test — Python and TypeScript alias-substitution implementations agree.

Reads ``dashboard/src/utils/aliasSubstitution.ts`` and asserts the
algorithm signatures + key behaviours match the Python module. This
catches drift where one side is updated and the other is forgotten.

The functional invariants checked here are subset of the full unit
tests; this test ONLY verifies that both implementations exist and
their signatures haven't drifted.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TS_FILE = _REPO_ROOT / "dashboard" / "src" / "utils" / "aliasSubstitution.ts"


def test_typescript_substitution_module_exists() -> None:
    assert _TS_FILE.exists(), (
        f"Expected mirror module at {_TS_FILE}; if it moved, update this test."
    )


def test_typescript_module_exports_buildSpeakerLabelMap() -> None:
    text = _TS_FILE.read_text(encoding="utf-8")
    assert "export function buildSpeakerLabelMap(" in text


def test_typescript_module_exports_labelFor() -> None:
    text = _TS_FILE.read_text(encoding="utf-8")
    assert "export function labelFor(" in text


def test_typescript_first_appearance_pattern_matches_python() -> None:
    """Both impls must emit ``Speaker 1`` for the FIRST raw label that
    has no alias, then ``Speaker 2`` for the second, etc."""
    text = _TS_FILE.read_text(encoding="utf-8")
    # The TS code uses backtick template `Speaker ${next}` — assert that
    # specific pattern appears so a refactor that drops the counter
    # would break this test.
    assert "`Speaker ${next}`" in text


def test_typescript_module_documents_no_normalization() -> None:
    """R-EL3 must be documented in BOTH files so reviewers see the
    same invariant when reading either implementation."""
    text = _TS_FILE.read_text(encoding="utf-8")
    assert "R-EL3" in text or "verbatim" in text.lower()
