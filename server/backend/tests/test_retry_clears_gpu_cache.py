"""A retry must not inherit the GPU state of the failure that caused it.

Retry exists almost exclusively to recover from a CUDA OOM, so it runs at the
one moment the GPU is most likely to still be saturated: the transcription
model is resident and keeps its allocations, and whatever else exhausted the
card may only just have let go.

Observed 2026-08-01 on an 11.6 GB card with an LLM loaded alongside: a job died
with "CUDA failed with error out of memory", the first retry 20 s later died
inside CTranslate2 with "parallel_for failed: cudaErrorInvalidDevice: invalid
device ordinal", and a second retry 9 s after that succeeded with no code
change in between. Dropping the cached allocator blocks before re-transcribing
gives the retry the free VRAM it needs instead of making the user click twice.

Run:  ../../build/.venv/bin/pytest tests/test_retry_clears_gpu_cache.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from server.api.routes import transcription


@dataclass
class _FakeResult:
    text: str = "recovered"
    segments: list[dict[str, Any]] = field(default_factory=list)
    words: list[dict[str, Any]] = field(default_factory=list)
    language: str | None = "en"
    language_probability: float = 0.0
    duration: float = 1.0
    num_speakers: int = 0
    partial: bool = False
    partial_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "segments": self.segments,
            "words": self.words,
            "language": self.language,
            "duration": self.duration,
            "partial": self.partial,
            "partial_reason": self.partial_reason,
        }


def _drive_retry(monkeypatch, *, transcribe_raises: Exception | None = None) -> list[str]:
    """Run _run_retry and return the ordered trace of collaborator calls."""
    trace: list[str] = []

    def _transcribe(*_args: Any, **_kwargs: Any) -> _FakeResult:
        trace.append("transcribe_file")
        if transcribe_raises is not None:
            raise transcribe_raises
        return _FakeResult()

    fake_engine = SimpleNamespace(transcribe_file=_transcribe)
    model_manager = SimpleNamespace(
        job_tracker=SimpleNamespace(
            try_start_job=lambda _client: (True, "tracker-1", None),
            end_job=lambda _id: None,
        ),
        ensure_transcription_loaded=lambda: fake_engine,
    )

    audio_utils = importlib.import_module("server.core.audio_utils")
    monkeypatch.setattr(
        audio_utils, "clear_gpu_cache", lambda: trace.append("clear_gpu_cache"), raising=False
    )

    repo = importlib.import_module("server.database.job_repository")
    monkeypatch.setattr(repo, "save_result", lambda **_kw: trace.append("save_result"))
    monkeypatch.setattr(repo, "mark_failed", lambda _id, _msg: trace.append("mark_failed"))

    job = {
        "client_name": "test-client",
        "language": None,
        "task": "transcribe",
        "translation_target": None,
    }
    asyncio.run(
        transcription._run_retry(
            "job-1", "/fake/audio.wav", job, SimpleNamespace(model_manager=model_manager)
        )
    )
    return trace


def test_gpu_cache_cleared_before_retrying(monkeypatch):
    """The freed-VRAM step must happen before the model is asked to transcribe."""
    trace = _drive_retry(monkeypatch)

    assert "clear_gpu_cache" in trace, "retry did not release cached VRAM before re-transcribing"
    assert trace.index("clear_gpu_cache") < trace.index("transcribe_file"), (
        f"clear_gpu_cache must precede transcribe_file, got {trace}"
    )
    assert "save_result" in trace


def test_retry_still_succeeds_if_cache_clear_fails(monkeypatch):
    """Freeing VRAM is best-effort — it must never sink an otherwise-good retry."""
    trace: list[str] = []

    fake_engine = SimpleNamespace(
        transcribe_file=lambda *a, **k: (trace.append("transcribe_file"), _FakeResult())[1]
    )
    model_manager = SimpleNamespace(
        job_tracker=SimpleNamespace(
            try_start_job=lambda _client: (True, "tracker-1", None),
            end_job=lambda _id: None,
        ),
        ensure_transcription_loaded=lambda: fake_engine,
    )

    def _boom() -> None:
        raise RuntimeError("no CUDA context")

    audio_utils = importlib.import_module("server.core.audio_utils")
    monkeypatch.setattr(audio_utils, "clear_gpu_cache", _boom, raising=False)

    repo = importlib.import_module("server.database.job_repository")
    monkeypatch.setattr(repo, "save_result", lambda **_kw: trace.append("save_result"))
    monkeypatch.setattr(repo, "mark_failed", lambda _id, _msg: trace.append("mark_failed"))

    job = {"client_name": "c", "language": None, "task": "transcribe", "translation_target": None}
    asyncio.run(
        transcription._run_retry(
            "job-2", "/fake/audio.wav", job, SimpleNamespace(model_manager=model_manager)
        )
    )

    assert "save_result" in trace, f"a failing cache clear aborted the retry: {trace}"
    assert "mark_failed" not in trace
