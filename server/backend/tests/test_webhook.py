"""Tests for the outgoing webhook dispatcher (server.core.webhook)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_config(enabled: bool = True, url: str = "https://example.com/hook", secret: str = ""):
    """Return a mock ServerConfig with webhook settings."""
    data = {"webhook": {"enabled": enabled, "url": url, "secret": secret}}

    def _get(*keys, default=None):
        current = data
        for k in keys:
            if isinstance(current, dict):
                current = current.get(k)
            else:
                return default
            if current is None:
                return default
        return current

    cfg = MagicMock()
    cfg.get = MagicMock(side_effect=_get)
    return cfg


def _patch_config(enabled: bool = True, url: str = "https://example.com/hook", secret: str = ""):
    """Patch get_config() to return a mock with the given webhook settings."""
    cfg = _mock_config(enabled=enabled, url=url, secret=secret)
    return patch("server.config.get_config", return_value=cfg)


# ---------------------------------------------------------------------------
# dispatch() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_skips_when_disabled():
    """Webhook dispatch does nothing when enabled=False."""
    from server.core.webhook import dispatch

    mock_httpx = MagicMock()
    with (
        _patch_config(enabled=False),
        patch("server.core.webhook._get_httpx", return_value=mock_httpx),
    ):
        await dispatch("test_event", {"key": "value"})

    mock_httpx.AsyncClient.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_skips_when_no_url():
    """Webhook dispatch does nothing when url is empty."""
    from server.core.webhook import dispatch

    mock_httpx = MagicMock()
    with (
        _patch_config(enabled=True, url=""),
        patch("server.core.webhook._get_httpx", return_value=mock_httpx),
    ):
        await dispatch("test_event", {"key": "value"})

    mock_httpx.AsyncClient.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_posts_correct_payload():
    """Webhook dispatch sends a POST with the correct envelope structure."""
    from server.core.webhook import dispatch

    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    mock_httpx = MagicMock()
    mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

    url = "https://example.com/hook"
    with (
        _patch_config(enabled=True, url=url, secret=""),
        patch("server.core.webhook._get_httpx", return_value=mock_httpx),
    ):
        await dispatch("live_sentence", {"source": "live", "text": "Hello world"})

    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert call_args[0][0] == url  # positional: URL

    body = call_args[1]["json"]
    assert body["event"] == "live_sentence"
    assert "timestamp" in body
    assert body["payload"]["source"] == "live"
    assert body["payload"]["text"] == "Hello world"

    headers = call_args[1]["headers"]
    assert headers["Content-Type"] == "application/json"
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_dispatch_sends_bearer_when_secret_set():
    """Authorization header is sent when a secret is configured."""
    from server.core.webhook import dispatch

    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    mock_httpx = MagicMock()
    mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

    with (
        _patch_config(enabled=True, secret="my-secret-token"),
        patch("server.core.webhook._get_httpx", return_value=mock_httpx),
    ):
        await dispatch("test", {"key": "val"})

    headers = mock_client.post.call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer my-secret-token"


@pytest.mark.asyncio
async def test_dispatch_no_auth_when_secret_empty():
    """No Authorization header when secret is empty."""
    from server.core.webhook import dispatch

    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    mock_httpx = MagicMock()
    mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

    with (
        _patch_config(enabled=True, secret=""),
        patch("server.core.webhook._get_httpx", return_value=mock_httpx),
    ):
        await dispatch("test", {"key": "val"})

    headers = mock_client.post.call_args[1]["headers"]
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_dispatch_logs_on_failure():
    """Dispatch logs a warning but does not raise on HTTP failure."""
    from server.core.webhook import dispatch

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=ConnectionError("refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    mock_httpx = MagicMock()
    mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

    with (
        _patch_config(enabled=True),
        patch("server.core.webhook._get_httpx", return_value=mock_httpx),
    ):
        # Should not raise
        await dispatch("test", {"key": "val"})


# ---------------------------------------------------------------------------
# send_test_webhook() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_test_webhook_success():
    """Test webhook returns success on 200 response."""
    from server.core.webhook import send_test_webhook

    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    mock_httpx = MagicMock()
    mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

    with patch("server.core.webhook._get_httpx", return_value=mock_httpx):
        result = await send_test_webhook("https://example.com/hook", "secret123")

    assert result["success"] is True
    assert result["status_code"] == 200
    assert "200" in result["message"]


@pytest.mark.asyncio
async def test_send_test_webhook_failure():
    """Test webhook returns failure info on connection error."""
    from server.core.webhook import send_test_webhook

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=ConnectionError("refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    mock_httpx = MagicMock()
    mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

    with patch("server.core.webhook._get_httpx", return_value=mock_httpx):
        result = await send_test_webhook("https://example.com/hook", "")

    assert result["success"] is False
    assert result["status_code"] is None
    assert "refused" in result["message"]


@pytest.mark.asyncio
async def test_send_test_webhook_no_url():
    """Test webhook returns error when URL is empty."""
    from server.core.webhook import send_test_webhook

    result = await send_test_webhook("", "")
    assert result["success"] is False
    assert "No webhook URL" in result["message"]


# ---------------------------------------------------------------------------
# dispatch_fire_and_forget() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_fire_and_forget_schedules_on_loop():
    """dispatch_fire_and_forget schedules dispatch() on the given event loop."""
    from server.core.webhook import dispatch_fire_and_forget

    loop = asyncio.get_running_loop()

    with (
        patch("server.core.webhook.dispatch", new_callable=AsyncMock) as mock_dispatch,
        _patch_config(enabled=True),
    ):
        dispatch_fire_and_forget(loop, "live_sentence", {"text": "hi"})
        # Give the scheduled coroutine time to run
        await asyncio.sleep(0.05)

    mock_dispatch.assert_called_once_with("live_sentence", {"text": "hi"})


# ---------------------------------------------------------------------------
# SSRF guard tests
# ---------------------------------------------------------------------------


def test_is_safe_url_allows_public():
    """Public HTTPS URLs are allowed."""
    from server.core.webhook import _is_safe_url

    assert _is_safe_url("https://example.com/hook") is True
    assert _is_safe_url("http://api.example.com/webhook") is True


def test_is_safe_url_blocks_private_ips():
    """Private IP addresses are blocked."""
    from server.core.webhook import _is_safe_url

    assert _is_safe_url("http://192.168.1.1/hook") is False
    assert _is_safe_url("http://10.0.0.1/hook") is False
    assert _is_safe_url("http://172.16.0.1/hook") is False


def test_is_safe_url_blocks_loopback():
    """Loopback addresses are blocked."""
    from server.core.webhook import _is_safe_url

    assert _is_safe_url("http://127.0.0.1/hook") is False
    assert _is_safe_url("http://localhost/hook") is False


def test_is_safe_url_blocks_internal_hostnames():
    """Internal hostnames (.internal, .local) are blocked."""
    from server.core.webhook import _is_safe_url

    assert _is_safe_url("http://metadata.google.internal/computeMetadata") is False
    assert _is_safe_url("http://myservice.local/api") is False


def test_is_safe_url_blocks_non_http_schemes():
    """Non-HTTP(S) schemes are blocked."""
    from server.core.webhook import _is_safe_url

    assert _is_safe_url("ftp://example.com/file") is False
    assert _is_safe_url("file:///etc/passwd") is False


@pytest.mark.asyncio
async def test_dispatch_blocks_ssrf_url():
    """Dispatch silently skips when the URL targets a private address."""
    from server.core.webhook import dispatch

    mock_httpx = MagicMock()
    with (
        _patch_config(enabled=True, url="http://192.168.1.1/hook"),
        patch("server.core.webhook._get_httpx", return_value=mock_httpx),
    ):
        await dispatch("test", {"key": "val"})

    mock_httpx.AsyncClient.assert_not_called()


@pytest.mark.asyncio
async def test_send_test_webhook_blocks_ssrf_url():
    """send_test_webhook returns error for private URLs."""
    from server.core.webhook import send_test_webhook

    result = await send_test_webhook("http://10.0.0.1/hook", "")
    assert result["success"] is False
    assert "blocked" in result["message"].lower()
