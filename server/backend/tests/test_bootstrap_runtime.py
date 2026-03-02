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
    assert diagnostics["selection_reason"] == "hash_mismatch"
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
    assert diagnostics["selection_reason"] == "hash_mismatch"
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
