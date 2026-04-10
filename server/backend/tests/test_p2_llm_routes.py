"""Tests for LLM integration routes (OpenAI-compatible endpoint support).

[P2] Covers P2-ROUTE-002: status, process, list models, load model.
Also covers GH-68 edge cases: API key auth, model discovery, 401 handling.

Follows the direct-call pattern: monkeypatch _get_httpx() and get_llm_config()
in the llm route module, call handlers directly via asyncio.run().
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from server.api.routes import llm

# ── Helpers ──────────────────────────────────────────────────────────────────


def _config(*, enabled: bool = True, base_url: str = "http://localhost:1234", **kw) -> dict:
    """Minimal LLM config dict."""
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


class _FakeResponse:
    """Stub for httpx.Response."""

    def __init__(self, status_code: int = 200, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


class _FakeAsyncClient:
    """Stub for httpx.AsyncClient that returns canned responses."""

    def __init__(
        self,
        *,
        get_response: _FakeResponse | None = None,
        post_response: _FakeResponse | None = None,
    ):
        self._get_response = get_response or _FakeResponse()
        self._post_response = post_response or _FakeResponse()
        self.last_headers: dict = {}
        self.last_url: str = ""

    async def get(self, url, **kwargs):
        self.last_url = url
        self.last_headers = kwargs.get("headers", {})
        return self._get_response

    async def post(self, url, **kwargs):
        self.last_url = url
        self.last_headers = kwargs.get("headers", {})
        return self._post_response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass


class _FakeHttpx:
    """Stub for the httpx module with configurable AsyncClient."""

    def __init__(self, client: _FakeAsyncClient):
        self._client = client

    def AsyncClient(self, **kwargs):
        return self._client

    # Expose exception types so `except httpx.ConnectError` works
    ConnectError = ConnectionError
    ConnectTimeout = TimeoutError
    TimeoutException = TimeoutError


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch):
    """Default to enabled LLM config."""
    monkeypatch.setattr(llm, "get_llm_config", _config)


# ── P2-ROUTE-002: LLM Routes ────────────────────────────────────────────────


@pytest.mark.p2
class TestP2Route002Status:
    """[P2] GET /api/llm/status — LLM availability check."""

    def test_status_available_when_model_loaded(self, monkeypatch):
        """Server responds 200 with a loaded LLM model."""
        resp = _FakeResponse(
            200,
            {"data": [{"id": "test-model", "type": "llm", "state": "loaded"}]},
        )
        fake_httpx = _FakeHttpx(_FakeAsyncClient(get_response=resp))
        monkeypatch.setattr(llm, "_get_httpx", lambda: fake_httpx)

        result = asyncio.run(llm.get_llm_status())

        assert result.available is True
        assert result.model == "test-model"
        assert result.model_state == "loaded"

    def test_status_unavailable_on_connection_error(self, monkeypatch):
        """Connection refused returns available=false."""

        class _ErrorClient(_FakeAsyncClient):
            async def get(self, url, **kwargs):
                raise ConnectionError("Connection refused")

        fake_httpx = _FakeHttpx(_ErrorClient())
        monkeypatch.setattr(llm, "_get_httpx", lambda: fake_httpx)

        result = asyncio.run(llm.get_llm_status())

        assert result.available is False
        assert "connect" in (result.error or "").lower()


@pytest.mark.p2
class TestP2Route002Process:
    """[P2] POST /api/llm/process — send transcription to LLM."""

    def test_process_returns_response_on_success(self, monkeypatch):
        """Successful LLM call returns LLMResponse with model and content."""
        api_response = _FakeResponse(
            200,
            {
                "choices": [{"message": {"content": "Summary of text."}}],
                "model": "test-model",
                "usage": {"total_tokens": 100},
            },
        )
        fake_httpx = _FakeHttpx(_FakeAsyncClient(post_response=api_response))
        monkeypatch.setattr(llm, "_get_httpx", lambda: fake_httpx)

        request = llm.LLMRequest(transcription_text="Hello world")
        result = asyncio.run(llm.process_with_llm(request))

        assert result.response == "Summary of text."
        assert result.model == "test-model"
        assert result.tokens_used == 100

    def test_process_503_when_disabled(self, monkeypatch):
        """Raises 503 when LLM integration is disabled in config."""
        monkeypatch.setattr(llm, "get_llm_config", lambda: _config(enabled=False))

        request = llm.LLMRequest(transcription_text="Hello world")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(llm.process_with_llm(request))
        assert exc.value.status_code == 503


@pytest.mark.p2
class TestP2Route002ListModels:
    """[P2] GET /api/llm/models/available — list available models."""

    def test_list_models_returns_llm_models(self, monkeypatch):
        """Returns filtered list of LLM-type models."""
        models_data = {
            "data": [
                {
                    "id": "llm-1",
                    "type": "llm",
                    "state": "loaded",
                    "quantization": "Q4_K_M",
                    "max_context_length": 4096,
                    "arch": "llama",
                },
                {
                    "id": "embed-1",
                    "type": "embedding",
                    "state": "not-loaded",
                    "quantization": None,
                    "max_context_length": 512,
                    "arch": "bert",
                },
            ]
        }
        resp = _FakeResponse(200, models_data)
        fake_httpx = _FakeHttpx(_FakeAsyncClient(get_response=resp))
        monkeypatch.setattr(llm, "_get_httpx", lambda: fake_httpx)

        result = asyncio.run(llm.list_available_models())

        assert result["total"] == 1
        assert result["loaded"] == 1
        assert result["models"][0]["id"] == "llm-1"


@pytest.mark.p2
class TestP2Route002LoadModel:
    """[P2] POST /api/llm/model/load — load a model into LM Studio."""

    def test_load_model_success(self, monkeypatch):
        """Successful model load returns success=True with timing info."""
        load_resp = _FakeResponse(
            200,
            {"instance_id": "test-model-inst", "load_time_seconds": 2.5},
        )
        fake_httpx = _FakeHttpx(_FakeAsyncClient(post_response=load_resp))
        monkeypatch.setattr(llm, "_get_httpx", lambda: fake_httpx)

        request = llm.ModelLoadRequest(model_id="test-model")
        result = asyncio.run(llm.load_model(request))

        assert result.success is True
        assert "test-model-inst" in result.message
        assert "2.5" in result.message


# ── GH-68: OpenAI-compatible endpoint edge cases ──────────────────────────


class TestGH68AuthHeaders:
    """API key is sent as Authorization: Bearer header when configured."""

    def test_get_headers_includes_bearer_when_key_set(self):
        """_get_headers returns Authorization header when api_key is present."""
        headers = llm._get_headers({"api_key": "sk-test-key"})
        assert headers["Authorization"] == "Bearer sk-test-key"

    def test_get_headers_omits_auth_when_key_empty(self):
        """_get_headers omits Authorization when api_key is empty."""
        headers = llm._get_headers({"api_key": ""})
        assert "Authorization" not in headers

    def test_get_headers_omits_auth_when_key_missing(self):
        """_get_headers omits Authorization when api_key key is absent."""
        headers = llm._get_headers({})
        assert "Authorization" not in headers


class TestGH68StatusWithExplicitModel:
    """Status endpoint with explicit model configured (skips auto-detect)."""

    def test_status_with_explicit_model_returns_available(self, monkeypatch):
        """When model is configured, status checks connectivity and returns it."""
        monkeypatch.setattr(
            llm, "get_llm_config", lambda: _config(model="gpt-4o", api_key="sk-key")
        )
        resp = _FakeResponse(200, {"data": []})
        fake_httpx = _FakeHttpx(_FakeAsyncClient(get_response=resp))
        monkeypatch.setattr(llm, "_get_httpx", lambda: fake_httpx)

        result = asyncio.run(llm.get_llm_status())

        assert result.available is True
        assert result.model == "gpt-4o"

    def test_status_401_returns_invalid_key_error(self, monkeypatch):
        """401 from provider returns a clear invalid API key message."""
        monkeypatch.setattr(
            llm, "get_llm_config", lambda: _config(model="gpt-4o", api_key="bad-key")
        )
        resp = _FakeResponse(401)
        fake_httpx = _FakeHttpx(_FakeAsyncClient(get_response=resp))
        monkeypatch.setattr(llm, "_get_httpx", lambda: fake_httpx)

        result = asyncio.run(llm.get_llm_status())

        assert result.available is False
        assert "API key" in (result.error or "")


class TestGH68ProviderModels:
    """GET /api/llm/models — model discovery from the provider."""

    def test_models_returns_list_from_v1_models(self, monkeypatch):
        """Standard /v1/models response is parsed into simplified list."""
        resp = _FakeResponse(
            200,
            {
                "data": [
                    {"id": "gpt-4o", "owned_by": "openai"},
                    {"id": "gpt-4o-mini", "owned_by": "openai"},
                ]
            },
        )
        fake_httpx = _FakeHttpx(_FakeAsyncClient(get_response=resp))
        monkeypatch.setattr(llm, "_get_httpx", lambda: fake_httpx)

        result = asyncio.run(llm.list_provider_models())

        assert len(result["models"]) == 2
        assert result["models"][0]["id"] == "gpt-4o"
        assert result["models"][1]["owned_by"] == "openai"

    def test_models_401_raises_http_exception(self, monkeypatch):
        """401 from provider raises HTTPException with clear message."""
        resp = _FakeResponse(401)
        fake_httpx = _FakeHttpx(_FakeAsyncClient(get_response=resp))
        monkeypatch.setattr(llm, "_get_httpx", lambda: fake_httpx)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(llm.list_provider_models())
        assert exc.value.status_code == 401
        assert "API key" in exc.value.detail

    def test_models_503_when_disabled(self, monkeypatch):
        """Returns 503 when LLM integration is disabled."""
        monkeypatch.setattr(llm, "get_llm_config", lambda: _config(enabled=False))

        with pytest.raises(HTTPException) as exc:
            asyncio.run(llm.list_provider_models())
        assert exc.value.status_code == 503


# ── GH-68 follow-up: Per-conversation model switching ──────────────────────


class TestConversationModelPydantic:
    """Pydantic models accept the new model field."""

    def test_conversation_create_accepts_model(self):
        """ConversationCreate can carry an optional model override."""
        req = llm.ConversationCreate(recording_id=1, title="Test", model="gpt-4o-mini")
        assert req.model == "gpt-4o-mini"

    def test_conversation_create_defaults_model_none(self):
        """ConversationCreate.model defaults to None when omitted."""
        req = llm.ConversationCreate(recording_id=1)
        assert req.model is None

    def test_conversation_update_accepts_model(self):
        """ConversationUpdate accepts model alongside optional title."""
        req = llm.ConversationUpdate(model="gpt-4o")
        assert req.model == "gpt-4o"
        assert req.title is None

    def test_conversation_update_model_in_fields_set(self):
        """model: null is distinguishable from model absent via model_fields_set."""
        req_with = llm.ConversationUpdate.model_validate({"model": None})
        req_without = llm.ConversationUpdate.model_validate({})
        assert "model" in req_with.model_fields_set
        assert "model" not in req_without.model_fields_set

    def test_chat_request_accepts_model(self):
        """ChatRequest carries an optional per-request model override."""
        req = llm.ChatRequest(conversation_id=1, user_message="hello", model="claude-sonnet-4-6")
        assert req.model == "claude-sonnet-4-6"

    def test_chat_request_defaults_model_none(self):
        """ChatRequest.model defaults to None when omitted."""
        req = llm.ChatRequest(conversation_id=1, user_message="hello")
        assert req.model is None
