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


def get_lock_file_path() -> Path:
    """Get the path to the lock file."""
    if sys.platform == "win32":
        # Windows: Use AppData
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            lock_dir = Path(appdata) / "TranscriptionSuite"
        else:
            lock_dir = Path.home() / "AppData" / "Roaming" / "TranscriptionSuite"
    else:
        # Linux/macOS: Use XDG config directory
        lock_dir = Path.home() / ".config" / "TranscriptionSuite"

    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / "dashboard.lock"


def acquire_instance_lock() -> Optional[object]:
    """
    Acquire an exclusive lock to ensure single instance.

    Returns:
        Lock file descriptor/handle if successful, None if another instance is running
    """
    lock_file = get_lock_file_path()

    if sys.platform == "win32":
        # Windows: Use ctypes to create a named mutex
        try:
            import ctypes
            from ctypes import wintypes

            # Create kernel32 reference
            kernel32 = ctypes.windll.kernel32

            # Define CreateMutex
            CreateMutexW = kernel32.CreateMutexW
            CreateMutexW.argtypes = [
                wintypes.LPVOID,  # lpMutexAttributes
                wintypes.BOOL,  # bInitialOwner
                wintypes.LPCWSTR,  # lpName
            ]
            CreateMutexW.restype = wintypes.HANDLE

            # Define GetLastError
            GetLastError = kernel32.GetLastError
            GetLastError.argtypes = []
            GetLastError.restype = wintypes.DWORD

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

        # Open lock file
        fd = open(lock_file, "w")

        # Try to acquire exclusive lock (non-blocking)
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Write PID to lock file for debugging
            fd.write(str(os.getpid()))
            fd.flush()
            logger.debug(f"Acquired instance lock: {lock_file}")
            return fd
        except (IOError, OSError) as e:
            logger.info(f"Another instance is already running (fcntl lock): {e}")
            fd.close()
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
        # Linux/macOS: Close file descriptor (releases fcntl lock)
        try:
            if hasattr(lock_fd, "close"):
                lock_fd.close()
            logger.debug("Released instance lock (fcntl)")
        except Exception as e:
            logger.warning(f"Failed to release file lock: {e}")
