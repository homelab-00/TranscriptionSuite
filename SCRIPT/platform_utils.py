#!/usr/bin/env python3
"""
Platform abstraction utilities for cross-platform compatibility.

This module provides unified interfaces for platform-specific operations,
ensuring the TranscriptionSuite works seamlessly on both Windows and Linux.
"""

import contextlib
import io
import os
import sys
import platform
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Any

# Configure logging
logger = logging.getLogger(__name__)


class PlatformManager:
    """
    Manages platform-specific functionality and provides unified interfaces.
    """

    def __init__(self):
        self.platform = platform.system().lower()
        self.is_windows = self.platform == "windows"
        self.is_linux = self.platform == "linux"
        self.is_macos = self.platform == "darwin"
        self._alsa_error_handler = None
        self._stderr_lock = threading.RLock()

        # Initialize platform-specific components
        self._initialize_console()
        self._initialize_pytorch_audio()
        self._suppress_alsa_warnings()

    def _initialize_console(self):
        """Initialize console encoding for proper Unicode support."""
        if self.is_windows:
            try:
                # Force UTF-8 encoding for stdout on Windows to handle Greek characters
                sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
                logger.info("Windows console encoding initialized to UTF-8")
            except (AttributeError, OSError) as e:
                logger.warning(f"Failed to set UTF-8 encoding on Windows: {e}")
        else:
            # On Linux/macOS, assume the terminal already handles Unicode properly
            logger.info("Unix-like system detected, using default console encoding")

    def _initialize_pytorch_audio(self):
        """Initialize PyTorch audio backend if needed."""
        if self.is_windows and (3, 8) <= sys.version_info < (3, 99):
            try:
                from torchaudio._extension.utils import _init_dll_path
                _init_dll_path()
                logger.info("PyTorch audio DLL path initialized for Windows")
            except ImportError as e:
                logger.warning(f"Failed to initialize PyTorch audio on Windows: {e}")
        elif self.is_linux:
            # On Linux, PyTorch audio should work out of the box
            # But we might want to check for specific audio backends
            logger.info("Linux detected, PyTorch audio should use system backends")

    def _suppress_alsa_warnings(self):
        """Prevent ALSA from spamming stderr while keeping critical errors."""
        if not self.is_linux:
            return

        try:
            from ctypes import CDLL, CFUNCTYPE, c_char_p, c_int

            ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)

            def _alsa_error_handler(filename, line, function, err, fmt):
                # Only log actual errors; ignore harmless configuration probes
                if err == 0:
                    return

                try:
                    message = fmt.decode("utf-8", "ignore") if fmt else ""
                    location = filename.decode("utf-8", "ignore") if filename else "libasound"
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
        if not self.is_linux:
            yield
            return

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
        """Get the appropriate configuration directory for the platform."""
        if self.is_windows:
            # Use %APPDATA% on Windows
            config_dir = Path.home() / "AppData" / "Roaming" / "TranscriptionSuite"
        elif self.is_linux:
            # Follow XDG Base Directory Specification
            xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
            if xdg_config_home:
                config_dir = Path(xdg_config_home) / "transcriptionsuite"
            else:
                config_dir = Path.home() / ".config" / "transcriptionsuite"
        else:  # macOS
            config_dir = Path.home() / "Library" / "Application Support" / "TranscriptionSuite"

        # Create directory if it doesn't exist
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir

    def get_cache_dir(self) -> Path:
        """Get the appropriate cache directory for the platform."""
        if self.is_windows:
            cache_dir = Path.home() / "AppData" / "Local" / "TranscriptionSuite" / "Cache"
        elif self.is_linux:
            xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
            if xdg_cache_home:
                cache_dir = Path(xdg_cache_home) / "transcriptionsuite"
            else:
                cache_dir = Path.home() / ".cache" / "transcriptionsuite"
        else:  # macOS
            cache_dir = Path.home() / "Library" / "Caches" / "TranscriptionSuite"

        # Create directory if it doesn't exist
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def get_temp_dir(self) -> Path:
        """Get a temporary directory for the platform."""
        import tempfile
        temp_dir = Path(tempfile.gettempdir()) / "transcriptionsuite"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    def get_executable_path(self, executable_name: str) -> Optional[Path]:
        """Find an executable in the system PATH."""
        import shutil

        # Add platform-specific extensions if needed
        if self.is_windows and not executable_name.endswith('.exe'):
            executable_name += '.exe'

        executable_path = shutil.which(executable_name)
        return Path(executable_path) if executable_path else None

    def check_cuda_availability(self) -> Dict[str, Any]:
        """Check CUDA availability and return detailed information."""
        cuda_info = {
            "available": False,
            "version": None,
            "device_count": 0,
            "device_name": None,
            "compute_capability": None,
            "error": None
        }

        try:
            import torch

            if torch.cuda.is_available():
                cuda_info["available"] = True
                # Use getattr to avoid Pylance warnings about torch.version
                cuda_info["version"] = getattr(torch, 'version', {}).cuda  # type: ignore
                cuda_info["device_count"] = torch.cuda.device_count()

                if cuda_info["device_count"] > 0:
                    cuda_info["device_name"] = torch.cuda.get_device_name(0)
                    # Get compute capability
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
                "compute_type": "float16" if self._supports_float16() else "float32"
            }
        else:
            return {
                "device": "cpu",
                "compute_type": "float32"
            }

    def _supports_float16(self) -> bool:
        """Check if the current GPU supports float16 operations efficiently."""
        try:
            import torch
            if torch.cuda.is_available():
                # Check compute capability - float16 is efficient on compute capability >= 6.0
                capability = torch.cuda.get_device_capability(0)
                major, minor = capability
                return major >= 6
        except:
            pass
        return False

    def get_audio_backends(self) -> list:
        """Get available audio backends for the platform."""
        backends = []

        if self.is_windows:
            backends = ["wasapi", "directsound", "wdm-ks"]
        elif self.is_linux:
            # Check which audio systems are available
            if self.get_executable_path("pulseaudio"):
                backends.append("pulseaudio")
            if self.get_executable_path("pipewire"):
                backends.append("pipewire")
            if Path("/proc/asound").exists():
                backends.append("alsa")
        else:  # macOS
            backends = ["coreaudio"]

        return backends


# Global instance
platform_manager = PlatformManager()


def get_platform_manager() -> PlatformManager:
    """Get the global platform manager instance."""
    return platform_manager


def ensure_platform_init():
    """Ensure platform-specific initialization has been performed."""
    # This function can be called from modules to ensure platform setup
    global platform_manager
    if platform_manager is None:
        platform_manager = PlatformManager()
    return platform_manager
