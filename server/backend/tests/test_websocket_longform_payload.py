"""Tests for the WebSocket longform result payload builder.

Covers _build_longform_result_payload(), verifying that the WS path persists
and delivers the full result — including segments, num_speakers, and the
partial/partial_reason truncation signal introduced in GH #172.

Previously the WS path used an inline dict with only {text, words, language,
duration}, permanently losing segment-level data from both result_json and
client delivery.  The HTTP submit path already used result.to_dict(); this
test ensures the WS path is now consistent.

A duck-typed _FakeResult (no engine.py import) avoids the torch/scipy/webrtcvad
import chain — the same pattern used in test_formatters.py.  The assertions
cover what matters: _build_longform_result_payload routes through to_dict() and
returns all fields, not just the four the old inline dict exposed.

Run:  ../../build/.venv/bin/pytest tests/test_websocket_longform_payload.py -v --tb=short
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from server.api.routes.websocket import _build_longform_result_payload


@dataclass
class _FakeResult:
    """Minimal stand-in for TranscriptionResult (avoids ML import chain).

    Mirrors TranscriptionResult.to_dict() so _build_longform_result_payload
    can be tested without pulling in torch/scipy/webrtcvad.
    """

    # Keep in sync with TranscriptionResult.to_dict() in
    # server/backend/core/stt/engine.py (imported indirectly to avoid engine.py's
    # top-level torch import in the test env).
    text: str = ""
    segments: list[dict[str, Any]] = field(default_factory=list)
    words: list[dict[str, Any]] = field(default_factory=list)
    language: str | None = None
    language_probability: float = 0.0
    duration: float = 0.0
    num_speakers: int = 0
    partial: bool = False
    partial_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "segments": self.segments,
            "words": self.words,
            "language": self.language,
            "language_probability": round(self.language_probability, 3),
            "duration": round(self.duration, 3),
            "num_speakers": self.num_speakers,
            "total_words": len(self.words),
            "partial": self.partial,
            "partial_reason": self.partial_reason,
            "metadata": {"num_segments": len(self.segments)},
        }


def test_longform_payload_includes_segments_and_partial():
    result = _FakeResult(
        text="hello world",
        segments=[{"text": "hello world", "start": 0.0, "end": 1.0}],
        words=[{"word": "hello", "start": 0.0, "end": 0.5}],
        language="en",
        duration=1.0,
        num_speakers=2,
        partial=True,
        partial_reason="sidecar returned implausible segment count",
    )
    payload = _build_longform_result_payload(result)
    assert payload["segments"] == [{"text": "hello world", "start": 0.0, "end": 1.0}]
    assert payload["num_speakers"] == 2
    assert payload["partial"] is True
    assert payload["partial_reason"] == "sidecar returned implausible segment count"
    # Backwards-compatible: existing keys the dashboard already reads remain.
    assert payload["text"] == "hello world"
    assert payload["language"] == "en"
    assert payload["duration"] == 1.0
    assert payload["words"]
