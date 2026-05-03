"""OS keychain wrapper with explicit headless fallback (Issue #104, Story 1.7).

Backends, in priority order:
  1. OS-native — macOS Keychain / Windows DPAPI / Linux libsecret — via the
     ``keyring`` package's auto-detected backend.
  2. ``keyrings.alt.file.EncryptedKeyring`` — gated by the env flag
     ``KEYRING_BACKEND_FALLBACK=encrypted_file``. The encryption key is read
     from ``secrets/master.key`` (bootstrapped by ``config_migration``).

If neither path is usable AND the env flag is NOT set, ``set()`` raises
:class:`KeychainUnavailableError` with an actionable message — never silently
falls back to plaintext storage (NFR8).

Tests MUST install the in-memory ``fake_keyring`` fixture from
``tests/conftest.py``; never touch the real OS keychain in tests.

Cross-references:
  - FR49 (private fields stored via OS keychain)
  - FR50 (file-encrypted fallback for headless Linux/Docker)
  - NFR8  (no plaintext secrets on disk)
  - NFR33 (``keyring >= 25.0, < 26``)
  - NFR34 (``keyrings.alt`` extra)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import keyring
from keyring.errors import KeyringError, NoKeyringError

logger = logging.getLogger(__name__)


_SERVICE_PREFIX = "transcriptionsuite"

_FALLBACK_ENV_VALUE = "encrypted_file"
_FALLBACK_HINT = (
    "No usable keyring backend on this host. "
    "Set KEYRING_BACKEND_FALLBACK=encrypted_file to enable the file-encrypted fallback "
    "(security delta: see docs/deployment-guide.md → 'Keychain fallback (encrypted-file mode)')."
)


class KeychainUnavailableError(RuntimeError):
    """Raised when no usable keyring backend is available and the
    ``KEYRING_BACKEND_FALLBACK`` env-flag is not set (NFR8)."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _secrets_dir() -> Path:
    """Project-root ``secrets/`` (NOT inside the package).

    Resolved relative to this file's location: ``server/backend/utils/keychain.py``
    → parents[2] is ``server/backend/`` is wrong. We need parents[3] for
    project root.

    server/backend/utils/keychain.py
    └─ parents[0] = utils/
    └─ parents[1] = backend/
    └─ parents[2] = server/
    └─ parents[3] = project root

    So return ``parents[3] / 'secrets'``.
    """
    return Path(__file__).resolve().parents[3] / "secrets"


def _read_master_key() -> str:
    p = _secrets_dir() / "master.key"
    return p.read_text(encoding="utf-8").strip()


def _maybe_install_encrypted_file_backend() -> bool:
    """Switch keyring to ``keyrings.alt.file.EncryptedKeyring`` if requested.

    Returns ``True`` if the alt backend was installed (caller can retry the
    operation); ``False`` otherwise.
    """
    if os.environ.get("KEYRING_BACKEND_FALLBACK") != _FALLBACK_ENV_VALUE:
        return False

    try:
        from keyrings.alt.file import EncryptedKeyring
    except ImportError:
        logger.warning(
            "KEYRING_BACKEND_FALLBACK=encrypted_file requested but "
            "keyrings.alt is not installed; install with `uv sync --extra dev`."
        )
        return False

    try:
        master_key = _read_master_key()
    except FileNotFoundError:
        logger.warning(
            "KEYRING_BACKEND_FALLBACK=encrypted_file requested but %s does not exist; "
            "run config_migration.ensure_master_key() first.",
            _secrets_dir() / "master.key",
        )
        return False

    backend = EncryptedKeyring()
    backend.file_path = str(_secrets_dir() / "encrypted_keyring.cfg")
    # The python-keyrings.alt backend reads the master key via its
    # ``keyring_key`` attribute; assign before any operation.
    backend.keyring_key = master_key
    keyring.set_keyring(backend)
    logger.info("Installed keyrings.alt.EncryptedKeyring (file fallback)")
    return True


def _try_or_install_fallback(op_name: str, op):
    """Run ``op``; on ``NoKeyringError`` / ``KeyringError`` try to install
    the encrypted-file fallback and retry once. If the fallback isn't
    available, raise :class:`KeychainUnavailableError`."""
    try:
        return op()
    except (NoKeyringError, KeyringError):
        if _maybe_install_encrypted_file_backend():
            try:
                return op()
            except (NoKeyringError, KeyringError) as exc2:
                raise KeychainUnavailableError(
                    f"keychain.{op_name} failed even with encrypted-file fallback: {exc2}"
                ) from exc2
        raise KeychainUnavailableError(_FALLBACK_HINT) from None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def set(key: str, value: str) -> None:  # noqa: A001 - matches AC2 wording
    """Store ``value`` under ``key`` in the OS keychain.

    Naming convention: ``key`` is ``<entity>.<id>.<field>`` such as
    ``profile.123.webhook_token``.
    """
    _try_or_install_fallback("set", lambda: keyring.set_password(_SERVICE_PREFIX, key, value))


def get(key: str) -> str | None:  # noqa: A001 - matches AC2 wording
    """Return the stored value, or ``None`` if no entry exists.

    Bridges keyring's "no entry" return (``None``) and "no backend"
    exceptions: in the latter case we attempt fallback installation and
    retry; if neither succeeds we return ``None`` (read-side is
    best-effort — callers should decide whether missing means "not set"
    or "infrastructure broken")."""
    try:
        return keyring.get_password(_SERVICE_PREFIX, key)
    except (NoKeyringError, KeyringError):
        if _maybe_install_encrypted_file_backend():
            try:
                return keyring.get_password(_SERVICE_PREFIX, key)
            except (NoKeyringError, KeyringError):
                return None
        return None


def delete(key: str) -> None:
    """Best-effort delete. Missing entries are not an error."""
    try:
        keyring.delete_password(_SERVICE_PREFIX, key)
    except (NoKeyringError, KeyringError):
        # Don't try to install fallback for delete — if the entry was set
        # via the fallback, it would have already been installed earlier.
        pass
