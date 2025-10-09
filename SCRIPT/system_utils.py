#!/usr/bin/env python3
"""
System utility functions for the Speech-to-Text system.

This module:
- Provides hardware and version information detection
- Manages configuration loading and saving
- Contains utility functions for system interactions
"""

import copy
import json
import logging
import os
import platform
import re
import subprocess
import sys
import time
from importlib.metadata import version as metadata_version, PackageNotFoundError
from typing import Dict, Any
from platform_utils import get_platform_manager

# Optional import for process management
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    psutil = None

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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("stt_orchestrator.log"),
    ],
)

# Try to import Rich for prettier console output
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.live import Live

    CONSOLE = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    CONSOLE = None
    Panel = None
    Live = None

def safe_print(message, style="default"):
    """Print function that handles I/O errors gracefully with optional styling."""
    try:
        if HAS_RICH and CONSOLE is not None:
            if style == "error":
                CONSOLE.print(f"[bold red]{message}[/bold red]")
            elif style == "warning":
                CONSOLE.print(f"[bold yellow]{message}[/bold yellow]")
            elif style == "success":
                CONSOLE.print(f"[bold green]{message}[/bold green]")
            elif style == "info":
                CONSOLE.print(f"[bold blue]{message}[/bold blue]")
            else:
                CONSOLE.print(message)
        else:
            print(message)
    except ValueError as exception:
        if "I/O operation on closed file" in str(exception):
            pass  # Silently ignore closed file errors
        else:
            # For other ValueErrors, log them
            logging.error("Error in safe_print: %s", exception)


class SystemUtils:
    """Utilities for system interaction and configuration management."""

    def __init__(self, config_path: str):
        """Initialize with configuration file path."""
        self.config_path = config_path
        self.config = {}
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.platform_manager = get_platform_manager()

    def load_or_create_config(self) -> Dict[str, Any]:
        """Load configuration from file or create it if it doesn't exist."""
        # Define default configuration with full model names and English language
        default_config = {
            "longform": {
                "model": "Systran/faster-whisper-large-v3",
                "language": "en",
                "compute_type": "default",
                "device": self.platform_manager.get_optimal_device_config()["device"],
                "input_device_index": None,
                "use_default_input": True,
                "gpu_device_index": 0,
                "silero_sensitivity": 0.4,
                "silero_use_onnx": False,
                "silero_deactivity_detection": False,
                "webtrtc_sensitivity": 3,
                "post_speech_silence_duration": 0.6,
                "min_length_of_recording": 1.0,
                "min_gap_between_recordings": 1.0,
                "pre_recording_buffer_duration": 0.2,
                "ensure_sentence_starting_uppercase": True,
                "ensure_sentence_ends_with_period": True,
                "batch_size": 16,
                "beam_size": 5,
                "initial_prompt": None,
                "allowed_latency_limit": 100,
                "faster_whisper_vad_filter": True,
            },
            "realtime_preview": {
                "model": "deepdml/faster-whisper-large-v3-turbo-ct2",
                "realtime_model_type": "Systran/faster-whisper-base",
                "language": "en",
                "compute_type": "default",
                "device": self.platform_manager.get_optimal_device_config()["device"],
                "input_device_index": None,
                "use_default_input": True,
                "gpu_device_index": 0,
                "silero_sensitivity": 0.4,
                "silero_use_onnx": True,
                "silero_deactivity_detection": True,
                "webrtc_sensitivity": 3,
                "post_speech_silence_duration": 0.6,
                "min_length_of_recording": 1.0,
                "min_gap_between_recordings": 1.0,
                "pre_recording_buffer_duration": 0.2,
                "batch_size": 16,
                "realtime_batch_size": 16,
                "beam_size": 5,
                "beam_size_realtime": 3,
                "enable_realtime_transcription": True,
                "use_main_model_for_realtime": False,
                "realtime_processing_pause": 0.2,
                "faster_whisper_vad_filter": False,
            },
        }

        # Ensure config directory exists
        config_dir = self.platform_manager.get_config_dir()
        if not os.path.isabs(self.config_path):
            self.config_path = config_dir / "config.json"

        # Try to load existing config
        if os.path.exists(self.config_path):
            try:
                with open(
                    self.config_path, "r", encoding="utf-8"
                ) as config_file:
                    loaded_config = json.load(config_file)

                    # Update default config with loaded values
                    for module_type, module_defaults in default_config.items():
                        if module_type in loaded_config:
                            for param, value in loaded_config[
                                module_type
                            ].items():
                                if param in module_defaults:
                                    module_defaults[param] = value

                    self.config = default_config
                    logging.info("Configuration loaded from file")
            except (json.JSONDecodeError, OSError) as exception:
                logging.error("Error loading configuration: %s", exception)
                self.config = default_config
        else:
            # Use defaults and save to file
            self.config = default_config
            self.save_config()
            logging.info("Default configuration created")

        return self.config

    def save_config(self) -> bool:
        """Save the current configuration to a file."""

        # Define a function to fix None values
        def fix_none_values(obj):
            if isinstance(obj, dict):
                return {k: fix_none_values(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [fix_none_values(i) for i in obj]
            if obj == "":
                return None  # Convert empty strings back to None
            return obj

        try:
            # Apply the fix to the config object
            fixed_config = fix_none_values(self.config)

            with open(self.config_path, "w", encoding="utf-8") as config_file:
                json.dump(fixed_config, config_file, indent=4)

            logging.info("Configuration saved to file")
            return True
        except (OSError, TypeError) as exception:
            logging.error("Error saving configuration: %s", exception)
            return False

    def _convert_input_value(self, original_value: Any, raw_value: str) -> Any:
        """Convert a user-entered string to the type of the original value."""
        if raw_value.lower() == "none":
            return None

        if isinstance(original_value, bool):
            return raw_value.strip().lower() in {"1", "true", "yes", "y"}

        if isinstance(original_value, int) and not isinstance(original_value, bool):
            try:
                return int(raw_value)
            except ValueError:
                safe_print("Invalid integer. Keeping previous value.", "warning")
                return original_value

        if isinstance(original_value, float):
            try:
                return float(raw_value)
            except ValueError:
                safe_print("Invalid float. Keeping previous value.", "warning")
                return original_value

        if isinstance(original_value, (list, dict)):
            try:
                return json.loads(raw_value)
            except json.JSONDecodeError:
                safe_print("Invalid JSON. Keeping previous value.", "warning")
                return original_value

        return raw_value

    def open_config_dialog(self, config_updated_callback=None):
        """Open an interactive terminal-based configuration editor."""
        safe_print("Opening configuration editor...", "info")

        try:
            current_config = self.load_or_create_config()
        except Exception as exception:
            logging.error("Failed to load configuration: %s", exception)
            safe_print("Failed to load configuration.", "error")
            return False

        if not isinstance(current_config, dict) or not current_config:
            safe_print("Configuration is empty or invalid.", "error")
            return False

        editable_config = copy.deepcopy(current_config)
        changes_made = False

        try:
            while True:
                sections = ", ".join(editable_config.keys())
                safe_print(f"Available sections: {sections}")
                safe_print("Press Enter to finish editing or type 'cancel' to abort.", "info")
                section = input("Section to edit: ").strip()

                if section == "":
                    break

                if section.lower() == "cancel":
                    safe_print("Configuration editing cancelled.", "warning")
                    return False

                if section not in editable_config:
                    safe_print(f"Unknown section '{section}'.", "warning")
                    continue

                section_config = editable_config[section]
                if not isinstance(section_config, dict):
                    safe_print(f"Section '{section}' is not editable.", "warning")
                    continue

                while True:
                    safe_print(
                        "Press Enter to return to section selection or type 'cancel' to abort.",
                        "info",
                    )
                    for key, value in section_config.items():
                        safe_print(f"  {key}: {value!r}")

                    parameter = input("Parameter to edit: ").strip()

                    if parameter == "":
                        break

                    if parameter.lower() == "cancel":
                        safe_print("Configuration editing cancelled.", "warning")
                        return False

                    if parameter not in section_config:
                        safe_print(f"Unknown parameter '{parameter}'.", "warning")
                        continue

                    current_value = section_config[parameter]
                    prompt = (
                        f"New value for '{parameter}' (current {current_value!r}). "
                        "Leave blank to keep current value: "
                    )
                    raw_value = input(prompt).strip()

                    if raw_value == "":
                        safe_print("No changes made.", "info")
                        continue

                    new_value = self._convert_input_value(current_value, raw_value)
                    section_config[parameter] = new_value
                    safe_print(
                        f"Updated {section}.{parameter} -> {new_value!r}", "success"
                    )
                    changes_made = True

        except (EOFError, KeyboardInterrupt):
            safe_print("Configuration editing interrupted.", "warning")
            return False

        if not changes_made:
            safe_print("No configuration changes to save.", "info")
            return False

        self.config = editable_config

        if not self.save_config():
            safe_print("Failed to save configuration.", "error")
            return False

        safe_print("Configuration saved.", "success")

        if config_updated_callback:
            config_updated_callback(copy.deepcopy(self.config))

        return True

    def get_version_info(self) -> Dict[str, Dict[str, Any]]:
        """Get version information for key dependencies and check for updates."""
        version_info = {}

        # Create a data structure to hold both current version and update info
        # Format: {"package_name": {"current": "version", "update": "newer_version or None"}}

        # Get PyTorch version
        if TORCH_AVAILABLE and torch is not None:
            version_info["torch"] = {
                "current": torch.__version__,
                "update": None,
            }
        else:
            version_info["torch"] = {"current": "Not installed", "update": None}

        # Get RealtimeSTT version
        try:
            realtime_version = metadata_version("realtimestt")
            version_info["RealtimeSTT"] = {
                "current": realtime_version,
                "update": None,
            }
        except PackageNotFoundError:
            version_info["RealtimeSTT"] = {
                "current": "Not installed",
                "update": None,
            }

        # Get Faster Whisper version
        if FASTER_WHISPER_AVAILABLE and faster_whisper is not None:
            faster_whisper_ver = getattr(
                faster_whisper, "__version__", "Unknown"
            )
            version_info["faster_whisper"] = {
                "current": faster_whisper_ver,
                "update": None,
            }
        else:
            version_info["faster_whisper"] = {
                "current": "Not installed",
                "update": None,
            }

        # Check for updates using pip list --outdated (only if we can run subprocess)
        try:
            # Run pip list --outdated to get update info in JSON format
            result = subprocess.run(
                ["pip", "list", "--outdated", "--format=json"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,  # Add timeout to prevent hanging
            )
            if result.returncode == 0:
                try:
                    outdated_packages = json.loads(result.stdout)
                    for package_info in outdated_packages:
                        package_name = package_info.get("name", "").lower()
                        latest_version = package_info.get("latest_version", "")

                        logging.info(
                            "Found update for %s: %s",
                            package_name,
                            latest_version,
                        )

                        # Update the version info dict with update info
                        self._update_package_version_info(
                            version_info, package_name, latest_version
                        )
                except json.JSONDecodeError:
                    logging.error(
                        "Error parsing JSON from pip list --outdated: %s",
                        result.stdout,
                    )
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as exception:
            logging.error("Error checking for updates: %s", exception)

        return version_info

    def _update_package_version_info(
        self, version_info, package_name, latest_version
    ):
        """Helper method to update package version info."""
        if package_name == "torch" and "torch" in version_info:
            version_info["torch"]["update"] = latest_version
        elif package_name == "realtimestt" and "RealtimeSTT" in version_info:
            version_info["RealtimeSTT"]["update"] = latest_version
        elif (
            package_name == "faster-whisper"
            and "faster_whisper" in version_info
        ):
            version_info["faster_whisper"]["update"] = latest_version

    def get_cuda_info(self) -> Dict[str, str]:
        """Get CUDA and CUDNN version information from system PATH."""
        cuda_info = {"cuda": "Not found", "cudnn": "Not found"}

        try:
            # Get CUDA version from PATH
            cuda_info["cuda"] = self._find_cuda_version_in_path()

            # If not found in PATH, try nvcc
            if cuda_info["cuda"] == "Not found":
                cuda_info["cuda"] = self._find_cuda_version_with_nvcc()

            # Get CUDNN version from PATH
            cuda_info["cudnn"] = self._find_cudnn_version_in_path()

        except (OSError, AttributeError) as exception:
            logging.error("Error getting CUDA/CUDNN info: %s", exception)

        return cuda_info

    def _find_cuda_version_in_path(self) -> str:
        """Find CUDA version in system PATH."""
        system_path = os.environ.get("PATH", "")
        path_entries = system_path.split(os.pathsep)

        cuda_patterns = [
            r"CUDA\\v(\d+\.\d+)",
            r"CUDA\\(\d+\.\d+)",
            r"cuda(\d+\.\d+)",
            r"cuda-(\d+\.\d+)",
        ]

        for path_entry in path_entries:
            for pattern in cuda_patterns:
                cuda_match = re.search(pattern, path_entry, re.IGNORECASE)
                if cuda_match:
                    version_str = cuda_match.group(1)
                    logging.info(
                        "Found CUDA version %s in PATH: %s",
                        version_str,
                        path_entry,
                    )
                    return version_str

        return "Not found"

    def _find_cuda_version_with_nvcc(self) -> str:
        """Find CUDA version using nvcc command."""
        try:
            result = subprocess.run(
                ["nvcc", "--version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if result.returncode == 0:
                match = re.search(r"release (\d+\.\d+)", result.stdout)
                if match:
                    version_str = match.group(1)
                    logging.info(
                        "Found CUDA version %s using nvcc", version_str
                    )
                    return version_str
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as exception:
            logging.error("Error getting CUDA version from nvcc: %s", exception)

        return "Not found"

    def _find_cudnn_version_in_path(self) -> str:
        """Find CUDNN version in system PATH."""
        system_path = os.environ.get("PATH", "")
        path_entries = system_path.split(os.pathsep)

        cudnn_patterns = [
            r"CUDNN\\v(\d+\.\d+)",
            r"cudnn(\d+\.\d+)",
            r"cudnn-(\d+\.\d+)",
            r"cudnn_(\d+\.\d+)",
        ]

        for path_entry in path_entries:
            for pattern in cudnn_patterns:
                cudnn_match = re.search(pattern, path_entry, re.IGNORECASE)
                if cudnn_match:
                    version_str = cudnn_match.group(1)
                    logging.info(
                        "Found CUDNN version %s in PATH: %s",
                        version_str,
                        path_entry,
                    )
                    return version_str

        return "Not found"

    def get_hardware_info(self) -> Dict[str, str]:
        """Get basic CPU and GPU information."""
        hardware_info = {}

        # Get CPU info
        try:
            hardware_info["cpu"] = platform.processor()
            if not hardware_info["cpu"]:
                hardware_info["cpu"] = self._get_detailed_cpu_info()
        except (OSError, subprocess.SubprocessError) as exception:
            hardware_info["cpu"] = "Unknown"
            logging.error("Error getting CPU info: %s", exception)

        # Get GPU info
        if TORCH_AVAILABLE and torch is not None:
            try:
                if torch.cuda.is_available():
                    hardware_info["gpu"] = torch.cuda.get_device_name(0)
                else:
                    hardware_info["gpu"] = "No CUDA GPU available"
            except (ImportError, RuntimeError) as exception:
                hardware_info["gpu"] = "Unknown"
                logging.error("Error getting GPU info: %s", exception)
        else:
            hardware_info["gpu"] = "PyTorch not available"

        return hardware_info

    def _get_detailed_cpu_info(self) -> str:
        """Get detailed CPU information when platform.processor() fails."""
        if self.platform_manager.is_windows:  # Windows
            try:
                result = (
                    subprocess.check_output("wmic cpu get name", shell=True, timeout=5)
                    .decode()
                    .strip()
                    .split("\n")
                )
                if len(result) > 1:
                    return result[1].strip()
            except (subprocess.SubprocessError, subprocess.TimeoutExpired, UnicodeDecodeError):
                pass
        else:  # Linux/Mac
            try:
                with open("/proc/cpuinfo", "r", encoding="utf-8") as cpu_file:
                    for line in cpu_file:
                        if line.startswith("model name"):
                            return line.split(":")[1].strip()
            except (OSError, IndexError):
                pass
        return "Unknown"

    def display_system_info(self) -> None:
        """Display system information including versions and hardware."""
        # Get version information
        version_info = self.get_version_info()

        # Get hardware information
        hardware_info = self.get_hardware_info()

        # Get enhanced CUDA information and platform info
        cuda_info_old = self.get_cuda_info()  # Keep the old method for CUDA toolkit detection
        cuda_info = self.platform_manager.check_cuda_availability()
        platform_info = f"Platform: {self.platform_manager.platform.title()}"

        # Helper function to format version with update marker
        def format_version(package):
            version = version_info[package]
            current = version["current"]
            update = version["update"]

            if update:
                if HAS_RICH:
                    return f"{current} [bold red][UPDATE AVAILABLE: {update}][/bold red]"
                return f"{current} [!] (update: {update})"
            return current

        # Display startup banner
        if HAS_RICH and Panel is not None and Live is not None:
            panel_content = (
                "[bold]Speech-to-Text Orchestrator[/bold]\n\n"
                f"[bold yellow]Control[/bold yellow] the system by clicking "
                f"on the [bold yellow]system tray icon[/bold yellow].\n\n"
                f"[bold yellow]Selected Languages:[/bold yellow]\n"
                f"  Long Form: {self.config.get('longform', {}).get('language', 'N/A')}\n"
                f"  RT Preview: {self.config.get('realtime_preview', {}).get('language', 'N/A')}\n"
                f"  RT Preview (Mini): {self.config.get('realtime_preview', {}).get('language', 'N/A')}\n\n"
                f"[bold yellow]Python Versions:[/bold yellow]\n"
                f"  Python: {sys.version.split()[0]}\n"
                f"  PyTorch: {format_version('torch')}\n"
                f"  RealtimeSTT: {format_version('RealtimeSTT')}\n"
                f"  Faster Whisper: {format_version('faster_whisper')}\n"
                f"[bold yellow]Platform & CUDA Info:[/bold yellow]\n"
                f"  {platform_info}\n"
                f"  CUDA Available: {'Yes' if cuda_info['available'] else 'No'}\n"
                f"  CUDA Version: {cuda_info.get('version', 'N/A')}\n"
                f"  GPU Device: {cuda_info.get('device_name', 'N/A')}\n"
                f"  Compute Capability: {cuda_info.get('compute_capability', 'N/A')}\n"
                f"[bold yellow]Hardware:[/bold yellow]\n"
                f"  CPU: {hardware_info['cpu']}\n"
                f"  GPU: {hardware_info['gpu']}"
            )

            info_panel = Panel(
                panel_content,
                title="Speech-to-Text System",
                border_style="green",
            )
            with Live(info_panel, console=CONSOLE, auto_refresh=False) as live:
                live.update(info_panel)
                # Brief pause to ensure proper display
                time.sleep(0.1)
        else:
            safe_print("=" * 50)
            safe_print("Speech-to-Text Orchestrator Running")
            safe_print("=" * 50)
            safe_print("Hotkeys:")
            safe_print("  F1: Open configuration dialogue box")
            safe_print("  F2: Toggle real-time transcription")
            safe_print("  F3: Start long-form recording")
            safe_print("  F4: Stop long-form recording and transcribe")
            safe_print("  F10: Run static file transcription")
            safe_print("  F7: Quit application")
            safe_print("=" * 50)
            safe_print("Selected Language:")
            safe_print(f"  Long Form: {self.config.get('longform', {}).get('language', 'N/A')}")
            safe_print("=" * 50)
            safe_print("Versions:")
            safe_print(f"  PyTorch: {format_version('torch')}")
            safe_print(f"  RealtimeSTT: {format_version('RealtimeSTT')}")
            safe_print(f"  Faster Whisper: {format_version('faster_whisper')}")
            safe_print(f"  CUDA Toolkit: {cuda_info_old['cuda']}")
            safe_print(f"  CUDNN: {cuda_info_old['cudnn']}")
            safe_print("=" * 50)
            safe_print("Hardware:")
            safe_print(f"  CPU: {hardware_info['cpu']}")
            safe_print(f"  GPU: {hardware_info['gpu']}")
            safe_print("=" * 50)