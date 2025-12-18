#!/usr/bin/env python3
"""
Model Manager for Speech-to-Text System.

Handles model loading, unloading, and reuse for the Speech-to-Text system.
This module:
- Manages the initialization of transcription models
- Handles efficient model reuse between different transcription modes
- Ensures proper cleanup of model resources when switching modes
- Provides a clean interface for model interaction
"""

import contextlib
import importlib.util
import logging
import os
import sys
from types import ModuleType
from typing import Any, Callable, Dict, Optional, TypedDict, Union

from MAIN.platform_utils import (
    HAS_PYAUDIO,
    get_platform_manager,
    pyaudio,
)
from MAIN.recorder import LongFormRecorder
from MAIN.shared.utils import clear_gpu_cache, safe_print


# Typed structure for audio device metadata
class AudioDeviceInfo(TypedDict):
    index: int
    name: str
    channels: int
    sample_rate: float
    is_default: bool


class ModelManager:
    """
    Manages transcription models for different speech-to-text modes.
    Handles initialization, reuse, and cleanup of models to optimize resource usage.
    """

    def __init__(self, config_dict: dict[str, Any], script_dir: str) -> None:
        """Initialize the model manager with configuration dictionary."""
        self.config = config_dict
        self.script_dir = script_dir
        # The manager now only creates instances on demand and doesn't hold state.
        self.transcribers: dict[str, LongFormRecorder] = {}
        self.modules: dict[str, ModuleType] = {}
        self.platform_manager = get_platform_manager()

    def get_audio_devices(self) -> list[AudioDeviceInfo]:
        """Get available audio input devices with cross-platform compatibility."""
        devices: list[AudioDeviceInfo] = []

        if not HAS_PYAUDIO or pyaudio is None:
            logging.warning("PyAudio not available for device enumeration")
            return devices

        suppress_ctx = getattr(self.platform_manager, "suppress_audio_warnings", None)

        try:
            with suppress_ctx() if suppress_ctx else contextlib.nullcontext():
                p = pyaudio.PyAudio()

                # Get device count
                device_count = p.get_device_count()

                for i in range(device_count):
                    try:
                        device_info = p.get_device_info_by_index(i)

                        # Robust type checking for maxInputChannels
                        max_input_channels = device_info.get("maxInputChannels", 0)
                        if not isinstance(max_input_channels, (int, float)):
                            continue

                        # Only include input devices
                        if max_input_channels > 0:
                            device_entry: AudioDeviceInfo = {
                                "index": i,
                                "name": str(device_info.get("name", f"Device {i}")),
                                "channels": int(max_input_channels),
                                "sample_rate": float(
                                    device_info.get("defaultSampleRate", 44100)
                                ),
                                "is_default": i
                                == p.get_default_input_device_info()["index"],
                            }
                            devices.append(device_entry)

                    except (OSError, ValueError, TypeError) as e:
                        logging.warning(f"Could not get info for audio device {i}: {e}")
                        continue

                p.terminate()

            # Sort devices - default device first, then by name
            devices.sort(key=lambda x: (not x["is_default"], x["name"]))

            logging.info(f"Found {len(devices)} audio input devices")
            return devices

        except Exception as e:
            logging.error(f"Error enumerating audio devices: {e}")
            return devices

    def _get_optimal_device(self, module_config: dict[str, Any]) -> str:
        """Get optimal device configuration with fallback."""
        requested_device = module_config.get("device", "cuda")
        cuda_info = self.platform_manager.check_cuda_availability()

        if requested_device == "cuda" and not cuda_info["available"]:
            logging.info("CUDA requested but not available, falling back to CPU")
            safe_print("CUDA not available, using CPU", "warning")
            return "cpu"

        return requested_device

    def _get_optimal_compute_type(
        self, module_config: dict[str, Any], device: str
    ) -> str:
        """Get optimal compute type based on device and platform."""
        if device == "cpu":
            return "float32"  # CPU doesn't support float16 efficiently

        requested_type = module_config.get("compute_type", "default")
        if requested_type == "default":
            return self.platform_manager.get_optimal_device_config()["compute_type"]

        return requested_type

    def import_module_lazily(self, module_name: str) -> Optional[ModuleType]:
        """Import a module only when needed."""
        if module_name in self.modules and self.modules[module_name]:
            return self.modules[module_name]

        module_paths: dict[str, str] = {
            "longform": "longform_module.py",
        }

        filepath = os.path.join(self.script_dir, module_paths.get(module_name, ""))

        try:
            if not os.path.exists(filepath):
                logging.error("Module file not found: %s", filepath)
                return None

            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                logging.error("Could not find module: %s at %s", module_name, filepath)
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            self.modules[module_name] = module
            logging.info("Successfully imported module: %s", module_name)
            return module
        except (ImportError, AttributeError, OSError) as e:
            logging.error("Error importing %s from %s: %s", module_name, filepath, e)
            return None

    def _resolve_input_device_index(
        self, module_config: dict[str, Any], fallback: Optional[int] = None
    ) -> Optional[int]:
        """Resolve the audio input device index honoring default-device flags."""
        use_default = module_config.get("use_default_input", True)

        if use_default:
            default_index = self.get_default_input_device_index()
            if default_index is not None:
                return default_index
            return fallback  # Fallback if default cannot be found

        explicit_index = module_config.get("input_device_index")
        if explicit_index is not None:
            return explicit_index

        return fallback

    def get_default_input_device_index(self) -> Optional[int]:
        """Get the index of the default input device with better error handling."""
        if not HAS_PYAUDIO or pyaudio is None:
            logging.error("PyAudio not available")
            return None

        suppress_ctx = getattr(self.platform_manager, "suppress_audio_warnings", None)
        context_manager = suppress_ctx() if suppress_ctx else contextlib.nullcontext()

        try:
            with context_manager:
                p = pyaudio.PyAudio()

                try:
                    default_device_info = p.get_default_input_device_info()
                    default_index = int(default_device_info["index"])
                    device_name = default_device_info["name"]
                    safe_print(
                        f"Using default input device: {device_name} "
                        f"(index: {default_index})",
                        "info",
                    )

                    p.terminate()
                    return default_index
                except (OSError, KeyError, ValueError) as e:
                    logging.warning(f"Could not get default input device: {e}")
                    p.terminate()
                    return None

        except Exception as e:
            logging.error(f"Error getting default input device: {e}")
            return None

    def initialize_transcriber(
        self,
        config_data: Union[str, Dict[str, Any]],
        instance_name: str,
        callbacks: Optional[Dict[str, Callable[..., Any]]] = None,
        use_microphone: bool = False,
    ) -> Optional[LongFormRecorder]:
        """Initialize a transcriber with an override for microphone usage."""
        callback_map: Dict[str, Callable[..., Any]] = (
            callbacks if callbacks is not None else {}
        )

        try:
            # Get configuration for this module
            module_config: Dict[str, Any]
            config_name: str
            if isinstance(config_data, str):
                config_name = config_data
                module_config = self.config.get(config_data, {})
            else:
                config_name = "custom"
                module_config = config_data

            if not module_config:
                logging.error("Config section '%s' not found.", config_name)
                return None

            # Add the microphone override to the config for this instance
            instance_config = module_config.copy()
            instance_config["use_microphone"] = use_microphone

            # If using microphone, resolve the device index from the global audio config
            if use_microphone:
                audio_config: dict[str, Any] = self.config.get("audio", {})
                if audio_config.get("use_default_input", True):
                    device_index = self.get_default_input_device_index()
                else:
                    device_index = audio_config.get("input_device_index")
                instance_config["input_device_index"] = device_index

            # Pass the specific config section to the recorder
            recorder = LongFormRecorder(
                config=instance_config, instance_name=instance_name, **callback_map
            )

            logging.info("%s recorder initialized successfully", config_name)
            return recorder

        except Exception as e:
            logging.error(
                "Error initializing recorder: %s",
                e,
                exc_info=True,
            )
            return None

    def cleanup_all_models(self) -> None:
        """
        Properly clean up models. This is now handled by the recorder's own
        clean_up method, but we can add extra cleanup here if needed.
        """
        # Use shared GPU cache clearing utility
        clear_gpu_cache()
        logging.info("All models cleaned up")
