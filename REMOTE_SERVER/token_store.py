"""
Persistent token storage for the remote transcription server.

Stores tokens in a JSON file with support for:
- Admin and regular user roles
- Token expiration (30 days default for regular users, never for admins)
- Token hashing (SHA-256) for secure storage
- Manual revocation
- Persistent secret key
- Non-secret token IDs for admin operations
"""

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Tuple
from filelock import FileLock

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_STORE_PATH = Path(__file__).parent / "data" / "tokens.json"


# Default token expiration (30 days)
DEFAULT_TOKEN_EXPIRY_DAYS = 30

# Token store version for migration tracking
CURRENT_STORE_VERSION = 2  # v2 = hashed tokens


def hash_token(token: str) -> str:
    """Hash a token using SHA-256 for secure storage."""
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class StoredToken:
    """Represents a token stored in the token store."""

    token: str  # This is the HASH of the token, not the plaintext
    client_name: str
    created_at: str  # ISO format
    is_admin: bool
    is_revoked: bool
    expires_at: Optional[str] = None  # ISO format, None = never expires (for admin)
    token_id: Optional[str] = None  # Short ID for UI operations (non-secret)

    @classmethod
    def create(
        cls,
        client_name: str,
        is_admin: bool = False,
        expiry_days: Optional[int] = None,
    ) -> Tuple["StoredToken", str]:
        """Create a new token.

        Args:
            client_name: Name/identifier for the client
            is_admin: Whether this token has admin privileges
            expiry_days: Days until expiration. None uses default (30 days).
                        Admin tokens don't expire by default.

        Returns:
            Tuple of (StoredToken with hashed token, plaintext token for user)
        """
        now = datetime.now(timezone.utc)

        # Admin tokens don't expire by default, regular tokens expire in 30 days
        if expiry_days is None:
            if is_admin:
                expires_at = None  # Admin tokens never expire
            else:
                expires_at = (now + timedelta(days=DEFAULT_TOKEN_EXPIRY_DAYS)).isoformat()
        elif expiry_days <= 0:
            expires_at = None  # Explicit no expiry
        else:
            expires_at = (now + timedelta(days=expiry_days)).isoformat()

        # Generate a non-secret ID for UI operations (128 bits)
        token_id = secrets.token_hex(16)  # 32 chars, sufficient entropy

        # Generate plaintext token and its hash
        plaintext_token = secrets.token_hex(32)
        hashed_token = hash_token(plaintext_token)

        stored_token = cls(
            token=hashed_token,  # Store only the hash
            client_name=client_name,
            created_at=now.isoformat(),
            is_admin=is_admin,
            is_revoked=False,
            expires_at=expires_at,
            token_id=token_id,
        )

        return (
            stored_token,
            plaintext_token,
        )  # Return hash for storage, plaintext for user

    def is_expired(self) -> bool:
        """Check if the token has expired."""
        if self.expires_at is None:
            return False
        try:
            expiry = datetime.fromisoformat(self.expires_at)
            return datetime.now(timezone.utc) > expiry
        except (ValueError, TypeError):
            return False

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
            expires_at=data.get("expires_at"),
            token_id=data.get("token_id"),
        )


class TokenStore:
    """
    Persistent token storage with file-based JSON backend.

    Features:
    - Token expiration (30 days for regular users, never for admins)
    - Admin tokens can manage other tokens
    - Non-secret token IDs for UI operations (revoke, etc.)
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
        else:
            self._migrate_store_if_needed()

    def _migrate_store_if_needed(self) -> None:
        """Migrate store to current version if needed.

        v1 -> v2: Tokens stored in plaintext become hashed.
        WARNING: After migration, existing plaintext tokens become INVALID.
        New tokens must be generated for all users.
        """
        data = self._read_store()
        store_version = data.get("version", 1)

        if store_version >= CURRENT_STORE_VERSION:
            return  # Already up to date

        logger.warning("=" * 70)
        logger.warning("TOKEN STORE MIGRATION REQUIRED")
        logger.warning("=" * 70)

        if store_version < 2:
            # v1 -> v2: Mark that tokens are now expected to be hashed
            # Old plaintext tokens will no longer validate
            # We DON'T hash existing tokens because we'd lose the ability
            # to validate them (can't hash a hash and match plaintext input)
            logger.warning(
                "Migrating to v2 (hashed tokens). ALL EXISTING TOKENS ARE NOW INVALID!"
            )
            logger.warning(
                "You must regenerate tokens for all users via the admin panel."
            )

            # Clear all existing tokens since they can't be used anymore
            # Keep only the structure, user will need to create new admin token
            old_token_count = len(data.get("tokens", []))
            data["tokens"] = []
            data["version"] = CURRENT_STORE_VERSION

            # Generate a new admin token
            admin_token, plaintext_token = StoredToken.create("admin", is_admin=True)
            data["tokens"].append(admin_token.to_dict())

            self._write_store(data)

            logger.warning(f"Cleared {old_token_count} old tokens.")
            print("\n" + "=" * 70)
            print("TOKEN STORE MIGRATED TO HASHED STORAGE (v2)")
            print("=" * 70)
            print(f"\nCleared {old_token_count} old (plaintext) tokens.")
            print("\nNEW ADMIN TOKEN GENERATED:")
            print(f"\nAdmin Token: {plaintext_token}")
            print("\nSave this token! It's required to access the admin panel.")
            print("This message will only appear once.")
            print("Generate new tokens for other users via the admin panel.")
            print("=" * 70 + "\n")

    def _initialize_store(self) -> None:
        """Initialize a new token store with an admin token."""
        secret_key = secrets.token_hex(32)
        admin_token, plaintext_token = StoredToken.create("admin", is_admin=True)

        data = {
            "version": CURRENT_STORE_VERSION,
            "secret_key": secret_key,
            "tokens": [admin_token.to_dict()],
        }

        self._write_store(data)

        logger.info("Token store initialized")
        print("\n" + "=" * 70)
        print("INITIAL ADMIN TOKEN GENERATED")
        print("=" * 70)
        print(f"\nAdmin Token: {plaintext_token}")
        print("\nSave this token! It's required to access the admin panel.")
        print("This message will only appear once.")
        print("(Token is stored securely as a hash)")
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
            token: The plaintext token string to validate

        Returns:
            StoredToken if valid, not revoked, and not expired, None otherwise
        """
        data = self._read_store()

        # Hash the input token for comparison
        token_hash = hash_token(token)

        for token_data in data["tokens"]:
            # Compare hashes (stored tokens are hashed)
            if token_data["token"] == token_hash:
                stored_token = StoredToken.from_dict(token_data)
                if stored_token.is_revoked:
                    logger.warning(f"Token for '{stored_token.client_name}' is revoked")
                    return None
                if stored_token.is_expired():
                    logger.warning(f"Token for '{stored_token.client_name}' has expired")
                    return None
                logger.debug(f"Token validated for client: {stored_token.client_name}")
                return stored_token

        logger.warning("Token validation failed: token not found")
        return None

    def is_admin(self, token: str) -> bool:
        """Check if a token has admin privileges."""
        stored_token = self.validate_token(token)
        return stored_token is not None and stored_token.is_admin

    def generate_token(
        self,
        client_name: str,
        is_admin: bool = False,
        expiry_days: Optional[int] = None,
    ) -> Tuple[StoredToken, str]:
        """
        Generate a new token.

        Args:
            client_name: Name/identifier for the client
            is_admin: Whether this token has admin privileges
            expiry_days: Days until expiration. None uses default (30 days for users).

        Returns:
            Tuple of (StoredToken with hashed token, plaintext token for user)
        """
        data = self._read_store()

        new_token, plaintext_token = StoredToken.create(
            client_name, is_admin, expiry_days
        )
        data["tokens"].append(new_token.to_dict())

        self._write_store(data)
        expiry_info = (
            f", expires_at={new_token.expires_at}"
            if new_token.expires_at
            else ", never expires"
        )
        logger.info(
            f"Generated new token for client: {client_name} (admin={is_admin}{expiry_info})"
        )

        return new_token, plaintext_token

    def revoke_token(self, token: str) -> bool:
        """
        Revoke a token by token string.

        Args:
            token: The plaintext token string to revoke

        Returns:
            True if revoked, False if token not found
        """
        data = self._read_store()

        # Hash the input token for comparison
        token_hash = hash_token(token)

        for token_data in data["tokens"]:
            if token_data["token"] == token_hash:
                token_data["is_revoked"] = True
                self._write_store(data)
                logger.info(f"Token revoked for client: {token_data['client_name']}")
                return True

        logger.warning("Cannot revoke token: not found")
        return False

    def revoke_token_by_id(self, token_id: str) -> bool:
        """
        Revoke a token by its ID (non-secret identifier).

        Args:
            token_id: The token ID to revoke

        Returns:
            True if revoked, False if token not found
        """
        data = self._read_store()

        for token_data in data["tokens"]:
            if token_data.get("token_id") == token_id:
                token_data["is_revoked"] = True
                self._write_store(data)
                logger.info(
                    f"Token revoked by ID for client: {token_data['client_name']}"
                )
                return True

        logger.warning(f"Cannot revoke token: ID {token_id} not found")
        return False

    def get_token_by_id(self, token_id: str) -> Optional[StoredToken]:
        """
        Get a token by its ID.

        Args:
            token_id: The token ID to look up

        Returns:
            StoredToken if found, None otherwise
        """
        data = self._read_store()

        for token_data in data["tokens"]:
            if token_data.get("token_id") == token_id:
                return StoredToken.from_dict(token_data)

        return None

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
