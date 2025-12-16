"""
Authentication module for the remote transcription server.

Provides token-based authentication with:
- Persistent token storage with configurable expiration
- Admin tokens (never expire) and regular tokens (30-day default)
- Rate limiting on authentication endpoints
- Admin and regular user roles
- Single-user session enforcement
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .token_store import TokenStore, StoredToken

logger = logging.getLogger(__name__)


@dataclass
class AuthSession:
    """Represents an active authenticated session."""

    token: str
    client_name: str
    is_admin: bool
    connected_at: float

    @classmethod
    def from_stored_token(cls, stored_token: StoredToken) -> "AuthSession":
        """Create a session from a stored token."""
        return cls(
            token=stored_token.token,
            client_name=stored_token.client_name,
            is_admin=stored_token.is_admin,
            connected_at=time.time(),
        )


class AuthManager:
    """
    Manages authentication for the remote transcription server.

    Features:
    - Token validation via persistent token store
    - Single-user session enforcement
    - Admin privilege checking
    """

    def __init__(self, token_store_path: Optional[Path] = None):
        """
        Initialize the authentication manager.

        Args:
            token_store_path: Path to the token store JSON file.
                            If not provided, uses the default path.
        """
        self.token_store = TokenStore(token_store_path)
        self._active_session: Optional[AuthSession] = None
        self._lock_acquired_at: Optional[float] = None
        logger.info("AuthManager initialized with persistent token store")

    def validate_token(self, token: str) -> Optional[StoredToken]:
        """
        Validate an authentication token.

        Args:
            token: The token string to validate

        Returns:
            StoredToken if valid and not revoked, None otherwise
        """
        return self.token_store.validate_token(token)

    def is_admin(self, token: str) -> bool:
        """Check if a token has admin privileges."""
        return self.token_store.is_admin(token)

    def generate_token(
        self,
        client_name: str,
        is_admin: bool = False,
        expiry_days: Optional[int] = None,
    ) -> StoredToken:
        """
        Generate a new authentication token.

        Args:
            client_name: Name/identifier for the client
            is_admin: Whether this token should have admin privileges
            expiry_days: Days until expiration. None uses default (30 days for users).

        Returns:
            The newly created StoredToken
        """
        return self.token_store.generate_token(client_name, is_admin, expiry_days)

    def revoke_token(self, token: str) -> bool:
        """
        Revoke a token by token string.

        Args:
            token: The token string to revoke

        Returns:
            True if revoked, False if not found
        """
        # Don't allow revoking the active session's token
        if self._active_session and self._active_session.token == token:
            logger.warning("Cannot revoke token of active session")
            return False
        return self.token_store.revoke_token(token)

    def revoke_token_by_id(self, token_id: str) -> bool:
        """
        Revoke a token by its ID.

        Args:
            token_id: The token ID to revoke

        Returns:
            True if revoked, False if not found
        """
        # Check if this is the active session's token
        stored_token = self.token_store.get_token_by_id(token_id)
        if stored_token and self._active_session:
            if self._active_session.token == stored_token.token:
                logger.warning("Cannot revoke token of active session")
                return False
        return self.token_store.revoke_token_by_id(token_id)

    def list_tokens(self):
        """List all tokens (admin operation)."""
        return self.token_store.list_tokens()

    def acquire_session(self, stored_token: StoredToken) -> bool:
        """
        Try to acquire the session lock (single-user enforcement).

        Args:
            stored_token: Validated stored token

        Returns:
            True if session acquired, False if another user is active
        """
        # Check if there's an active session
        if self._active_session is not None:
            # Allow same client to reconnect
            if self._active_session.token == stored_token.token:
                logger.debug("Session reacquired by same client")
                self._active_session.connected_at = time.time()
                return True

            logger.warning(
                f"Session lock denied: another user ({self._active_session.client_name}) "
                f"is using the server"
            )
            return False

        # Acquire the session
        self._active_session = AuthSession.from_stored_token(stored_token)
        self._lock_acquired_at = time.time()
        logger.info(f"Session acquired by client: {stored_token.client_name}")
        return True

    def release_session(self, token: str) -> bool:
        """
        Release the session lock.

        Args:
            token: The token of the session to release

        Returns:
            True if released, False if token doesn't match active session
        """
        if self._active_session is None:
            return True

        if self._active_session.token != token:
            logger.warning("Cannot release session: token mismatch")
            return False

        logger.info(f"Session released by client: {self._active_session.client_name}")
        self._active_session = None
        self._lock_acquired_at = None
        return True

    def is_session_active(self) -> bool:
        """Check if there's an active session."""
        return self._active_session is not None

    def get_active_session(self) -> Optional[AuthSession]:
        """Get the current active session, if any."""
        return self._active_session

    def get_active_client_name(self) -> Optional[str]:
        """Get the client name of the active session, if any."""
        if self._active_session:
            return self._active_session.client_name
        return None

    def force_release(self) -> None:
        """Force release the session lock (admin operation)."""
        if self._active_session:
            logger.warning(
                f"Force releasing session for client: {self._active_session.client_name}"
            )
        self._active_session = None
        self._lock_acquired_at = None
