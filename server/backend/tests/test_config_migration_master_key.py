"""Tests for server.utils.config_migration (Issue #104, Story 1.7 AC4).

Note: the AC text frames this as an "existing test that passes" — that's a
planning-narrative artifact. The module + test are first introduced here
as part of Story 1.7. See sprint-1-design.md §0 for the override rationale.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest
from server.utils import config_migration


def test_creates_master_key_when_missing(tmp_path: Path) -> None:
    """AC4 — ensure_master_key generates a 32-byte random secret (hex-encoded)."""
    secrets_dir = tmp_path / "secrets"
    target = config_migration.ensure_master_key(secrets_dir)

    assert target == secrets_dir / "master.key"
    assert target.exists()

    content = target.read_text(encoding="utf-8").strip()
    # 32 bytes hex-encoded → 64 chars
    assert len(content) == 64
    # Hex characters only
    int(content, 16)  # raises ValueError if not hex


def test_idempotent_when_key_already_exists(tmp_path: Path) -> None:
    """Calling twice does NOT regenerate the key — the original value is preserved."""
    secrets_dir = tmp_path / "secrets"
    config_migration.ensure_master_key(secrets_dir)
    first_value = (secrets_dir / "master.key").read_text(encoding="utf-8")

    config_migration.ensure_master_key(secrets_dir)
    second_value = (secrets_dir / "master.key").read_text(encoding="utf-8")

    assert first_value == second_value


def test_creates_secrets_dir_if_missing(tmp_path: Path) -> None:
    """The function should create the secrets/ dir if it doesn't exist."""
    secrets_dir = tmp_path / "subdir" / "secrets"
    assert not secrets_dir.exists()
    config_migration.ensure_master_key(secrets_dir)
    assert secrets_dir.is_dir()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only chmod semantics")
def test_master_key_has_mode_0600(tmp_path: Path) -> None:
    """AC4 — newly-created file has mode 0600 (owner read/write only)."""
    secrets_dir = tmp_path / "secrets"
    target = config_migration.ensure_master_key(secrets_dir)

    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


def test_two_invocations_in_sequence_produce_distinct_keys(tmp_path: Path) -> None:
    """Sanity-check randomness: distinct dirs → distinct keys (the secrets
    package's token_hex(32) really does provide cryptographic randomness)."""
    a = config_migration.ensure_master_key(tmp_path / "a")
    b = config_migration.ensure_master_key(tmp_path / "b")
    assert a.read_text() != b.read_text()
