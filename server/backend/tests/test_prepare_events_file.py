"""Tests for the startup-events file preparation step (GH-318).

The dashboard creates the events directory on the host as the desktop user
(0700) and the file inside it as 0600, then bind-mounts the directory. The
server runs as the unprivileged ``appuser``, a different uid, which could not
even traverse that directory - so every startup and download event was dropped
with EACCES and the dashboard never saw one. This step runs as root from
docker-entrypoint.sh and hands the file to appuser.
"""

from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path
from types import ModuleType

import pytest


def _load_module() -> ModuleType:
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "server/docker/prepare_events_file.py"
    spec = importlib.util.spec_from_file_location("prepare_events_file_test_module", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _host_style_events_file(tmp_path: Path) -> Path:
    """What the dashboard creates: a private dir with a private file."""
    events_dir = tmp_path / "transcription-suite-events-abc"
    events_dir.mkdir(mode=0o700)
    events_file = events_dir / "startup-events.jsonl"
    events_file.write_text("", encoding="utf-8")
    events_file.chmod(0o600)
    return events_file


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_opens_the_file_for_the_server_user_and_the_dir_for_traversal(tmp_path: Path) -> None:
    module = _load_module()
    events_file = _host_style_events_file(tmp_path)

    assert (
        module.prepare_events_file(
            events_file, os.getuid(), os.getgid(), allowed_dir=events_file.parent
        )
        is True
    )

    # Owner (the server user) writes; the host user reads it back as "other".
    assert _mode(events_file) == 0o644
    # Traversable but not listable by others; the host user still owns it.
    assert _mode(events_file.parent) == 0o711


def test_hands_ownership_of_the_file_to_the_server_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    events_file = _host_style_events_file(tmp_path)
    chowned: list[tuple[int, int, int]] = []
    file_inode = events_file.stat().st_ino

    def fake_fchown(fd, uid, gid):
        chowned.append((os.fstat(fd).st_ino, uid, gid))

    monkeypatch.setattr(module.os, "fchown", fake_fchown)

    module.prepare_events_file(events_file, 10000, 10000, allowed_dir=events_file.parent)

    # Only the file changes owner - the directory must stay the host user's so
    # the dashboard can still clean it up. And it is done through the open
    # descriptor, so nothing can be swapped in between the check and the change.
    assert chowned == [(file_inode, 10000, 10000)]


def test_still_fixes_modes_when_the_mount_ignores_ownership_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Docker Desktop file sharing rejects chown; the modes must still be set."""
    module = _load_module()
    events_file = _host_style_events_file(tmp_path)

    def refuse(*_args, **_kwargs):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(module.os, "fchown", refuse)

    assert (
        module.prepare_events_file(events_file, 10000, 10000, allowed_dir=events_file.parent)
        is True
    )
    assert _mode(events_file) == 0o644


def test_does_nothing_when_there_is_no_events_file(tmp_path: Path) -> None:
    module = _load_module()

    assert (
        module.prepare_events_file(tmp_path / "missing.jsonl", 10000, 10000, allowed_dir=tmp_path)
        is False
    )


def test_refuses_a_symlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Root must not be steered into re-owning whatever a link points at."""
    module = _load_module()
    target = tmp_path / "secret"
    target.write_text("x", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "startup-events.jsonl"
    link.symlink_to(target)
    chowned: list[object] = []
    monkeypatch.setattr(module.os, "fchown", lambda *a, **k: chowned.append(a))

    assert module.prepare_events_file(link, 10000, 10000, allowed_dir=tmp_path) is False
    assert chowned == []
    assert _mode(target) == 0o600


def test_refuses_a_file_outside_the_events_mount(tmp_path: Path) -> None:
    """STARTUP_EVENTS_FILE is operator-settable. Pointed at, say, the mounted
    config directory, this step would have re-moded that directory as root."""
    module = _load_module()
    elsewhere = tmp_path / "user-config"
    elsewhere.mkdir(mode=0o700)
    victim = elsewhere / "config.yaml"
    victim.write_text("x", encoding="utf-8")
    victim.chmod(0o600)

    assert (
        module.prepare_events_file(
            victim, os.getuid(), os.getgid(), allowed_dir=tmp_path / "startup-events"
        )
        is False
    )
    assert _mode(victim) == 0o600
    assert _mode(elsewhere) == 0o700


def test_main_only_acts_inside_the_events_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    events_file = _host_style_events_file(tmp_path)
    monkeypatch.setenv("STARTUP_EVENTS_FILE", str(events_file))

    assert str(module.EVENTS_MOUNT_DIR) == "/startup-events"
    assert module.main() == 0
    assert _mode(events_file) == 0o600  # a tmp path is not the mount: untouched


def test_main_is_a_no_op_without_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.delenv("STARTUP_EVENTS_FILE", raising=False)

    assert module.main() == 0


def test_main_never_fails_the_entrypoint_when_the_user_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    events_file = _host_style_events_file(tmp_path)
    monkeypatch.setenv("STARTUP_EVENTS_FILE", str(events_file))

    def no_such_user(_name):
        raise KeyError("appuser")

    monkeypatch.setattr(module.pwd, "getpwnam", no_such_user)

    assert module.main() == 0
    assert _mode(events_file) == 0o600  # untouched


def test_the_image_ships_the_script_and_the_entrypoint_runs_it_before_bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    dockerfile = (repo_root / "server/docker/Dockerfile").read_text(encoding="utf-8")
    entrypoint = (repo_root / "server/docker/docker-entrypoint.sh").read_text(encoding="utf-8")

    # Root-owned (no --chown): it runs as root, so appuser must not be able to edit it.
    assert "COPY server/docker/prepare_events_file.py ./docker/" in dockerfile
    assert entrypoint.index("docker/prepare_events_file.py") < entrypoint.index(
        "docker/bootstrap_runtime.py"
    )
