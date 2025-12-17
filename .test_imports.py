from __future__ import annotations

import importlib
import shutil
import sys
from dataclasses import dataclass
from importlib import metadata
from typing import Iterable, Tuple


@dataclass(frozen=True)
class Dependency:
    name: str
    import_name: str
    required: bool = True
    metadata_name: str | None = None


DEPENDENCIES: Tuple[Dependency, ...] = (
    Dependency("torch", "torch", metadata_name="torch"),
    Dependency("faster-whisper", "faster_whisper", metadata_name="faster-whisper"),
    # RealtimeSTT has been vendored as MAIN/stt_engine.py - no longer a separate package
    Dependency("PyAudio", "pyaudio", metadata_name="PyAudio"),
    Dependency("PyQt6", "PyQt6", metadata_name="PyQt6"),
    Dependency(
        "Pillow", "PIL", required=False, metadata_name="Pillow"
    ),  # Not actively used
    Dependency("rich", "rich", required=False, metadata_name="rich"),
    Dependency("webrtcvad", "webrtcvad", required=False, metadata_name="webrtcvad"),
    Dependency("pyperclip", "pyperclip", metadata_name="pyperclip"),
    Dependency("psutil", "psutil", required=False, metadata_name="psutil"),
)

EXECUTABLES: Tuple[str, ...] = ("ffmpeg",)


def resolve_version(dep: Dependency, module: object) -> str:
    if dep.metadata_name:
        try:
            return metadata.version(dep.metadata_name)
        except metadata.PackageNotFoundError:
            pass
    return getattr(module, "__version__", "unknown")


def check_imports(deps: Iterable[Dependency]) -> bool:
    success = True
    print("Import checks\n--------------")
    for dep in deps:
        try:
            module = importlib.import_module(dep.import_name)
            version = resolve_version(dep, module)
            print(f"[OK] {dep.name:<15} (import '{dep.import_name}', version={version})")
        except Exception as exc:
            status = "ERROR" if dep.required else "WARN"
            print(f"[{status}] {dep.name:<15} -> {exc}")
            if dep.required:
                success = False
    return success


def check_executables(executables: Iterable[str]) -> bool:
    success = True
    print("\nExecutable checks\n-----------------")
    for exe in executables:
        path = shutil.which(exe)
        if path:
            print(f"[OK] {exe:<10} found at {path}")
        else:
            print(f"[WARN] {exe:<10} not found on PATH")
            success = False
    return success


def main() -> int:
    imports_ok = check_imports(DEPENDENCIES)
    executables_ok = check_executables(EXECUTABLES)
    overall = imports_ok and executables_ok
    print("\nSummary\n-------")
    print("All checks passed." if overall else "Issues detected.")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
