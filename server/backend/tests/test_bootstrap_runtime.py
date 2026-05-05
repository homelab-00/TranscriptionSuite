"""Tests for runtime bootstrap dependency bootstrap decision flow."""

from __future__ import annotations

import importlib.util
import json
import subprocess
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


def _patch_fingerprint_context(module: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "compute_dependency_fingerprint", lambda **_: "fp")
    monkeypatch.setattr(module, "compute_structural_fingerprint", lambda **_: "struct-fp")
    monkeypatch.setattr(module, "compute_lock_fingerprint", lambda: "lock-fp")
    monkeypatch.setattr(module, "python_abi_tag", lambda: "abi")
    monkeypatch.setattr(module.platform, "machine", lambda: "arch")


def test_hash_match_uses_skip(
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
            "fingerprint": "fp",
            "python_abi": "abi",
            "arch": "arch",
        },
    )
    _patch_fingerprint_context(module, monkeypatch)
    monkeypatch.setattr(
        module,
        "run_dependency_sync",
        lambda **_: (_ for _ in ()).throw(AssertionError("sync should not run in skip")),
    )

    _, sync_mode, _, diagnostics = module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        log_changes=False,
    )

    assert sync_mode == "skip"
    assert diagnostics["selection_reason"] == "hash_match_skip"


def test_venv_missing_uses_rebuild_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_bootstrap_module()
    runtime_dir = tmp_path / "runtime"
    cache_dir = tmp_path / "runtime-cache"
    runtime_dir.mkdir()
    cache_dir.mkdir()
    _patch_fingerprint_context(module, monkeypatch)

    sync_calls: list[str] = []

    def fake_sync(**_: object) -> None:
        sync_calls.append("sync")
        _touch_runtime_python(runtime_dir)

    monkeypatch.setattr(module, "run_dependency_sync", fake_sync)

    _, sync_mode, _, diagnostics = module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        log_changes=False,
    )

    assert sync_mode == "rebuild-sync"
    assert len(sync_calls) == 1
    assert diagnostics["selection_reason"] == "venv_missing"
    persisted = json.loads(
        (runtime_dir / ".runtime-bootstrap-marker.json").read_text(encoding="utf-8")
    )
    assert persisted["sync_mode"] == "rebuild-sync"
    assert persisted["selection_reason"] == "venv_missing"


def test_hash_mismatch_rebuilds_sync_once(
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
            "fingerprint": "old-fingerprint",
            "python_abi": "old-abi",
            "arch": "arch",
        },
    )
    _patch_fingerprint_context(module, monkeypatch)

    sync_calls: list[str] = []
    rmtree_calls: list[Path] = []
    original_rmtree = module.shutil.rmtree

    def fake_rmtree(path: Path, ignore_errors: bool = False) -> None:
        assert ignore_errors is True
        rmtree_calls.append(path)
        if Path(path) == runtime_dir / ".venv" and (runtime_dir / ".venv").exists():
            original_rmtree(path, ignore_errors=ignore_errors)

    def fake_sync(**_: object) -> None:
        sync_calls.append("sync")
        _touch_runtime_python(runtime_dir)

    monkeypatch.setattr(module, "run_dependency_sync", fake_sync)
    monkeypatch.setattr(module.shutil, "rmtree", fake_rmtree)

    _, sync_mode, _, diagnostics = module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        log_changes=False,
    )

    assert sync_mode == "rebuild-sync"
    assert len(sync_calls) == 1
    assert diagnostics["selection_reason"] == "structural_mismatch"
    assert rmtree_calls[0] == runtime_dir / ".venv"


def test_rebuild_sync_failure_raises_and_keeps_marker(
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
        "fingerprint": "old-fingerprint",
        "python_abi": "abi",
        "arch": "arch",
        "sync_mode": "original",
    }
    _write_marker(runtime_dir, original_marker)
    _patch_fingerprint_context(module, monkeypatch)

    with pytest.raises(
        RuntimeError,
        match="Dependency sync failed for mode=rebuild-sync",
    ):
        monkeypatch.setattr(
            module,
            "run_dependency_sync",
            lambda **_: (_ for _ in ()).throw(RuntimeError("sync exploded")),
        )
        module.ensure_runtime_dependencies(
            runtime_dir=runtime_dir,
            cache_dir=cache_dir,
            timeout_seconds=300,
            log_changes=False,
        )

    marker_file = runtime_dir / ".runtime-bootstrap-marker.json"
    persisted = json.loads(marker_file.read_text(encoding="utf-8"))
    assert persisted == original_marker


def test_hash_mismatch_selects_rebuild_sync_without_integrity_checks(
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
            "fingerprint": "old-fingerprint",
            "python_abi": "old-abi",
            "arch": "arch",
        },
    )
    _patch_fingerprint_context(module, monkeypatch)

    sync_calls: list[str] = []

    def fake_sync(**_: object) -> None:
        sync_calls.append("sync")
        _touch_runtime_python(runtime_dir)

    monkeypatch.setattr(module, "run_dependency_sync", fake_sync)

    _, sync_mode, _, diagnostics = module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        log_changes=False,
    )

    assert sync_mode == "rebuild-sync"
    assert diagnostics["selection_reason"] == "structural_mismatch"
    assert len(sync_calls) == 1


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
            "selection_reason": "hash_match_skip",
            "escalated_to_rebuild": False,
            "integrity": {},
        }
        return runtime_dir / ".venv", "skip", {}, diagnostics

    def fail_diarization_check(**_: object) -> None:  # type: ignore[no-untyped-def]
        raise AssertionError("check_diarization_access should be skipped when cache key matches")

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
        lambda: (
            "Systran/faster-whisper-large-v3",
            "Systran/faster-whisper-large-v3",
            module.DEFAULT_DIARIZATION_MODEL,
        ),
    )
    monkeypatch.setattr(
        module,
        "compute_diarization_preload_cache_key",
        lambda **_: "cache-key-match",
    )
    monkeypatch.setattr(module, "check_diarization_access", fail_diarization_check)
    monkeypatch.setattr(
        module,
        "check_nemo_asr_import",
        lambda **_: {"available": False, "reason": "import_failed"},
    )
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


def test_check_vibevoice_asr_import_parses_extended_probe_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_bootstrap_module()

    payload = {
        "available": False,
        "reason": "import_failed",
        "error": "legacy: ModuleNotFoundError: no module named x",
        "attempted_imports": [
            (
                "vibevoice.modeling_vibevoice_asr:VibeVoiceASRForConditionalGeneration + "
                + "vibevoice.processor.vibevoice_asr_processing:VibeVoiceASRProcessor"
            ),
            (
                "vibevoice.modular.modeling_vibevoice_asr:VibeVoiceASRForConditionalGeneration + "
                + "vibevoice.processor.vibevoice_asr_processor:VibeVoiceASRProcessor"
            ),
        ],
        "top_level_error": "ModuleNotFoundError: No module named 'vibevoice'",
    }

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        return subprocess.CompletedProcess(
            args=["python", "-c", "probe"],
            returncode=0,
            stdout=json.dumps(payload) + "\n",
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.check_vibevoice_asr_import(Path("/tmp/fake-python"), timeout_seconds=30)

    assert result["available"] is False
    assert result["reason"] == "import_failed"
    assert result["error"] == payload["error"]
    assert result["attempted_imports"] == payload["attempted_imports"]
    assert result["top_level_error"] == payload["top_level_error"]


def test_vibevoice_model_family_detection_helpers() -> None:
    module = _load_bootstrap_module()

    assert module.is_vibevoice_asr_model_name("microsoft/VibeVoice-ASR") is True
    assert module.is_vibevoice_asr_model_name("scerz/VibeVoice-ASR-4bit") is True
    assert module.is_vibevoice_asr_model_name("Systran/faster-whisper-large-v3") is False

    assert module.is_vibevoice_asr_quantized_model_name("microsoft/VibeVoice-ASR") is False
    assert module.is_vibevoice_asr_quantized_model_name("scerz/VibeVoice-ASR-4bit") is True
    assert (
        module.is_vibevoice_asr_quantized_model_name("someone/VibeVoice-ASR-nf4") is False
    )  # unknown suffix; no quant extras


def test_whisper_model_family_detection_helpers() -> None:
    module = _load_bootstrap_module()

    assert module.is_whisper_model_name("Systran/faster-whisper-large-v3") is True
    assert module.is_whisper_model_name("nvidia/parakeet-tdt-0.6b-v3") is False
    assert module.is_whisper_model_name("microsoft/VibeVoice-ASR") is False
    assert module.is_whisper_model_name("__none__") is False
    assert module.is_whisper_model_name("") is False


def test_check_whisper_import_returns_ready_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_bootstrap_module()

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        return subprocess.CompletedProcess(
            args=["python", "-c", "probe"],
            returncode=0,
            stdout='{"available": true, "reason": "ready"}\n',
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    status = module.check_whisper_import(Path("/tmp/fake-python"), timeout_seconds=30)
    assert status == {"available": True, "reason": "ready"}


def test_main_persists_vibevoice_import_failure_details_in_bootstrap_status(
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

    def fake_ensure_runtime_dependencies(**_: object):  # type: ignore[no-untyped-def]
        diagnostics = {
            "selection_reason": "hash_match_skip",
            "escalated_to_rebuild": False,
            "integrity": {"status": "pass"},
        }
        return runtime_dir / ".venv", "skip", {}, diagnostics

    captured_status: dict[str, object] = {}

    def fake_write_status_file(path: Path, payload: dict[str, object]) -> None:
        captured_status["path"] = path
        captured_status["payload"] = payload

    monkeypatch.setattr(module, "ensure_runtime_dependencies", fake_ensure_runtime_dependencies)
    monkeypatch.setattr(
        module,
        "load_config_models",
        lambda: (
            "microsoft/VibeVoice-ASR",
            "microsoft/VibeVoice-ASR",
            module.DEFAULT_DIARIZATION_MODEL,
        ),
    )
    monkeypatch.setattr(
        module,
        "compute_diarization_preload_cache_key",
        lambda **_: "vv-test-diar-key",
    )
    monkeypatch.setattr(
        module,
        "check_diarization_access",
        lambda **_: {"available": True, "reason": "ready"},
    )
    monkeypatch.setattr(
        module,
        "check_nemo_asr_import",
        lambda **_: {"available": False, "reason": "import_failed"},
    )
    monkeypatch.setattr(module, "run_command", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        module,
        "check_vibevoice_asr_import",
        lambda **_: {
            "available": False,
            "reason": "import_failed",
            "error": "legacy missing | modular missing",
            "attempted_imports": [
                "legacy-path",
                "modular-path",
            ],
        },
    )
    monkeypatch.setattr(module, "write_status_file", fake_write_status_file)

    monkeypatch.setenv("BOOTSTRAP_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("BOOTSTRAP_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("BOOTSTRAP_STATUS_FILE", str(status_file))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "models"))
    monkeypatch.setenv("INSTALL_VIBEVOICE_ASR", "true")

    rc = module.main()

    assert rc == 0
    payload = captured_status.get("payload")
    assert isinstance(payload, dict)
    features = payload["features"]  # type: ignore[index]
    vibevoice = features["vibevoice_asr"]  # type: ignore[index]
    assert vibevoice["available"] is False  # type: ignore[index]
    assert vibevoice["reason"] == "import_failed"  # type: ignore[index]
    assert vibevoice["error"] == "legacy missing | modular missing"  # type: ignore[index]


def test_main_installs_vibevoice_quant_runtime_deps_for_4bit_model(
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

    def fake_ensure_runtime_dependencies(**_: object):  # type: ignore[no-untyped-def]
        diagnostics = {
            "selection_reason": "hash_match_skip",
            "escalated_to_rebuild": False,
            "integrity": {"status": "pass"},
        }
        return runtime_dir / ".venv", "skip", {}, diagnostics

    captured_status: dict[str, object] = {}

    def fake_write_status_file(path: Path, payload: dict[str, object]) -> None:
        captured_status["path"] = path
        captured_status["payload"] = payload

    install_calls: list[list[str]] = []

    def fake_run_command(cmd: list[str], **kwargs: object) -> None:
        del kwargs
        install_calls.append(cmd)

    vibevoice_probe_results = iter(
        [
            {"available": False, "reason": "not_installed"},
            {"available": True, "reason": "ready", "variant": "modular"},
        ]
    )

    monkeypatch.setattr(module, "ensure_runtime_dependencies", fake_ensure_runtime_dependencies)
    monkeypatch.setattr(
        module,
        "load_config_models",
        lambda: (
            "scerz/VibeVoice-ASR-4bit",
            "scerz/VibeVoice-ASR-4bit",
            module.DEFAULT_DIARIZATION_MODEL,
        ),
    )
    monkeypatch.setattr(
        module,
        "compute_diarization_preload_cache_key",
        lambda **_: "vv-4bit-diar-key",
    )
    monkeypatch.setattr(
        module,
        "check_diarization_access",
        lambda **_: {"available": False, "reason": "token_missing"},
    )
    monkeypatch.setattr(
        module,
        "check_nemo_asr_import",
        lambda **_: {"available": False, "reason": "not_requested"},
    )
    monkeypatch.setattr(module, "run_command", fake_run_command)
    monkeypatch.setattr(
        module,
        "check_vibevoice_asr_import",
        lambda **_: next(vibevoice_probe_results),
    )
    monkeypatch.setattr(module, "write_status_file", fake_write_status_file)

    monkeypatch.setenv("BOOTSTRAP_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("BOOTSTRAP_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("BOOTSTRAP_STATUS_FILE", str(status_file))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "models"))
    monkeypatch.setenv("INSTALL_VIBEVOICE_ASR", "true")

    rc = module.main()

    assert rc == 0
    assert len(install_calls) == 1
    cmd = install_calls[0]
    assert cmd[:5] == [
        "uv",
        "pip",
        "install",
        "--python",
        str(runtime_dir / ".venv/bin/python"),
    ]
    assert (
        "git+https://github.com/microsoft/VibeVoice.git@1807b858d4f7dffdd286249a01616c243e488c9e"
        in cmd
    )
    assert "accelerate>=0.26.0" in cmd
    assert "bitsandbytes>=0.43.1" in cmd

    payload = captured_status.get("payload")
    assert isinstance(payload, dict)
    vibevoice = payload["features"]["vibevoice_asr"]  # type: ignore[index]
    assert vibevoice["available"] is True  # type: ignore[index]
    assert vibevoice["reason"] == "ready"  # type: ignore[index]
    assert vibevoice["variant"] == "modular"  # type: ignore[index]


def test_main_installs_missing_quant_runtime_deps_when_vibevoice_core_already_present(
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

    def fake_ensure_runtime_dependencies(**_: object):  # type: ignore[no-untyped-def]
        diagnostics = {
            "selection_reason": "hash_match_skip",
            "escalated_to_rebuild": False,
            "integrity": {"status": "pass"},
        }
        return runtime_dir / ".venv", "skip", {}, diagnostics

    captured_status: dict[str, object] = {}

    def fake_write_status_file(path: Path, payload: dict[str, object]) -> None:
        captured_status["path"] = path
        captured_status["payload"] = payload

    install_calls: list[list[str]] = []

    def fake_run_command(cmd: list[str], **kwargs: object) -> None:
        del kwargs
        install_calls.append(cmd)

    quant_runtime_probe_results = iter(
        [
            {
                "available": False,
                "reason": "missing_packages",
                "missing_packages": ["accelerate", "bitsandbytes"],
            },
            {
                "available": True,
                "reason": "ready",
                "versions": {"accelerate": "1.0.0", "bitsandbytes": "0.45.0"},
            },
        ]
    )

    monkeypatch.setattr(module, "ensure_runtime_dependencies", fake_ensure_runtime_dependencies)
    monkeypatch.setattr(
        module,
        "load_config_models",
        lambda: (
            "scerz/VibeVoice-ASR-4bit",
            "scerz/VibeVoice-ASR-4bit",
            module.DEFAULT_DIARIZATION_MODEL,
        ),
    )
    monkeypatch.setattr(
        module,
        "compute_diarization_preload_cache_key",
        lambda **_: "vv-core-present-diar-key",
    )
    monkeypatch.setattr(
        module,
        "check_diarization_access",
        lambda **_: {"available": False, "reason": "token_missing"},
    )
    monkeypatch.setattr(
        module,
        "check_nemo_asr_import",
        lambda **_: {"available": False, "reason": "not_requested"},
    )
    monkeypatch.setattr(
        module,
        "check_vibevoice_asr_import",
        lambda **_: {"available": True, "reason": "ready", "variant": "modular"},
    )
    monkeypatch.setattr(
        module,
        "check_vibevoice_asr_quant_runtime",
        lambda **_: next(quant_runtime_probe_results),
    )
    monkeypatch.setattr(module, "run_command", fake_run_command)
    monkeypatch.setattr(module, "write_status_file", fake_write_status_file)

    monkeypatch.setenv("BOOTSTRAP_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("BOOTSTRAP_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("BOOTSTRAP_STATUS_FILE", str(status_file))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "models"))
    monkeypatch.setenv("INSTALL_VIBEVOICE_ASR", "true")

    rc = module.main()

    assert rc == 0
    assert len(install_calls) == 1
    cmd = install_calls[0]
    assert cmd[:5] == [
        "uv",
        "pip",
        "install",
        "--python",
        str(runtime_dir / ".venv/bin/python"),
    ]
    assert "accelerate>=0.26.0" in cmd
    assert "bitsandbytes>=0.43.1" in cmd
    assert "git+https://github.com/microsoft/VibeVoice.git" not in cmd

    payload = captured_status.get("payload")
    assert isinstance(payload, dict)
    vibevoice = payload["features"]["vibevoice_asr"]  # type: ignore[index]
    assert vibevoice["available"] is True  # type: ignore[index]
    assert vibevoice["reason"] == "ready"  # type: ignore[index]
    assert vibevoice["variant"] == "modular"  # type: ignore[index]


def test_main_reports_existing_optional_dependency_installs_without_install_flags(
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

    def fake_ensure_runtime_dependencies(**_: object):  # type: ignore[no-untyped-def]
        diagnostics = {
            "selection_reason": "hash_match_skip",
            "escalated_to_rebuild": False,
            "integrity": {"status": "pass"},
        }
        return runtime_dir / ".venv", "skip", {}, diagnostics

    captured_status: dict[str, object] = {}

    def fake_write_status_file(path: Path, payload: dict[str, object]) -> None:
        captured_status["path"] = path
        captured_status["payload"] = payload

    install_calls: list[tuple[object, ...]] = []

    def fake_run_command(*args: object, **kwargs: object) -> None:
        del kwargs
        install_calls.append(args)

    monkeypatch.setattr(module, "ensure_runtime_dependencies", fake_ensure_runtime_dependencies)
    monkeypatch.setattr(
        module,
        "load_config_models",
        lambda: (
            "Systran/faster-whisper-large-v3",
            "Systran/faster-whisper-large-v3",
            module.DEFAULT_DIARIZATION_MODEL,
        ),
    )
    monkeypatch.setattr(
        module,
        "compute_diarization_preload_cache_key",
        lambda **_: "existing-optional-feature-diar-key",
    )
    monkeypatch.setattr(
        module,
        "check_diarization_access",
        lambda **_: {"available": True, "reason": "ready"},
    )
    monkeypatch.setattr(
        module,
        "check_nemo_asr_import",
        lambda **_: {"available": True, "reason": "ready"},
    )
    monkeypatch.setattr(
        module,
        "check_whisper_import",
        lambda **_: {"available": True, "reason": "ready"},
    )
    monkeypatch.setattr(
        module,
        "check_vibevoice_asr_import",
        lambda **_: {"available": True, "reason": "ready", "variant": "legacy"},
    )
    monkeypatch.setattr(module, "run_command", fake_run_command)
    monkeypatch.setattr(module, "write_status_file", fake_write_status_file)

    monkeypatch.setenv("BOOTSTRAP_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("BOOTSTRAP_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("BOOTSTRAP_STATUS_FILE", str(status_file))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "models"))
    monkeypatch.setenv("INSTALL_NEMO", "false")
    monkeypatch.setenv("INSTALL_VIBEVOICE_ASR", "false")

    rc = module.main()

    assert rc == 0
    assert install_calls == []
    payload = captured_status.get("payload")
    assert isinstance(payload, dict)
    features = payload["features"]  # type: ignore[index]
    whisper = features["whisper"]  # type: ignore[index]
    nemo = features["nemo"]  # type: ignore[index]
    vibevoice = features["vibevoice_asr"]  # type: ignore[index]
    assert whisper["available"] is True  # type: ignore[index]
    assert whisper["reason"] == "ready"  # type: ignore[index]
    # NeMo and VibeVoice are not selected by the configured whisper models,
    # so their feature checks are skipped entirely (Change 1: conditional backend checks).
    assert nemo["available"] is False  # type: ignore[index]
    assert nemo["reason"] == "not_selected"  # type: ignore[index]
    assert vibevoice["available"] is False  # type: ignore[index]
    assert vibevoice["reason"] == "not_selected"  # type: ignore[index]


def test_lock_only_change_uses_delta_sync(
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
            "fingerprint": "old-fingerprint",
            "python_abi": "abi",
            "arch": "arch",
            "structural_fingerprint": "struct-fp",
            "lock_fingerprint": "old-lock-fp",
        },
    )
    _patch_fingerprint_context(module, monkeypatch)

    sync_calls: list[str] = []
    rmtree_calls: list[Path] = []

    def fake_sync(**_: object) -> None:
        sync_calls.append("sync")

    def fake_rmtree(path: Path, ignore_errors: bool = False) -> None:
        rmtree_calls.append(path)

    monkeypatch.setattr(module, "run_dependency_sync", fake_sync)
    monkeypatch.setattr(module.shutil, "rmtree", fake_rmtree)

    _, sync_mode, _, diagnostics = module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        log_changes=False,
    )

    assert sync_mode == "delta-sync"
    assert diagnostics["selection_reason"] == "lock_changed"
    assert len(sync_calls) == 1
    assert len(rmtree_calls) == 0


def test_delta_sync_fallback_to_rebuild(
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
            "fingerprint": "old-fingerprint",
            "python_abi": "abi",
            "arch": "arch",
            "structural_fingerprint": "struct-fp",
            "lock_fingerprint": "old-lock-fp",
        },
    )
    _patch_fingerprint_context(module, monkeypatch)

    sync_calls: list[str] = []
    rmtree_calls: list[Path] = []
    original_rmtree = module.shutil.rmtree

    def fake_rmtree(path: Path, ignore_errors: bool = False) -> None:
        rmtree_calls.append(path)
        if Path(path) == runtime_dir / ".venv" and (runtime_dir / ".venv").exists():
            original_rmtree(path, ignore_errors=ignore_errors)

    call_count = 0

    def fake_sync(**_: object) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("delta-sync failed")
        sync_calls.append("sync")
        _touch_runtime_python(runtime_dir)

    monkeypatch.setattr(module, "run_dependency_sync", fake_sync)
    monkeypatch.setattr(module.shutil, "rmtree", fake_rmtree)

    _, sync_mode, _, diagnostics = module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        log_changes=False,
    )

    assert sync_mode == "rebuild-sync"
    assert diagnostics["escalated_to_rebuild"] is True
    assert "delta-sync failed" in diagnostics["delta_sync_error"]
    assert call_count == 2
    assert rmtree_calls[0] == runtime_dir / ".venv"


def test_force_rebuild_env_var(
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
            "fingerprint": "fp",
            "python_abi": "abi",
            "arch": "arch",
            "structural_fingerprint": "struct-fp",
            "lock_fingerprint": "lock-fp",
        },
    )
    _patch_fingerprint_context(module, monkeypatch)
    monkeypatch.setenv("BOOTSTRAP_FORCE_REBUILD", "true")

    sync_calls: list[str] = []

    def fake_sync(**_: object) -> None:
        sync_calls.append("sync")
        _touch_runtime_python(runtime_dir)

    monkeypatch.setattr(module, "run_dependency_sync", fake_sync)

    _, sync_mode, _, diagnostics = module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        log_changes=False,
    )

    assert sync_mode == "rebuild-sync"
    assert diagnostics["selection_reason"] == "force_rebuild"
    assert len(sync_calls) == 1


def test_old_marker_without_structural_fp_triggers_rebuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_bootstrap_module()
    runtime_dir = tmp_path / "runtime"
    cache_dir = tmp_path / "runtime-cache"
    runtime_dir.mkdir()
    cache_dir.mkdir()
    _touch_runtime_python(runtime_dir)
    # Old schema v2 marker without structural_fingerprint field
    _write_marker(
        runtime_dir,
        {
            "schema_version": module.BOOTSTRAP_SCHEMA_VERSION,
            "fingerprint": "old-fingerprint",
            "python_abi": "abi",
            "arch": "arch",
        },
    )
    _patch_fingerprint_context(module, monkeypatch)

    sync_calls: list[str] = []

    def fake_sync(**_: object) -> None:
        sync_calls.append("sync")
        _touch_runtime_python(runtime_dir)

    monkeypatch.setattr(module, "run_dependency_sync", fake_sync)

    _, sync_mode, _, diagnostics = module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        log_changes=False,
    )

    assert sync_mode == "rebuild-sync"
    assert diagnostics["selection_reason"] == "structural_mismatch"
    assert len(sync_calls) == 1


def test_marker_written_with_sub_fingerprints(
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
            "fingerprint": "old-fingerprint",
            "python_abi": "abi",
            "arch": "arch",
            "structural_fingerprint": "struct-fp",
            "lock_fingerprint": "old-lock-fp",
        },
    )
    _patch_fingerprint_context(module, monkeypatch)

    def fake_sync(**_: object) -> None:
        pass  # delta-sync succeeds

    monkeypatch.setattr(module, "run_dependency_sync", fake_sync)

    module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        log_changes=False,
    )

    marker_file = runtime_dir / ".runtime-bootstrap-marker.json"
    persisted = json.loads(marker_file.read_text(encoding="utf-8"))
    assert persisted["structural_fingerprint"] == "struct-fp"
    assert persisted["lock_fingerprint"] == "lock-fp"
    assert persisted["sync_mode"] == "delta-sync"
    assert persisted["escalated_to_rebuild"] is False


# ─── PyTorch variant branching (Issue #83 — legacy-GPU image) ─────────────────


def _capture_run_dependency_sync_cmd(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    *,
    pytorch_variant: str,
    extras: tuple[str, ...] = (),
) -> list[str]:
    """Invoke run_dependency_sync with run_command monkeypatched to capture argv."""
    captured: dict[str, list[str]] = {}

    def fake_run_command(cmd: list[str], **_: object) -> None:
        captured["cmd"] = list(cmd)

    monkeypatch.setattr(module, "run_command", fake_run_command)
    monkeypatch.setattr(module, "build_uv_sync_env", lambda **_: {})

    module.run_dependency_sync(
        venv_dir=Path("/tmp/venv"),
        cache_dir=Path("/tmp/cache"),
        timeout_seconds=300,
        extras=extras,
        pytorch_variant=pytorch_variant,
    )
    return captured["cmd"]


def test_run_dependency_sync_default_cu129_uses_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default cu129 path stays --frozen and never injects an --index override."""
    module = _load_bootstrap_module()
    cmd = _capture_run_dependency_sync_cmd(monkeypatch, module, pytorch_variant="cu129")

    assert "--frozen" in cmd, "cu129 path must keep --frozen for lock-pinned wheels"
    assert "--index-strategy" not in cmd
    assert not any(
        arg.startswith("pytorch-cu129=") and arg != cmd[cmd.index("--index") + 1]
        if "--index" in cmd
        else False
        for arg in cmd
    ), "cu129 path must not carry a URL-override --index"
    assert "--index" not in cmd, "cu129 path relies on lock-pinned index; no CLI override"


def test_run_dependency_sync_legacy_cu126_drops_frozen_and_overrides_cu129_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy cu126 path drops --frozen and swaps the pytorch-cu129 index URL.

    The override MUST reuse the `pytorch-cu129` name because `[tool.uv.sources]`
    in pyproject.toml pins `torch`/`torchaudio` to that named index. Declaring a
    new name (e.g. `pytorch-cu126`) would leave the source pin untouched and uv
    would still install cu129 wheels.
    """
    module = _load_bootstrap_module()
    cmd = _capture_run_dependency_sync_cmd(monkeypatch, module, pytorch_variant="cu126")

    assert "--frozen" not in cmd, "cu126 path must drop --frozen (lock pins cu129 hashes)"
    assert "--index" in cmd, "cu126 path must supply the --index override"
    idx = cmd.index("--index")
    assert cmd[idx + 1] == "pytorch-cu129=https://download.pytorch.org/whl/cu126", (
        "cu126 path must reuse the `pytorch-cu129` name with the cu126 URL — "
        "adding a new index name would not override the `[tool.uv.sources]` pin"
    )
    # Issue #115: the CLI form `--index name=url` redefines the index but does
    # not preserve the `explicit = true` flag from pyproject, so uv would apply
    # the default first-index policy to non-torch packages on cu126 and refuse
    # to fall back to PyPI for newer transitive deps (e.g. tqdm>=4.67.1 needed
    # by pyannote-pipeline 4.0.0). `unsafe-best-match` lets uv consider every
    # index for non-explicit packages while keeping torch/torchaudio pinned to
    # the cu126-swapped index via [tool.uv.sources].
    assert "--index-strategy" in cmd, (
        "cu126 path must pass --index-strategy unsafe-best-match (Issue #115)"
    )
    strategy_idx = cmd.index("--index-strategy")
    assert cmd[strategy_idx + 1] == "unsafe-best-match", (
        "cu126 path must use unsafe-best-match so uv considers PyPI for "
        "non-torch packages whose pinned versions don't exist on cu126"
    )


def test_run_dependency_sync_legacy_propagates_extras(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extras are appended after the cu126 index args, not swallowed by the branch."""
    module = _load_bootstrap_module()
    cmd = _capture_run_dependency_sync_cmd(
        monkeypatch,
        module,
        pytorch_variant="cu126",
        extras=("whisper", "nemo"),
    )

    extras_pairs = [(cmd[i], cmd[i + 1]) for i in range(len(cmd) - 1) if cmd[i] == "--extra"]
    assert ("--extra", "whisper") in extras_pairs
    assert ("--extra", "nemo") in extras_pairs
    # Extras land after the --index override so they don't get captured as its value.
    index_idx = cmd.index("--index")
    first_extra_idx = cmd.index("--extra")
    assert first_extra_idx > index_idx


def test_marker_persists_pytorch_variant_for_legacy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The marker file records the active variant so a flip rebuilds the venv."""
    module = _load_bootstrap_module()
    runtime_dir = tmp_path / "runtime"
    cache_dir = tmp_path / "runtime-cache"
    runtime_dir.mkdir()
    cache_dir.mkdir()
    _patch_fingerprint_context(module, monkeypatch)

    def fake_sync(**_: object) -> None:
        _touch_runtime_python(runtime_dir)

    monkeypatch.setattr(module, "run_dependency_sync", fake_sync)

    module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        log_changes=False,
        pytorch_variant="cu126",
    )

    marker = json.loads(
        (runtime_dir / ".runtime-bootstrap-marker.json").read_text(encoding="utf-8")
    )
    assert marker["pytorch_variant"] == "cu126"


# ─── Blind Hunter #10 (Issue #83) — grandfathered pre-variant markers ─────────


def _patch_fingerprint_context_with_variant_flag(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fingerprint fakes that branch on the ``include_variant`` kwarg."""

    def fake_dep_fp(*, include_variant: bool = True, **_: object) -> str:
        return "fp" if include_variant else "legacy-fp"

    def fake_struct_fp(*, include_variant: bool = True, **_: object) -> str:
        return "struct-fp" if include_variant else "legacy-struct-fp"

    monkeypatch.setattr(module, "compute_dependency_fingerprint", fake_dep_fp)
    monkeypatch.setattr(module, "compute_structural_fingerprint", fake_struct_fp)
    monkeypatch.setattr(module, "compute_lock_fingerprint", lambda: "lock-fp")
    monkeypatch.setattr(module, "python_abi_tag", lambda: "abi")
    monkeypatch.setattr(module.platform, "machine", lambda: "arch")


def test_grandfathered_pre_variant_marker_skips_for_cu129(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-GH-83 cu129 markers (no pytorch_variant field) take the skip path."""
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
            # Pre-GH-83 fingerprint — computed without pytorch_variant.
            "fingerprint": "legacy-fp",
            "python_abi": "abi",
            "arch": "arch",
            # No "pytorch_variant" key — this is the grandfather signal.
        },
    )
    _patch_fingerprint_context_with_variant_flag(module, monkeypatch)
    monkeypatch.setattr(
        module,
        "run_dependency_sync",
        lambda **_: (_ for _ in ()).throw(AssertionError("sync should not run")),
    )

    _, sync_mode, _, diagnostics = module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        log_changes=False,
        pytorch_variant="cu129",
    )

    assert sync_mode == "skip"
    assert diagnostics["selection_reason"] == "hash_match_skip"
    assert diagnostics.get("grandfathered_pre_variant_marker") is True


def test_grandfathered_marker_is_upgraded_in_place(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After grandfather-match, the marker is rewritten with the new form so
    the next boot hits the fast hash-match-skip path without the compat branch."""
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
            "fingerprint": "legacy-fp",
            "python_abi": "abi",
            "arch": "arch",
        },
    )
    _patch_fingerprint_context_with_variant_flag(module, monkeypatch)
    monkeypatch.setattr(module, "run_dependency_sync", lambda **_: None)

    module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        log_changes=False,
        pytorch_variant="cu129",
    )

    persisted = json.loads(
        (runtime_dir / ".runtime-bootstrap-marker.json").read_text(encoding="utf-8")
    )
    assert persisted["fingerprint"] == "fp"  # variant-aware form
    assert persisted["pytorch_variant"] == "cu129"
    assert persisted["structural_fingerprint"] == "struct-fp"


def test_grandfather_does_not_apply_to_cu126_flip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cu126 boot against a pre-variant marker must rebuild (wheels differ)."""
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
            "fingerprint": "legacy-fp",
            "python_abi": "abi",
            "arch": "arch",
        },
    )
    _patch_fingerprint_context_with_variant_flag(module, monkeypatch)

    sync_calls: list[str] = []

    def fake_sync(**_: object) -> None:
        sync_calls.append("sync")
        _touch_runtime_python(runtime_dir)

    monkeypatch.setattr(module, "run_dependency_sync", fake_sync)

    _, sync_mode, _, diagnostics = module.ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=300,
        log_changes=False,
        pytorch_variant="cu126",
    )

    assert sync_mode == "rebuild-sync"
    assert diagnostics.get("grandfathered_pre_variant_marker") is not True
    assert len(sync_calls) == 1


# ─── EC-4 (Issue #83) — cuDNN discovery and import classification ─────────────


def test_discover_cudnn_lib_path_returns_directory_with_libcudnn(
    tmp_path: Path,
) -> None:
    module = _load_bootstrap_module()
    cudnn_dir = tmp_path / "lib" / "python3.14" / "site-packages" / "nvidia" / "cudnn" / "lib"
    cudnn_dir.mkdir(parents=True)
    (cudnn_dir / "libcudnn.so.9").write_bytes(b"elf")

    found = module.discover_cudnn_lib_path(tmp_path)

    assert found == str(cudnn_dir)


def test_discover_cudnn_lib_path_returns_empty_when_no_libs(
    tmp_path: Path,
) -> None:
    module = _load_bootstrap_module()
    cudnn_dir = tmp_path / "lib" / "python3.13" / "site-packages" / "nvidia" / "cudnn" / "lib"
    cudnn_dir.mkdir(parents=True)

    assert module.discover_cudnn_lib_path(tmp_path) == ""


def test_check_whisper_import_classifies_cudnn_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_bootstrap_module()

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        return subprocess.CompletedProcess(
            args=["python", "-c", "probe"],
            returncode=0,
            stdout=(
                '{"available": false, "reason": "cudnn_missing", '
                '"error": "ctranslate2: OSError: libcudnn_ops_infer.so.8: cannot open shared object file"}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    status = module.check_whisper_import(Path("/tmp/fake-python"), timeout_seconds=30)

    assert status["available"] is False
    assert status["reason"] == "cudnn_missing"


def test_probe_whisper_with_cudnn_fallback_retries_with_discovered_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First probe fails with cudnn_missing; second probe sees the glob path and succeeds."""
    module = _load_bootstrap_module()
    venv_dir = tmp_path / ".venv"
    cudnn_dir = venv_dir / "lib" / "python3.13" / "site-packages" / "nvidia" / "cudnn" / "lib"
    cudnn_dir.mkdir(parents=True)
    (cudnn_dir / "libcudnn.so.9").write_bytes(b"elf")

    call_count = 0
    observed_envs: list[dict[str, str] | None] = []

    def fake_check(
        venv_python: Path,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
    ) -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        observed_envs.append(env)
        if call_count == 1:
            return {
                "available": False,
                "reason": "cudnn_missing",
                "error": "libcudnn.so.9: cannot open shared object file",
            }
        return {"available": True, "reason": "ready"}

    monkeypatch.setattr(module, "check_whisper_import", fake_check)

    status, discovered = module.probe_whisper_with_cudnn_fallback(
        venv_python=venv_dir / "bin/python",
        venv_dir=venv_dir,
        timeout_seconds=30,
    )

    assert status["available"] is True
    assert status["cudnn_fallback_applied"] is True
    assert status["cudnn_lib_dir"] == str(cudnn_dir)
    assert discovered == str(cudnn_dir)
    assert call_count == 2
    # Second probe must be invoked with a patched LD_LIBRARY_PATH.
    second_env = observed_envs[1]
    assert second_env is not None
    assert str(cudnn_dir) in second_env.get("LD_LIBRARY_PATH", "")


def test_probe_whisper_with_cudnn_fallback_preserves_error_when_retry_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry-still-fails keeps the original reason but records the discovered dir."""
    module = _load_bootstrap_module()
    venv_dir = tmp_path / ".venv"
    cudnn_dir = venv_dir / "lib" / "python3.13" / "site-packages" / "nvidia" / "cudnn" / "lib"
    cudnn_dir.mkdir(parents=True)
    (cudnn_dir / "libcudnn.so.9").write_bytes(b"elf")

    def fake_check(**_: object) -> dict[str, object]:
        return {
            "available": False,
            "reason": "cudnn_missing",
            "error": "libcudnn.so.9 load failure",
        }

    monkeypatch.setattr(module, "check_whisper_import", fake_check)

    status, discovered = module.probe_whisper_with_cudnn_fallback(
        venv_python=venv_dir / "bin/python",
        venv_dir=venv_dir,
        timeout_seconds=30,
    )

    assert status["available"] is False
    assert status["reason"] == "cudnn_missing"
    assert status["cudnn_fallback_applied"] is True
    assert status["cudnn_lib_dir"] == str(cudnn_dir)
    assert discovered == str(cudnn_dir)


# ─── EC-5/EC-14 (Issue #83) — baked PYTORCH_VARIANT cross-check ───────────────


def test_main_trusts_baked_variant_over_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When /app/.pytorch_variant disagrees with the runtime env, the baked value wins."""
    module = _load_bootstrap_module()
    runtime_dir = tmp_path / "runtime"
    cache_dir = tmp_path / "runtime-cache"
    status_file = runtime_dir / "bootstrap-status.json"
    runtime_dir.mkdir()
    cache_dir.mkdir()
    _touch_runtime_python(runtime_dir)

    baked_file = tmp_path / ".pytorch_variant"
    baked_file.write_text("cu126\n", encoding="utf-8")
    monkeypatch.setattr(module, "APP_ROOT", tmp_path)

    resolved_variant: dict[str, str] = {}

    def fake_ensure_runtime_dependencies(
        **kwargs: object,
    ):  # type: ignore[no-untyped-def]
        resolved_variant["variant"] = str(kwargs.get("pytorch_variant"))
        diagnostics = {
            "selection_reason": "hash_match_skip",
            "escalated_to_rebuild": False,
        }
        return runtime_dir / ".venv", "skip", {}, diagnostics

    monkeypatch.setattr(module, "ensure_runtime_dependencies", fake_ensure_runtime_dependencies)
    monkeypatch.setattr(
        module,
        "load_config_models",
        lambda: (
            "Systran/faster-whisper-large-v3",
            "Systran/faster-whisper-large-v3",
            module.DEFAULT_DIARIZATION_MODEL,
        ),
    )
    monkeypatch.setattr(
        module,
        "compute_diarization_preload_cache_key",
        lambda **_: "k",
    )
    monkeypatch.setattr(
        module,
        "check_diarization_access",
        lambda **_: {"available": False, "reason": "token_missing"},
    )
    monkeypatch.setattr(
        module,
        "probe_whisper_with_cudnn_fallback",
        lambda **_: ({"available": True, "reason": "ready"}, ""),
    )
    monkeypatch.setattr(
        module,
        "check_nemo_asr_import",
        lambda **_: {"available": False, "reason": "not_requested"},
    )
    monkeypatch.setattr(module, "write_status_file", lambda *_args, **_kwargs: None)

    monkeypatch.setenv("BOOTSTRAP_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("BOOTSTRAP_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("BOOTSTRAP_STATUS_FILE", str(status_file))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "models"))
    # Runtime env says cu129 but the image was built with cu126.
    monkeypatch.setenv("PYTORCH_VARIANT", "cu129")

    rc = module.main()

    assert rc == 0
    assert resolved_variant["variant"] == "cu126"
