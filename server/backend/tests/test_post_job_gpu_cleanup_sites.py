"""Every job completion must hand cached GPU memory back to the driver.

The cleanup lives in each site's ``finally`` so it runs on success, failure
and cancellation alike. These tests drive the cheapest deterministic path
(usually a failure right at engine load) and assert the cleanup still fired.

Run:  ../../build/.venv/bin/pytest tests/test_post_job_gpu_cleanup_sites.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from server.api.routes import notebook as notebook_routes
from server.api.routes import openai_audio, transcription


def _trace_cleanup(monkeypatch) -> list[str]:
    calls: list[str] = []
    audio_utils = importlib.import_module("server.core.audio_utils")
    monkeypatch.setattr(
        audio_utils,
        "post_job_gpu_cleanup",
        lambda ctx="job", device_index=0: calls.append(ctx),
        raising=False,
    )
    return calls


def _raise_boom() -> Any:
    raise RuntimeError("boom")


def test_file_import_runs_gpu_cleanup_even_on_failure(monkeypatch, tmp_path):
    calls = _trace_cleanup(monkeypatch)
    ended: list[Any] = []
    model_manager = SimpleNamespace(
        job_tracker=SimpleNamespace(
            update_progress=lambda *a: None,
            set_phase=lambda *_: None,
            end_job=lambda job_id, result=None: ended.append(result),
            is_cancelled=lambda: False,
        ),
        ensure_transcription_loaded=_raise_boom,
        gpu_device_index=0,
    )
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")

    transcription._run_file_import(
        model_manager=model_manager,
        tmp_path=wav,
        filename="a.wav",
        language=None,
        translation_enabled=False,
        translation_target_language=None,
        enable_diarization=False,
        enable_word_timestamps=True,
        expected_speakers=None,
        parallel_diarization=None,
        use_parallel_default=False,
        multitrack=False,
        job_id="job12345",
        event_loop=None,
    )

    assert calls == ["file import"]
    assert ended and "error" in ended[-1]


def test_notebook_import_runs_gpu_cleanup_even_on_failure(monkeypatch, tmp_path):
    calls = _trace_cleanup(monkeypatch)
    ended: list[Any] = []
    model_manager = SimpleNamespace(
        job_tracker=SimpleNamespace(
            update_progress=lambda *a: None,
            set_phase=lambda *_: None,
            end_job=lambda job_id, result=None: ended.append(result),
            is_cancelled=lambda: False,
        ),
        ensure_transcription_loaded=_raise_boom,
        gpu_device_index=0,
    )
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")

    notebook_routes._run_transcription(
        model_manager=model_manager,
        tmp_path=wav,
        filename="a.wav",
        language=None,
        translation_enabled=False,
        translation_target_language=None,
        enable_diarization=False,
        enable_word_timestamps=True,
        file_created_at=None,
        expected_speakers=None,
        parallel_diarization=None,
        use_parallel_default=False,
        title=None,
        job_id="job12345",
        event_loop=None,
    )

    assert calls == ["notebook import"]
    assert ended and "error" in ended[-1]


def _openai_request(mm: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(model_manager=mm)))


def _openai_model_manager(ended: list[Any]) -> SimpleNamespace:
    return SimpleNamespace(
        ensure_transcription_loaded=lambda: None,
        gpu_device_index=0,
        job_tracker=SimpleNamespace(
            try_start_job=lambda _c: (True, "job-1", None),
            end_job=lambda job_id: ended.append(job_id),
        ),
    )


def test_openai_transcription_runs_gpu_cleanup(monkeypatch):
    calls = _trace_cleanup(monkeypatch)
    monkeypatch.setattr(openai_audio, "_assert_model_loaded", lambda _r: None)
    monkeypatch.setattr(openai_audio, "get_client_name", lambda _r: "test-client")

    async def _boom(**_kw: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(openai_audio, "_run_transcription", _boom)
    ended: list[Any] = []
    mm = _openai_model_manager(ended)
    file = MagicMock()
    file.filename = "a.wav"
    file.read = AsyncMock(return_value=b"riff")

    # Calling the route directly bypasses FastAPI's Form(...) resolution, so
    # every Form-declared parameter must be passed explicitly — left at their
    # signature defaults they are unresolved fastapi.params.Form sentinels,
    # not the values those defaults describe, and `response_format not in
    # _VALID_RESPONSE_FORMATS` trips before the try/finally is ever reached.
    asyncio.run(
        openai_audio.create_transcription(
            request=_openai_request(mm),
            file=file,
            model="whisper-1",
            language=None,
            prompt=None,
            response_format="json",
            temperature=None,
            timestamp_granularities=None,
            diarization=False,
            expected_speakers=None,
            parallel_diarization=None,
        )
    )

    assert calls == ["openai transcription"]
    assert ended == ["job-1"]


def test_openai_translation_runs_gpu_cleanup(monkeypatch):
    calls = _trace_cleanup(monkeypatch)
    monkeypatch.setattr(openai_audio, "_assert_model_loaded", lambda _r: None)
    monkeypatch.setattr(openai_audio, "get_client_name", lambda _r: "test-client")

    async def _boom(**_kw: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(openai_audio, "_run_transcription", _boom)
    ended: list[Any] = []
    mm = _openai_model_manager(ended)
    file = MagicMock()
    file.filename = "a.wav"
    file.read = AsyncMock(return_value=b"riff")

    # Same Form(...) resolution caveat as the transcription test above.
    asyncio.run(
        openai_audio.create_translation(
            request=_openai_request(mm),
            file=file,
            model="whisper-1",
            prompt=None,
            response_format="json",
            temperature=None,
            timestamp_granularities=None,
            diarization=False,
            expected_speakers=None,
            parallel_diarization=None,
        )
    )

    assert calls == ["openai translation"]
    assert ended == ["job-1"]
