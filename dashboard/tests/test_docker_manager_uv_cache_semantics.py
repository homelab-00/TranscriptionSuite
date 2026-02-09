"""Tests for UV cache reconciliation and config reset semantics."""

from __future__ import annotations

from pathlib import Path

from dashboard.common.docker_manager import DockerManager


def test_reconcile_uv_cache_enabled_missing_volume_reports_cold_cache(
    tmp_path: Path, monkeypatch
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    manager = DockerManager(config_dir=config_dir)
    manager.update_uv_cache_state(decision="enabled")

    messages: list[str] = []
    monkeypatch.setattr(manager, "volume_exists", lambda _name: False)

    decision, cache_dir, cold_cache_expected = manager.reconcile_uv_cache_state(
        progress_callback=messages.append
    )

    assert decision == "enabled"
    assert cache_dir == manager.UV_CACHE_PERSISTENT_DIR
    assert cold_cache_expected is True
    assert any("cold cache expected" in msg.lower() for msg in messages)


def test_reconcile_uv_cache_skipped_ignores_existing_volume(
    tmp_path: Path, monkeypatch
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    manager = DockerManager(config_dir=config_dir)
    manager.update_uv_cache_state(decision="skipped")

    messages: list[str] = []
    monkeypatch.setattr(manager, "volume_exists", lambda _name: True)

    decision, cache_dir, cold_cache_expected = manager.reconcile_uv_cache_state(
        progress_callback=messages.append
    )

    assert decision == "skipped"
    assert cache_dir == manager.UV_CACHE_EPHEMERAL_DIR
    assert cold_cache_expected is False
    assert any("will be ignored" in msg.lower() for msg in messages)


def test_reconcile_uv_cache_unset_keeps_onboarding_semantics(
    tmp_path: Path, monkeypatch
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    manager = DockerManager(config_dir=config_dir)

    # Unset is default for fresh state.
    called = {"volume_exists": False}

    def _volume_exists(_name: str) -> bool:
        called["volume_exists"] = True
        return True

    monkeypatch.setattr(manager, "volume_exists", _volume_exists)
    decision, cache_dir, cold_cache_expected = manager.reconcile_uv_cache_state()

    assert decision == "unset"
    assert cache_dir == manager.UV_CACHE_PERSISTENT_DIR
    assert cold_cache_expected is False
    assert called["volume_exists"] is False


def test_remove_config_directory_clears_external_state(
    tmp_path: Path, monkeypatch
) -> None:
    config_dir = tmp_path / "config"
    external_dir = tmp_path / "external-state"
    config_dir.mkdir(parents=True)
    external_dir.mkdir(parents=True)
    (config_dir / "dashboard.yaml").write_text("test: true\n", encoding="utf-8")
    (external_dir / ".env").write_text(
        "UV_CACHE_VOLUME_DECISION=enabled\n", encoding="utf-8"
    )

    manager = DockerManager(config_dir=config_dir)
    manager._cached_auth_token = "token-to-clear"
    monkeypatch.setattr(manager, "_get_external_state_dir", lambda: external_dir)

    result = manager.remove_config_directory()

    assert result.success is True
    assert not config_dir.exists()
    assert not external_dir.exists()
    assert manager._cached_auth_token is None


def test_get_container_user_config_dir_removes_stale_target_config(
    tmp_path: Path, monkeypatch
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    external_dir = tmp_path / "external-state"
    stale_target = external_dir / "docker-user-config" / "config.yaml"
    stale_target.parent.mkdir(parents=True, exist_ok=True)
    stale_target.write_text("stale: true\n", encoding="utf-8")

    manager = DockerManager(config_dir=config_dir)
    monkeypatch.setattr(manager, "_get_external_state_dir", lambda: external_dir)

    target_dir = manager._get_container_user_config_dir()

    assert target_dir == external_dir / "docker-user-config"
    assert not stale_target.exists()
