"""Guard the .env -> compose -> container contract for optional-install flags.

Regression test for the SenseVoice Phase 1 bug where ``INSTALL_FUNASR`` was wired
through the bootstrap reader, the dashboard writer, and ``.env`` -- but the
``docker-compose.yml`` ``environment:`` block never forwarded it into the
container. The variable was therefore dropped at the compose boundary,
``bootstrap_runtime.py`` read its ``False`` default, FunASR was never installed,
and the SenseVoice model failed to load (Record button greyed out) despite the
flag being set everywhere a human would look.

The invariant: every ``INSTALL_*`` flag the runtime bootstrap consumes via
``parse_bool_env(...)`` MUST be forwarded by the base compose file, otherwise the
flag is silently inert. A pure-text contract test (no Docker needed) is the
cheapest place to catch a future flag that forgets the compose line.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE_FILE = _REPO_ROOT / "server/docker/docker-compose.yml"
_BOOTSTRAP_FILE = _REPO_ROOT / "server/docker/bootstrap_runtime.py"

# Flags consumed by the bootstrap but intentionally NOT plumbed through the base
# compose environment (none today). Keep empty; document any exception here.
_KNOWN_COMPOSE_OMISSIONS: frozenset[str] = frozenset()


def _flags_consumed_by_bootstrap() -> set[str]:
    text = _BOOTSTRAP_FILE.read_text(encoding="utf-8")
    return set(re.findall(r'parse_bool_env\(\s*"(INSTALL_\w+)"', text))


def _flags_forwarded_by_compose() -> set[str]:
    text = _COMPOSE_FILE.read_text(encoding="utf-8")
    # Matches an environment entry like:  - INSTALL_FUNASR=${INSTALL_FUNASR:-false}
    return set(re.findall(r"-\s*(INSTALL_\w+)=\$\{", text))


def test_repo_files_exist() -> None:
    assert _COMPOSE_FILE.is_file(), f"missing {_COMPOSE_FILE}"
    assert _BOOTSTRAP_FILE.is_file(), f"missing {_BOOTSTRAP_FILE}"


def test_every_bootstrap_install_flag_is_forwarded_by_compose() -> None:
    consumed = _flags_consumed_by_bootstrap()
    forwarded = _flags_forwarded_by_compose()
    # Sanity: we actually parsed something, so the regexes did not silently rot.
    assert "INSTALL_WHISPER" in consumed
    assert "INSTALL_WHISPER" in forwarded

    missing = consumed - forwarded - _KNOWN_COMPOSE_OMISSIONS
    assert not missing, (
        "These INSTALL_* flags are read by bootstrap_runtime.py but are not "
        f"forwarded by {_COMPOSE_FILE.name}'s environment block, so they are "
        f"silently inert inside the container: {sorted(missing)}"
    )


def test_install_funasr_is_wired_end_to_end() -> None:
    # Explicit guard for the exact flag whose missing compose line shipped the bug.
    assert "INSTALL_FUNASR" in _flags_consumed_by_bootstrap()
    assert "INSTALL_FUNASR" in _flags_forwarded_by_compose()
