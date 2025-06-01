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

import os
import sys
import io
import logging
import time
import gc
import importlib.util

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

    def import_module_lazily(self, module_name):
        """Import a module only when needed."""
        if module_name in self.modules and self.modules[module_name]:
            return self.modules[module_name]

        module_paths = {
            "realtime": "realtime_module.py",
            "longform": "longform_module.py",
            "static": "static_module.py",
        }

        filepath = os.path.join(
            self.script_dir, module_paths.get(module_name, "")
        )

        try:
            # First check if the file exists
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
            sys.modules[module_name] = (
                module  # Add to sys.modules to avoid import errors
            )
            spec.loader.exec_module(module)

            # Store the imported module
            self.modules[module_name] = module
            self._log_info("Successfully imported module: %s", module_name)
            return module
        except (ImportError, AttributeError, OSError) as e:
            self._log_error(
                "Error importing %s from %s: %s", module_name, filepath, e
            )
            return None

    def get_default_input_device_index(self):
        """Get the index of the default input device."""
        if not HAS_PYAUDIO or pyaudio is None:
            self._log_error("PyAudio not available")
            return None

        try:
            p = pyaudio.PyAudio()

            # Get default input device index from PyAudio
            default_index = p.get_default_input_device_info()["index"]

            device_name = p.get_device_info_by_index(int(default_index))["name"]
            safe_print(
                f"Using default input device: {device_name} (index: {default_index})",
                "info",
            )

            p.terminate()
            return default_index
        except (OSError, IOError) as e:
            self._log_error("Error getting default input device: %s", e)
            return None  # Return None to use system default

    def _get_reusable_model(self, current_model_name):
        """Get a reusable model if available."""
        for model_type, model_info in self.loaded_models.items():
            if model_info["name"] == current_model_name:
                safe_print(
                    f"Reusing already loaded {model_type} model",
                    "success",
                )
                return self._extract_model_from_transcriber(
                    model_info, model_type
                )
        return None

    def _extract_model_from_transcriber(self, model_info, model_type):
        """Extract model from existing transcriber based on type."""
        transcriber = model_info["transcriber"]

        if model_type in ("longform", "realtime"):
            if hasattr(transcriber, "recorder") and transcriber.recorder:
                return True  # Flag that we're reusing
        elif model_type == "static":
            if hasattr(transcriber, "whisper_model"):
                return transcriber.whisper_model
        return None

    def _initialize_realtime_transcriber(
        self, module, module_config, preinitialized_model
    ):
        """Initialize realtime transcriber with configuration."""
        safe_print("Initializing real-time transcriber...", "info")
        # Force disable real-time preview functionality
        module_config["enable_realtime_transcription"] = False

        return module.LongFormTranscriber(
            model=module_config.get("model", "Systran/faster-whisper-large-v3"),
            language=module_config.get("language", "en"),
            compute_type=module_config.get("compute_type", "default"),
            device=module_config.get("device", "cuda"),
            input_device_index=(
                self.get_default_input_device_index()
                if module_config.get("use_default_input", True)
                else module_config.get("input_device_index")
            ),
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
            beam_size_realtime=module_config.get("beam_size_realtime", 3),
            initial_prompt=module_config.get("initial_prompt"),
            allowed_latency_limit=module_config.get(
                "allowed_latency_limit", 100
            ),
            early_transcription_on_silence=module_config.get(
                "early_transcription_on_silence", 0
            ),
            enable_realtime_transcription=False,
            realtime_processing_pause=module_config.get(
                "realtime_processing_pause", 0.2
            ),
            realtime_model_type=module_config.get(
                "realtime_model_type", "tiny.en"
            ),
            realtime_batch_size=module_config.get("realtime_batch_size", 16),
            preinitialized_model=preinitialized_model,
        )

    def _initialize_longform_transcriber(
        self, module, module_config, preinitialized_model
    ):
        """Initialize longform transcriber with configuration."""
        safe_print("Initializing long-form transcriber...", "info")

        return module.LongFormTranscriber(
            model=module_config.get("model", "Systran/faster-whisper-large-v3"),
            language=module_config.get("language", "en"),
            compute_type=module_config.get("compute_type", "default"),
            device=module_config.get("device", "cuda"),
            input_device_index=(
                self.get_default_input_device_index()
                if module_config.get("use_default_input", True)
                else module_config.get("input_device_index")
            ),
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
            preload_model=True,
            preinitialized_model=preinitialized_model,
        )

    def _initialize_static_transcriber(
        self, module, module_config, preinitialized_model
    ):
        """Initialize static transcriber with configuration."""
        safe_print("Initializing static file transcriber...", "info")

        return module.DirectFileTranscriber(
            use_tk_mainloop=False,
            model=module_config.get("model", "Systran/faster-whisper-large-v3"),
            language=module_config.get("language", "en"),
            compute_type=module_config.get("compute_type", "float16"),
            device=module_config.get("device", "cuda"),
            device_index=module_config.get("gpu_device_index", 0),
            beam_size=module_config.get("beam_size", 5),
            batch_size=module_config.get("batch_size", 16),
            vad_aggressiveness=module_config.get("vad_aggressiveness", 2),
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
            preinitialized_model = self._get_reusable_model(current_model_name)

            # Initialize based on module type
            transcriber_initializers = {
                "realtime": self._initialize_realtime_transcriber,
                "longform": self._initialize_longform_transcriber,
                "static": self._initialize_static_transcriber,
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

    def can_reuse_model(self, target_mode):
        """Check if we can reuse the currently loaded model for the target mode."""
        if not self.current_loaded_model_type:
            return False

        current_model = self.config[self.current_loaded_model_type].get("model")
        target_model = self.config[target_mode].get("model")

        if current_model == target_model:
            self._log_info(
                "Can reuse %s model for %s (both using %s)",
                self.current_loaded_model_type,
                target_mode,
                current_model,
            )
            return True

        return False

    def _cleanup_recorder(self, transcriber):
        """Clean up recorder resources."""
        if hasattr(transcriber, "recorder") and transcriber.recorder:
            try:
                # Redirect stdout temporarily to suppress messages
                original_stdout = sys.stdout
                sys.stdout = io.StringIO()

                transcriber.recorder.abort()
                transcriber.recorder.shutdown()

                # Restore stdout
                sys.stdout = original_stdout
            except (AttributeError, OSError) as e:
                self._log_error("Error during recorder shutdown: %s", e)

    def unload_current_model(self):
        """Unload the currently loaded model to free up memory more aggressively."""
        if not self.current_loaded_model_type:
            return

        try:
            self._log_info(
                "Aggressively unloading %s model...",
                self.current_loaded_model_type,
            )
            safe_print(
                f"Unloading {self.current_loaded_model_type} model...", "info"
            )

            if self.current_loaded_model_type in self.transcribers:
                transcriber = self.transcribers[self.current_loaded_model_type]

                # Handle different transcribers differently with more aggressive cleanup
                if self.current_loaded_model_type == "realtime":
                    self._cleanup_recorder(transcriber)

                elif self.current_loaded_model_type == "longform":
                    self._cleanup_recorder(transcriber)
                    if hasattr(transcriber, "recorder"):
                        transcriber.recorder = None

                elif self.current_loaded_model_type == "static":
                    if hasattr(transcriber, "whisper_model"):
                        # Explicitly delete the model
                        del transcriber.whisper_model
                        transcriber.whisper_model = None

                # Remove from transcribers dictionary to ensure complete cleanup
                self.transcribers[self.current_loaded_model_type] = None

                # Remove from loaded_models dictionary
                if self.current_loaded_model_type in self.loaded_models:
                    del self.loaded_models[self.current_loaded_model_type]

                self._log_info(
                    "Successfully unloaded %s model",
                    self.current_loaded_model_type,
                )

            # Clear the tracking variable
            self.current_loaded_model_type = None

            # Force garbage collection multiple times to ensure memory is freed
            gc.collect()
            gc.collect()  # Second collection often helps with circular references

            # On CUDA systems, try to release CUDA memory explicitly
            if HAS_TORCH and torch is not None and torch.cuda.is_available():
                torch.cuda.empty_cache()
                self._log_info("CUDA cache emptied")

        except (AttributeError, OSError) as e:
            self._log_error("Error unloading model: %s", e)

    def cleanup_all_models(self):
        """Properly clean up all loaded models and transcribers."""
        # First, try to unload the current model
        if self.current_loaded_model_type:
            self.unload_current_model()
            time.sleep(0.5)  # Give it time to release resources

        # Clean up any remaining resources
        for module_type, transcriber in list(self.transcribers.items()):
            try:
                if transcriber is not None:
                    safe_print(
                        f"Final cleanup of {module_type} transcriber...", "info"
                    )

                    if module_type == "realtime":
                        if hasattr(transcriber, "stop"):
                            transcriber.stop()

                    elif module_type == "longform":
                        if hasattr(transcriber, "clean_up"):
                            transcriber.clean_up()

                    elif module_type == "static":
                        if hasattr(transcriber, "cleanup"):
                            transcriber.cleanup()

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

    def _log_error(self, message, *args):
        """Log an error message."""
        logging.error(message, *args)
