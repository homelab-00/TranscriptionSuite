"""Tests for runtime bootstrap dependency integrity decision flow."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


def _load_bootstrap_module() -> ModuleType:
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "server/docker/bootstrap_runtime.py"
    spec = importlib.util.spec_from_file_location(
        "bootstrap_runtime_test_module",
        module_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _touch_runtime_python(runtime_dir: Path) -> None:
    python_path = runtime_dir / ".venv/bin/python"
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text("", encoding="utf-8")


def _write_marker(runtime_dir: Path, payload: dict[str, str]) -> None:
    marker_file = runtime_dir / ".runtime-bootstrap-marker.json"
    marker_file.write_text(json.dumps(payload), encoding="utf-8")


def _patch_fingerprint_context(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "compute_dependency_fingerprint", lambda **_: "fp")
    monkeypatch.setattr(module, "python_abi_tag", lambda: "abi")
    monkeypatch.setattr(module.platform, "machine", lambda: "arch")
    monkeypatch.setattr(module, "run_best_effort_uv_cache_prune", lambda **_: None)


def test_marker_match_integrity_pass_uses_skip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_bootstrap_module()
    runtime_dir = tmp_path / "runtime"
    cache_dir = tmp_path / "runtime-cache"
    runtime_dir.mkdir()
    cache_dir.mkdir()
    _touch_runtime_python(runtime_dir)
    _write_marker(
        runtime_dir,
        {
            "schema_version": module.BOOTSTRAP_SCHEMA_VERSION,
            "fingerprint_source": "lockfile",
            "fingerprint": "fp",
            "python_abi": "abi",
            "arch": "arch",
        },
    )
    _patch_fingerprint_context(module, monkeypatch)
    monkeypatch.setattr(
        module,
        "check_runtime_environment_integrity",
        lambda **_: (True, "ok"),
    )
    monkeypatch.setattr(
        module,
        "run_dependency_sync",
        lambda **_: (_ for _ in ()).throw(
            AssertionError("sync should not run in skip")
        ),
    )

    _, sync_mode, _, diagnostics = module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        fingerprint_source="lockfile",
        rebuild_policy="abi_only",
        log_changes=False,
    )

    assert sync_mode == "skip"
    assert diagnostics["selection_reason"] == "marker_match_integrity_ok"
    assert diagnostics["integrity"]["status"] == "pass"


def test_marker_match_integrity_fail_repairs_with_delta_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_bootstrap_module()
    runtime_dir = tmp_path / "runtime"
    cache_dir = tmp_path / "runtime-cache"
    runtime_dir.mkdir()
    cache_dir.mkdir()
    _touch_runtime_python(runtime_dir)
    _write_marker(
        runtime_dir,
        {
            "schema_version": module.BOOTSTRAP_SCHEMA_VERSION,
            "fingerprint_source": "lockfile",
            "fingerprint": "fp",
            "python_abi": "abi",
            "arch": "arch",
        },
    )
    _patch_fingerprint_context(module, monkeypatch)

    results = iter(
        [
            (False, "precheck failed"),
            (True, "post delta ok"),
        ]
    )
    monkeypatch.setattr(
        module,
        "check_runtime_environment_integrity",
        lambda **_: next(results),
    )

    sync_calls: list[str] = []

    def fake_sync(**_: object) -> None:
        sync_calls.append("sync")
        _touch_runtime_python(runtime_dir)

    monkeypatch.setattr(module, "run_dependency_sync", fake_sync)

    _, sync_mode, _, diagnostics = module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        fingerprint_source="lockfile",
        rebuild_policy="abi_only",
        log_changes=False,
    )

    assert sync_mode == "delta-sync"
    assert len(sync_calls) == 1
    assert diagnostics["selection_reason"] == "marker_match_integrity_failed"
    assert diagnostics["integrity"]["failure_snippet"] == "precheck failed"


def test_post_delta_integrity_fail_escalates_to_rebuild_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_bootstrap_module()
    runtime_dir = tmp_path / "runtime"
    cache_dir = tmp_path / "runtime-cache"
    runtime_dir.mkdir()
    cache_dir.mkdir()
    _touch_runtime_python(runtime_dir)
    _write_marker(
        runtime_dir,
        {
            "schema_version": module.BOOTSTRAP_SCHEMA_VERSION,
            "fingerprint_source": "lockfile",
            "fingerprint": "fp",
            "python_abi": "abi",
            "arch": "arch",
        },
    )
    _patch_fingerprint_context(module, monkeypatch)

    results = iter(
        [
            (False, "precheck failed"),
            (False, "post delta failed"),
            (True, "post rebuild ok"),
        ]
    )
    monkeypatch.setattr(
        module,
        "check_runtime_environment_integrity",
        lambda **_: next(results),
    )

    sync_calls: list[str] = []

    def fake_sync(**_: object) -> None:
        sync_calls.append("sync")
        _touch_runtime_python(runtime_dir)

    monkeypatch.setattr(module, "run_dependency_sync", fake_sync)

    _, sync_mode, _, diagnostics = module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        fingerprint_source="lockfile",
        rebuild_policy="abi_only",
        log_changes=False,
    )

    assert sync_mode == "rebuild-sync"
    assert len(sync_calls) == 2
    assert diagnostics["escalated_to_rebuild"] is True
    assert diagnostics["integrity"]["status"] == "pass"


def test_post_rebuild_integrity_fail_raises_and_keeps_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_bootstrap_module()
    runtime_dir = tmp_path / "runtime"
    cache_dir = tmp_path / "runtime-cache"
    runtime_dir.mkdir()
    cache_dir.mkdir()
    _touch_runtime_python(runtime_dir)
    original_marker = {
        "schema_version": module.BOOTSTRAP_SCHEMA_VERSION,
        "fingerprint_source": "lockfile",
        "fingerprint": "fp",
        "python_abi": "abi",
        "arch": "arch",
        "sync_mode": "original",
    }
    _write_marker(runtime_dir, original_marker)
    _patch_fingerprint_context(module, monkeypatch)

    results = iter(
        [
            (False, "precheck failed"),
            (False, "post delta failed"),
            (False, "post rebuild failed"),
        ]
    )
    monkeypatch.setattr(
        module,
        "check_runtime_environment_integrity",
        lambda **_: next(results),
    )

    def fake_sync(**_: object) -> None:
        _touch_runtime_python(runtime_dir)

    monkeypatch.setattr(module, "run_dependency_sync", fake_sync)

    with pytest.raises(
        RuntimeError,
        match="Runtime integrity check failed after rebuild-sync",
    ):
        module.ensure_runtime_dependencies(
            runtime_dir=runtime_dir,
            cache_dir=cache_dir,
            timeout_seconds=300,
            fingerprint_source="lockfile",
            rebuild_policy="abi_only",
            log_changes=False,
        )

    marker_file = runtime_dir / ".runtime-bootstrap-marker.json"
    persisted = json.loads(marker_file.read_text(encoding="utf-8"))
    assert persisted.get("sync_mode") == "original"


def test_marker_mismatch_and_abi_incompatible_selects_rebuild_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_bootstrap_module()
    runtime_dir = tmp_path / "runtime"
    cache_dir = tmp_path / "runtime-cache"
    runtime_dir.mkdir()
    cache_dir.mkdir()
    _touch_runtime_python(runtime_dir)
    _write_marker(
        runtime_dir,
        {
            "schema_version": module.BOOTSTRAP_SCHEMA_VERSION,
            "fingerprint_source": "lockfile",
            "fingerprint": "old-fingerprint",
            "python_abi": "old-abi",
            "arch": "arch",
        },
    )
    _patch_fingerprint_context(module, monkeypatch)

    checks_called: list[str] = []

    def fake_check(**_: object) -> tuple[bool, str]:
        checks_called.append("check")
        return True, "ok"

    monkeypatch.setattr(module, "check_runtime_environment_integrity", fake_check)

    sync_calls: list[str] = []

    def fake_sync(**_: object) -> None:
        sync_calls.append("sync")
        _touch_runtime_python(runtime_dir)

    monkeypatch.setattr(module, "run_dependency_sync", fake_sync)

    _, sync_mode, _, diagnostics = module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        fingerprint_source="lockfile",
        rebuild_policy="abi_only",
        log_changes=False,
    )

    assert sync_mode == "rebuild-sync"
    assert diagnostics["selection_reason"] == "abi_incompatible"
    assert len(sync_calls) == 1
    assert len(checks_called) == 1
