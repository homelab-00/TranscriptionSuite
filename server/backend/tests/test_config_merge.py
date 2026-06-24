"""Tests for config deep-merge + sparse-overlay loading."""

from __future__ import annotations

from pathlib import Path

from server import config

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
