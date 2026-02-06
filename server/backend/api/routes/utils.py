"""
Shared utilities for API routes.
"""

import asyncio
import os
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Any

from fastapi import Request, WebSocket
from starlette.websockets import WebSocketState

from server.core.token_store import get_token_store

# Check if TLS mode is enabled
TLS_MODE = os.environ.get("TLS_ENABLED", "false").lower() == "true"


@dataclass
class WebSocketAuthResult:
    """Result of websocket authentication."""

    client_name: str
    is_admin: bool
    is_localhost_bypass: bool
    stored_token: Any | None = None


def is_localhost(client_host: str | None) -> bool:
    """Return True if the provided host is localhost."""
    return client_host in ("127.0.0.1", "::1", "localhost")


def extract_bearer_token(auth_header: str | None) -> str | None:
    """Extract bearer token from an Authorization header."""
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        return token or None
    return None


def get_request_auth_token(request: Request) -> str | None:
    """Get auth token from request header or cookie."""
    token = extract_bearer_token(request.headers.get("Authorization"))
    if token:
        return token
    cookie_token = request.cookies.get("auth_token")
    return cookie_token.strip() if cookie_token and cookie_token.strip() else None


def get_websocket_auth_token(websocket: WebSocket) -> str | None:
    """Get auth token from websocket header or cookie."""
    token = extract_bearer_token(websocket.headers.get("authorization"))
    if token:
        return token

    cookie_header = websocket.headers.get("cookie")
    if not cookie_header:
        return None

    cookie = SimpleCookie()
    cookie.load(cookie_header)
    morsel = cookie.get("auth_token")
    if morsel is None:
        return None
    value = morsel.value.strip()
    return value or None


def validate_auth_token(token: str | None):
    """Validate a token and return the stored token object if valid."""
    if not token:
        return None
    return get_token_store().validate_token(token)


async def send_websocket_auth_failure(
    websocket: WebSocket,
    message: str,
    *,
    failure_type: str = "auth_fail",
    close: bool = True,
) -> None:
    """Send a websocket auth failure payload and optionally close the socket."""
    payload = {
        "type": failure_type,
        "data": {"message": message},
        "timestamp": asyncio.get_event_loop().time(),
    }

    if websocket.client_state == WebSocketState.CONNECTED:
        try:
            await websocket.send_json(payload)
        except Exception:
            pass

    if close:
        try:
            await websocket.close()
        except Exception:
            pass


async def authenticate_websocket_from_message(
    websocket: WebSocket,
    *,
    timeout_seconds: float = 10.0,
    require_admin: bool = False,
    allow_localhost_bypass: bool = True,
    failure_type: str = "auth_fail",
) -> WebSocketAuthResult | None:
    """
    Authenticate a websocket using the first client message.

    Expects payload: {"type":"auth","data":{"token":"..."}}.
    """
    try:
        auth_msg = await asyncio.wait_for(
            websocket.receive_json(), timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        await send_websocket_auth_failure(
            websocket,
            "Authentication timeout",
            failure_type=failure_type,
        )
        return None
    except Exception:
        await send_websocket_auth_failure(
            websocket,
            "Invalid authentication payload",
            failure_type=failure_type,
        )
        return None

    if auth_msg.get("type") != "auth":
        await send_websocket_auth_failure(
            websocket,
            "Expected auth message",
            failure_type=failure_type,
        )
        return None

    client_host = websocket.client.host if websocket.client else None
    if allow_localhost_bypass and not TLS_MODE and is_localhost(client_host):
        return WebSocketAuthResult(
            client_name="localhost-user",
            is_admin=True,
            is_localhost_bypass=True,
            stored_token=None,
        )

    token = auth_msg.get("data", {}).get("token")
    stored_token = validate_auth_token(token)
    if stored_token is None:
        await send_websocket_auth_failure(
            websocket,
            "Invalid or expired token",
            failure_type=failure_type,
        )
        return None

    if require_admin and not stored_token.is_admin:
        await send_websocket_auth_failure(
            websocket,
            "Admin access required",
            failure_type=failure_type,
        )
        return None

    return WebSocketAuthResult(
        client_name=stored_token.client_name,
        is_admin=stored_token.is_admin,
        is_localhost_bypass=False,
        stored_token=stored_token,
    )


async def authenticate_websocket_from_headers(
    websocket: WebSocket,
    *,
    require_admin: bool = False,
    allow_localhost_bypass: bool = False,
    failure_type: str = "auth_fail",
) -> WebSocketAuthResult | None:
    """Authenticate websocket using Authorization/Cookie headers."""
    client_host = websocket.client.host if websocket.client else None
    if allow_localhost_bypass and not TLS_MODE and is_localhost(client_host):
        return WebSocketAuthResult(
            client_name="localhost-user",
            is_admin=True,
            is_localhost_bypass=True,
            stored_token=None,
        )

    token = get_websocket_auth_token(websocket)
    if not token:
        await send_websocket_auth_failure(
            websocket,
            "No token provided",
            failure_type=failure_type,
        )
        return None

    stored_token = validate_auth_token(token)
    if stored_token is None:
        await send_websocket_auth_failure(
            websocket,
            "Invalid or expired token",
            failure_type=failure_type,
        )
        return None

    if require_admin and not stored_token.is_admin:
        await send_websocket_auth_failure(
            websocket,
            "Admin access required",
            failure_type=failure_type,
        )
        return None

    return WebSocketAuthResult(
        client_name=stored_token.client_name,
        is_admin=stored_token.is_admin,
        is_localhost_bypass=False,
        stored_token=stored_token,
    )


def get_client_name(request: Request) -> str:
    """
    Extract the client name from the request's authentication token.

    Returns the client_name from the token, or a default value if not found.
    """
    stored_token = validate_auth_token(get_request_auth_token(request))
    if stored_token:
        return stored_token.client_name

    return "Unknown Client"


def get_authenticated_token(request: Request):
    """
    Get the authenticated token from the request.

    Returns the StoredToken if valid, None otherwise.
    """
    return validate_auth_token(get_request_auth_token(request))


def require_admin(request: Request) -> bool:
    """
    Check if the request is from an admin user.

    In local mode (TLS disabled), localhost requests are treated as admin.
    In TLS mode, a valid admin token is required.

    Returns True if authenticated as admin, False otherwise.
    """
    # In local mode, allow localhost requests as admin
    if not TLS_MODE:
        client_host = request.client.host if request.client else None
        if is_localhost(client_host):
            return True

    # Check for valid admin token
    stored_token = get_authenticated_token(request)
    return stored_token is not None and stored_token.is_admin


def sanitize_for_log(value: str, max_length: int = 200) -> str:
    """
    Sanitize user input before logging to prevent log injection attacks.

    Escapes newlines and removes control characters that could interfere
    with log parsing or monitoring systems.

    Args:
        value: The string to sanitize
        max_length: Maximum length before truncation (default: 200)

    Returns:
        Sanitized string safe for logging
    """
    if not value:
        return value

    # Escape newlines and carriage returns
    sanitized = value.replace("\n", "\\n").replace("\r", "\\r")

    # Remove non-printable control characters (keep spaces and tabs)
    sanitized = "".join(c for c in sanitized if c.isprintable() or c in " \t")

    # Truncate if too long
    if len(sanitized) > max_length:
        return sanitized[:max_length] + "..."

    return sanitized
