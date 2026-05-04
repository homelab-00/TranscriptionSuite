"""Story 5.8 AC3 — manual summary always bypasses the auto-summary HOLD.

The HOLD predicate (``auto_summary_is_held``) is consulted ONLY by the
auto-summary lifecycle hook (Sprint 4 Story 6.2). The manual summary
endpoints (``POST /api/llm/summarize/{recording_id}`` and the streaming
variant) MUST NOT consult it — manual generation is always allowed
even while the recording is held.

This test asserts the contract by inspecting the source of llm.py and
confirming neither summarize endpoint imports ``auto_summary_is_held``.
A test that's static-analysis-only is acceptable here because:
  - The full integration (LLM round-trip) is heavy and not necessary to
    prove the negative contract;
  - The test is a regression guard: any future addition of HOLD
    enforcement in the manual path would have to add the import, which
    this test will reject.
"""

from __future__ import annotations

from pathlib import Path

_LLM_PY = Path(__file__).resolve().parents[1] / "api" / "routes" / "llm.py"


def test_manual_summary_route_does_not_import_hold_predicate() -> None:
    """Story 5.8 AC3 — guarding against accidental HOLD enforcement on manual."""
    assert _LLM_PY.exists()
    text = _LLM_PY.read_text(encoding="utf-8")
    assert "auto_summary_is_held" not in text, (
        "Manual summary endpoints (summarize_recording / "
        "summarize_recording_stream) must NOT consult "
        "auto_summary_is_held — manual is always allowed (Story 5.8 AC3)."
    )


def test_manual_summary_route_does_not_import_diarization_review_lifecycle() -> None:
    """The lifecycle module should be reachable only from the auto-summary
    consumer (Sprint 4 Story 6.2). Importing it into llm.py would mean
    someone wired HOLD into manual summary — regression."""
    text = _LLM_PY.read_text(encoding="utf-8")
    assert "diarization_review_lifecycle" not in text, (
        "Manual summary path imported diarization_review_lifecycle — "
        "Story 5.8 AC3 would fail. Move the HOLD predicate consumption "
        "to the AUTO summary hook only."
    )
