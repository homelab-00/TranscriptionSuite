"""Tests that _run_retry persists the full TranscriptionResult (incl. segments).

Previously _run_retry built result_payload with only {text, words, language, duration},
permanently losing segments/num_speakers/partial flags from result_json.
GET /result/{job_id} replays result_json, so retried jobs silently lost segment data.
This test drives the success path end-to-end and asserts the persisted JSON
contains segments and partial_reason (GH #172).

Mirrors the duck-typed _FakeResult pattern from test_websocket_longform_payload.py
and the monkeypatch conventions from test_transcription_durability_routes.py.

Run:  ../../build/.venv/bin/pytest tests/test_retry_persists_segments.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from server.api.routes import transcription

# ── Fake result (avoids torch/ML import chain) ────────────────────────────────


@dataclass
class _FakeResult:
    """Minimal stand-in for TranscriptionResult.

    Mirrors TranscriptionResult.to_dict() in server/backend/core/stt/engine.py
    without importing engine.py (which has a top-level ``import torch``).
    Keep in sync with the real to_dict() keys.
    """

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


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_app_state(fake_result: _FakeResult) -> SimpleNamespace:
    """Build a minimal app_state driving _run_retry to the save_result call."""
    fake_engine = SimpleNamespace(
        transcribe_file=lambda *args, **kwargs: fake_result,
    )
    job_tracker = SimpleNamespace(
        try_start_job=lambda client_name: (True, "tracker-job-1", None),
        end_job=lambda tracker_job_id: None,
    )
    model_manager = SimpleNamespace(
        job_tracker=job_tracker,
        ensure_transcription_loaded=lambda: fake_engine,
    )
    return SimpleNamespace(model_manager=model_manager)


def _run(fake_result: _FakeResult, monkeypatch, job_id: str = "job-retry-1") -> dict[str, Any]:
    """Drive _run_retry to completion and return the parsed result_json payload."""
    captured: dict[str, Any] = {}

    def _fake_save_result(**kwargs: Any) -> None:
        captured.update(kwargs)

    repo = importlib.import_module("server.database.job_repository")
    monkeypatch.setattr(repo, "save_result", _fake_save_result)
    monkeypatch.setattr(repo, "mark_failed", lambda _id, _msg: None)

    app_state = _make_app_state(fake_result)
    job = {
        "client_name": "test-client",
        "language": None,
        "task": "transcribe",
        "translation_target": None,
    }

    asyncio.run(transcription._run_retry(job_id, "/fake/audio.wav", job, app_state))

    assert "result_json" in captured, "save_result was never called — check collaborator stubs"
    return json.loads(captured["result_json"])


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestRetryPersistsSegments:
    """_run_retry must persist the full result payload, not only 4 fields."""

    def test_segments_present_and_non_empty(self, monkeypatch):
        """The core regression: persisted result_json must contain segments."""
        fake_result = _FakeResult(
            text="hello retry world",
            segments=[{"text": "hello retry world", "start": 0.0, "end": 2.5, "words": []}],
            words=[{"word": "hello", "start": 0.0, "end": 0.5}],
            language="en",
            duration=2.5,
            num_speakers=1,
        )
        payload = _run(fake_result, monkeypatch)

        assert "segments" in payload, "result_json missing 'segments' key"
        assert len(payload["segments"]) > 0, "result_json has empty segments list"
        assert payload["segments"][0]["text"] == "hello retry world"

    def test_partial_flags_persisted(self, monkeypatch):
        """partial and partial_reason must survive the retry persist round-trip."""
        fake_result = _FakeResult(
            text="truncated",
            segments=[{"text": "truncated", "start": 0.0, "end": 1.0, "words": []}],
            duration=1.0,
            partial=True,
            partial_reason="sidecar returned implausible segment count",
        )
        payload = _run(fake_result, monkeypatch, job_id="job-retry-partial")

        assert payload.get("partial") is True
        assert payload.get("partial_reason") == "sidecar returned implausible segment count"

    def test_num_speakers_persisted(self, monkeypatch):
        """num_speakers must survive the retry persist round-trip."""
        fake_result = _FakeResult(
            text="multi speaker",
            segments=[{"text": "multi speaker", "start": 0.0, "end": 1.0, "words": []}],
            num_speakers=3,
            duration=1.0,
        )
        payload = _run(fake_result, monkeypatch, job_id="job-retry-speakers")

        assert payload.get("num_speakers") == 3

    def test_backwards_compatible_fields_remain(self, monkeypatch):
        """Existing keys the dashboard already reads must still be present."""
        fake_result = _FakeResult(
            text="stable fields",
            segments=[{"text": "stable fields", "start": 0.0, "end": 1.0, "words": []}],
            words=[{"word": "stable", "start": 0.0, "end": 0.4}],
            language="en",
            duration=1.0,
        )
        payload = _run(fake_result, monkeypatch, job_id="job-retry-compat")

        assert payload["text"] == "stable fields"
        assert payload["language"] == "en"
        assert payload["duration"] == pytest.approx(1.0)
        assert len(payload["words"]) == 1
