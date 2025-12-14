"""
Authentication module for the remote transcription server.

Provides token-based authentication using JWT for secure client verification.
Tokens are time-limited and verified on both WebSocket channels.
"""

import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Token validity duration (1 hour by default)
DEFAULT_TOKEN_EXPIRY_SECONDS = 3600


@dataclass
class AuthToken:
    """Represents a validated authentication token."""

    token_id: str
    created_at: float
    expires_at: float
    client_id: str

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


def generate_auth_token(
    secret_key: str,
    client_id: str = "default",
    expiry_seconds: int = DEFAULT_TOKEN_EXPIRY_SECONDS,
) -> str:
    """
    Generate a secure authentication token.

    Args:
        secret_key: Server's secret key for signing
        client_id: Optional client identifier
        expiry_seconds: Token validity duration

    Returns:
        A signed token string: "token_id.timestamp.expiry.client_id.signature"
    """
    token_id = secrets.token_hex(16)
    created_at = int(time.time())
    expires_at = created_at + expiry_seconds

    # Create payload
    payload = f"{token_id}.{created_at}.{expires_at}.{client_id}"

    # Sign with HMAC-SHA256
    signature = hmac.new(
        secret_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return f"{payload}.{signature}"


class AuthManager:
    """
    Manages authentication for the remote transcription server.

    Handles token validation, active session tracking, and
    single-user enforcement.
    """

    def __init__(self, secret_key: Optional[str] = None):
        """
        Initialize the authentication manager.

        Args:
            secret_key: Secret key for token signing. If not provided,
                       a random key is generated (tokens won't persist across restarts).
        """
        self.secret_key = secret_key or secrets.token_hex(32)
        self._active_session: Optional[AuthToken] = None
        self._lock_acquired_at: Optional[float] = None
        logger.info("AuthManager initialized")

    def generate_token(
        self,
        client_id: str = "default",
        expiry_seconds: int = DEFAULT_TOKEN_EXPIRY_SECONDS,
    ) -> str:
        """Generate a new authentication token."""
        return generate_auth_token(self.secret_key, client_id, expiry_seconds)

    def validate_token(self, token: str) -> Optional[AuthToken]:
        """
        Validate an authentication token.

        Args:
            token: The token string to validate

        Returns:
            AuthToken if valid, None otherwise
        """
        try:
            parts = token.split(".")
            if len(parts) != 5:
                logger.warning("Token validation failed: invalid format")
                return None

            token_id, created_str, expires_str, client_id, signature = parts

            # Reconstruct payload and verify signature
            payload = f"{token_id}.{created_str}.{expires_str}.{client_id}"
            expected_sig = hmac.new(
                self.secret_key.encode("utf-8"),
                payload.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(signature, expected_sig):
                logger.warning("Token validation failed: invalid signature")
                return None

            created_at = float(created_str)
            expires_at = float(expires_str)

            auth_token = AuthToken(
                token_id=token_id,
                created_at=created_at,
                expires_at=expires_at,
                client_id=client_id,
            )

            if auth_token.is_expired():
                logger.warning(f"Token validation failed: token expired for {client_id}")
                return None

            logger.debug(f"Token validated successfully for client: {client_id}")
            return auth_token

        except (ValueError, IndexError) as e:
            logger.warning(f"Token validation failed: {e}")
            return None

    def acquire_session(self, token: AuthToken) -> bool:
        """
        Try to acquire the session lock (single-user enforcement).

        Args:
            token: Validated authentication token

        Returns:
            True if session acquired, False if another user is active
        """
        # Check if there's an active session
        if self._active_session is not None:
            # Check if the active session is from the same client
            if self._active_session.token_id == token.token_id:
                logger.debug("Session reacquired by same client")
                return True

            # Check if active session has expired
            if self._active_session.is_expired():
                logger.info("Previous session expired, releasing lock")
                self._active_session = None
                self._lock_acquired_at = None
            else:
                logger.warning(
                    f"Session lock denied: another user ({self._active_session.client_id}) "
                    f"is using the server"
                )
                return False

        # Acquire the session
        self._active_session = token
        self._lock_acquired_at = time.time()
        logger.info(f"Session acquired by client: {token.client_id}")
        return True

    def release_session(self, token: AuthToken) -> bool:
        """
        Release the session lock.

        Args:
            token: The token of the session to release

        Returns:
            True if released, False if token doesn't match active session
        """
        if self._active_session is None:
            return True

        if self._active_session.token_id != token.token_id:
            logger.warning("Cannot release session: token mismatch")
            return False

        logger.info(f"Session released by client: {token.client_id}")
        self._active_session = None
        self._lock_acquired_at = None
        return True

    def is_session_active(self) -> bool:
        """Check if there's an active session."""
        if self._active_session is None:
            return False

        # Check if session expired
        if self._active_session.is_expired():
            logger.info("Active session expired, auto-releasing")
            self._active_session = None
            self._lock_acquired_at = None
            return False

        return True

    def get_active_client_id(self) -> Optional[str]:
        """Get the client ID of the active session, if any."""
        if self.is_session_active():
            return self._active_session.client_id  # type: ignore
        return None

    def force_release(self) -> None:
        """Force release the session lock (admin operation)."""
        if self._active_session:
            logger.warning(
                f"Force releasing session for client: {self._active_session.client_id}"
            )
        self._active_session = None
        self._lock_acquired_at = None
