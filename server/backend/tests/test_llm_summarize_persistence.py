"""Tests for AI-summary persistence on the /api/llm/summarize/{id} routes.

Covers spec `spec-fix-ai-summary-persistence`: after an LLM call completes,
the generated summary MUST be written to the ``recordings`` table before the
client sees the terminal `{'done': True}` SSE event (streaming) or the
``LLMResponse`` returns (blocking).

Follows the direct-call pattern: monkeypatch ``_get_httpx()`` and
``get_llm_config()`` on the ``llm`` route module, plus the module-local
``update_recording_summary`` import for each handler, then invoke the
handlers directly via ``asyncio.run()``.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from server.api.routes import llm

# ── Shared helpers ───────────────────────────────────────────────────────────


def _config(*, enabled: bool = True, base_url: str = "http://localhost:1234", **kw) -> dict:
    defaults = {
        "enabled": enabled,
        "base_url": base_url,
        "api_key": kw.get("api_key", ""),
        "model": kw.get("model", ""),
        "gpu_offload": 1.0,
        "context_length": None,
        "max_tokens": 2048,
        "temperature": 0.7,
        "default_system_prompt": "Summarize this transcription concisely.",
    }
    defaults.update(kw)
    return defaults


class _FakeStreamResponse:
    """Minimal async context manager that mimics ``httpx.Response`` for streaming."""

    def __init__(
        self, *, status_code: int = 200, lines: list[str] | None = None, body: bytes = b""
    ):
        self.status_code = status_code
        self._lines = lines or []
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def aread(self) -> bytes:
        return self._body

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamingClient:
    """Stub for ``httpx.AsyncClient`` that exposes ``.stream(...)`` only."""

    def __init__(self, stream_response: _FakeStreamResponse):
        self._stream_response = stream_response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def stream(self, *_args, **_kwargs):
        return self._stream_response


class _FakeStreamingHttpx:
    """Stub httpx module exposing ``AsyncClient`` + exception types."""

    def __init__(self, client: _FakeStreamingClient):
        self._client = client

    def AsyncClient(self, **_kwargs):
        return self._client

    ConnectError = ConnectionError
    ConnectTimeout = TimeoutError
    TimeoutException = TimeoutError


def _sse_chunk(*, content: str | None = None, model: str = "test-model") -> str:
    delta: dict = {}
    if content is not None:
        delta["content"] = content
    payload = {"model": model, "choices": [{"delta": delta}]}
    return f"data: {json.dumps(payload)}"


def _drain_streaming_response(response) -> list[str]:
    """Synchronously consume an async StreamingResponse body."""

    async def _collect() -> list[str]:
        chunks: list[str] = []
        async for chunk in response.body_iterator:
            if isinstance(chunk, bytes):
                chunks.append(chunk.decode("utf-8"))
            else:
                chunks.append(chunk)
        return chunks

    return asyncio.run(_collect())


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch):
    monkeypatch.setattr(llm, "get_llm_config", _config)


@pytest.fixture
def _stub_recording_lookups(monkeypatch):
    """Make the summarize handlers see a recording with one transcription segment."""

    def fake_get_recording(rid: int):
        return {"id": rid, "filename": "test.wav"} if rid == 42 else None

    def fake_get_transcription(rid: int):
        if rid == 42:
            return {"segments": [{"text": "Hello world"}]}
        return None

    import server.database.database as database_mod

    monkeypatch.setattr(database_mod, "get_recording", fake_get_recording)
    monkeypatch.setattr(database_mod, "get_transcription", fake_get_transcription)
    return database_mod


# ── Tests ────────────────────────────────────────────────────────────────────


class TestSummarizeStreamPersistence:
    """POST /api/llm/summarize/{id}/stream persists before the done event."""

    def test_happy_path_saves_accumulated_text_and_model(
        self, monkeypatch, _stub_recording_lookups
    ):
        """Successful stream writes full text + captured model to the DB before done."""
        saves: list[tuple[int, str | None, str | None]] = []

        def fake_update(rid: int, summary: str | None, summary_model: str | None = None) -> bool:
            saves.append((rid, summary, summary_model))
            return True

        monkeypatch.setattr(_stub_recording_lookups, "update_recording_summary", fake_update)

        stream_response = _FakeStreamResponse(
            status_code=200,
            lines=[
                _sse_chunk(content="Part 1. ", model="gpt-4o"),
                _sse_chunk(content="Part 2.", model="gpt-4o"),
                "data: [DONE]",
            ],
        )
        fake_httpx = _FakeStreamingHttpx(_FakeStreamingClient(stream_response))
        monkeypatch.setattr(llm, "_get_httpx", lambda: fake_httpx)

        response = asyncio.run(llm.summarize_recording_stream(42))
        chunks = _drain_streaming_response(response)
        body = "".join(chunks)

        assert saves == [(42, "Part 1. Part 2.", "gpt-4o")]
        # Persistence runs BEFORE the terminal done event is delivered.
        save_marker = body.index("Part 2.")
        done_marker = body.index('"done": true')
        assert save_marker < done_marker
        assert '"content": "Part 1. "' in body
        assert '"content": "Part 2."' in body

    def test_llm_error_event_skips_save(self, monkeypatch, _stub_recording_lookups):
        """If the upstream LLM returns non-200, no DB write happens."""
        save_calls: list[tuple] = []

        def fake_update(*args, **_kwargs) -> bool:
            save_calls.append(args)
            return True

        monkeypatch.setattr(_stub_recording_lookups, "update_recording_summary", fake_update)

        stream_response = _FakeStreamResponse(status_code=500, body=b"upstream boom")
        fake_httpx = _FakeStreamingHttpx(_FakeStreamingClient(stream_response))
        monkeypatch.setattr(llm, "_get_httpx", lambda: fake_httpx)

        response = asyncio.run(llm.summarize_recording_stream(42))
        body = "".join(_drain_streaming_response(response))

        assert save_calls == []
        assert '"error"' in body
        assert '"done": true' not in body  # error path must not emit done

    def test_empty_stream_does_not_overwrite_existing_summary(
        self, monkeypatch, _stub_recording_lookups
    ):
        """[DONE] with zero content chunks must not call update_recording_summary.

        Regression guard: an empty LLM response would otherwise blank out an
        existing persisted summary. The DB helper writes whatever we pass it.
        """
        save_calls: list[tuple] = []

        def fake_update(*args, **_kwargs) -> bool:
            save_calls.append(args)
            return True

        monkeypatch.setattr(_stub_recording_lookups, "update_recording_summary", fake_update)

        stream_response = _FakeStreamResponse(
            status_code=200,
            lines=["data: [DONE]"],  # no content chunks at all
        )
        fake_httpx = _FakeStreamingHttpx(_FakeStreamingClient(stream_response))
        monkeypatch.setattr(llm, "_get_httpx", lambda: fake_httpx)

        response = asyncio.run(llm.summarize_recording_stream(42))
        body = "".join(_drain_streaming_response(response))

        assert save_calls == []
        assert '"done": true' in body

    def test_last_wins_captured_model(self, monkeypatch, _stub_recording_lookups):
        """Later chunks' `model` field overrides earlier ones (proxy/router case)."""
        saves: list[tuple[int, str | None, str | None]] = []

        def fake_update(rid: int, summary: str | None, summary_model: str | None = None) -> bool:
            saves.append((rid, summary, summary_model))
            return True

        monkeypatch.setattr(_stub_recording_lookups, "update_recording_summary", fake_update)

        stream_response = _FakeStreamResponse(
            status_code=200,
            lines=[
                _sse_chunk(content="X", model="router-alias"),
                _sse_chunk(content="Y", model="real-model-v2"),
                "data: [DONE]",
            ],
        )
        fake_httpx = _FakeStreamingHttpx(_FakeStreamingClient(stream_response))
        monkeypatch.setattr(llm, "_get_httpx", lambda: fake_httpx)

        response = asyncio.run(llm.summarize_recording_stream(42))
        _drain_streaming_response(response)

        assert saves == [(42, "XY", "real-model-v2")]

    def test_save_failure_does_not_break_stream(self, monkeypatch, _stub_recording_lookups):
        """A raising ``update_recording_summary`` is logged but the stream still completes."""

        def raising_update(*_args, **_kwargs) -> bool:
            raise RuntimeError("sqlite locked")

        monkeypatch.setattr(_stub_recording_lookups, "update_recording_summary", raising_update)

        stream_response = _FakeStreamResponse(
            status_code=200,
            lines=[
                _sse_chunk(content="Final summary text.", model="gpt-4o"),
                "data: [DONE]",
            ],
        )
        fake_httpx = _FakeStreamingHttpx(_FakeStreamingClient(stream_response))
        monkeypatch.setattr(llm, "_get_httpx", lambda: fake_httpx)

        response = asyncio.run(llm.summarize_recording_stream(42))
        body = "".join(_drain_streaming_response(response))

        assert '"content": "Final summary text."' in body
        assert '"done": true' in body


class TestSummarizeBlockingPersistence:
    """POST /api/llm/summarize/{id} (non-streaming) persists before returning."""

    def test_blocking_happy_path_persists_summary(self, monkeypatch, _stub_recording_lookups):
        """Successful blocking call writes the response text + model to the DB."""
        saves: list[tuple[int, str | None, str | None]] = []

        def fake_update(rid: int, summary: str | None, summary_model: str | None = None) -> bool:
            saves.append((rid, summary, summary_model))
            return True

        monkeypatch.setattr(_stub_recording_lookups, "update_recording_summary", fake_update)

        fake_llm = llm.LLMResponse(response="Full summary.", model="gpt-4o", tokens_used=12)

        async def fake_process(_request):
            return fake_llm

        monkeypatch.setattr(llm, "process_with_llm", fake_process)

        result = asyncio.run(llm.summarize_recording(42))

        assert result is fake_llm
        assert saves == [(42, "Full summary.", "gpt-4o")]

    def test_blocking_empty_response_skips_save(self, monkeypatch, _stub_recording_lookups):
        """An empty LLM response must not overwrite an existing persisted summary."""
        save_calls: list[tuple] = []

        def fake_update(*args, **_kwargs) -> bool:
            save_calls.append(args)
            return True

        monkeypatch.setattr(_stub_recording_lookups, "update_recording_summary", fake_update)

        async def fake_process(_request):
            return llm.LLMResponse(response="", model="gpt-4o", tokens_used=0)

        monkeypatch.setattr(llm, "process_with_llm", fake_process)

        asyncio.run(llm.summarize_recording(42))

        assert save_calls == []
