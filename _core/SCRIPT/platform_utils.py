#!/usr/bin/env python3
"""
Platform abstraction utilities for Linux.

This module provides unified interfaces for platform-specific operations,
streamlined for a Linux environment.
"""

import contextlib
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

# Configure logging
logger = logging.getLogger(__name__)


class PlatformManager:
    """
    Manages Linux-specific functionality and provides unified interfaces.
    """

    def __init__(self):
        self.platform = "linux"
        self.is_linux = True
        self._alsa_error_handler = None
        self._stderr_lock = threading.RLock()

        # Initialize platform-specific components
        self._suppress_alsa_warnings()

    def _suppress_alsa_warnings(self):
        """Prevent ALSA from spamming stderr while keeping critical errors."""
        try:
            from ctypes import CDLL, CFUNCTYPE, c_char_p, c_int

            ERROR_HANDLER_FUNC = CFUNCTYPE(
                None, c_char_p, c_int, c_char_p, c_int, c_char_p
            )

            def _alsa_error_handler(
                filename: Optional[bytes],
                line: int,
                function: Optional[bytes],
                err: int,
                fmt: Optional[bytes],
            ) -> None:
                # Only log actual errors; ignore harmless configuration probes
                if err == 0:
                    return

                try:
                    message = fmt.decode("utf-8", "ignore") if fmt else ""
                    location = (
                        filename.decode("utf-8", "ignore") if filename else "libasound"
                    )
                except Exception:
                    message = ""
                    location = "libasound"

                if message:
                    logger.debug("ALSA (%s:%s): %s", location, err, message.strip())

            handler = ERROR_HANDLER_FUNC(_alsa_error_handler)
            asound = CDLL("libasound.so.2")
            asound.snd_lib_error_set_handler(handler)
            self._alsa_error_handler = handler  # keep reference to prevent GC
            logger.debug("ALSA warnings suppressed via custom handler")
        except OSError as e:
            logger.debug("libasound not available for warning suppression: %s", e)
        except Exception as e:
            logger.debug("Could not suppress ALSA warnings: %s", e)

    @contextlib.contextmanager
    def suppress_audio_warnings(self):
        """Temporarily silence low-level audio backend spew (PortAudio/ALSA)."""
        try:
            stderr_fd = sys.stderr.fileno()
        except (AttributeError, OSError):
            yield
            return

        with self._stderr_lock:
            saved_fd = os.dup(stderr_fd)
            devnull = os.open(os.devnull, os.O_WRONLY)
            try:
                sys.stderr.flush()
                os.dup2(devnull, stderr_fd)
                os.close(devnull)
                yield
            finally:
                os.dup2(saved_fd, stderr_fd)
                os.close(saved_fd)
                try:
                    sys.stderr.flush()
                except Exception:
                    pass

    def get_config_dir(self) -> Path:
        """Get the appropriate configuration directory for Linux (XDG spec)."""
        # Follow XDG Base Directory Specification
        xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config_home:
            config_dir = Path(xdg_config_home) / "transcriptionsuite"
        else:
            config_dir = Path.home() / ".config" / "transcriptionsuite"
        return config_dir

    def get_cache_dir(self) -> Path:
        """Get the appropriate cache directory for Linux (XDG spec)."""
        xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
        if xdg_cache_home:
            cache_dir = Path(xdg_cache_home) / "transcriptionsuite"
        else:
            cache_dir = Path.home() / ".cache" / "transcriptionsuite"
        return cache_dir

    def get_temp_dir(self) -> Path:
        """Get a temporary directory for the application."""
        import tempfile

        # Get the system's temp dir path
        temp_dir_str = tempfile.gettempdir()

        # If the environment variable is empty, default to a known-good path
        if not temp_dir_str or not os.path.isabs(temp_dir_str):
            # Fallback for empty or relative paths
            temp_dir_str = "/tmp"

        app_temp_dir = Path(temp_dir_str) / "transcriptionsuite"
        app_temp_dir.mkdir(parents=True, exist_ok=True)  # Proactively create it
        return app_temp_dir

    def get_executable_path(self, executable_name: str) -> Optional[Path]:
        """Find an executable in the system PATH."""
        import shutil

        executable_path = shutil.which(executable_name)
        return Path(executable_path) if executable_path else None

    def check_cuda_availability(self) -> Dict[str, Any]:
        """Check CUDA availability and return detailed information."""
        cuda_info: Dict[str, Any] = {
            "available": False,
            "version": None,
            "device_count": 0,
            "device_name": None,
            "compute_capability": None,
            "error": None,
        }

        try:
            import torch

            if torch.cuda.is_available():
                cuda_info["available"] = True
                cuda_info["version"] = getattr(torch.version, "cuda", None)
                cuda_info["device_count"] = torch.cuda.device_count()

                if cuda_info["device_count"] > 0:
                    cuda_info["device_name"] = torch.cuda.get_device_name(0)
                    capability = torch.cuda.get_device_capability(0)
                    cuda_info["compute_capability"] = f"{capability[0]}.{capability[1]}"

                logger.info(f"CUDA available: {cuda_info}")
            else:
                cuda_info["error"] = "CUDA not available through PyTorch"
                logger.info("CUDA not available")

        except ImportError:
            cuda_info["error"] = "PyTorch not installed"
            logger.warning("PyTorch not available for CUDA detection")
        except Exception as e:
            cuda_info["error"] = str(e)
            logger.error(f"Error checking CUDA availability: {e}")

        return cuda_info

    def get_optimal_device_config(self) -> Dict[str, str]:
        """Get optimal device configuration based on available hardware."""
        cuda_info = self.check_cuda_availability()

        if cuda_info["available"]:
            return {
                "device": "cuda",
                "compute_type": "float16" if self._supports_float16() else "float32",
            }
        else:
            return {"device": "cpu", "compute_type": "float32"}

    def _supports_float16(self) -> bool:
        """Check if the current GPU supports float16 operations efficiently."""
        try:
            import torch

            if torch.cuda.is_available():
                # F16 is efficient on compute capability >= 6.0
                capability = torch.cuda.get_device_capability(0)
                major, _ = capability
                return major >= 6
        except Exception as e:
            logger.debug(f"Error checking float16 support: {e}")
        return False

    def get_audio_backends(self) -> list[str]:
        """Get available audio backends for Linux."""
        backends: list[str] = []
        # Check which audio systems are available
        if self.get_executable_path("pulseaudio"):
            backends.append("pulseaudio")
        if self.get_executable_path("pipewire"):
            backends.append("pipewire")
        if Path("/proc/asound").exists():
            backends.append("alsa")
        return backends


# --- Singleton Pattern ---
# This ensures that we only ever have one instance of PlatformManager,
# preventing redundant initializations.
_platform_manager_instance: Optional[PlatformManager] = None
_platform_manager_lock = threading.Lock()


def get_platform_manager() -> PlatformManager:
    """Get the global platform manager instance."""
    global _platform_manager_instance
    if _platform_manager_instance is None:
        with _platform_manager_lock:
            if _platform_manager_instance is None:
                _platform_manager_instance = PlatformManager()
    return _platform_manager_instance


def ensure_platform_init():
    """Ensure platform-specific initialization has been performed."""
    return get_platform_manager()
