"""Tests for Live Mode language semantics and migration behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dashboard.common.config import ClientConfig
from dashboard.common.live_mode_config import (
    build_live_mode_start_config,
    resolve_live_mode_language,
)


class _StubConfig:
    """Minimal config stub for orchestrator Live Mode config resolution tests."""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    def _read(self, root: dict[str, Any], keys: tuple[str, ...], default: Any) -> Any:
        value: Any = root
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return default
            if value is None:
                return default
        return value

    def get_server_config(self, *keys: str, default: Any = None) -> Any:
        return self._read(self._data, keys, default)

    def get(self, *keys: str, default: Any = None) -> Any:
        return self._read(self._data, keys, default)


def test_live_language_migration_runs_once(tmp_path: Path, monkeypatch) -> None:
    cfg = ClientConfig(config_path=tmp_path / "dashboard.yaml")
    calls: list[tuple[tuple[str, ...], Any]] = []

    def fake_set_server_config(*keys: str, value: Any) -> bool:
        calls.append((keys, value))
        return True

    monkeypatch.setattr(cfg, "set_server_config", fake_set_server_config)

    assert cfg.get("ui", "live_language_default_migrated_v1", default=False) is False
    assert cfg.migrate_live_language_default_v1() is True
    assert calls == [(("live_transcriber", "live_language"), "en")]
    assert cfg.get("ui", "live_language_default_migrated_v1", default=False) is True

    calls.clear()
    assert cfg.migrate_live_language_default_v1() is True
    assert calls == []


def test_live_language_migration_does_not_flip_flag_on_failure(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = ClientConfig(config_path=tmp_path / "dashboard.yaml")

    def fake_set_server_config(*keys: str, value: Any) -> bool:
        del keys, value
        return False

    monkeypatch.setattr(cfg, "set_server_config", fake_set_server_config)

    assert cfg.migrate_live_language_default_v1() is False
    assert cfg.get("ui", "live_language_default_migrated_v1", default=False) is False


def test_live_mode_language_resolution_for_english_and_auto() -> None:
    base = {
        "main_transcriber": {"model": "Systran/faster-whisper-large-v3"},
        "live_transcriber": {
            "model": None,
            "translation_enabled": False,
            "translation_target_language": "en",
            "live_language": "en",
        },
        "live_mode": {"grace_period": 1.25},
    }

    config = _StubConfig(base)
    assert resolve_live_mode_language(config) == "en"
    cfg, task = build_live_mode_start_config(config)
    assert cfg["language"] == "en"
    assert task == "transcribe"

    base["live_transcriber"]["live_language"] = ""
    assert resolve_live_mode_language(config) == ""
    cfg, task = build_live_mode_start_config(config)
    assert cfg["language"] == ""
    assert task == "transcribe"


def test_live_mode_task_changes_only_with_translation_toggle() -> None:
    data = {
        "main_transcriber": {"model": "Systran/faster-whisper-large-v3"},
        "live_transcriber": {
            "model": None,
            "translation_enabled": False,
            "translation_target_language": "en",
            "live_language": "el",
        },
        "live_mode": {"grace_period": 1.0},
    }
    config = _StubConfig(data)

    _, task = build_live_mode_start_config(config)
    assert task == "transcribe"

    data["live_transcriber"]["translation_enabled"] = True
    _, task = build_live_mode_start_config(config)
    assert task == "translate"
