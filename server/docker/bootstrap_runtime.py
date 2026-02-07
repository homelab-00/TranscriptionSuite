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
import subprocess
import sys
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


def compute_dependency_fingerprint() -> str:
    hasher = hashlib.sha256()
    hasher.update(f"python={sys.version}".encode("utf-8"))
    hasher.update(f"machine={platform.machine()}".encode("utf-8"))
    for path in (PYPROJECT_FILE, LOCK_FILE):
        if not path.exists():
            continue
        hasher.update(path.name.encode("utf-8"))
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def run_command(cmd: list[str], timeout_seconds: int, env: dict[str, str]) -> None:
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


def ensure_runtime_dependencies(runtime_dir: Path, timeout_seconds: int) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = runtime_dir / ".venv"
    cache_dir = runtime_dir / ".uv-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    marker_file = runtime_dir / ".runtime-bootstrap-marker.json"
    lock_file = runtime_dir / ".runtime-bootstrap.lock"
    fingerprint = compute_dependency_fingerprint()

    with lock_file.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)

        if marker_file.exists() and venv_dir.joinpath("bin/python").exists():
            try:
                marker_data = json.loads(marker_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                marker_data = {}
            if marker_data.get("fingerprint") == fingerprint:
                log("Runtime dependencies already up-to-date")
                return venv_dir

        log("Installing Python runtime dependencies...")
        env = os.environ.copy()
        env["UV_PROJECT_ENVIRONMENT"] = str(venv_dir)
        env["UV_CACHE_DIR"] = str(cache_dir)
        env["UV_PYTHON"] = "/usr/bin/python3.13"

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
            env=env,
        )

        marker_file.write_text(
            json.dumps(
                {
                    "fingerprint": fingerprint,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        log("Runtime dependencies installed")

    return venv_dir


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
    HfApi().model_info(repo_id=model, token=token)
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
        timeout=max(60, min(timeout_seconds, 600)),
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
    status_file = Path(
        os.environ.get(
            "BOOTSTRAP_STATUS_FILE",
            str(runtime_dir / "bootstrap-status.json"),
        )
    )
    timeout_seconds = parse_int_env("BOOTSTRAP_TIMEOUT_SECONDS", 1800)
    require_hf_token = parse_bool_env("BOOTSTRAP_REQUIRE_HF_TOKEN", False)
    hf_token = (os.environ.get("HF_TOKEN") or "").strip() or None
    hf_home = os.environ.get("HF_HOME", "/models")

    if require_hf_token and not hf_token:
        log("HF token required by configuration but not provided")
        return 1

    venv_dir = ensure_runtime_dependencies(runtime_dir, timeout_seconds)
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
            "features": {
                "diarization": diarization_status,
            },
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
