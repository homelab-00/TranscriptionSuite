"""Tests for the OpenAI-compatible audio routes (``/v1/audio/``)."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@dataclass
class _FakeResult:
    """Minimal stand-in for TranscriptionResult (avoids ML import chain)."""

    text: str = ""
    language: str | None = None
    language_probability: float = 0.0
    duration: float = 0.0
    segments: list[dict[str, Any]] = field(default_factory=list)
    words: list[dict[str, Any]] = field(default_factory=list)
    num_speakers: int = 0


def _make_result(**overrides) -> _FakeResult:
    defaults = {
        "text": "Hello world",
        "language": "en",
        "language_probability": 0.95,
        "duration": 3.5,
        "segments": [
            {"start_time": 0.0, "end_time": 1.5, "text": "Hello"},
            {"start_time": 1.5, "end_time": 3.5, "text": "world"},
        ],
        "words": [
            {"word": "Hello", "start_time": 0.0, "end_time": 1.0},
            {"word": "world", "start_time": 1.5, "end_time": 3.5},
        ],
    }
    defaults.update(overrides)
    return _FakeResult(**defaults)


@pytest.fixture()
def openai_client():
    """TestClient with the openai_audio router mounted and a mocked engine."""
    from server.api.routes import openai_audio

    app = FastAPI()
    app.include_router(openai_audio.router, prefix="/v1/audio")

    mock_engine = MagicMock()
    mock_engine.transcribe_file.return_value = _make_result()

    app.state.model_manager = SimpleNamespace(
        engine=mock_engine,
        job_tracker=SimpleNamespace(
            try_start_job=lambda client_name: (True, "job-1", None),
            end_job=lambda job_id: None,
        ),
    )
    app.state.config = SimpleNamespace(
        transcription={"model": "test-model"},
        get=lambda *a, default=None, **kw: default,
    )

    # Patch resolve_main_transcriber_model to return a valid model name
    with patch(
        "server.api.routes.openai_audio.resolve_main_transcriber_model",
        return_value="test-model",
    ):
        client = TestClient(app, raise_server_exceptions=False)
        yield client, mock_engine


def _upload(client, path="/v1/audio/transcriptions", **kwargs):
    """POST a dummy WAV file to the given path."""
    files = kwargs.pop("files", None)
    if files is None:
        files = {"file": ("test.wav", io.BytesIO(b"RIFF" + b"\x00" * 100), "audio/wav")}
    data = {"model": "whisper-1"}
    data.update(kwargs)
    return client.post(path, files=files, data=data)


# ------------------------------------------------------------------
# Transcription endpoint tests
# ------------------------------------------------------------------


def test_transcription_json_default(openai_client):
    client, engine = openai_client
    resp = _upload(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"text": "Hello world"}


def test_transcription_text_format(openai_client):
    client, _ = openai_client
    resp = _upload(client, response_format="text")
    assert resp.status_code == 200
    assert resp.text == "Hello world"
    assert "text/plain" in resp.headers["content-type"]


def test_transcription_verbose_json(openai_client):
    client, _ = openai_client
    resp = _upload(client, response_format="verbose_json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["task"] == "transcribe"
    assert body["language"] == "en"
    assert body["duration"] == 3.5
    assert body["text"] == "Hello world"
    assert len(body["segments"]) == 2
    seg = body["segments"][0]
    assert "id" in seg
    assert "start" in seg
    assert "end" in seg
    assert "text" in seg


def test_transcription_srt_format(openai_client):
    client, _ = openai_client
    resp = _upload(client, response_format="srt")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "00:00:00,000 --> 00:00:01,500" in resp.text
    assert "Hello" in resp.text


def test_transcription_vtt_format(openai_client):
    client, _ = openai_client
    resp = _upload(client, response_format="vtt")
    assert resp.status_code == 200
    assert resp.text.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.500" in resp.text


def test_transcription_invalid_format(openai_client):
    client, _ = openai_client
    resp = _upload(client, response_format="xml")
    assert resp.status_code == 400
    body = resp.json()
    assert "error" in body
    assert body["error"]["type"] == "invalid_request_error"
    assert "xml" in body["error"]["message"]


def test_transcription_forwards_language(openai_client):
    client, engine = openai_client
    _upload(client, language="fr")
    call_kwargs = engine.transcribe_file.call_args
    assert call_kwargs.kwargs.get("language") == "fr" or call_kwargs[1].get("language") == "fr"


def test_transcription_forwards_prompt(openai_client):
    client, engine = openai_client
    _upload(client, prompt="Context prompt")
    call_kwargs = engine.transcribe_file.call_args
    assert (
        call_kwargs.kwargs.get("initial_prompt") == "Context prompt"
        or call_kwargs[1].get("initial_prompt") == "Context prompt"
    )


def test_transcription_model_accepted(openai_client):
    """The model field is accepted but does not affect which model is used."""
    client, _ = openai_client
    resp = _upload(client, model="whisper-large-v3")
    assert resp.status_code == 200


def test_verbose_json_with_word_timestamps(openai_client):
    client, engine = openai_client
    files = {"file": ("test.wav", io.BytesIO(b"RIFF" + b"\x00" * 100), "audio/wav")}
    data = {
        "model": "whisper-1",
        "response_format": "verbose_json",
        "timestamp_granularities[]": "word",
    }
    resp = client.post("/v1/audio/transcriptions", files=files, data=data)
    assert resp.status_code == 200
    body = resp.json()
    assert "words" in body
    assert len(body["words"]) == 2
    # Verify word_timestamps=True was forwarded
    call_kwargs = engine.transcribe_file.call_args
    assert (
        call_kwargs.kwargs.get("word_timestamps") is True
        or call_kwargs[1].get("word_timestamps") is True
    )


# ------------------------------------------------------------------
# Translation endpoint tests
# ------------------------------------------------------------------


def test_translation_json_default(openai_client):
    client, engine = openai_client
    resp = _upload(client, path="/v1/audio/translations")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"text": "Hello world"}
    call_kwargs = engine.transcribe_file.call_args
    assert (
        call_kwargs.kwargs.get("task") == "translate" or call_kwargs[1].get("task") == "translate"
    )


def test_translation_sets_target_language_en(openai_client):
    client, engine = openai_client
    _upload(client, path="/v1/audio/translations")
    call_kwargs = engine.transcribe_file.call_args
    kwargs = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
    assert kwargs.get("translation_target_language") == "en"


def test_translation_verbose_json(openai_client):
    client, _ = openai_client
    resp = _upload(client, path="/v1/audio/translations", response_format="verbose_json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["task"] == "translate"


# ------------------------------------------------------------------
# Error handling tests
# ------------------------------------------------------------------


def test_no_model_loaded_returns_503():
    from server.api.routes import openai_audio

    app = FastAPI()
    app.include_router(openai_audio.router, prefix="/v1/audio")
    app.state.model_manager = SimpleNamespace(
        engine=MagicMock(),
        job_tracker=SimpleNamespace(
            try_start_job=lambda cn: (True, "j", None),
            end_job=lambda j: None,
        ),
    )
    app.state.config = SimpleNamespace(
        transcription={"model": ""},
        get=lambda *a, default=None, **kw: default,
    )

    with patch("server.api.routes.openai_audio.resolve_main_transcriber_model", return_value=""):
        client = TestClient(app, raise_server_exceptions=False)
        resp = _upload(client)
        assert resp.status_code == 503
        assert resp.json()["error"]["type"] == "server_error"


def test_job_busy_returns_429():
    from server.api.routes import openai_audio

    app = FastAPI()
    app.include_router(openai_audio.router, prefix="/v1/audio")
    app.state.model_manager = SimpleNamespace(
        engine=MagicMock(),
        job_tracker=SimpleNamespace(
            try_start_job=lambda cn: (False, None, "other-user"),
            end_job=lambda j: None,
        ),
    )
    app.state.config = SimpleNamespace(
        transcription={"model": "test"},
        get=lambda *a, default=None, **kw: default,
    )

    with patch(
        "server.api.routes.openai_audio.resolve_main_transcriber_model",
        return_value="test-model",
    ):
        client = TestClient(app, raise_server_exceptions=False)
        resp = _upload(client)
        assert resp.status_code == 429
        assert resp.json()["error"]["type"] == "rate_limit_error"


def test_openai_error_shape(openai_client):
    """All error responses follow OpenAI's error schema."""
    client, _ = openai_client
    resp = _upload(client, response_format="invalid")
    body = resp.json()
    assert "error" in body
    err = body["error"]
    assert "message" in err
    assert "type" in err
    assert "param" in err
    assert "code" in err
