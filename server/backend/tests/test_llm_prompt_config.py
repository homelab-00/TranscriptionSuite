"""GH-254 — prompt configuration for AI summaries and AI chat.

Two config keys replace the single shared ``default_system_prompt``:

  * ``local_llm.summary_system_prompt`` — manual + automatic summaries
  * ``local_llm.chat_system_prompt``    — notebook AI chat

Both fall back to the legacy ``default_system_prompt`` before reaching their
built-in default, so a config.yaml written before this change keeps producing
byte-identical behaviour. Empty strings fall through to the built-in — that is
what makes the Settings "Reset to default" button a plain write rather than a
key deletion.
"""

import asyncio
import json

import pytest
from server.api.routes import llm


class _FakeServerConfig:
    """Stand-in for ``ServerConfig`` — only ``.config`` is read."""

    def __init__(self, data: dict):
        self.config = data


def _resolve(monkeypatch, local_llm: dict) -> dict:
    """Run ``get_llm_config()`` against a fake ``local_llm`` config block."""
    monkeypatch.setattr(llm, "get_config", lambda: _FakeServerConfig({"local_llm": local_llm}))
    return llm.get_llm_config()


class TestPromptResolution:
    def test_builtin_defaults_when_nothing_configured(self, monkeypatch):
        cfg = _resolve(monkeypatch, {})
        assert cfg["summary_system_prompt"] == llm.DEFAULT_SUMMARY_SYSTEM_PROMPT
        assert cfg["chat_system_prompt"] == llm.DEFAULT_CHAT_SYSTEM_PROMPT

    def test_legacy_key_feeds_both_chains(self, monkeypatch):
        """A pre-GH-254 config.yaml must not change behaviour on upgrade."""
        cfg = _resolve(monkeypatch, {"default_system_prompt": "Legacy prompt"})
        assert cfg["summary_system_prompt"] == "Legacy prompt"
        assert cfg["chat_system_prompt"] == "Legacy prompt"

    def test_new_keys_win_over_legacy(self, monkeypatch):
        cfg = _resolve(
            monkeypatch,
            {
                "default_system_prompt": "Legacy prompt",
                "summary_system_prompt": "Summary prompt",
                "chat_system_prompt": "Chat prompt",
            },
        )
        assert cfg["summary_system_prompt"] == "Summary prompt"
        assert cfg["chat_system_prompt"] == "Chat prompt"

    def test_empty_string_falls_through_to_builtin(self, monkeypatch):
        cfg = _resolve(monkeypatch, {"summary_system_prompt": "", "chat_system_prompt": ""})
        assert cfg["summary_system_prompt"] == llm.DEFAULT_SUMMARY_SYSTEM_PROMPT
        assert cfg["chat_system_prompt"] == llm.DEFAULT_CHAT_SYSTEM_PROMPT

    def test_config_load_failure_still_returns_builtin_prompts(self, monkeypatch):
        def _boom():
            raise RuntimeError("config unavailable")

        monkeypatch.setattr(llm, "get_config", _boom)
        cfg = llm.get_llm_config()
        assert cfg["summary_system_prompt"] == llm.DEFAULT_SUMMARY_SYSTEM_PROMPT
        assert cfg["chat_system_prompt"] == llm.DEFAULT_CHAT_SYSTEM_PROMPT

    def test_summary_and_chat_defaults_are_distinct(self):
        """The whole point of the split: chat must not be told to summarise."""
        assert llm.DEFAULT_SUMMARY_SYSTEM_PROMPT != llm.DEFAULT_CHAT_SYSTEM_PROMPT
        assert "Summarize" in llm.DEFAULT_SUMMARY_SYSTEM_PROMPT
        assert "Summarize" not in llm.DEFAULT_CHAT_SYSTEM_PROMPT


def _full_config(**overrides) -> dict:
    """A complete get_llm_config() result — every key the routes index."""
    cfg = {
        "enabled": True,
        "base_url": "http://localhost:1234",
        "api_key": "",
        "model": "test-model",
        "gpu_offload": 1.0,
        "context_length": None,
        "max_tokens": 2048,
        "temperature": 0.7,
        "default_system_prompt": "Legacy prompt",
        "summary_system_prompt": "Summary prompt",
        "chat_system_prompt": "Chat prompt",
        "title_generation_prompt": "Title prompt",
        "auto_title_enabled": True,
    }
    cfg.update(overrides)
    return cfg


class TestStatusExposesPrompts:
    def test_status_returns_effective_and_default_prompts(self, monkeypatch):
        """Settings → AI reads the effective values and the built-ins for Reset."""
        monkeypatch.setattr(llm, "get_llm_config", lambda: _full_config(enabled=False))

        status = asyncio.run(llm.get_llm_status())

        assert status.summary_system_prompt == "Summary prompt"
        assert status.chat_system_prompt == "Chat prompt"
        assert status.summary_system_prompt_default == llm.DEFAULT_SUMMARY_SYSTEM_PROMPT
        assert status.chat_system_prompt_default == llm.DEFAULT_CHAT_SYSTEM_PROMPT


class _FakeJsonResponse:
    status_code = 200

    def json(self) -> dict:
        return {
            "choices": [{"message": {"content": "A summary."}}],
            "model": "test-model",
            "usage": {"total_tokens": 12},
        }


class _FakeStreamResponse:
    """Async context manager mimicking a streaming ``httpx.Response``."""

    status_code = 200

    def __init__(self, lines: list[str]):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def aread(self) -> bytes:
        return b""

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _CapturingClient:
    """``httpx.AsyncClient`` stub that records every JSON payload it is given."""

    def __init__(self, captured: list[dict], lines: list[str]):
        self._captured = captured
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, _url, json=None, headers=None):
        self._captured.append(json)
        return _FakeJsonResponse()

    def stream(self, _method, _url, json=None, headers=None):
        self._captured.append(json)
        return _FakeStreamResponse(self._lines)


class _CapturingHttpx:
    """Stub httpx module — only what the LLM routes touch."""

    def __init__(self, captured: list[dict], lines: list[str] | None = None):
        self._client = _CapturingClient(captured, lines or [])

    def AsyncClient(self, **_kwargs):
        return self._client

    ConnectError = ConnectionError
    ConnectTimeout = TimeoutError
    TimeoutException = TimeoutError


def _sse(content: str) -> str:
    payload = {"model": "test-model", "choices": [{"delta": {"content": content}}]}
    return f"data: {json.dumps(payload)}"


def _drain(response) -> list[str]:
    """Synchronously consume an async StreamingResponse body."""

    async def _collect() -> list[str]:
        return [
            chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            async for chunk in response.body_iterator
        ]

    return asyncio.run(_collect())


@pytest.fixture
def _stub_recording(monkeypatch):
    """Recording 42 exists with one transcription segment; summary saves are no-ops."""
    import server.database.database as database_mod

    monkeypatch.setattr(
        database_mod, "get_recording", lambda rid: {"id": rid} if rid == 42 else None
    )
    monkeypatch.setattr(
        database_mod,
        "get_transcription",
        lambda rid: {"segments": [{"text": "Hello world"}]} if rid == 42 else None,
    )
    monkeypatch.setattr(database_mod, "update_recording_summary", lambda *_a, **_kw: True)
    return database_mod


class TestSummarizeUsesSummaryPrompt:
    def test_streaming_summarize_sends_summary_prompt(self, monkeypatch, _stub_recording):
        captured: list[dict] = []
        monkeypatch.setattr(llm, "get_llm_config", lambda: _full_config())
        monkeypatch.setattr(
            llm,
            "_get_httpx",
            lambda: _CapturingHttpx(captured, [_sse("A summary."), "data: [DONE]"]),
        )

        _drain(asyncio.run(llm.summarize_recording_stream(42)))

        assert captured, "no request was sent to the provider"
        assert captured[0]["messages"][0] == {"role": "system", "content": "Summary prompt"}

    def test_blocking_summarize_sends_summary_prompt(self, monkeypatch, _stub_recording):
        captured: list[dict] = []
        monkeypatch.setattr(llm, "get_llm_config", lambda: _full_config())
        monkeypatch.setattr(llm, "_get_httpx", lambda: _CapturingHttpx(captured))

        asyncio.run(llm.summarize_recording(42))

        assert captured[0]["messages"][0] == {"role": "system", "content": "Summary prompt"}
