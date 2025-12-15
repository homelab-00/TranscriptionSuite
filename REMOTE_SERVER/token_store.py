"""
Persistent token storage for the remote transcription server.

Stores tokens in a JSON file with support for:
- Admin and regular user roles
- Manual revocation (tokens never expire automatically)
- Persistent secret key
"""

import json
import logging
import secrets
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List
from filelock import FileLock

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_STORE_PATH = Path(__file__).parent / "data" / "tokens.json"


@dataclass
class StoredToken:
    """Represents a token stored in the token store."""

    token: str
    client_name: str
    created_at: str  # ISO format
    is_admin: bool
    is_revoked: bool

    @classmethod
    def create(cls, client_name: str, is_admin: bool = False) -> "StoredToken":
        """Create a new token."""
        return cls(
            token=secrets.token_hex(32),
            client_name=client_name,
            created_at=datetime.now(timezone.utc).isoformat(),
            is_admin=is_admin,
            is_revoked=False,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "StoredToken":
        """Create from dictionary."""
        return cls(
            token=data["token"],
            client_name=data["client_name"],
            created_at=data["created_at"],
            is_admin=data.get("is_admin", False),
            is_revoked=data.get("is_revoked", False),
        )


class TokenStore:
    """
    Persistent token storage with file-based JSON backend.

    Features:
    - Tokens never expire automatically
    - Admin tokens can manage other tokens
    - Thread-safe file operations with file locking
    """

    def __init__(self, store_path: Optional[Path] = None):
        """
        Initialize the token store.

        Args:
            store_path: Path to the JSON file. Uses default if not specified.
        """
        self.store_path = Path(store_path) if store_path else DEFAULT_TOKEN_STORE_PATH
        self.lock_path = self.store_path.with_suffix(".lock")
        self._ensure_store_exists()

    def _ensure_store_exists(self) -> None:
        """Ensure the store file and directory exist."""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.store_path.exists():
            self._initialize_store()

    def _initialize_store(self) -> None:
        """Initialize a new token store with an admin token."""
        secret_key = secrets.token_hex(32)
        admin_token = StoredToken.create("admin", is_admin=True)

        data = {"secret_key": secret_key, "tokens": [admin_token.to_dict()]}

        self._write_store(data)

        logger.info("Token store initialized")
        print("\n" + "=" * 70)
        print("INITIAL ADMIN TOKEN GENERATED")
        print("=" * 70)
        print(f"\nAdmin Token: {admin_token.token}")
        print("\nSave this token! It's required to access the admin panel.")
        print("This message will only appear once.")
        print("=" * 70 + "\n")

    def _read_store(self) -> dict:
        """Read the token store file with locking."""
        with FileLock(self.lock_path):
            with open(self.store_path, "r") as f:
                return json.load(f)

    def _write_store(self, data: dict) -> None:
        """Write to the token store file with locking."""
        with FileLock(self.lock_path):
            # Write to temp file first, then rename for atomicity
            temp_path = self.store_path.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                json.dump(data, f, indent=2)
            temp_path.rename(self.store_path)

    def get_secret_key(self) -> str:
        """Get the secret key for token signing (if needed for other purposes)."""
        data = self._read_store()
        return data["secret_key"]

    def validate_token(self, token: str) -> Optional[StoredToken]:
        """
        Validate a token string.

        Args:
            token: The token string to validate

        Returns:
            StoredToken if valid and not revoked, None otherwise
        """
        data = self._read_store()

        for token_data in data["tokens"]:
            if token_data["token"] == token:
                stored_token = StoredToken.from_dict(token_data)
                if stored_token.is_revoked:
                    logger.warning(f"Token for '{stored_token.client_name}' is revoked")
                    return None
                logger.debug(f"Token validated for client: {stored_token.client_name}")
                return stored_token

        logger.warning("Token validation failed: token not found")
        return None

    def is_admin(self, token: str) -> bool:
        """Check if a token has admin privileges."""
        stored_token = self.validate_token(token)
        return stored_token is not None and stored_token.is_admin

    def generate_token(self, client_name: str, is_admin: bool = False) -> StoredToken:
        """
        Generate a new token.

        Args:
            client_name: Name/identifier for the client
            is_admin: Whether this token has admin privileges

        Returns:
            The newly created StoredToken
        """
        data = self._read_store()

        new_token = StoredToken.create(client_name, is_admin)
        data["tokens"].append(new_token.to_dict())

        self._write_store(data)
        logger.info(f"Generated new token for client: {client_name} (admin={is_admin})")

        return new_token

    def revoke_token(self, token: str) -> bool:
        """
        Revoke a token.

        Args:
            token: The token string to revoke

        Returns:
            True if revoked, False if token not found
        """
        data = self._read_store()

        for token_data in data["tokens"]:
            if token_data["token"] == token:
                token_data["is_revoked"] = True
                self._write_store(data)
                logger.info(f"Token revoked for client: {token_data['client_name']}")
                return True

        logger.warning("Cannot revoke token: not found")
        return False

    def delete_token(self, token: str) -> bool:
        """
        Permanently delete a token.

        Args:
            token: The token string to delete

        Returns:
            True if deleted, False if token not found
        """
        data = self._read_store()

        for i, token_data in enumerate(data["tokens"]):
            if token_data["token"] == token:
                client_name = token_data["client_name"]
                del data["tokens"][i]
                self._write_store(data)
                logger.info(f"Token deleted for client: {client_name}")
                return True

        logger.warning("Cannot delete token: not found")
        return False

    def list_tokens(self) -> List[StoredToken]:
        """
        List all tokens.

        Returns:
            List of all stored tokens
        """
        data = self._read_store()
        return [StoredToken.from_dict(t) for t in data["tokens"]]

    def get_active_tokens(self) -> List[StoredToken]:
        """
        Get all non-revoked tokens.

        Returns:
            List of active (non-revoked) tokens
        """
        return [t for t in self.list_tokens() if not t.is_revoked]

    def get_token_by_client_name(self, client_name: str) -> Optional[StoredToken]:
        """
        Find a token by client name.

        Args:
            client_name: The client name to search for

        Returns:
            StoredToken if found, None otherwise
        """
        for token in self.list_tokens():
            if token.client_name == client_name:
                return token
        return None
