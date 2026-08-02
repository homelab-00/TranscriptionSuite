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


#: Calls that start a transcription from a route. ``transcribe_file`` is the
#: engine call itself; ``transcribe_with_optional_diarization`` (GH-258) wraps
#: it for the WebSocket path and forwards ``cancellation_check`` down to it.
#: The wrapper has to be listed here or this guard silently stops watching the
#: main longform path — the exact path the bug it guards against was on.
_TRANSCRIBE_ENTRY_POINTS = frozenset({"transcribe_file", "transcribe_with_optional_diarization"})


def _called_name(node: ast.Call) -> str | None:
    """The bare callable name, whether it is `a.b()` or a directly imported `b()`."""
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _transcribe_calls(path: Path) -> list[ast.Call]:
    """Every call in a module that starts a transcription."""
    tree = ast.parse(path.read_text())
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _called_name(node) in _TRANSCRIBE_ENTRY_POINTS
    ]


def _cancellation_source(call: ast.Call) -> str | None:
    for kw in call.keywords:
        if kw.arg == "cancellation_check":
            return ast.unparse(kw.value)
    return None


@pytest.mark.parametrize(
    "module", ["websocket.py", "notebook.py", "transcription.py", "openai_audio.py"]
)
def test_every_transcribe_call_passes_cancellation_check(module: str) -> None:
    calls = _transcribe_calls(ROUTES / module)
    assert calls, f"expected at least one transcribe entry-point call in {module}"
    for call in calls:
        src = _cancellation_source(call)
        assert src is not None, (
            f"{module}: {_called_name(call)}() called without cancellation_check — "
            "a job started here can never be cancelled"
        )


@pytest.mark.parametrize(
    "module", ["websocket.py", "notebook.py", "transcription.py", "openai_audio.py"]
)
def test_cancellation_check_consults_the_job_tracker(module: str) -> None:
    """POST /cancel flips job_tracker._cancelled. Every path must read it."""
    for call in _transcribe_calls(ROUTES / module):
        src = _cancellation_source(call) or ""
        assert "job_tracker.is_cancelled" in src, (
            f"{module}: cancellation_check={src!r} does not consult "
            "job_tracker.is_cancelled, so POST /cancel cannot stop this job"
        )


def test_diarization_dispatch_forwards_cancellation_to_the_engine() -> None:
    """The GH-258 wrapper is only as cancellable as what it passes down.

    The route-level guards above accept the wrapper as a transcribe entry point.
    That is only sound while the wrapper itself hands ``cancellation_check`` to
    every ``transcribe_file`` it makes, so check that here rather than trusting it.
    """
    dispatch = Path(__file__).resolve().parents[1] / "core" / "diarization_dispatch.py"
    calls = _transcribe_calls(dispatch)
    assert calls, "expected diarization_dispatch to call transcribe_file"
    for call in calls:
        assert _cancellation_source(call) == "cancellation_check", (
            "diarization_dispatch must forward the caller's cancellation_check "
            "verbatim, otherwise POST /cancel dies at the wrapper"
        )
