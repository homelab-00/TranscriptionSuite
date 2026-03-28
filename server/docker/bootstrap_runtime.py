#!/usr/bin/env python3
"""Runtime bootstrap for the TranscriptionSuite Docker container.

This script is intentionally stdlib-only so it can run before Python
dependencies are installed in the runtime virtual environment.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APP_ROOT = Path("/app")
PROJECT_DIR = APP_ROOT / "server"
LOCK_FILE = PROJECT_DIR / "uv.lock"
DEFAULT_CONFIG_FILE = APP_ROOT / "config.yaml"
USER_CONFIG_FILE = Path("/user-config/config.yaml")

DEFAULT_MAIN_MODEL = "Systran/faster-whisper-large-v3"
DISABLED_MODEL_SENTINEL = "__none__"
DEFAULT_DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"

BOOTSTRAP_SCHEMA_VERSION = 2
_BOOTSTRAP_START = time.perf_counter()
_VIBEVOICE_ASR_IMPORT_CANDIDATES: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "legacy",
        "vibevoice.modeling_vibevoice_asr",
        "VibeVoiceASRForConditionalGeneration",
        "vibevoice.processor.vibevoice_asr_processing",
        "VibeVoiceASRProcessor",
    ),
    (
        "modular",
        "vibevoice.modular.modeling_vibevoice_asr",
        "VibeVoiceASRForConditionalGeneration",
        "vibevoice.processor.vibevoice_asr_processor",
        "VibeVoiceASRProcessor",
    ),
)
_VIBEVOICE_ASR_MODEL_PATTERN = re.compile(r"^[^/]+/vibevoice-asr(?:-[^/]+)?$", re.IGNORECASE)
_VIBEVOICE_ASR_4BIT_MODEL_PATTERN = re.compile(
    r"^[^/]+/vibevoice-asr(?:-[^/]+)?-4bit$", re.IGNORECASE
)
_VIBEVOICE_ASR_QUANT_RUNTIME_PACKAGE_SPECS: tuple[str, ...] = (
    "accelerate>=0.26.0",
    "bitsandbytes>=0.43.1",
)


def log(message: str) -> None:
    print(f"[bootstrap] {message}", flush=True)


def log_timing(message: str, start_time: float | None = None) -> None:
    if start_time is None:
        elapsed = time.perf_counter() - _BOOTSTRAP_START
    else:
        elapsed = time.perf_counter() - start_time
    log(f"[TIMING] {elapsed:.3f}s - {message}")


def parse_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def parse_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def is_vibevoice_asr_model_name(model_name: str | None) -> bool:
    """Return True when *model_name* selects a VibeVoice-ASR family variant."""
    name = normalize_selected_model_name(model_name)
    return bool(_VIBEVOICE_ASR_MODEL_PATTERN.match(name))


def is_vibevoice_asr_quantized_model_name(model_name: str | None) -> bool:
    """Return True for known quantized VibeVoice-ASR variants that need extra runtime deps."""
    name = normalize_selected_model_name(model_name)
    return bool(_VIBEVOICE_ASR_4BIT_MODEL_PATTERN.match(name))


def normalize_selected_model_name(model_name: str | None) -> str:
    """Return an empty string when model is unset/disabled, otherwise stripped name."""
    name = (model_name or "").strip()
    if not name or name == DISABLED_MODEL_SENTINEL:
        return ""
    return name


def is_nemo_model_name(model_name: str | None) -> bool:
    """Return True when *model_name* belongs to NeMo families."""
    name = normalize_selected_model_name(model_name).lower()
    if not name:
        return False
    return name.startswith("nvidia/parakeet") or name.startswith("nvidia/canary")


def is_whisper_model_name(model_name: str | None) -> bool:
    """Return True when *model_name* belongs to the faster-whisper family."""
    name = normalize_selected_model_name(model_name)
    if not name:
        return False
    return not is_nemo_model_name(name) and not is_vibevoice_asr_model_name(name)


_NVIDIA_PROC_VERSION = Path("/proc/driver/nvidia/version")


def detect_gpu_driver_version() -> str:
    """Return the host NVIDIA driver version visible inside the container.

    Reads ``/proc/driver/nvidia/version`` (exposed by the NVIDIA container
    runtime).  Returns an empty string when no GPU driver is detected so that
    CPU-only containers are unaffected.
    """
    try:
        text = _NVIDIA_PROC_VERSION.read_text(encoding="utf-8", errors="replace")
        # First line looks like:
        #   NVRM version: NVIDIA UNIX x86_64 Kernel Module  595.58.03  ...
        match = re.search(r"Kernel Module\s+([\d.]+)", text)
        if match:
            return match.group(1)
    except OSError:
        pass
    return ""


def python_abi_tag() -> str:
    soabi = sysconfig.get_config_var("SOABI")
    if soabi:
        return str(soabi)
    cache_tag = getattr(sys.implementation, "cache_tag", None)
    if cache_tag:
        return str(cache_tag)
    return f"py{sys.version_info.major}.{sys.version_info.minor}"


def update_hash_with_file(hasher: Any, label: str, path: Path) -> None:
    hasher.update(f"{label}:".encode())
    hasher.update(path.name.encode("utf-8"))
    if path.exists():
        hasher.update(path.read_bytes())
    else:
        hasher.update(b"<missing>")


def compute_dependency_fingerprint(
    python_abi: str,
    arch: str,
    extras: tuple[str, ...] = (),
    gpu_driver: str = "",
) -> str:
    hasher = hashlib.sha256()
    hasher.update(f"schema={BOOTSTRAP_SCHEMA_VERSION}".encode())
    hasher.update(f"abi={python_abi}".encode())
    hasher.update(f"arch={arch}".encode())
    hasher.update(f"extras={','.join(sorted(extras))}".encode())
    hasher.update(f"gpu_driver={gpu_driver}".encode())

    update_hash_with_file(hasher, "uv-lock", LOCK_FILE)

    return hasher.hexdigest()


def compute_structural_fingerprint(
    python_abi: str,
    arch: str,
    extras: tuple[str, ...] = (),
    gpu_driver: str = "",
) -> str:
    """Hash of factors that determine venv shape (ABI, arch, extras, GPU driver).

    A change here means the venv cannot be incrementally updated.
    The GPU driver version is structural because compiled CUDA extensions
    (e.g. PyTorch) are linked against a specific driver ABI.
    """
    hasher = hashlib.sha256()
    hasher.update(f"schema={BOOTSTRAP_SCHEMA_VERSION}".encode())
    hasher.update(f"abi={python_abi}".encode())
    hasher.update(f"arch={arch}".encode())
    hasher.update(f"extras={','.join(sorted(extras))}".encode())
    hasher.update(f"gpu_driver={gpu_driver}".encode())
    return hasher.hexdigest()


def compute_lock_fingerprint() -> str:
    """Hash of uv.lock content only — changes here are ideal for incremental sync."""
    hasher = hashlib.sha256()
    update_hash_with_file(hasher, "uv-lock", LOCK_FILE)
    return hasher.hexdigest()


def run_command(
    cmd: list[str],
    timeout_seconds: int,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        output = (result.stdout or "") + (result.stderr or "")
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(cmd)}\n{output}")
    return result


def load_marker(marker_file: Path) -> dict[str, Any]:
    if not marker_file.exists():
        return {}
    try:
        payload = json.loads(marker_file.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        log(f"Marker file is unreadable; ignoring ({marker_file}): {exc}")
    return {}


def load_status_file(status_file: Path) -> dict[str, Any]:
    if not status_file.exists():
        return {}
    try:
        payload = json.loads(status_file.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        log(f"Status file is unreadable; ignoring ({status_file}): {exc}")
    return {}


def collect_installed_packages(
    venv_python: Path,
    timeout_seconds: int,
) -> dict[str, str]:
    if not venv_python.exists():
        return {}

    inspector = r"""
import importlib.metadata as md
import json

packages = {}
for dist in md.distributions():
    name = (dist.metadata.get("Name") or dist.name or "").strip()
    if not name:
        continue
    packages[name.lower()] = dist.version

print(json.dumps(packages, sort_keys=True))
"""
    try:
        result = subprocess.run(
            [str(venv_python), "-c", inspector],
            text=True,
            capture_output=True,
            timeout=max(30, min(timeout_seconds, 300)),
            check=False,
        )
        if result.returncode != 0:
            return {}
        output = (result.stdout or "").strip().splitlines()
        if not output:
            return {}
        payload = json.loads(output[-1])
        if isinstance(payload, dict):
            return {str(k): str(v) for k, v in payload.items()}
    except Exception:
        return {}
    return {}


def build_uv_sync_env(venv_dir: Path, cache_dir: Path) -> dict[str, str]:
    """Build environment variables used by runtime uv commands."""
    env = os.environ.copy()
    env["UV_PROJECT_ENVIRONMENT"] = str(venv_dir)
    env["UV_CACHE_DIR"] = str(cache_dir)
    env["UV_PYTHON"] = "/usr/bin/python3.13"
    return env


def run_dependency_sync(
    venv_dir: Path,
    cache_dir: Path,
    timeout_seconds: int,
    extras: tuple[str, ...] = (),
) -> None:
    """Run dependency sync into the runtime virtual environment."""
    cmd = [
        "uv",
        "sync",
        "--frozen",
        "--no-dev",
        "--project",
        str(PROJECT_DIR),
    ]
    for extra in extras:
        cmd.extend(["--extra", extra])
    run_command(
        cmd,
        timeout_seconds=max(timeout_seconds, 10800),
        env=build_uv_sync_env(venv_dir=venv_dir, cache_dir=cache_dir),
    )


def summarize_package_delta(
    before: dict[str, str],
    after: dict[str, str],
) -> tuple[dict[str, int], dict[str, list[str]]]:
    before_keys = set(before)
    after_keys = set(after)

    added = sorted(after_keys - before_keys)
    removed = sorted(before_keys - after_keys)
    updated = sorted(key for key in (before_keys & after_keys) if before.get(key) != after.get(key))

    summary = {
        "added": len(added),
        "removed": len(removed),
        "updated": len(updated),
        "before_count": len(before),
        "after_count": len(after),
    }
    samples = {
        "added": added[:10],
        "removed": removed[:10],
        "updated": updated[:10],
    }
    return summary, samples


def write_marker(marker_file: Path, payload: dict[str, Any]) -> None:
    marker_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def ensure_runtime_dependencies(
    runtime_dir: Path,
    cache_dir: Path,
    timeout_seconds: int,
    log_changes: bool,
    extras: tuple[str, ...] = (),
) -> tuple[Path, str, dict[str, int], dict[str, Any]]:
    ensure_start = time.perf_counter()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    venv_dir = runtime_dir / ".venv"
    marker_file = runtime_dir / ".runtime-bootstrap-marker.json"
    lock_file = runtime_dir / ".runtime-bootstrap.lock"

    python_abi = python_abi_tag()
    arch = platform.machine()
    gpu_driver = detect_gpu_driver_version()
    if gpu_driver:
        log(f"Detected host GPU driver: {gpu_driver}")
    fingerprint = compute_dependency_fingerprint(
        python_abi=python_abi,
        arch=arch,
        extras=extras,
        gpu_driver=gpu_driver,
    )
    structural_fp = compute_structural_fingerprint(
        python_abi=python_abi,
        arch=arch,
        extras=extras,
        gpu_driver=gpu_driver,
    )
    lock_fp = compute_lock_fingerprint()
    force_rebuild = parse_bool_env("BOOTSTRAP_FORCE_REBUILD", False)

    package_delta: dict[str, int] = {
        "added": 0,
        "removed": 0,
        "updated": 0,
        "before_count": 0,
        "after_count": 0,
    }
    diagnostics: dict[str, Any] = {
        "selection_reason": "unknown",
    }

    with lock_file.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)

        marker_data = load_marker(marker_file)
        venv_python = venv_dir / "bin/python"
        venv_exists = venv_python.exists()

        marker_matches = bool(
            venv_exists
            and not force_rebuild
            and marker_data.get("schema_version") == BOOTSTRAP_SCHEMA_VERSION
            and marker_data.get("fingerprint") == fingerprint
            and marker_data.get("python_abi") == python_abi
            and marker_data.get("arch") == arch
        )

        if marker_matches:
            diagnostics["selection_reason"] = "hash_match_skip"
            log("Bootstrap path selected: mode=skip reason=hash_match_skip")
            log("Runtime dependencies already up-to-date (mode=skip)")
            log_timing("ensure_runtime_dependencies complete (mode=skip)", ensure_start)
            return venv_dir, "skip", package_delta, diagnostics

        structural_matches = bool(
            venv_exists
            and not force_rebuild
            and marker_data.get("schema_version") == BOOTSTRAP_SCHEMA_VERSION
            and marker_data.get("structural_fingerprint") == structural_fp
            and marker_data.get("python_abi") == python_abi
            and marker_data.get("arch") == arch
        )

        before_packages: dict[str, str] = {}

        if structural_matches:
            # Delta-sync: only uv.lock changed, venv shape is compatible
            diagnostics["selection_reason"] = "lock_changed"
            final_sync_mode = "delta-sync"
            log(f"Bootstrap path selected: mode={final_sync_mode} reason=lock_changed")

            if log_changes:
                before_packages = collect_installed_packages(venv_python, timeout_seconds)

            log(f"Installing Python runtime dependencies (mode={final_sync_mode})...")
            sync_start = time.perf_counter()
            try:
                run_dependency_sync(
                    venv_dir=venv_dir,
                    cache_dir=cache_dir,
                    timeout_seconds=timeout_seconds,
                    extras=extras,
                )
                log_timing(
                    f"dependency sync complete (mode={final_sync_mode})",
                    sync_start,
                )
            except Exception as delta_exc:
                log_timing(
                    f"dependency sync failed (mode={final_sync_mode})",
                    sync_start,
                )
                log("Delta-sync failed, falling back to rebuild-sync")
                diagnostics["escalated_to_rebuild"] = True
                diagnostics["delta_sync_error"] = str(delta_exc)[:240]
                final_sync_mode = "rebuild-sync"

                if venv_dir.exists():
                    shutil.rmtree(venv_dir, ignore_errors=True)

                log(f"Installing Python runtime dependencies (mode={final_sync_mode})...")
                sync_start = time.perf_counter()
                try:
                    run_dependency_sync(
                        venv_dir=venv_dir,
                        cache_dir=cache_dir,
                        timeout_seconds=timeout_seconds,
                        extras=extras,
                    )
                    log_timing(
                        f"dependency sync complete (mode={final_sync_mode})",
                        sync_start,
                    )
                except Exception as exc:
                    log_timing(
                        f"dependency sync failed (mode={final_sync_mode})",
                        sync_start,
                    )
                    failure_snippet = str(exc).strip()
                    if len(failure_snippet) > 240:
                        failure_snippet = f"{failure_snippet[:237]}..."
                    raise RuntimeError(
                        f"Dependency sync failed for mode={final_sync_mode}: {failure_snippet}"
                    ) from exc
        else:
            # Rebuild-sync: venv missing, structural mismatch, or force rebuild
            if force_rebuild:
                diagnostics["selection_reason"] = "force_rebuild"
            elif not venv_exists:
                diagnostics["selection_reason"] = "venv_missing"
            else:
                diagnostics["selection_reason"] = "structural_mismatch"

            final_sync_mode = "rebuild-sync"
            log(
                f"Bootstrap path selected: mode={final_sync_mode} reason={diagnostics['selection_reason']}"
            )

            if log_changes and venv_exists:
                before_packages = collect_installed_packages(venv_python, timeout_seconds)
            if venv_dir.exists():
                log(f"Rebuilding runtime virtual environment ({diagnostics['selection_reason']})")
                shutil.rmtree(venv_dir, ignore_errors=True)

            log(f"Installing Python runtime dependencies (mode={final_sync_mode})...")
            sync_start = time.perf_counter()
            try:
                run_dependency_sync(
                    venv_dir=venv_dir,
                    cache_dir=cache_dir,
                    timeout_seconds=timeout_seconds,
                    extras=extras,
                )
                log_timing(
                    f"dependency sync complete (mode={final_sync_mode})",
                    sync_start,
                )
            except Exception as exc:
                log_timing(
                    f"dependency sync failed (mode={final_sync_mode})",
                    sync_start,
                )
                failure_snippet = str(exc).strip()
                if len(failure_snippet) > 240:
                    failure_snippet = f"{failure_snippet[:237]}..."
                raise RuntimeError(
                    f"Dependency sync failed for mode={final_sync_mode}: {failure_snippet}"
                ) from exc

        venv_python = venv_dir / "bin/python"
        if not venv_python.exists():
            raise RuntimeError("Runtime Python not found after dependency sync")

        if log_changes:
            after_packages = collect_installed_packages(venv_python, timeout_seconds)
            package_delta, samples = summarize_package_delta(before_packages, after_packages)
            log(
                "Package delta: "
                f"added={package_delta['added']} "
                f"updated={package_delta['updated']} "
                f"removed={package_delta['removed']}"
            )
            if samples["added"]:
                log(f"Sample added packages: {', '.join(samples['added'])}")
            if samples["updated"]:
                log(f"Sample updated packages: {', '.join(samples['updated'])}")
            if samples["removed"]:
                log(f"Sample removed packages: {', '.join(samples['removed'])}")

        marker_write_start = time.perf_counter()
        write_marker(
            marker_file,
            {
                "schema_version": BOOTSTRAP_SCHEMA_VERSION,
                "fingerprint": fingerprint,
                "python_abi": python_abi,
                "arch": arch,
                "gpu_driver": gpu_driver,
                "structural_fingerprint": structural_fp,
                "lock_fingerprint": lock_fp,
                "sync_mode": final_sync_mode,
                "selection_reason": diagnostics["selection_reason"],
                "package_delta": package_delta,
                "escalated_to_rebuild": diagnostics.get("escalated_to_rebuild", False),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
        log_timing("runtime bootstrap marker write complete", marker_write_start)

        log("Runtime dependencies installed")

        # Optionally prune UV package cache to reclaim space from the runtime volume.
        # Keeping the cache speeds up future rebuild-syncs (warm wheel cache).
        # Set BOOTSTRAP_PRUNE_UV_CACHE=true to reclaim ~1-2GB if disk space is tight.
        if parse_bool_env("BOOTSTRAP_PRUNE_UV_CACHE", False):
            log("Pruning UV cache to reclaim space from runtime volume...")
            shutil.rmtree(cache_dir, ignore_errors=True)
        else:
            log(
                "Keeping UV cache for faster future syncs (set BOOTSTRAP_PRUNE_UV_CACHE=true to prune)"
            )

    log_timing(
        f"ensure_runtime_dependencies complete (mode={final_sync_mode})",
        ensure_start,
    )
    return venv_dir, final_sync_mode, package_delta, diagnostics


def extract_config_value(content: str, section: str, key: str, default: str) -> str:
    section_re = re.compile(
        rf"(?ms)^{re.escape(section)}:\s*(.*?)(?:^\S.*?:|\Z)",
    )
    section_match = section_re.search(content)
    if not section_match:
        return default

    section_block = section_match.group(1)
    key_re = re.compile(rf"(?m)^\s+{re.escape(key)}:\s*[\"']?([^\"'\n#]+)")
    key_match = key_re.search(section_block)
    if not key_match:
        return default
    return key_match.group(1).strip() or default


def load_config_models() -> tuple[str, str, str]:
    # Environment variables take precedence (set by dashboard via docker-compose)
    env_main = os.environ.get("MAIN_TRANSCRIBER_MODEL", "").strip()
    env_live = os.environ.get("LIVE_TRANSCRIBER_MODEL", "").strip()
    env_diar = os.environ.get("DIARIZATION_MODEL", "").strip()

    config_file = USER_CONFIG_FILE if USER_CONFIG_FILE.exists() else DEFAULT_CONFIG_FILE
    if not config_file.exists():
        default_main = env_main or DEFAULT_MAIN_MODEL
        return (
            default_main,
            env_live or default_main,
            env_diar or DEFAULT_DIARIZATION_MODEL,
        )

    content = config_file.read_text(encoding="utf-8", errors="replace")
    main_model = env_main or extract_config_value(
        content,
        section="main_transcriber",
        key="model",
        default=DEFAULT_MAIN_MODEL,
    )
    live_model = env_live or extract_config_value(
        content,
        section="live_transcriber",
        key="model",
        default=main_model,
    )
    diar_model = env_diar or extract_config_value(
        content,
        section="diarization",
        key="model",
        default=DEFAULT_DIARIZATION_MODEL,
    )
    return (main_model, live_model, diar_model)


def collect_hf_model_cache_state(
    hf_home: str,
    model_id: str,
) -> dict[str, Any]:
    model_cache_name = model_id.strip().replace("/", "--")
    hub_dir = Path(hf_home) / "hub"
    repo_dir = hub_dir / f"models--{model_cache_name}"
    refs_main = repo_dir / "refs" / "main"
    snapshots_dir = repo_dir / "snapshots"

    refs_main_value = ""
    try:
        if refs_main.exists():
            refs_main_value = refs_main.read_text(
                encoding="utf-8",
                errors="replace",
            ).strip()
    except Exception:
        refs_main_value = ""

    snapshot_names: list[str] = []
    try:
        if snapshots_dir.exists():
            for entry in snapshots_dir.iterdir():
                if not entry.is_dir():
                    continue
                snapshot_names.append(entry.name)
    except Exception:
        snapshot_names = []

    snapshot_names.sort()
    snapshot_name_hasher = hashlib.sha256()
    for name in snapshot_names:
        snapshot_name_hasher.update(name.encode("utf-8"))
        snapshot_name_hasher.update(b"\0")

    return {
        "hf_home": str(Path(hf_home)),
        "repo_cache_dir": str(repo_dir),
        "repo_exists": repo_dir.exists(),
        "refs_main": refs_main_value,
        "snapshots_dir_exists": snapshots_dir.exists(),
        "snapshots_count": len(snapshot_names),
        "snapshots_hash": snapshot_name_hasher.hexdigest() if snapshot_names else "",
    }


def compute_diarization_preload_cache_key(
    diarization_model: str,
    hf_token: str | None,
    hf_home: str,
) -> str:
    token_hash = ""
    if hf_token:
        token_hash = hashlib.sha256(hf_token.encode("utf-8")).hexdigest()

    payload = {
        "schema_version": 1,
        "model": diarization_model.strip(),
        "token_hash": token_hash,
        "cache_state": collect_hf_model_cache_state(hf_home=hf_home, model_id=diarization_model),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def should_reuse_cached_feature_status(
    previous_status_payload: dict[str, Any],
    sync_mode: str,
) -> bool:
    """Return True when all three feature import results can be reused from cache.

    This is safe when ``sync_mode == "skip"`` (deps unchanged) and the previous
    bootstrap-status.json already contains results for whisper, nemo, and
    vibevoice_asr features.
    """
    if sync_mode != "skip":
        return False
    features = previous_status_payload.get("features")
    if not isinstance(features, dict):
        return False
    for key in ("whisper", "nemo", "vibevoice_asr"):
        entry = features.get(key)
        if not isinstance(entry, dict):
            return False
        if "available" not in entry or "reason" not in entry:
            return False
    return True


def should_reuse_cached_diarization_status(
    previous_status_payload: dict[str, Any],
    preload_cache_key: str,
) -> bool:
    features = previous_status_payload.get("features")
    if not isinstance(features, dict):
        return False

    diarization = features.get("diarization")
    if not isinstance(diarization, dict):
        return False

    available = bool(diarization.get("available", False))
    reason = str(diarization.get("reason", "") or "")
    cached_key = str(diarization.get("preload_cache_key", "") or "")

    return available and reason == "ready" and cached_key == preload_cache_key


def check_diarization_access(
    venv_python: Path,
    diarization_model: str,
    hf_token: str | None,
    hf_home: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    if not hf_token:
        return {"available": False, "reason": "token_missing"}

    checker = r"""
import json
import sys

from huggingface_hub import HfApi

model = sys.argv[1]
token = sys.argv[2]

try:
    # Validate token/model access first to surface auth errors clearly.
    HfApi().model_info(repo_id=model, token=token)
    # Force model materialization into HF_HOME so first diarization request
    # does not trigger a large cold download.
    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(model, token=token)
    del pipeline
    print(json.dumps({"available": True, "reason": "ready"}))
except Exception as exc:
    status_code = None
    response = getattr(exc, "response", None)
    if response is not None:
        status_code = getattr(response, "status_code", None)

    message = str(exc).lower()
    reason = "unavailable"
    if status_code == 401 or "invalid token" in message or "unauthorized" in message:
        reason = "token_invalid"
    elif (
        status_code == 403
        and ("gated" in message or "terms" in message or "accept" in message)
    ):
        reason = "terms_not_accepted"
    elif status_code == 403:
        reason = "token_invalid"
    elif "gated" in message or "terms" in message or "accept" in message:
        reason = "terms_not_accepted"

    print(json.dumps({"available": False, "reason": reason, "error": str(exc)}))
"""

    env = os.environ.copy()
    env["HF_HOME"] = hf_home
    result = subprocess.run(
        [str(venv_python), "-c", checker, diarization_model, hf_token],
        text=True,
        capture_output=True,
        timeout=max(120, min(timeout_seconds, 1800)),
        env=env,
        check=False,
    )

    output = (result.stdout or "").strip().splitlines()
    if not output:
        return {"available": False, "reason": "unavailable"}

    try:
        payload = json.loads(output[-1])
    except json.JSONDecodeError:
        return {"available": False, "reason": "unavailable"}

    if payload.get("available"):
        return {"available": True, "reason": "ready"}
    return {
        "available": False,
        "reason": payload.get("reason", "unavailable"),
    }


def write_status_file(status_file: Path, payload: dict[str, Any]) -> None:
    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def check_whisper_import(
    venv_python: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    checker = """
import importlib.util
import json

modules = ("faster_whisper", "ctranslate2", "whisperx")
errors = []

for module_name in modules:
    try:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            errors.append(f"{module_name}: not found")
    except Exception as exc:
        errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

if errors:
    print(
        json.dumps(
            {
                "available": False,
                "reason": "import_failed",
                "error": " | ".join(errors),
            }
        )
    )
else:
    print(json.dumps({"available": True, "reason": "ready"}))
"""

    try:
        result = subprocess.run(
            [str(venv_python), "-c", checker],
            text=True,
            capture_output=True,
            timeout=max(30, min(timeout_seconds, 300)),
            check=False,
        )
    except Exception as exc:
        return {
            "available": False,
            "reason": "import_failed",
            "error": f"{type(exc).__name__}: {exc}",
        }

    output = (result.stdout or "").strip().splitlines()
    if not output:
        return {"available": False, "reason": "import_failed"}

    try:
        payload = json.loads(output[-1])
    except json.JSONDecodeError:
        return {"available": False, "reason": "import_failed"}

    result_payload = {
        "available": bool(payload.get("available", False)),
        "reason": str(payload.get("reason", "import_failed") or "import_failed"),
    }
    error = payload.get("error")
    if error:
        result_payload["error"] = str(error)
    return result_payload


def check_nemo_asr_import(
    venv_python: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    checker = """
import importlib.util
import json

try:
    spec = importlib.util.find_spec("nemo.collections.asr")
    if spec is None:
        print(
            json.dumps(
                {
                    "available": False,
                    "reason": "import_failed",
                    "error": "nemo.collections.asr: not found",
                }
            )
        )
    else:
        print(json.dumps({"available": True, "reason": "ready"}))
except Exception as exc:
    print(
        json.dumps(
            {
                "available": False,
                "reason": "import_failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    )
"""

    try:
        result = subprocess.run(
            [str(venv_python), "-c", checker],
            text=True,
            capture_output=True,
            timeout=max(30, min(timeout_seconds, 300)),
            check=False,
        )
    except Exception as exc:
        return {
            "available": False,
            "reason": "import_failed",
            "error": f"{type(exc).__name__}: {exc}",
        }

    output = (result.stdout or "").strip().splitlines()
    if not output:
        return {"available": False, "reason": "import_failed"}
    try:
        payload = json.loads(output[-1])
    except json.JSONDecodeError:
        return {"available": False, "reason": "import_failed"}

    result_payload = {
        "available": bool(payload.get("available", False)),
        "reason": str(payload.get("reason", "import_failed") or "import_failed"),
    }
    error = payload.get("error")
    if error:
        result_payload["error"] = str(error)
    return result_payload


def check_vibevoice_asr_import(
    venv_python: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    candidates_json = json.dumps(_VIBEVOICE_ASR_IMPORT_CANDIDATES)
    checker = f"""
import importlib.util
import json

candidates = json.loads({candidates_json!r})
attempted = []
errors = []

for (
    variant,
    model_module,
    model_symbol,
    processor_module,
    processor_symbol,
) in candidates:
    attempted.append(
        f"{{model_module}}:{{model_symbol}} + {{processor_module}}:{{processor_symbol}}"
    )
    try:
        model_spec = importlib.util.find_spec(model_module)
        processor_spec = importlib.util.find_spec(processor_module)
        if model_spec is None or processor_spec is None:
            missing = []
            if model_spec is None:
                missing.append(model_module)
            if processor_spec is None:
                missing.append(processor_module)
            errors.append(f"{{variant}}: modules not found: {{', '.join(missing)}}")
            continue
        print(
            json.dumps(
                {{
                    "available": True,
                    "reason": "ready",
                    "variant": variant,
                    "attempted_imports": attempted,
                }}
            )
        )
        break
    except Exception as exc:
        errors.append(
            f"{{variant}}: {{type(exc).__name__}}: {{exc}}"
        )
else:
    top_level_error = None
    try:
        spec = importlib.util.find_spec("vibevoice")
        if spec is None:
            top_level_error = "vibevoice: not found"
    except Exception as exc:
        top_level_error = f"{{type(exc).__name__}}: {{exc}}"

    payload = {{
        "available": False,
        "reason": "import_failed",
        "error": " | ".join(errors) if errors else "No import candidates attempted",
        "attempted_imports": attempted,
    }}
    if top_level_error:
        payload["top_level_error"] = top_level_error
    print(json.dumps(payload))
"""

    try:
        result = subprocess.run(
            [str(venv_python), "-c", checker],
            text=True,
            capture_output=True,
            timeout=max(30, min(timeout_seconds, 300)),
            check=False,
        )
    except Exception as exc:
        return {
            "available": False,
            "reason": "import_failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    output = (result.stdout or "").strip().splitlines()
    if not output:
        return {"available": False, "reason": "import_failed"}
    try:
        payload = json.loads(output[-1])
    except json.JSONDecodeError:
        return {"available": False, "reason": "import_failed"}
    result_payload = {
        "available": bool(payload.get("available", False)),
        "reason": str(payload.get("reason", "import_failed") or "import_failed"),
    }
    error = payload.get("error")
    if error:
        result_payload["error"] = str(error)
    attempted_imports = payload.get("attempted_imports")
    if isinstance(attempted_imports, list):
        result_payload["attempted_imports"] = [str(item) for item in attempted_imports]
    variant = payload.get("variant")
    if variant:
        result_payload["variant"] = str(variant)
    top_level_error = payload.get("top_level_error")
    if top_level_error:
        result_payload["top_level_error"] = str(top_level_error)
    return result_payload


def check_vibevoice_asr_quant_runtime(
    venv_python: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Check quantized VibeVoice runtime dependencies in the runtime venv."""
    required_json = json.dumps(
        [spec.split(">=", 1)[0] for spec in _VIBEVOICE_ASR_QUANT_RUNTIME_PACKAGE_SPECS]
    )
    checker = f"""
import importlib.metadata
import json

required = json.loads({required_json!r})
missing = []
versions = {{}}
errors = {{}}

for name in required:
    try:
        versions[name] = importlib.metadata.version(name)
    except Exception as exc:
        missing.append(name)
        errors[name] = f"{{type(exc).__name__}}: {{exc}}"

payload = {{
    "available": len(missing) == 0,
    "reason": "ready" if len(missing) == 0 else "missing_packages",
    "missing_packages": missing,
    "versions": versions,
}}
if errors:
    payload["error"] = " | ".join(f"{{name}}={{msg}}" for name, msg in errors.items())
print(json.dumps(payload))
"""
    try:
        result = subprocess.run(
            [str(venv_python), "-c", checker],
            text=True,
            capture_output=True,
            timeout=max(30, min(timeout_seconds, 300)),
            check=False,
        )
    except Exception as exc:
        return {
            "available": False,
            "reason": "probe_failed",
            "error": f"{type(exc).__name__}: {exc}",
        }

    output = (result.stdout or "").strip().splitlines()
    if not output:
        return {"available": False, "reason": "probe_failed"}
    try:
        payload = json.loads(output[-1])
    except json.JSONDecodeError:
        return {"available": False, "reason": "probe_failed"}

    result_payload: dict[str, Any] = {
        "available": bool(payload.get("available", False)),
        "reason": str(payload.get("reason", "probe_failed") or "probe_failed"),
    }
    missing = payload.get("missing_packages")
    if isinstance(missing, list):
        result_payload["missing_packages"] = [str(item) for item in missing]
    versions = payload.get("versions")
    if isinstance(versions, dict):
        result_payload["versions"] = {str(k): str(v) for k, v in versions.items()}
    error = payload.get("error")
    if error:
        result_payload["error"] = str(error)
    return result_payload


def main() -> int:
    log_timing("bootstrap main() started")
    runtime_dir = Path(os.environ.get("BOOTSTRAP_RUNTIME_DIR", "/runtime"))
    cache_dir = Path(os.environ.get("BOOTSTRAP_CACHE_DIR", "/runtime/cache"))
    status_file = Path(
        os.environ.get(
            "BOOTSTRAP_STATUS_FILE",
            str(runtime_dir / "bootstrap-status.json"),
        )
    )
    timeout_seconds = parse_int_env("BOOTSTRAP_TIMEOUT_SECONDS", 1800)
    require_hf_token = parse_bool_env("BOOTSTRAP_REQUIRE_HF_TOKEN", False)
    log_changes = parse_bool_env("BOOTSTRAP_LOG_CHANGES", True)

    hf_token = (os.environ.get("HF_TOKEN") or "").strip() or None
    hf_home = os.environ.get("HF_HOME", "/models")
    previous_status_payload = load_status_file(status_file)

    if require_hf_token and not hf_token:
        log("HF token required by configuration but not provided")
        return 1

    # Compute extras to include in uv sync based on env flags.
    # This avoids separate `uv pip install` calls for optional packages.
    requested_extras: list[str] = []
    if parse_bool_env("INSTALL_WHISPER", False):
        requested_extras.append("whisper")
    if parse_bool_env("INSTALL_NEMO", False):
        requested_extras.append("nemo")
    # vibevoice_asr uses env-overridable git+ URL, continues with uv pip install
    extras_tuple = tuple(sorted(requested_extras))

    deps_start = time.perf_counter()
    venv_dir, sync_mode, package_delta, diagnostics = ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=timeout_seconds,
        log_changes=log_changes,
        extras=extras_tuple,
    )
    log_timing("runtime dependency bootstrap phase complete", deps_start)
    log(f"Dependency update path: {sync_mode}")

    venv_python = venv_dir / "bin/python"
    if not venv_python.exists():
        log("Runtime Python not found after bootstrap")
        return 1

    model_config_start = time.perf_counter()
    main_model, live_model, diarization_model = load_config_models()
    log_timing("model config load complete", model_config_start)
    log(f"Configured main model: {main_model}")
    log(f"Configured live model: {live_model}")
    log(f"Configured diarization model: {diarization_model}")

    diarization_start = time.perf_counter()
    preload_cache_key = compute_diarization_preload_cache_key(
        diarization_model=diarization_model,
        hf_token=hf_token,
        hf_home=hf_home,
    )
    if should_reuse_cached_diarization_status(
        previous_status_payload=previous_status_payload,
        preload_cache_key=preload_cache_key,
    ):
        diarization_status = {
            "available": True,
            "reason": "ready",
            "preload_mode": "cached",
            "preload_cache_key": preload_cache_key,
        }
    else:
        diarization_status = check_diarization_access(
            venv_python=venv_python,
            diarization_model=diarization_model,
            hf_token=hf_token,
            hf_home=hf_home,
            timeout_seconds=timeout_seconds,
        )
        diarization_status["preload_mode"] = "performed"
        diarization_status["preload_cache_key"] = compute_diarization_preload_cache_key(
            diarization_model=diarization_model,
            hf_token=hf_token,
            hf_home=hf_home,
        )
    log_timing("diarization capability check complete", diarization_start)
    if diarization_status["available"]:
        if diarization_status.get("preload_mode") == "cached":
            log("Diarization capability check: ready (cached)")
        else:
            log("Diarization capability check: ready")
    else:
        log(
            "Diarization capability check: unavailable "
            f"({diarization_status.get('reason', 'unavailable')})"
        )

    whisper_selected = is_whisper_model_name(main_model) or is_whisper_model_name(live_model)
    nemo_selected = is_nemo_model_name(main_model) or is_nemo_model_name(live_model)
    vibevoice_selected = is_vibevoice_asr_model_name(main_model) or is_vibevoice_asr_model_name(
        live_model
    )

    # ── Reuse cached feature status when deps are unchanged ───────────────
    _reuse_feature_cache = should_reuse_cached_feature_status(
        previous_status_payload=previous_status_payload,
        sync_mode=sync_mode,
    )
    if _reuse_feature_cache:
        log("Reusing cached feature import results (deps unchanged, sync_mode=skip)")

    # ── faster-whisper family (optional) ───────────────────────────────────
    whisper_start = time.perf_counter()
    install_whisper = parse_bool_env("INSTALL_WHISPER", False)
    whisper_status: dict[str, Any]

    if not whisper_selected and not install_whisper:
        whisper_status = {"available": False, "reason": "not_selected"}
        log("faster-whisper not selected by configured models, skipping feature check")
    elif _reuse_feature_cache and not install_whisper:
        whisper_status = previous_status_payload["features"]["whisper"]
        log(
            "faster-whisper feature check: reusing cached result "
            f"(available={whisper_status.get('available')})"
        )
    else:
        existing_whisper_status = check_whisper_import(
            venv_python=venv_python,
            timeout_seconds=timeout_seconds,
        )

        if existing_whisper_status.get("available"):
            whisper_status = existing_whisper_status
            if install_whisper:
                log("faster-whisper family already installed, skipping reinstall")
            else:
                log("faster-whisper family already available, skipping optional install")
        elif install_whisper:
            log("Installing faster-whisper family dependencies...")
            try:
                run_command(
                    [
                        "uv",
                        "pip",
                        "install",
                        "--python",
                        str(venv_python),
                        "faster-whisper>=1.2.1",
                        "ctranslate2>=4.6.2",
                        "whisperx>=3.1.0",
                    ],
                    timeout_seconds=timeout_seconds,
                    env=build_uv_sync_env(
                        venv_dir=venv_dir,
                        cache_dir=cache_dir,
                    ),
                )
                whisper_status = check_whisper_import(
                    venv_python=venv_python,
                    timeout_seconds=timeout_seconds,
                )
                if whisper_status.get("available"):
                    log("faster-whisper family dependencies installed")
                else:
                    failure_error = str(whisper_status.get("error", "")).strip()
                    log(
                        "faster-whisper dependency installation completed but import check failed "
                        f"({whisper_status.get('reason', 'import_failed')}"
                        + (f": {failure_error}" if failure_error else "")
                        + ")"
                    )
            except Exception as exc:
                whisper_status = {
                    "available": False,
                    "reason": "install_failed",
                    "error": str(exc),
                }
                log(f"faster-whisper dependency installation failed: {exc}")
        else:
            # Reachable only when whisper_selected=True and install_whisper=False
            whisper_status = {
                "available": False,
                "reason": "selected_but_not_requested",
            }
            log(
                "faster-whisper selected but INSTALL_WHISPER is not enabled, "
                "skipping optional install"
            )
    log_timing("faster-whisper feature check complete", whisper_start)

    # ── NeMo toolkit (optional, for NVIDIA Parakeet ASR models) ──────────
    nemo_start = time.perf_counter()
    install_nemo = parse_bool_env("INSTALL_NEMO", False)
    nemo_status: dict[str, Any]

    if not nemo_selected and not install_nemo:
        nemo_status = {"available": False, "reason": "not_selected"}
        log("NeMo not selected by configured models, skipping feature check")
    elif _reuse_feature_cache and not install_nemo:
        nemo_status = previous_status_payload["features"]["nemo"]
        log(f"NeMo feature check: reusing cached result (available={nemo_status.get('available')})")
    else:
        existing_nemo_status = check_nemo_asr_import(
            venv_python=venv_python,
            timeout_seconds=timeout_seconds,
        )

        if existing_nemo_status.get("available"):
            nemo_status = existing_nemo_status
            if install_nemo:
                log("NeMo toolkit already installed, skipping reinstall")
            else:
                log("NeMo toolkit already available, skipping optional install")
        elif install_nemo:
            log("Installing NeMo toolkit for NVIDIA Parakeet support...")
            try:
                run_command(
                    [
                        "uv",
                        "pip",
                        "install",
                        "--python",
                        str(venv_python),
                        "nemo_toolkit[asr]>=2.2.0",
                    ],
                    timeout_seconds=timeout_seconds,
                    env=build_uv_sync_env(
                        venv_dir=venv_dir,
                        cache_dir=cache_dir,
                    ),
                )
                nemo_status = check_nemo_asr_import(
                    venv_python=venv_python,
                    timeout_seconds=timeout_seconds,
                )
                if nemo_status.get("available"):
                    log("NeMo toolkit installed")
                else:
                    failure_error = str(nemo_status.get("error", "")).strip()
                    log(
                        "NeMo toolkit installation completed but import check failed "
                        f"({nemo_status.get('reason', 'import_failed')}"
                        + (f": {failure_error}" if failure_error else "")
                        + ")"
                    )
            except Exception as exc:
                nemo_status = {
                    "available": False,
                    "reason": "install_failed",
                    "error": str(exc),
                }
                log(f"NeMo toolkit installation failed: {exc}")
        else:
            # Reachable only when nemo_selected=True and install_nemo=False
            nemo_status = {"available": False, "reason": "selected_but_not_requested"}
            log("NeMo model selected but INSTALL_NEMO is not enabled, skipping optional install")
    log_timing("NeMo feature check complete", nemo_start)

    # ── VibeVoice-ASR (optional, experimental in-process backend) ───────────
    vibevoice_start = time.perf_counter()
    install_vibevoice_asr = parse_bool_env("INSTALL_VIBEVOICE_ASR", False)
    vibevoice_asr_status: dict[str, Any]
    vibevoice_asr_package_spec = (
        os.environ.get(
            "VIBEVOICE_ASR_PACKAGE_SPEC",
            "git+https://github.com/microsoft/VibeVoice.git@1807b858d4f7dffdd286249a01616c243e488c9e",
        ).strip()
        or "git+https://github.com/microsoft/VibeVoice.git@1807b858d4f7dffdd286249a01616c243e488c9e"
    )
    vibevoice_quantized_selected = is_vibevoice_asr_quantized_model_name(main_model)

    if not vibevoice_selected and not install_vibevoice_asr:
        vibevoice_asr_status = {"available": False, "reason": "not_selected"}
        log("VibeVoice-ASR not selected by configured models, skipping feature check")
    elif _reuse_feature_cache and not install_vibevoice_asr:
        vibevoice_asr_status = previous_status_payload["features"]["vibevoice_asr"]
        log(
            "VibeVoice-ASR feature check: reusing cached result "
            f"(available={vibevoice_asr_status.get('available')})"
        )
    else:
        existing_vibevoice_asr_status = check_vibevoice_asr_import(
            venv_python=venv_python,
            timeout_seconds=timeout_seconds,
        )
        vibevoice_quant_runtime_status: dict[str, Any] | None = None
        if install_vibevoice_asr and vibevoice_quantized_selected:
            vibevoice_quant_runtime_status = check_vibevoice_asr_quant_runtime(
                venv_python=venv_python,
                timeout_seconds=timeout_seconds,
            )

        if existing_vibevoice_asr_status.get("available"):
            need_quant_runtime_install = (
                install_vibevoice_asr
                and vibevoice_quantized_selected
                and not bool((vibevoice_quant_runtime_status or {}).get("available", False))
            )
            if need_quant_runtime_install:
                missing_quant_runtime = (
                    vibevoice_quant_runtime_status.get("missing_packages")
                    if isinstance(vibevoice_quant_runtime_status, dict)
                    else None
                )
                missing_list = (
                    [str(item) for item in missing_quant_runtime]
                    if isinstance(missing_quant_runtime, list)
                    else []
                )
                log(
                    "VibeVoice-ASR core already installed; installing quantization runtime "
                    "dependencies for selected quantized model"
                    + (f" (missing={', '.join(missing_list)})" if missing_list else "")
                    + "..."
                )
                try:
                    run_command(
                        [
                            "uv",
                            "pip",
                            "install",
                            "--python",
                            str(venv_python),
                            *_VIBEVOICE_ASR_QUANT_RUNTIME_PACKAGE_SPECS,
                        ],
                        timeout_seconds=timeout_seconds,
                        env=build_uv_sync_env(
                            venv_dir=venv_dir,
                            cache_dir=cache_dir,
                        ),
                    )
                    vibevoice_quant_runtime_status = check_vibevoice_asr_quant_runtime(
                        venv_python=venv_python,
                        timeout_seconds=timeout_seconds,
                    )
                    if vibevoice_quant_runtime_status.get("available"):
                        log("VibeVoice-ASR quantization runtime dependencies ready")
                    else:
                        failure_error = str(vibevoice_quant_runtime_status.get("error", "")).strip()
                        log(
                            "VibeVoice-ASR quantization runtime dependency installation completed "
                            "but verification failed "
                            f"({vibevoice_quant_runtime_status.get('reason', 'missing_packages')}"
                            + (f": {failure_error}" if failure_error else "")
                            + ")"
                        )
                except Exception as exc:
                    vibevoice_asr_status = {
                        "available": False,
                        "reason": "install_failed",
                        "error": str(exc),
                    }
                    log(f"VibeVoice-ASR quantization runtime dependency installation failed: {exc}")
                else:
                    if vibevoice_quant_runtime_status.get("available"):
                        vibevoice_asr_status = existing_vibevoice_asr_status
                        variant = vibevoice_asr_status.get("variant")
                        if variant:
                            log(
                                f"VibeVoice-ASR support already installed (import layout={variant})"
                            )
                        else:
                            log("VibeVoice-ASR support already installed")
                    else:
                        vibevoice_asr_status = {
                            "available": False,
                            "reason": str(
                                vibevoice_quant_runtime_status.get(
                                    "reason", "quant_runtime_missing"
                                )
                                or "quant_runtime_missing"
                            ),
                        }
                        error = vibevoice_quant_runtime_status.get("error")
                        if error:
                            vibevoice_asr_status["error"] = str(error)
            else:
                vibevoice_asr_status = existing_vibevoice_asr_status
                variant = vibevoice_asr_status.get("variant")
                if variant:
                    log(f"VibeVoice-ASR support already installed (import layout={variant})")
                else:
                    log("VibeVoice-ASR support already installed")
        elif install_vibevoice_asr:
            log("Installing VibeVoice-ASR (experimental) support...")
            try:
                vibevoice_install_specs = [vibevoice_asr_package_spec]
                if vibevoice_quantized_selected:
                    log(
                        "Selected VibeVoice-ASR model appears quantized; installing quantization runtime "
                        f"dependencies: {', '.join(_VIBEVOICE_ASR_QUANT_RUNTIME_PACKAGE_SPECS)}"
                    )
                    vibevoice_install_specs.extend(_VIBEVOICE_ASR_QUANT_RUNTIME_PACKAGE_SPECS)
                run_command(
                    [
                        "uv",
                        "pip",
                        "install",
                        "--python",
                        str(venv_python),
                        *vibevoice_install_specs,
                    ],
                    timeout_seconds=timeout_seconds,
                    env=build_uv_sync_env(
                        venv_dir=venv_dir,
                        cache_dir=cache_dir,
                    ),
                )
                vibevoice_asr_status = check_vibevoice_asr_import(
                    venv_python=venv_python,
                    timeout_seconds=timeout_seconds,
                )
                if vibevoice_asr_status.get("available"):
                    variant = vibevoice_asr_status.get("variant")
                    if variant:
                        log(f"VibeVoice-ASR support installed (import layout={variant})")
                    else:
                        log("VibeVoice-ASR support installed")
                else:
                    failure_error = str(vibevoice_asr_status.get("error", "")).strip()
                    log(
                        "VibeVoice-ASR installation completed but import check failed "
                        f"({vibevoice_asr_status.get('reason', 'import_failed')}"
                        + (f": {failure_error}" if failure_error else "")
                        + ")"
                    )
            except Exception as exc:
                vibevoice_asr_status = {
                    "available": False,
                    "reason": "install_failed",
                    "error": str(exc),
                }
                log(f"VibeVoice-ASR installation failed: {exc}")
        else:
            # Reachable only when vibevoice_selected=True and install_vibevoice_asr=False
            vibevoice_asr_status = {
                "available": False,
                "reason": "selected_but_not_requested",
            }
            log(
                "VibeVoice-ASR selected but INSTALL_VIBEVOICE_ASR is not enabled, "
                "skipping optional install"
            )
    log_timing("VibeVoice-ASR feature check complete", vibevoice_start)

    status_write_start = time.perf_counter()
    write_status_file(
        status_file,
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "bootstrap": {
                "schema_version": BOOTSTRAP_SCHEMA_VERSION,
                "sync_mode": sync_mode,
                "package_delta": package_delta,
                "selection_reason": diagnostics.get("selection_reason"),
                "escalated_to_rebuild": diagnostics.get("escalated_to_rebuild", False),
                "delta_sync_error": diagnostics.get("delta_sync_error"),
            },
            "features": {
                "diarization": diarization_status,
                "whisper": whisper_status,
                "nemo": nemo_status,
                "vibevoice_asr": vibevoice_asr_status,
            },
        },
    )
    log_timing("bootstrap status file write complete", status_write_start)
    log_timing("bootstrap main() complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
