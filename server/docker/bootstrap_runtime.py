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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_ROOT = Path("/app")
PROJECT_DIR = APP_ROOT / "server"
LOCK_FILE = PROJECT_DIR / "uv.lock"
PYPROJECT_FILE = PROJECT_DIR / "pyproject.toml"
DEFAULT_CONFIG_FILE = APP_ROOT / "config.yaml"
USER_CONFIG_FILE = Path("/user-config/config.yaml")

DEFAULT_MAIN_MODEL = "Systran/faster-whisper-large-v3"
DEFAULT_DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"

BOOTSTRAP_SCHEMA_VERSION = 2
FINGERPRINT_SOURCES = {"lockfile", "legacy"}
REBUILD_POLICIES = {"abi_only", "always", "never"}


def log(message: str) -> None:
    print(f"[bootstrap] {message}", flush=True)


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


def parse_choice_env(name: str, default: str, choices: set[str]) -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in choices:
        return value
    log(
        f"Invalid value for {name}: {raw!r}. Using default {default!r}. "
        f"Allowed values: {', '.join(sorted(choices))}"
    )
    return default


def python_abi_tag() -> str:
    soabi = sysconfig.get_config_var("SOABI")
    if soabi:
        return str(soabi)
    cache_tag = getattr(sys.implementation, "cache_tag", None)
    if cache_tag:
        return str(cache_tag)
    return f"py{sys.version_info.major}.{sys.version_info.minor}"


def update_hash_with_file(hasher: Any, label: str, path: Path) -> None:
    hasher.update(f"{label}:".encode("utf-8"))
    hasher.update(path.name.encode("utf-8"))
    if path.exists():
        hasher.update(path.read_bytes())
    else:
        hasher.update(b"<missing>")


def compute_dependency_fingerprint(
    fingerprint_source: str,
    python_abi: str,
    arch: str,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(f"schema={BOOTSTRAP_SCHEMA_VERSION}".encode("utf-8"))
    hasher.update(f"source={fingerprint_source}".encode("utf-8"))
    hasher.update(f"abi={python_abi}".encode("utf-8"))
    hasher.update(f"arch={arch}".encode("utf-8"))

    # Recommended mode: lockfile-only (dependency-resolving source of truth).
    update_hash_with_file(hasher, "uv-lock", LOCK_FILE)

    # Backward-compatible mode for legacy behavior.
    if fingerprint_source == "legacy":
        update_hash_with_file(hasher, "pyproject", PYPROJECT_FILE)

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
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(cmd)}\n{output}"
        )
    return result


def run_best_effort_uv_cache_prune(
    cache_dir: Path,
    timeout_seconds: int,
    env: dict[str, str],
) -> None:
    """Prune stale cache entries without failing bootstrap."""
    prune_timeout = max(60, min(timeout_seconds, 600))
    try:
        result = subprocess.run(
            ["uv", "cache", "prune"],
            env=env,
            text=True,
            capture_output=True,
            timeout=prune_timeout,
            check=False,
        )
    except Exception as exc:
        log(f"UV cache prune failed (non-fatal): {exc}")
        return

    if result.returncode == 0:
        log(f"UV cache prune complete ({cache_dir})")
        return

    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if output:
        log(f"UV cache prune failed (non-fatal): {output}")
    else:
        log("UV cache prune failed (non-fatal)")


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


def summarize_failure_snippet(
    stdout: str | None,
    stderr: str | None,
    returncode: int,
) -> str:
    """Create a short, stable one-line failure summary from command output."""
    merged = "\n".join(
        part for part in ((stdout or "").strip(), (stderr or "").strip()) if part
    )
    lines = [line.strip() for line in merged.splitlines() if line.strip()]

    if lines:
        snippet = lines[-1]
    else:
        snippet = f"command failed with exit code {returncode}"

    if len(snippet) > 240:
        return f"{snippet[:237]}..."
    return snippet


def build_uv_sync_env(venv_dir: Path, cache_dir: Path) -> dict[str, str]:
    """Build environment variables used by runtime uv commands."""
    env = os.environ.copy()
    env["UV_PROJECT_ENVIRONMENT"] = str(venv_dir)
    env["UV_CACHE_DIR"] = str(cache_dir)
    env["UV_PYTHON"] = "/usr/bin/python3.13"
    return env


def check_runtime_environment_integrity(
    venv_dir: Path,
    cache_dir: Path,
    timeout_seconds: int,
) -> tuple[bool, str]:
    """
    Validate runtime venv against uv.lock for all packages.

    This is intentionally lock-level integrity checking, not package-specific probing.
    """
    check_timeout = max(30, min(timeout_seconds, 600))
    cmd = [
        "uv",
        "sync",
        "--check",
        "--frozen",
        "--no-dev",
        "--project",
        str(PROJECT_DIR),
    ]
    try:
        result = subprocess.run(
            cmd,
            env=build_uv_sync_env(venv_dir=venv_dir, cache_dir=cache_dir),
            text=True,
            capture_output=True,
            timeout=check_timeout,
            check=False,
        )
    except Exception as exc:
        return False, f"integrity check command failed: {exc}"

    if result.returncode == 0:
        return True, "ok"

    return False, summarize_failure_snippet(
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
    )


def run_dependency_sync(
    venv_dir: Path,
    cache_dir: Path,
    timeout_seconds: int,
) -> None:
    """Run dependency sync into the runtime virtual environment."""
    run_command(
        [
            "uv",
            "sync",
            "--frozen",
            "--no-dev",
            "--project",
            str(PROJECT_DIR),
        ],
        timeout_seconds=timeout_seconds,
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
    updated = sorted(
        key for key in (before_keys & after_keys) if before.get(key) != after.get(key)
    )

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
    fingerprint_source: str,
    rebuild_policy: str,
    log_changes: bool,
) -> tuple[Path, str, dict[str, int], dict[str, Any]]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    venv_dir = runtime_dir / ".venv"
    marker_file = runtime_dir / ".runtime-bootstrap-marker.json"
    lock_file = runtime_dir / ".runtime-bootstrap.lock"

    python_abi = python_abi_tag()
    arch = platform.machine()
    fingerprint = compute_dependency_fingerprint(
        fingerprint_source=fingerprint_source,
        python_abi=python_abi,
        arch=arch,
    )

    package_delta: dict[str, int] = {
        "added": 0,
        "removed": 0,
        "updated": 0,
        "before_count": 0,
        "after_count": 0,
    }
    diagnostics: dict[str, Any] = {
        "selection_reason": "unknown",
        "escalated_to_rebuild": False,
        "integrity": {
            "check_command": "uv sync --check --frozen --no-dev --project /app/server",
            "status": "unknown",
            "failure_snippet": None,
            "checks": [],
        },
    }

    with lock_file.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)

        marker_data = load_marker(marker_file)
        venv_python = venv_dir / "bin/python"
        venv_exists = venv_python.exists()

        marker_abi = str(marker_data.get("python_abi", ""))
        marker_arch = str(marker_data.get("arch", ""))
        marker_has_abi_info = bool(marker_abi and marker_arch)
        abi_compatible = bool(
            venv_exists
            and marker_has_abi_info
            and marker_abi == python_abi
            and marker_arch == arch
        )

        if rebuild_policy == "always":
            rebuild_required = True
        elif rebuild_policy == "never":
            rebuild_required = False
        else:  # abi_only
            rebuild_required = bool(
                venv_exists and marker_has_abi_info and not abi_compatible
            )

        marker_matches = bool(
            venv_exists
            and marker_data.get("schema_version") == BOOTSTRAP_SCHEMA_VERSION
            and marker_data.get("fingerprint_source") == fingerprint_source
            and marker_data.get("fingerprint") == fingerprint
            and not rebuild_required
        )

        integrity_checks: list[dict[str, Any]] = diagnostics["integrity"]["checks"]

        def record_integrity_check(stage: str, ok: bool, message: str) -> None:
            integrity_checks.append(
                {
                    "stage": stage,
                    "ok": ok,
                    "message": message,
                }
            )
            if not ok and diagnostics["integrity"]["failure_snippet"] is None:
                diagnostics["integrity"]["failure_snippet"] = message

        selected_mode = "delta-sync"
        if not venv_exists:
            selected_mode = "rebuild-sync"
            diagnostics["selection_reason"] = "venv_missing"
        elif rebuild_required:
            selected_mode = "rebuild-sync"
            diagnostics["selection_reason"] = "abi_incompatible"
        elif marker_matches:
            pre_ok, pre_msg = check_runtime_environment_integrity(
                venv_dir=venv_dir,
                cache_dir=cache_dir,
                timeout_seconds=timeout_seconds,
            )
            record_integrity_check("pre_skip_gate", pre_ok, pre_msg)
            if pre_ok:
                diagnostics["selection_reason"] = "marker_match_integrity_ok"
                diagnostics["integrity"]["status"] = "pass"
                log(
                    "Bootstrap path selected: mode=skip reason=marker_match_integrity_ok"
                )
                log("Runtime dependencies already up-to-date (mode=skip)")
                return venv_dir, "skip", package_delta, diagnostics
            diagnostics["selection_reason"] = "marker_match_integrity_failed"
            log(
                "Bootstrap path selected: mode=delta-sync "
                "reason=marker_match_integrity_failed"
            )
            log(f"Runtime integrity check failed (pre-sync): {pre_msg}")
        else:
            diagnostics["selection_reason"] = "fingerprint_drift"

        if diagnostics["selection_reason"] in {"venv_missing", "abi_incompatible"}:
            log(
                "Bootstrap path selected: "
                f"mode={selected_mode} reason={diagnostics['selection_reason']}"
            )
        elif diagnostics["selection_reason"] == "fingerprint_drift":
            log("Bootstrap path selected: mode=delta-sync reason=fingerprint_drift")

        before_packages: dict[str, str] = {}
        if log_changes and venv_exists:
            before_packages = collect_installed_packages(venv_python, timeout_seconds)

        attempt_modes: list[str]
        if selected_mode == "delta-sync":
            attempt_modes = ["delta-sync", "rebuild-sync"]
        else:
            attempt_modes = [selected_mode]

        final_sync_mode: str | None = None
        for idx, attempt_mode in enumerate(attempt_modes):
            if idx > 0 and attempt_mode == "rebuild-sync":
                diagnostics["escalated_to_rebuild"] = True

            if attempt_mode == "rebuild-sync" and venv_dir.exists():
                log(
                    "Rebuilding runtime virtual environment "
                    f"(policy={rebuild_policy}, abi_compatible={abi_compatible})"
                )
                shutil.rmtree(venv_dir, ignore_errors=True)

            log(f"Installing Python runtime dependencies (mode={attempt_mode})...")
            try:
                run_dependency_sync(
                    venv_dir=venv_dir,
                    cache_dir=cache_dir,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                failure_snippet = str(exc).strip()
                if len(failure_snippet) > 240:
                    failure_snippet = f"{failure_snippet[:237]}..."

                if diagnostics["integrity"]["failure_snippet"] is None:
                    diagnostics["integrity"]["failure_snippet"] = failure_snippet

                if attempt_mode == "delta-sync" and idx + 1 < len(attempt_modes):
                    log(
                        "Dependency sync failed for mode=delta-sync; "
                        "escalating to rebuild-sync"
                    )
                    log(f"Delta-sync failure snippet: {failure_snippet}")
                    continue

                raise RuntimeError(
                    f"Dependency sync failed for mode={attempt_mode}: {failure_snippet}"
                ) from exc

            post_ok, post_msg = check_runtime_environment_integrity(
                venv_dir=venv_dir,
                cache_dir=cache_dir,
                timeout_seconds=timeout_seconds,
            )
            record_integrity_check(f"post_{attempt_mode}", post_ok, post_msg)
            if post_ok:
                final_sync_mode = attempt_mode
                diagnostics["integrity"]["status"] = "pass"
                break

            log(f"Runtime integrity check failed after {attempt_mode}: {post_msg}")
            if attempt_mode == "delta-sync" and idx + 1 < len(attempt_modes):
                log(
                    "Bootstrap escalation: mode=rebuild-sync "
                    "reason=post_delta_integrity_failed"
                )
                continue

            raise RuntimeError(
                f"Runtime integrity check failed after {attempt_mode}: {post_msg}"
            )

        if final_sync_mode is None:
            raise RuntimeError("Runtime dependency sync did not converge")

        venv_python = venv_dir / "bin/python"
        if not venv_python.exists():
            raise RuntimeError("Runtime Python not found after dependency sync")

        if log_changes:
            after_packages = collect_installed_packages(venv_python, timeout_seconds)
            package_delta, samples = summarize_package_delta(
                before_packages, after_packages
            )
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

        run_best_effort_uv_cache_prune(
            cache_dir=cache_dir,
            timeout_seconds=timeout_seconds,
            env=build_uv_sync_env(venv_dir=venv_dir, cache_dir=cache_dir),
        )

        write_marker(
            marker_file,
            {
                "schema_version": BOOTSTRAP_SCHEMA_VERSION,
                "fingerprint": fingerprint,
                "fingerprint_source": fingerprint_source,
                "python_abi": python_abi,
                "arch": arch,
                "rebuild_policy": rebuild_policy,
                "sync_mode": final_sync_mode,
                "selection_reason": diagnostics["selection_reason"],
                "integrity_status": diagnostics["integrity"]["status"],
                "package_delta": package_delta,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        log("Runtime dependencies installed")

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


def load_config_models() -> tuple[str, str]:
    config_file = USER_CONFIG_FILE if USER_CONFIG_FILE.exists() else DEFAULT_CONFIG_FILE
    if not config_file.exists():
        return (DEFAULT_MAIN_MODEL, DEFAULT_DIARIZATION_MODEL)

    content = config_file.read_text(encoding="utf-8", errors="replace")
    main_model = extract_config_value(
        content,
        section="main_transcriber",
        key="model",
        default=DEFAULT_MAIN_MODEL,
    )
    diar_model = extract_config_value(
        content,
        section="diarization",
        key="model",
        default=DEFAULT_DIARIZATION_MODEL,
    )
    return (main_model, diar_model)


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


def main() -> int:
    runtime_dir = Path(os.environ.get("BOOTSTRAP_RUNTIME_DIR", "/runtime"))
    cache_dir = Path(os.environ.get("BOOTSTRAP_CACHE_DIR", "/runtime-cache"))
    status_file = Path(
        os.environ.get(
            "BOOTSTRAP_STATUS_FILE",
            str(runtime_dir / "bootstrap-status.json"),
        )
    )
    timeout_seconds = parse_int_env("BOOTSTRAP_TIMEOUT_SECONDS", 1800)
    require_hf_token = parse_bool_env("BOOTSTRAP_REQUIRE_HF_TOKEN", False)
    fingerprint_source = parse_choice_env(
        "BOOTSTRAP_FINGERPRINT_SOURCE",
        "lockfile",
        FINGERPRINT_SOURCES,
    )
    rebuild_policy = parse_choice_env(
        "BOOTSTRAP_REBUILD_POLICY",
        "abi_only",
        REBUILD_POLICIES,
    )
    log_changes = parse_bool_env("BOOTSTRAP_LOG_CHANGES", True)

    hf_token = (os.environ.get("HF_TOKEN") or "").strip() or None
    hf_home = os.environ.get("HF_HOME", "/models")

    if require_hf_token and not hf_token:
        log("HF token required by configuration but not provided")
        return 1

    venv_dir, sync_mode, package_delta, diagnostics = ensure_runtime_dependencies(
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        timeout_seconds=timeout_seconds,
        fingerprint_source=fingerprint_source,
        rebuild_policy=rebuild_policy,
        log_changes=log_changes,
    )
    log(f"Dependency update path: {sync_mode}")

    venv_python = venv_dir / "bin/python"
    if not venv_python.exists():
        log("Runtime Python not found after bootstrap")
        return 1

    main_model, diarization_model = load_config_models()
    log(f"Configured main model: {main_model}")
    log(f"Configured diarization model: {diarization_model}")

    diarization_status = check_diarization_access(
        venv_python=venv_python,
        diarization_model=diarization_model,
        hf_token=hf_token,
        hf_home=hf_home,
        timeout_seconds=timeout_seconds,
    )
    if diarization_status["available"]:
        log("Diarization capability check: ready")
    else:
        log(
            "Diarization capability check: unavailable "
            f"({diarization_status.get('reason', 'unavailable')})"
        )

    write_status_file(
        status_file,
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "bootstrap": {
                "schema_version": BOOTSTRAP_SCHEMA_VERSION,
                "sync_mode": sync_mode,
                "package_delta": package_delta,
                "fingerprint_source": fingerprint_source,
                "rebuild_policy": rebuild_policy,
                "selection_reason": diagnostics.get("selection_reason"),
                "escalated_to_rebuild": diagnostics.get("escalated_to_rebuild", False),
                "integrity": diagnostics.get("integrity", {}),
            },
            "features": {
                "diarization": diarization_status,
            },
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
