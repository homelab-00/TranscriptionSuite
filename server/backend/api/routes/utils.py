"""
Shared utilities for API routes.
"""

from fastapi import Request

from server.core.token_store import get_token_store


def get_client_name(request: Request) -> str:
    """
    Extract the client name from the request's authentication token.

    Returns the client_name from the token, or a default value if not found.
    """
    # Try Authorization header first
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        # Try cookie
        token = request.cookies.get("auth_token")

    if token:
        token_store = get_token_store()
        stored_token = token_store.validate_token(token)
        if stored_token:
            return stored_token.client_name

    return "Unknown Client"


def get_authenticated_token(request: Request):
    """
    Get the authenticated token from the request.

    Returns the StoredToken if valid, None otherwise.
    """
    # Try Authorization header first
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        # Try cookie
        token = request.cookies.get("auth_token")

    if token:
        token_store = get_token_store()
        return token_store.validate_token(token)

    return None


def require_admin(request: Request) -> bool:
    """
    Check if the request is from an admin user.

    Returns True if authenticated as admin, False otherwise.
    """
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
