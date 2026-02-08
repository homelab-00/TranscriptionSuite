"""
Single instance enforcement for the TranscriptionSuite client.

Ensures only one instance of the client can run at a time using platform-specific locking.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def get_lock_file_paths() -> list[Path]:
    """Get candidate lock file paths (most preferred first)."""
    candidates: list[Path] = []

    if sys.platform == "win32":
        # Windows: Use AppData
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            candidates.append(Path(appdata) / "TranscriptionSuite" / "dashboard.lock")
        else:
            candidates.append(
                Path.home()
                / "AppData"
                / "Roaming"
                / "TranscriptionSuite"
                / "dashboard.lock"
            )
        return candidates

    # Linux/macOS: Prefer runtime/cache locations that are user-owned.
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime:
        candidates.append(Path(xdg_runtime) / "TranscriptionSuite" / "dashboard.lock")

    if sys.platform == "darwin":
        candidates.append(
            Path.home() / "Library" / "Caches" / "TranscriptionSuite" / "dashboard.lock"
        )
    else:
        xdg_cache = os.environ.get("XDG_CACHE_HOME")
        if xdg_cache:
            candidates.append(Path(xdg_cache) / "TranscriptionSuite" / "dashboard.lock")
        else:
            candidates.append(
                Path.home() / ".cache" / "TranscriptionSuite" / "dashboard.lock"
            )
        candidates.append(
            Path("/tmp") / f"transcriptionsuite-{os.getuid()}" / "dashboard.lock"
        )

    # Legacy path (kept last for backward compatibility with older instances).
    candidates.append(Path.home() / ".config" / "TranscriptionSuite" / "dashboard.lock")

    # De-duplicate while preserving order.
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path not in seen:
            unique.append(path)
            seen.add(path)

    return unique


def acquire_instance_lock() -> Optional[object]:
    """
    Acquire an exclusive lock to ensure single instance.

    Returns:
        Lock file descriptor/handle if successful, None if another instance is running
    """
    if sys.platform == "win32":
        # Windows: Use ctypes to create a named mutex
        try:
            import ctypes

            # Create kernel32 reference
            kernel32 = ctypes.windll.kernel32

            # Define CreateMutex
            CreateMutexW = kernel32.CreateMutexW
            CreateMutexW.argtypes = [
                ctypes.wintypes.LPVOID,  # lpMutexAttributes
                ctypes.wintypes.BOOL,  # bInitialOwner
                ctypes.wintypes.LPCWSTR,  # lpName
            ]
            CreateMutexW.restype = ctypes.wintypes.HANDLE

            # Define GetLastError
            GetLastError = kernel32.GetLastError
            GetLastError.argtypes = []
            GetLastError.restype = ctypes.wintypes.DWORD

            # Create named mutex
            mutex_name = "Global\\TranscriptionSuite-Dashboard-Instance-Lock"
            mutex_handle = CreateMutexW(None, True, mutex_name)

            ERROR_ALREADY_EXISTS = 183
            if GetLastError() == ERROR_ALREADY_EXISTS:
                logger.info("Another instance is already running (Windows mutex)")
                return None

            logger.debug(f"Acquired instance lock via Windows mutex: {mutex_name}")
            return mutex_handle

        except Exception as e:
            logger.warning(
                f"Failed to create Windows mutex, falling back to file lock: {e}"
            )
            # Fall through to file-based locking

    # Linux/macOS: Use fcntl file locking
    try:
        import fcntl

        acquired_fds: list[object] = []
        lock_paths = get_lock_file_paths()

        for lock_file in lock_paths:
            try:
                lock_file.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.debug(
                    f"Skipping lock path {lock_file} (cannot create directory): {e}"
                )
                continue

            try:
                fd = open(lock_file, "a+", encoding="utf-8")
            except PermissionError as e:
                logger.debug(f"Skipping lock path {lock_file} (permission denied): {e}")
                continue
            except Exception as e:
                logger.debug(f"Skipping lock path {lock_file} (open failed): {e}")
                continue

            # Try to acquire exclusive lock (non-blocking)
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError) as e:
                logger.info(f"Another instance is already running (fcntl lock): {e}")
                fd.close()
                for held in acquired_fds:
                    try:
                        if hasattr(held, "close"):
                            held.close()
                    except Exception as cleanup_error:
                        logger.debug(
                            "Failed to close acquired lock handle during rollback: %s",
                            cleanup_error,
                        )
                return None

            # Write PID to lock file for debugging (best effort)
            try:
                fd.seek(0)
                fd.truncate()
                fd.write(str(os.getpid()))
                fd.flush()
            except Exception as pid_write_error:
                logger.debug(
                    "Failed to write PID into lock file %s: %s",
                    lock_file,
                    pid_write_error,
                )

            acquired_fds.append(fd)

        if acquired_fds:
            logger.debug(f"Acquired instance lock(s): {lock_paths}")
            return acquired_fds

        logger.error("Failed to acquire instance lock: no writable lock path available")
        return None

    except Exception as e:
        logger.error(f"Failed to acquire instance lock: {e}")
        return None


def release_instance_lock(lock_fd: Optional[object]) -> None:
    """
    Release the instance lock.

    Args:
        lock_fd: Lock file descriptor/handle from acquire_instance_lock()
    """
    if lock_fd is None:
        return

    if sys.platform == "win32":
        # Windows: Close mutex handle
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.CloseHandle(lock_fd)
            logger.debug("Released instance lock (Windows mutex)")
        except Exception as e:
            logger.warning(f"Failed to release Windows mutex: {e}")
    else:
        # Linux/macOS: Close file descriptor(s) (releases fcntl locks)
        try:
            if isinstance(lock_fd, (list, tuple)):
                lock_handles = list(lock_fd)
            else:
                lock_handles = [lock_fd]

            for handle in lock_handles:
                if hasattr(handle, "close"):
                    handle.close()
            logger.debug("Released instance lock (fcntl)")
        except Exception as e:
            logger.warning(f"Failed to release file lock: {e}")
