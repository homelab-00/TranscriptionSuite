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
import io
import logging
import time
import gc
import importlib.util
from platform_utils import get_platform_manager

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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("stt_orchestrator.log"),
    ],
)

# Try to import Rich for console output with color support
try:
    from rich.console import Console

    CONSOLE = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    CONSOLE = None


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
    except ValueError as e:
        if "I/O operation on closed file" in str(e):
            pass  # Silently ignore closed file errors
        else:
            # For other ValueErrors, log them
            logging.error("Error in safe_print: %s", e)


class ModelManager:
    """
    Manages transcription models for different speech-to-text modes.
    Handles initialization, reuse, and cleanup of models to optimize resource usage.
    """

    def __init__(self, config_dict, script_dir):
        """Initialize the model manager with configuration dictionary."""
        self.config = config_dict
        self.script_dir = script_dir
        self.current_loaded_model_type = None
        self.loaded_models = {}
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
                        max_input_channels = device_info.get('maxInputChannels', 0)
                        if not isinstance(max_input_channels, (int, float)):
                            continue

                        # Only include input devices
                        if max_input_channels > 0:
                            device_entry = {
                                'index': i,
                                'name': str(device_info.get('name', f'Device {i}')),
                                'channels': int(max_input_channels),
                                'sample_rate': float(device_info.get('defaultSampleRate', 44100)),
                                'is_default': i == p.get_default_input_device_info()['index']
                            }
                            devices.append(device_entry)

                    except (OSError, ValueError, TypeError) as e:
                        self._log_warning(f"Could not get info for audio device {i}: {e}")
                        continue

                p.terminate()

            # Sort devices - default device first, then by name
            devices.sort(key=lambda x: (not x['is_default'], x['name']))

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

        filepath = os.path.join(
            self.script_dir, module_paths.get(module_name, "")
        )

        try:
            if not os.path.exists(filepath):
                self._log_error("Module file not found: %s", filepath)
                return None

            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                self._log_error(
                    "Could not find module: %s at %s", module_name, filepath
                )
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            self.modules[module_name] = module
            self._log_info("Successfully imported module: %s", module_name)
            return module
        except (ImportError, AttributeError, OSError) as e:
            self._log_error(
                "Error importing %s from %s: %s", module_name, filepath, e
            )
            return None

    def _resolve_input_device_index(self, module_config, fallback=None):
        """Resolve the audio input device index honoring default-device flags."""
        use_default = module_config.get("use_default_input", True)
 
        if use_default:
            default_index = self.get_default_input_device_index()
            if default_index is not None:
                return default_index
            return fallback # Fallback if default cannot be found

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
                        frames_per_buffer=1024
                    )
                    stream.close()

                    safe_print(
                        f"Using default input device: {device_name} (index: {default_index})",
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
                                input_device_index=device['index'],
                                frames_per_buffer=1024
                            )
                            stream.close()
                            safe_print(f"Using alternative device: {device['name']}", "info")
                            p.terminate()
                            return device['index']
                        except:
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

    def _initialize_longform_transcriber(
        self, module, module_config, preinitialized_model
    ):
        """Initialize longform transcriber with configuration."""
        safe_print("Initializing long-form transcriber...", "info")

        # Get device and compute type
        device = self._get_optimal_device(module_config)
        compute_type = self._get_optimal_compute_type(module_config, device)

        resolved_input_index = self._resolve_input_device_index(module_config)

        return module.LongFormTranscriber(
            model=module_config.get("model", "Systran/faster-whisper-large-v3"),
            language=module_config.get("language", "en"),
            compute_type=compute_type,
            device=device,
            input_device_index=resolved_input_index,
            gpu_device_index=module_config.get("gpu_device_index", 0),
            silero_sensitivity=module_config.get("silero_sensitivity", 0.4),
            silero_use_onnx=module_config.get("silero_use_onnx", False),
            silero_deactivity_detection=module_config.get(
                "silero_deactivity_detection", False
            ),
            webrtc_sensitivity=module_config.get("webrtc_sensitivity", 3),
            post_speech_silence_duration=module_config.get(
                "post_speech_silence_duration", 0.6
            ),
            min_length_of_recording=module_config.get(
                "min_length_of_recording", 1.0
            ),
            min_gap_between_recordings=module_config.get(
                "min_gap_between_recordings", 1.0
            ),
            pre_recording_buffer_duration=module_config.get(
                "pre_recording_buffer_duration", 0.2
            ),
            ensure_sentence_starting_uppercase=module_config.get(
                "ensure_sentence_starting_uppercase", True
            ),
            ensure_sentence_ends_with_period=module_config.get(
                "ensure_sentence_ends_with_period", True
            ),
            batch_size=module_config.get("batch_size", 16),
            beam_size=module_config.get("beam_size", 5),
            initial_prompt=module_config.get("initial_prompt"),
            allowed_latency_limit=module_config.get(
                "allowed_latency_limit", 100
            ),
            faster_whisper_vad_filter=module_config.get(
                "faster_whisper_vad_filter", True
            ),
            preinitialized_model=preinitialized_model,
        )

    def initialize_transcriber(self, module_type):
        """Initialize a transcriber only when needed with improved cleanup."""
        # If we already have this transcriber type loaded and ready
        if module_type in self.transcribers and self.transcribers[module_type]:
            self.current_loaded_model_type = module_type
            return self.transcribers[module_type]

        module = self.import_module_lazily(module_type)
        if not module:
            self._log_error("Failed to import %s module", module_type)
            return None

        try:
            # Get configuration for this module
            module_config = self.config.get(module_type, {})

            # Check if we can reuse an existing model
            current_model_name = module_config.get(
                "model", "Systran/faster-whisper-large-v3"
            )
            preinitialized_model = None # No reuse logic anymore

            # Initialize based on module type
            transcriber_initializers = {
                "longform": self._initialize_longform_transcriber,
            }

            if module_type in transcriber_initializers:
                self.transcribers[module_type] = transcriber_initializers[
                    module_type
                ](module, module_config, preinitialized_model)
            else:
                raise ValueError(f"Unknown module type: {module_type}")

            # Store the loaded model information
            if module_type not in self.loaded_models:
                self.loaded_models[module_type] = {
                    "name": current_model_name,
                    "transcriber": self.transcribers[module_type],
                }

            self._log_info(
                "%s transcriber initialized successfully",
                module_type.capitalize(),
            )
            self.current_loaded_model_type = module_type
            return self.transcribers[module_type]

        except (ImportError, AttributeError, ValueError, OSError) as e:
            self._log_error(
                "Error initializing %s transcriber: %s", module_type, e
            )
            return None

    def _cleanup_recorder(self, transcriber):
        """Clean up recorder resources."""
        if hasattr(transcriber, "recorder") and transcriber.recorder:
            original_stdout = sys.stdout
            try:
                # Redirect stdout temporarily to suppress messages
                sys.stdout = io.StringIO()

                # Prefer the transcriber-level abort which has timeout handling
                if hasattr(transcriber, "abort"):
                    ok = False
                    try:
                        ok = bool(transcriber.abort())
                    except Exception as e:
                        self._log_warning("transcriber.abort() raised: %s", e)
                    if not ok:
                        # Fallback to direct recorder shutdown
                        try:
                            transcriber.recorder.abort()
                        except Exception:
                            pass
                        try:
                            transcriber.recorder.shutdown()
                        except Exception:
                            pass
                else:
                    # Legacy path: call recorder abort/shutdown directly
                    try:
                        transcriber.recorder.abort()
                    except Exception:
                        pass
                    try:
                        transcriber.recorder.shutdown()
                    except Exception:
                        pass
            except (AttributeError, OSError) as e:
                self._log_error("Error during recorder shutdown: %s", e)
            finally:
                # Restore stdout
                sys.stdout = original_stdout

    def cleanup_all_models(self):
        """Properly clean up all loaded models and transcribers."""
        # Now we only ever have one primary transcriber: longform
        longform_transcriber = self.transcribers.get("longform")
        if longform_transcriber:
            safe_print("Cleaning up long-form transcriber...", "info")
            if hasattr(longform_transcriber, "clean_up"):
                longform_transcriber.clean_up()
            self.transcribers["longform"] = None

        # Clean up any other remaining resources just in case
        for module_type, transcriber in list(self.transcribers.items()):
            try:
                if transcriber is not None:
                    safe_print(
                        f"Final cleanup of {module_type} transcriber...", "info"
                    )

                    if module_type == "longform":
                        if hasattr(transcriber, "clean_up"):
                            transcriber.clean_up()

                    # Remove the reference
                    self.transcribers[module_type] = None
            except (AttributeError, OSError) as e:
                self._log_error(
                    "Error during final cleanup of %s transcriber: %s",
                    module_type,
                    e,
                )

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