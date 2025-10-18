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
from typing import Optional

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

    def initialize_transcriber(
        self,
        config_section: str,
        callbacks: dict | None = None,
        use_microphone: bool = False,
    ) -> Optional[LongFormRecorder]:
        """Initialize a transcriber with an override for microphone usage."""
        if callbacks is None:
            callbacks = {}

        try:
            module_config = self.config.get(config_section, {})
            if not module_config:
                self._log_error("Config section '%s' not found.", config_section)
                return None

            # Add the microphone override to the config for this instance
            instance_config = module_config.copy()
            instance_config["use_microphone"] = use_microphone

            # If using microphone, resolve the device index from the global audio config
            if use_microphone:
                audio_config = self.config.get("audio", {})
                if audio_config.get("use_default_input", True):
                    device_index = self.get_default_input_device_index()
                else:
                    device_index = audio_config.get("input_device_index")
                instance_config["input_device_index"] = device_index

            recorder = LongFormRecorder(config=instance_config, **callbacks)
            self._log_info("%s recorder initialized successfully", config_section)
            return recorder

        except (ImportError, AttributeError, ValueError, OSError) as e:
            self._log_error(
                "Error initializing %s recorder: %s", config_section, e, exc_info=True
            )
            return None

    def get_default_input_device_index(self):
        """Get the index of the default input device."""
        if not HAS_PYAUDIO or pyaudio is None:
            return None

        suppress_ctx = getattr(self.platform_manager, "suppress_audio_warnings", None)
        context_manager = suppress_ctx() if suppress_ctx else contextlib.nullcontext()

        try:
            with context_manager:
                p = pyaudio.PyAudio()
                try:
                    info = p.get_default_input_device_info()
                    return info["index"]
                finally:
                    p.terminate()
        except Exception as e:
            self._log_error("Could not get default audio device: %s", e)
            return None

    def cleanup_all_models(self):
        """Clean up models and GPU memory."""
        gc.collect()
        if HAS_TORCH and torch and torch.cuda.is_available():
            torch.cuda.empty_cache()
        self._log_info("All models cleaned up")

    def _log_info(self, message, *args):
        logging.info(message, *args)

    def _log_warning(self, message, *args):
        logging.warning(message, *args)

    def _log_error(self, message, *args, **kwargs):
        logging.error(message, *args, **kwargs)
