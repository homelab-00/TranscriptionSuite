"""The Cancel button (POST /cancel -> job_tracker) must reach every transcribe path.

Regression guard for the bug where websocket.py bound cancellation_check to
_client_disconnected, so POST /cancel never reached the backend on the main
longform path.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROUTES = Path(__file__).resolve().parents[1] / "api" / "routes"


def _transcribe_calls(path: Path) -> list[ast.Call]:
    """Every engine.transcribe_file(...) call in a route module."""
    tree = ast.parse(path.read_text())
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "transcribe_file"
    ]


def _cancellation_source(call: ast.Call) -> str | None:
    for kw in call.keywords:
        if kw.arg == "cancellation_check":
            return ast.unparse(kw.value)
    return None


@pytest.mark.parametrize("module", ["websocket.py", "notebook.py", "transcription.py"])
def test_every_transcribe_call_passes_cancellation_check(module: str) -> None:
    calls = _transcribe_calls(ROUTES / module)
    assert calls, f"expected at least one transcribe_file call in {module}"
    for call in calls:
        src = _cancellation_source(call)
        assert src is not None, (
            f"{module}: transcribe_file() called without cancellation_check — "
            "a job started here can never be cancelled"
        )


@pytest.mark.parametrize("module", ["websocket.py", "notebook.py", "transcription.py"])
def test_cancellation_check_consults_the_job_tracker(module: str) -> None:
    """POST /cancel flips job_tracker._cancelled. Every path must read it."""
    for call in _transcribe_calls(ROUTES / module):
        src = _cancellation_source(call) or ""
        assert "job_tracker.is_cancelled" in src, (
            f"{module}: cancellation_check={src!r} does not consult "
            "job_tracker.is_cancelled, so POST /cancel cannot stop this job"
        )
