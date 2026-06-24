"""Tests for config deep-merge + sparse-overlay loading."""

from __future__ import annotations

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
