"""Bootstrap helper: ensure ``secrets/master.key`` exists (Issue #104, Story 1.7).

This module is idempotent — calling :func:`ensure_master_key` on a
post-bootstrap install is a no-op. The function is invoked from
``api/main.py``'s lifespan startup so a brand-new install can immediately
use the file-encrypted keyring fallback (FR50 / NFR8 AC1).

Security delta of the file-encrypted fallback: see
``docs/deployment-guide.md`` → "Keychain fallback (encrypted-file mode)".
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)

_KEY_BYTES = 32  # → 64 hex chars; matches NFR8 AC1 expectations


def ensure_master_key(secrets_dir: Path) -> Path:
    """Generate ``secrets/master.key`` if missing.

    Returns the path to the key file (always — whether newly created or
    already present).

    File mode 0600 is enforced on the freshly-created file. We do NOT
    re-chmod an existing file — operators may have intentionally tightened
    permissions further (e.g. via systemd file ACLs).
    """
    secrets_dir.mkdir(parents=True, exist_ok=True)
    target = secrets_dir / "master.key"

    if target.exists():
        return target

    target.write_text(secrets.token_hex(_KEY_BYTES), encoding="utf-8")
    # chmod is a best-effort op on Windows; failure is non-fatal there.
    try:
        target.chmod(0o600)
    except OSError as exc:  # pragma: no cover — Windows-only failure mode
        logger.warning(
            "Could not chmod 0600 on %s: %s — review permissions manually on Windows",
            target,
            exc,
        )

    logger.info("Generated new master.key at %s", target)
    return target
