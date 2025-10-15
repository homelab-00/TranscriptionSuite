#!/usr/bin/env python3
"""
System diagnostics for the TranscriptionSuite.

Gathers information about the environment, including hardware, platform, and key
python package versions, and displays it in a startup banner.
"""

import logging
import platform
import subprocess
import sys
import time
from importlib.metadata import version as metadata_version, PackageNotFoundError
from typing import Dict, Any

from platform_utils import PlatformManager
from utils import safe_print

# Import optional dependencies at module level
try:
    import torch

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    torch = None

try:
    import faster_whisper

    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    faster_whisper = None

# Try to import Rich for prettier console output
try:
    from rich.panel import Panel

    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    Panel = None


class SystemDiagnostics:
    """Gathers and displays system hardware and software information."""

    def __init__(self, config: Dict[str, Any], platform_manager: PlatformManager):
        self.config = config
        self.platform_manager = platform_manager

    def get_version_info(self) -> Dict[str, str]:
        """Get version information for key dependencies."""
        versions = {
            "torch": torch.__version__ if TORCH_AVAILABLE and torch else "Not installed",
            "faster_whisper": (
                getattr(faster_whisper, "__version__", "Unknown")
                if FASTER_WHISPER_AVAILABLE and faster_whisper
                else "Not installed"
            ),
        }
        try:
            versions["RealtimeSTT"] = metadata_version("realtimestt")
        except PackageNotFoundError:
            versions["RealtimeSTT"] = "Not installed"

        return versions

    def get_hardware_info(self) -> Dict[str, str]:
        """Get basic CPU and GPU information."""
        hardware_info = {"cpu": "Unknown", "gpu": "PyTorch not available"}

        # Get CPU info
        try:
            cpu_info = platform.processor()
            if not cpu_info:
                # Since this is Linux-only, we directly use the /proc/cpuinfo method.
                with open("/proc/cpuinfo", "r", encoding="utf-8") as cpu_file:
                    for line in cpu_file:
                        if line.startswith("model name"):
                            cpu_info = line.split(":", 1)[1].strip()
                            break
            hardware_info["cpu"] = cpu_info or "Unknown"
        except (OSError, subprocess.SubprocessError, IndexError) as e:
            logging.error("Error getting CPU info: %s", e)

        # Get GPU info from PyTorch
        if TORCH_AVAILABLE and torch:
            try:
                if torch.cuda.is_available():
                    hardware_info["gpu"] = torch.cuda.get_device_name(0)
                else:
                    hardware_info["gpu"] = "No CUDA GPU available"
            except (ImportError, RuntimeError) as e:
                logging.error("Error getting GPU info: %s", e)

        return hardware_info

    def display_system_info(self) -> None:
        """Display a rich summary of system information."""
        version_info = self.get_version_info()
        hardware_info = self.get_hardware_info()
        cuda_info = self.platform_manager.check_cuda_availability()
        platform_info = f"Platform: {self.platform_manager.platform.title()}"
        long_form_language = self.config.get("longform", {}).get("language", "N/A")

        if HAS_RICH and Panel:
            panel_content = (
                "[bold]Speech-to-Text Orchestrator[/bold]\n\n"
                f"[bold yellow]Control[/bold yellow] the system by clicking "
                f"on the [bold yellow]system tray icon[/bold yellow].\n\n"
                f"[bold yellow]Selected Language:[/bold yellow]\n"
                f"  Long Form: {long_form_language}\n\n"
                f"[bold yellow]Python Versions:[/bold yellow]\n"
                f"  Python: {sys.version.split()[0]}\n"
                f"  PyTorch: {version_info['torch']}\n"
                f"  RealtimeSTT: {version_info['RealtimeSTT']}\n"
                f"  Faster Whisper: {version_info['faster_whisper']}\n"
                f"[bold yellow]Platform & CUDA Info:[/bold yellow]\n"
                f"  {platform_info}\n"
                f"  CUDA Available: {'Yes' if cuda_info['available'] else 'No'}\n"
                f"  CUDA Version: {cuda_info.get('version', 'N/A')}\n"
                f"  GPU Device: {cuda_info.get('device_name', 'N/A')}\n"
                f"  Compute Capability: {cuda_info.get('compute_capability', 'N/A')}\n"
                f"[bold yellow]Hardware:[/bold yellow]\n"
                f"  CPU: {hardware_info.get('cpu', 'N/A')}\n"
                f"  GPU: {hardware_info.get('gpu', 'N/A')}"
            )
            safe_print(
                Panel(panel_content, title="Speech-to-Text System", border_style="green")
            )
            time.sleep(0.1)
        else:
            safe_print("=" * 50)
            safe_print("Speech-to-Text Orchestrator Running")
            safe_print(f"  Selected Language: {long_form_language}")
            safe_print("-" * 50)
            safe_print("Versions:")
            safe_print(f"  PyTorch: {version_info['torch']}")
            safe_print(f"  RealtimeSTT: {version_info['RealtimeSTT']}")
            safe_print(f"  Faster Whisper: {version_info['faster_whisper']}")
            safe_print("-" * 50)
            safe_print("Hardware:")
            safe_print(f"  CPU: {hardware_info.get('cpu', 'N/A')}")
            safe_print(f"  GPU: {hardware_info.get('gpu', 'N/A')}")
            safe_print("=" * 50)
