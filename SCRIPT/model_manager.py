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
import os
import sys
import logging
import gc
import importlib.util

from utils import safe_print
from platform_utils import get_platform_manager
from recorder import LongFormRecorder

# Try to import optional dependencies at module level
try:
    import pyaudio

    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False
    pyaudio = None

try:
    import torch

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    torch = None


class ModelManager:
    """
    Manages transcription models for different speech-to-text modes.
    Handles initialization, reuse, and cleanup of models to optimize resource usage.
    """

    def __init__(self, config_dict, script_dir):
        """Initialize the model manager with configuration dictionary."""
        self.config = config_dict
        self.script_dir = script_dir
        # The manager now only creates instances on demand and doesn't hold state.
        self.transcribers = {}
        self.modules = {}
        self.platform_manager = get_platform_manager()

    def get_audio_devices(self):
        """Get available audio input devices with cross-platform compatibility."""
        devices = []

        if not HAS_PYAUDIO or pyaudio is None:
            self._log_warning("PyAudio not available for device enumeration")
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
                            device_entry = {
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
                        self._log_warning(f"Could not get info for audio device {i}: {e}")
                        continue

                p.terminate()

            # Sort devices - default device first, then by name
            devices.sort(key=lambda x: (not x["is_default"], x["name"]))

            self._log_info(f"Found {len(devices)} audio input devices")
            return devices

        except Exception as e:
            self._log_error(f"Error enumerating audio devices: {e}")
            return devices

    def _get_optimal_device(self, module_config):
        """Get optimal device configuration with fallback."""
        requested_device = module_config.get("device", "cuda")
        cuda_info = self.platform_manager.check_cuda_availability()

        if requested_device == "cuda" and not cuda_info["available"]:
            self._log_info("CUDA requested but not available, falling back to CPU")
            safe_print("CUDA not available, using CPU", "warning")
            return "cpu"

        return requested_device

    def _get_optimal_compute_type(self, module_config, device):
        """Get optimal compute type based on device and platform."""
        if device == "cpu":
            return "float32"  # CPU doesn't support float16 efficiently

        requested_type = module_config.get("compute_type", "default")
        if requested_type == "default":
            return self.platform_manager.get_optimal_device_config()["compute_type"]

        return requested_type

    def import_module_lazily(self, module_name):
        """Import a module only when needed."""
        if module_name in self.modules and self.modules[module_name]:
            return self.modules[module_name]

        module_paths = {
            "longform": "longform_module.py",
        }

        filepath = os.path.join(self.script_dir, module_paths.get(module_name, ""))

        try:
            if not os.path.exists(filepath):
                self._log_error("Module file not found: %s", filepath)
                return None

            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                self._log_error("Could not find module: %s at %s", module_name, filepath)
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            self.modules[module_name] = module
            self._log_info("Successfully imported module: %s", module_name)
            return module
        except (ImportError, AttributeError, OSError) as e:
            self._log_error("Error importing %s from %s: %s", module_name, filepath, e)
            return None

    def _resolve_input_device_index(self, module_config, fallback=None):
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

    def get_default_input_device_index(self):
        """Get the index of the default input device with better error handling."""
        if not HAS_PYAUDIO or pyaudio is None:
            self._log_error("PyAudio not available")
            return None

        suppress_ctx = getattr(self.platform_manager, "suppress_audio_warnings", None)

        try:
            with suppress_ctx() if suppress_ctx else contextlib.nullcontext():
                p = pyaudio.PyAudio()

                # Get default input device info
                default_device_info = p.get_default_input_device_info()
                default_index = default_device_info["index"]
                device_name = default_device_info["name"]

                # Ensure we have a valid integer index
                if not isinstance(default_index, (int, float)):
                    self._log_warning(f"Invalid device index type: {type(default_index)}")
                    p.terminate()
                    return None

                default_index = int(default_index)

                # Verify the device actually works by testing it
                try:
                    stream = p.open(
                        format=pyaudio.paInt16,
                        channels=1,
                        rate=16000,
                        input=True,
                        input_device_index=default_index,
                        frames_per_buffer=1024,
                    )
                    stream.close()

                    safe_print(
                        f"Using default input device: {device_name} "
                        f"(index: {default_index})",
                        "info",
                    )

                except (OSError, ValueError) as e:
                    self._log_warning(f"Default device {device_name} not accessible: {e}")
                    # Try to find an alternative working device
                    devices = self.get_audio_devices()
                    for device in devices:
                        try:
                            stream = p.open(
                                format=pyaudio.paInt16,
                                channels=1,
                                rate=16000,
                                input=True,
                                input_device_index=device["index"],
                                frames_per_buffer=1024,
                            )
                            stream.close()
                            safe_print(
                                f"Using alternative device: {device['name']}", "info"
                            )
                            p.terminate()
                            return device["index"]
                        except (OSError, ValueError) as e:
                            self._log_warning(
                                f"Default device {device_name} not accessible: {e}"
                            )
                            continue

                    # If no devices work, return None
                    self._log_error("No working audio input devices found")
                    p.terminate()
                    return None

                p.terminate()
                return default_index

        except Exception as e:
            self._log_error(f"Error getting default input device: {e}")
            return None

    def _create_longform_recorder(self, module_config, callbacks):
        """Initialize longform transcriber with configuration."""
        safe_print("Initializing long-form recorder...", "info")

        # Get device and compute type
        device = self._get_optimal_device(module_config)
        compute_type = self._get_optimal_compute_type(module_config, device)

        resolved_input_index = self._resolve_input_device_index(module_config)

        # Combine base config with dynamic callbacks
        recorder_params = {
            "model": module_config.get("model", "Systran/faster-whisper-large-v3"),
            "language": module_config.get("language", "en"),
            "compute_type": compute_type,
            "device": device,
            "input_device_index": resolved_input_index,
            "gpu_device_index": module_config.get("gpu_device_index", 0),
            "batch_size": module_config.get("batch_size", 16),
            "silero_sensitivity": module_config.get("silero_sensitivity", 0.4),
            "silero_use_onnx": module_config.get("silero_use_onnx", False),
            "post_speech_silence_duration": module_config.get(
                "post_speech_silence_duration", 0.6
            ),
            "min_length_of_recording": module_config.get("min_length_of_recording", 1.0),
            "beam_size": module_config.get("beam_size", 5),
            "initial_prompt": module_config.get("initial_prompt"),
            "faster_whisper_vad_filter": module_config.get(
                "faster_whisper_vad_filter", True
            ),
        }
        recorder_params.update(callbacks)

        return LongFormRecorder(**recorder_params)

    def initialize_transcriber(self, module_type: str, extra_args: dict | None = None):
        """Initialize a transcriber only when needed with improved cleanup."""
        if module_type != "longform":
            self._log_error("Unknown module type requested: %s", module_type)
            return None

        if extra_args is None:
            extra_args = {}

        try:
            # Get configuration for this module
            module_config = self.config.get(module_type, {})

            recorder = self._create_longform_recorder(module_config, extra_args)
            self._log_info(
                "%s recorder initialized successfully", module_type.capitalize()
            )
            return recorder

        except (ImportError, AttributeError, ValueError, OSError) as e:
            self._log_error("Error initializing %s recorder: %s", module_type, e)
            return None

    def cleanup_all_models(self):
        """
        Properly clean up models. This is now handled by the recorder's own
        clean_up method, but we can add extra cleanup here if needed.
        """
        # Final garbage collection
        try:
            gc.collect()
            gc.collect()

            if HAS_TORCH and torch is not None and torch.cuda.is_available():
                torch.cuda.empty_cache()
        except (AttributeError, ImportError):
            pass

        self._log_info("All models cleaned up")

    def _log_info(self, message, *args):
        """Log an info message."""
        logging.info(message, *args)

    def _log_warning(self, message, *args):
        """Log a warning message."""
        logging.warning(message, *args)

    def _log_error(self, message, *args):
        """Log an error message."""
        logging.error(message, *args)
