"""Tests for config deep-merge + sparse-overlay loading."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server import config

# Capture the REAL get_user_config_dir at import time (before the autouse
# _isolate_user_config_dir fixture monkeypatches the module attribute), so the
# env-var test below can exercise the genuine implementation.
_REAL_GET_USER_CONFIG_DIR = config.get_user_config_dir


# ── _deep_merge (pure) ───────────────────────────────────────────────────────


def test_deep_merge_overrides_scalar():
    assert config._deep_merge({"a": 1, "b": 2}, {"b": 3}) == {"a": 1, "b": 3}


def test_deep_merge_recurses_nested_dicts():
    base = {"s": {"x": 1, "y": 2}}
    overlay = {"s": {"y": 9}}
    assert config._deep_merge(base, overlay) == {"s": {"x": 1, "y": 9}}


def test_deep_merge_replaces_lists_not_concatenate():
    assert config._deep_merge({"t": [-1]}, {"t": [1, 2]}) == {"t": [1, 2]}


def test_deep_merge_null_overrides_value():
    assert config._deep_merge({"lang": "en"}, {"lang": None}) == {"lang": None}


def test_deep_merge_type_mismatch_overlay_wins():
    assert config._deep_merge({"a": {"x": 1}}, {"a": 5}) == {"a": 5}


def test_deep_merge_adds_new_keys():
    assert config._deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_deep_merge_does_not_mutate_inputs():
    base = {"s": {"x": 1}}
    overlay = {"s": {"y": 2}}
    config._deep_merge(base, overlay)
    assert base == {"s": {"x": 1}}
    assert overlay == {"s": {"y": 2}}


# ── Two-layer load (defaults + sparse overlay) ──────────────────────────────
# The autouse fixture _isolate_user_config_dir (conftest.py) points
# get_user_config_dir() at the per-test tmp_path, so a config.yaml written
# there is picked up as the user overlay; defaults come from server/config.yaml.


def test_sparse_overlay_merges_onto_defaults(tmp_path: Path):
    (tmp_path / "config.yaml").write_text(
        "diarization:\n  embedding_batch_size: 1\n", encoding="utf-8"
    )
    cfg = config.ServerConfig()
    assert cfg.get("diarization", "embedding_batch_size") == 1  # overridden
    assert cfg.get("diarization", "device") == "auto"  # inherited
    assert cfg.get("diarization", "parallel") is False  # inherited
    assert cfg.get("stt", "buffer_size") == 512  # untouched section


def test_no_overlay_loads_defaults_only(tmp_path: Path):
    cfg = config.ServerConfig()  # tmp_path has no config.yaml
    assert cfg.get("stt", "buffer_size") == 512
    assert cfg.defaults_path is not None
    assert cfg.defaults_path.name == "config.yaml"


def test_explicit_config_path_is_single_file_no_merge(tmp_path: Path):
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("diarization:\n  parallel: true\n", encoding="utf-8")
    cfg = config.ServerConfig(config_path=explicit)
    assert cfg.get("diarization", "parallel") is True
    assert cfg.get("stt", "buffer_size") is None  # defaults NOT merged in


def test_env_override_wins_over_merged_overlay(tmp_path: Path, monkeypatch):
    (tmp_path / "config.yaml").write_text(
        "main_transcriber:\n  model: from-overlay\n", encoding="utf-8"
    )
    monkeypatch.setenv("MAIN_TRANSCRIBER_MODEL", "from-env")
    cfg = config.ServerConfig()
    assert cfg.get("main_transcriber", "model") == "from-env"


def test_invalid_overlay_degrades_to_defaults(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("foo: [1, 2\n", encoding="utf-8")  # unclosed
    cfg = config.ServerConfig()  # must NOT raise
    assert cfg.get("stt", "buffer_size") == 512


def test_overlay_path_points_at_user_file(tmp_path: Path):
    cfg = config.ServerConfig()
    assert cfg.overlay_path == tmp_path / "config.yaml"
    assert cfg.loaded_from == tmp_path / "config.yaml"


# ── set() persists a sparse overlay ─────────────────────────────────────────


def test_set_creates_sparse_overlay(tmp_path: Path):
    cfg = config.ServerConfig()  # no overlay file yet
    cfg.set("diarization", "parallel", value=False)
    assert cfg.get("diarization", "parallel") is False
    written = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert written == {"diarization": {"parallel": False}}  # SPARSE, not full


def test_set_merges_into_existing_sparse_overlay(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("diarization:\n  parallel: false\n", encoding="utf-8")
    cfg = config.ServerConfig()
    cfg.set("diarization", "embedding_batch_size", value=1)
    written = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert written == {"diarization": {"parallel": False, "embedding_batch_size": 1}}
    # defaults still resolved for untouched keys
    assert cfg.get("stt", "buffer_size") == 512


def test_set_does_not_materialize_full_defaults(tmp_path: Path):
    cfg = config.ServerConfig()
    cfg.set("diarization", "parallel", value=True)
    written = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert "stt" not in written and "main_transcriber" not in written


# ── USER_CONFIG_DIR env override (native macOS server / advanced users) ─────


def test_get_user_config_dir_honors_env(tmp_path: Path, monkeypatch):
    # Skip if a real /user-config exists (Docker), which takes precedence.
    if Path("/user-config").is_dir():
        pytest.skip("/user-config present; Docker branch wins")
    target = tmp_path / "server-config"
    monkeypatch.setenv("USER_CONFIG_DIR", str(target))
    assert _REAL_GET_USER_CONFIG_DIR() == target


def test_get_user_config_dir_ignores_empty_env(tmp_path: Path, monkeypatch):
    if Path("/user-config").is_dir():
        pytest.skip("/user-config present; Docker branch wins")
    monkeypatch.setenv("USER_CONFIG_DIR", "   ")
    # Falls through to a platform default (never returns an empty path).
    assert str(_REAL_GET_USER_CONFIG_DIR()) not in ("", "   ")


# ── Defaults located through the editable-install symlink (native macOS) ────
# Regression: the native (MLX) launcher creates a self-referential symlink
# server/backend/server -> . so `import server` resolves under the editable
# install. That makes config.__file__ report one dir too deep
# (server/backend/server/config.py), so parent.parent pointed at
# server/backend/ and the bundled defaults at server/config.yaml were never
# found — the sparse overlay then had no merge base. _defaults_candidates()
# must .resolve() the symlink so the defaults are still located.


@pytest.mark.skipif(
    __import__("sys").platform == "win32", reason="symlink creation needs privileges on Windows"
)
def test_defaults_located_through_editable_symlink(tmp_path: Path, monkeypatch):
    # Recreate the native-macOS layout: defaults one dir above the backend, and
    # a self-referential symlink so the module is reachable one level deeper.
    server_dir = tmp_path / "server"
    backend = server_dir / "backend"
    backend.mkdir(parents=True)
    (server_dir / "config.yaml").write_text("stt:\n  buffer_size: 512\n", encoding="utf-8")
    (backend / "config.py").write_text("# stub module\n", encoding="utf-8")
    (backend / "server").symlink_to(".")  # editable-install self-reference

    # config.__file__ as reported under the editable install (via the symlink).
    deep_file = backend / "server" / "config.py"
    monkeypatch.setattr(config, "__file__", str(deep_file))
    # cwd must NOT accidentally contain a config.yaml (candidate #3).
    monkeypatch.chdir(tmp_path)

    cands = config.ServerConfig.__new__(config.ServerConfig)._defaults_candidates()
    # The bundled defaults are found via the resolved (symlink-collapsed) path.
    assert [p.resolve() for p in cands] == [(server_dir / "config.yaml").resolve()]
