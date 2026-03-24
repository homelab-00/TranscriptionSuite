"""
Outgoing webhook dispatcher for TranscriptionSuite.

Fires HTTP POST requests to a user-configured URL when transcription
events occur (live sentences and longform completions).

Delivery is fire-and-forget: POST once, log errors, move on.
"""

import asyncio
import ipaddress
import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _is_safe_url(url: str) -> bool:
    """Check that a webhook URL does not target private/internal networks (SSRF guard).

    Blocks: private IPs, loopback, link-local, multicast, and non-HTTP(S) schemes.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    # Block obvious internal hostnames
    if hostname in ("localhost", "metadata.google.internal"):
        return False
    if hostname.endswith(".internal") or hostname.endswith(".local"):
        return False

    # Resolve to IP and check for private/reserved ranges
    try:
        addr = ipaddress.ip_address(hostname)
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
        ):
            return False
    except ValueError:
        # hostname is a DNS name, not an IP literal — allow it
        # (DNS rebinding is out of scope for this guard)
        pass

    return True


def _get_httpx():
    """Import httpx lazily to avoid startup cost when webhooks are disabled."""
    import httpx

    return httpx


def _read_webhook_config() -> tuple[bool, str, str]:
    """Read webhook configuration from the server config singleton.

    Returns:
        Tuple of (enabled, url, secret).
    """
    from server.config import get_config

    cfg = get_config()
    enabled = cfg.get("webhook", "enabled", default=False)
    url = cfg.get("webhook", "url", default="")
    secret = cfg.get("webhook", "secret", default="")
    return (bool(enabled), str(url or "").strip(), str(secret or "").strip())


async def dispatch(event_type: str, payload: dict[str, Any]) -> None:
    """Fire a webhook POST request.  Fire-and-forget: logs errors, never raises.

    Args:
        event_type: Event name (e.g. "live_sentence", "longform_complete").
        payload: Event-specific data dict.
    """
    enabled, url, secret = _read_webhook_config()
    if not enabled or not url:
        return

    if not _is_safe_url(url):
        logger.warning("Webhook %s blocked by SSRF guard", event_type)
        return

    httpx = _get_httpx()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    body = {
        "event": event_type,
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": payload,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=body, headers=headers)
            if response.status_code >= 400:
                logger.warning(
                    "Webhook %s returned HTTP %d",
                    event_type,
                    response.status_code,
                )
            else:
                logger.info("Webhook %s dispatched (HTTP %d)", event_type, response.status_code)
    except Exception as e:
        logger.warning("Webhook %s dispatch failed: %s", event_type, e)


def dispatch_fire_and_forget(
    loop: asyncio.AbstractEventLoop,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Schedule a webhook dispatch from a non-async context (background thread).

    Uses ``asyncio.run_coroutine_threadsafe`` to schedule the coroutine on
    the given event loop — the same pattern used by
    ``LiveModeSession._queue_message()`` for thread-safe async operations.

    Args:
        loop: The asyncio event loop to schedule on.
        event_type: Event name.
        payload: Event-specific data dict.
    """
    try:
        asyncio.run_coroutine_threadsafe(dispatch(event_type, payload), loop)
    except Exception:
        # Event loop closed or other scheduling error — session is shutting down.
        logger.debug("Failed to schedule webhook dispatch for %s", event_type)


async def send_test_webhook(url: str, secret: str) -> dict[str, Any]:
    """Send a test webhook and return the result.

    Unlike ``dispatch()``, this returns status information so the caller
    (the admin test endpoint) can report success/failure to the dashboard.

    Args:
        url: Target URL.
        secret: Bearer token (empty string for no auth).

    Returns:
        Dict with ``success``, ``status_code``, and ``message`` fields.
    """
    if not url:
        return {"success": False, "status_code": None, "message": "No webhook URL provided"}

    if not _is_safe_url(url):
        return {
            "success": False,
            "status_code": None,
            "message": "URL blocked: targets a private or internal address",
        }

    httpx = _get_httpx()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    body = {
        "event": "test",
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": {
            "message": "Test webhook from TranscriptionSuite.",
            "source": "test",
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=body, headers=headers)
            return {
                "success": response.status_code < 400,
                "status_code": response.status_code,
                "message": f"Webhook test sent (HTTP {response.status_code})",
            }
    except Exception as e:
        return {
            "success": False,
            "status_code": None,
            "message": f"Webhook test failed: {e}",
        }
