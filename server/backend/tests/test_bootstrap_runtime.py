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


def test_check_diarization_access_without_token_skips_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_bootstrap_module()

    def fail_run(**_: object) -> None:
        raise AssertionError("subprocess.run should not be called when token missing")

    monkeypatch.setattr(module.subprocess, "run", fail_run)

    status = module.check_diarization_access(
        venv_python=Path("/runtime/.venv/bin/python"),
        diarization_model=module.DEFAULT_DIARIZATION_MODEL,
        hf_token=None,
        hf_home="/models",
        timeout_seconds=1800,
    )

    assert status == {"available": False, "reason": "token_missing"}


def test_check_diarization_access_preloads_pipeline_and_clamps_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_bootstrap_module()
    seen: dict[str, object] = {}

    class FakeResult:
        def __init__(self) -> None:
            self.stdout = '{"available": true, "reason": "ready"}\n'

    def fake_run(cmd, text, capture_output, timeout, env, check):  # type: ignore[no-untyped-def]
        seen["cmd"] = cmd
        seen["timeout"] = timeout
        seen["env"] = env
        assert text is True
        assert capture_output is True
        assert check is False
        return FakeResult()

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    status = module.check_diarization_access(
        venv_python=Path("/runtime/.venv/bin/python"),
        diarization_model=module.DEFAULT_DIARIZATION_MODEL,
        hf_token="hf_test_token",
        hf_home="/models",
        timeout_seconds=5000,
    )

    assert status == {"available": True, "reason": "ready"}
    assert seen["timeout"] == 1800

    cmd = seen["cmd"]
    assert isinstance(cmd, list)
    assert cmd[0] == "/runtime/.venv/bin/python"
    assert cmd[1] == "-c"
    assert "Pipeline.from_pretrained" in cmd[2]

    env = seen["env"]
    assert isinstance(env, dict)
    assert env["HF_HOME"] == "/models"


def test_compute_diarization_preload_cache_key_changes_with_context(
    tmp_path: Path,
) -> None:
    module = _load_bootstrap_module()
    hf_home = tmp_path / "models"
    diar_model = module.DEFAULT_DIARIZATION_MODEL

    key_without_cache = module.compute_diarization_preload_cache_key(
        diarization_model=diar_model,
        hf_token="hf_test_token_a",
        hf_home=str(hf_home),
    )

    repo_dir = hf_home / "hub" / "models--pyannote--speaker-diarization-community-1"
    (repo_dir / "refs").mkdir(parents=True, exist_ok=True)
    (repo_dir / "refs" / "main").write_text("revision-a\n", encoding="utf-8")
    (repo_dir / "snapshots" / "revision-a").mkdir(parents=True, exist_ok=True)

    key_with_cache = module.compute_diarization_preload_cache_key(
        diarization_model=diar_model,
        hf_token="hf_test_token_a",
        hf_home=str(hf_home),
    )
    key_with_other_token = module.compute_diarization_preload_cache_key(
        diarization_model=diar_model,
        hf_token="hf_test_token_b",
        hf_home=str(hf_home),
    )
    key_with_other_model = module.compute_diarization_preload_cache_key(
        diarization_model="pyannote/speaker-diarization-3.1",
        hf_token="hf_test_token_a",
        hf_home=str(hf_home),
    )

    assert key_without_cache != key_with_cache
    assert key_with_cache != key_with_other_token
    assert key_with_cache != key_with_other_model


def test_should_reuse_cached_diarization_status_gate() -> None:
    module = _load_bootstrap_module()

    assert module.should_reuse_cached_diarization_status(
        previous_status_payload={
            "features": {
                "diarization": {
                    "available": True,
                    "reason": "ready",
                    "preload_cache_key": "match-key",
                }
            }
        },
        preload_cache_key="match-key",
    )

    assert not module.should_reuse_cached_diarization_status(
        previous_status_payload={
            "features": {
                "diarization": {
                    "available": True,
                    "reason": "ready",
                    "preload_cache_key": "stale-key",
                }
            }
        },
        preload_cache_key="match-key",
    )

    assert not module.should_reuse_cached_diarization_status(
        previous_status_payload={
            "features": {
                "diarization": {
                    "available": False,
                    "reason": "unavailable",
                    "preload_cache_key": "match-key",
                }
            }
        },
        preload_cache_key="match-key",
    )


def test_main_reuses_cached_diarization_status_when_preload_key_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_bootstrap_module()
    runtime_dir = tmp_path / "runtime"
    cache_dir = tmp_path / "runtime-cache"
    status_file = runtime_dir / "bootstrap-status.json"
    runtime_dir.mkdir()
    cache_dir.mkdir()
    _touch_runtime_python(runtime_dir)

    status_file.write_text(
        json.dumps(
            {
                "features": {
                    "diarization": {
                        "available": True,
                        "reason": "ready",
                        "preload_cache_key": "cache-key-match",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def fake_ensure_runtime_dependencies(**_: object):  # type: ignore[no-untyped-def]
        diagnostics = {
            "selection_reason": "marker_match_integrity_ok",
            "escalated_to_rebuild": False,
            "integrity": {},
        }
        return runtime_dir / ".venv", "skip", {}, diagnostics

    def fail_diarization_check(**_: object) -> None:  # type: ignore[no-untyped-def]
        raise AssertionError(
            "check_diarization_access should be skipped when cache key matches"
        )

    captured_status: dict[str, object] = {}

    def fake_write_status_file(path: Path, payload: dict[str, object]) -> None:
        captured_status["path"] = path
        captured_status["payload"] = payload

    monkeypatch.setattr(
        module,
        "ensure_runtime_dependencies",
        fake_ensure_runtime_dependencies,
    )
    monkeypatch.setattr(
        module,
        "load_config_models",
        lambda: ("Systran/faster-whisper-large-v3", module.DEFAULT_DIARIZATION_MODEL),
    )
    monkeypatch.setattr(
        module,
        "compute_diarization_preload_cache_key",
        lambda **_: "cache-key-match",
    )
    monkeypatch.setattr(module, "check_diarization_access", fail_diarization_check)
    monkeypatch.setattr(module, "write_status_file", fake_write_status_file)

    monkeypatch.setenv("HF_TOKEN", "hf_test_token")
    monkeypatch.setenv("HF_HOME", str(tmp_path / "models"))
    monkeypatch.setenv("BOOTSTRAP_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("BOOTSTRAP_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("BOOTSTRAP_STATUS_FILE", str(status_file))

    rc = module.main()

    assert rc == 0
    payload = captured_status.get("payload")
    assert isinstance(payload, dict)
    diarization = payload["features"]["diarization"]  # type: ignore[index]
    assert diarization["available"] is True  # type: ignore[index]
    assert diarization["reason"] == "ready"  # type: ignore[index]
    assert diarization["preload_mode"] == "cached"  # type: ignore[index]
    assert diarization["preload_cache_key"] == "cache-key-match"  # type: ignore[index]
