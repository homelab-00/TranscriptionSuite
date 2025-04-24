#!/usr/bin/env python3
# orchestrator.py
#
# Main controller for the Speech-to-Text system
#
# This script:
# - Imports and integrates the three transcription modules:
#   * Real-time transcription for immediate feedback
#   * Long-form transcription for extended dictation
#   * Static file transcription for pre-recorded audio/video
# - Sets up a TCP server to listen for commands from the AutoHotkey script
# - Manages the state of different transcription modes
# - Provides a clean interface for hotkey-based control
# - Handles command processing and module coordination
# - Implements lazy loading of transcription models
#
# The system is designed to be controlled via the following hotkeys:
# - F2: Toggle real-time transcription on/off
# - F3: Start long-form recording
# - F4: Stop long-form recording and transcribe
# - F10: Run static file transcription
# - F7: Quit application

import os
import sys
import socket
import threading
import time
import logging
from typing import Optional, Dict, Any
import importlib.util
import subprocess
import signal
import atexit
import io
import psutil

# Configure logging to file only (not to console)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("stt_orchestrator.log"),
    ]
)

# Console output with color support
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    console = None

# TCP server settings
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 35000

# Module paths
MODULE_PATHS = {
    "realtime": "realtime_module.py",
    "longform": "longform_module.py",
    "static": "static_module.py"
}

def safe_print(message):
    """Print function that handles I/O errors gracefully."""
    try:
        if HAS_RICH:
            console.print(message)
        else:
            print(message)
    except ValueError as e:
        if "I/O operation on closed file" in str(e):
            pass  # Silently ignore closed file errors
        else:
            # For other ValueErrors, log them
            logging.error(f"Error in safe_print: {e}")

class STTOrchestrator:
    """
    Main orchestrator for the Speech-to-Text system.
    Coordinates between different transcription modes and handles hotkey commands.
    """
    
    def __init__(self):
        """Initialize the orchestrator."""
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(self.script_dir, "config.json")
        self.current_loaded_model_type = None
        
        # Application state
        self.running = False
        self.server_thread = None
        self.current_mode = None  # Can be "realtime", "longform", or "static"
        self.ahk_pid = None

        # Track loaded models
        self.loaded_models = {}

        # Initialize configuration
        self._load_or_create_config()
        
        # Module information - we'll import modules lazily
        self.modules = {}
        self.transcribers = {}
        
        # Register cleanup handler
        atexit.register(self.stop)

    def _load_or_create_config(self):
        """Load configuration from file or create it if it doesn't exist."""
        import json

        # Define default configuration with full model names and English language
        default_config = {
            "realtime": {
                "model": "Systran/faster-whisper-large-v3",
                "language": "en",
                "compute_type": "default",
                "device": "cuda",
                "input_device_index": None,
                "use_default_input": True,
                    # This flag controls whether the application will dynamically detect and use 
                    # the system's current default input device (when set to True) or use a fixed
                    # device specified by input_device_index (when set to False). When True, the 
                    # application will automatically use whichever audio input device is currently 
                    # selected as the default in Windows Sound settings, enabling on-the-fly
                    # device switching without restarting the application.
                "gpu_device_index": 0,
                "silero_sensitivity": 0.4,
                "silero_use_onnx": False,
                "silero_deactivity_detection": False,
                "webrtc_sensitivity": 3,
                "post_speech_silence_duration": 0.6,
                "min_length_of_recording": 1.0,
                "min_gap_between_recordings": 1.0,
                "pre_recording_buffer_duration": 0.2,
                "ensure_sentence_starting_uppercase": True,
                "ensure_sentence_ends_with_period": True,
                "batch_size": 16,
                "beam_size": 5,
                "beam_size_realtime": 3,
                "initial_prompt": None,
                "allowed_latency_limit": 100,
                "early_transcription_on_silence": 0,
                "enable_realtime_transcription": True,
                "realtime_processing_pause": 0.2,
                "realtime_model_type": "tiny.en",
                "realtime_batch_size": 16
            },
            "longform": {
                "model": "Systran/faster-whisper-large-v3",
                "language": "en",
                "compute_type": "default",
                "device": "cuda",
                "input_device_index": None,
                "use_default_input": True,
                "gpu_device_index": 0,
                "silero_sensitivity": 0.4,
                "silero_use_onnx": False,
                "silero_deactivity_detection": False,
                "webrtc_sensitivity": 3,
                "post_speech_silence_duration": 0.6,
                "min_length_of_recording": 1.0,
                "min_gap_between_recordings": 1.0,
                "pre_recording_buffer_duration": 0.2,
                "ensure_sentence_starting_uppercase": True,
                "ensure_sentence_ends_with_period": True,
                "batch_size": 16,
                "beam_size": 5,
                "initial_prompt": None,
                "allowed_latency_limit": 100
            },
            "static": {
                "model": "Systran/faster-whisper-large-v3",
                "language": "en",
                "compute_type": "float16",
                "device": "cuda",
                "gpu_device_index": 0,
                "beam_size": 5,
                "batch_size": 16,
                "vad_aggressiveness": 2
            }
        }

        # Try to load existing config
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    loaded_config = json.load(f)

                    # Update default config with loaded values
                    for module_type in default_config:
                        if module_type in loaded_config:
                            for param, value in loaded_config[module_type].items():
                                if param in default_config[module_type]:
                                    default_config[module_type][param] = value

                    self.config = default_config
                    self.log_info("Configuration loaded from file")
            except Exception as e:
                self.log_error(f"Error loading configuration: {e}")
                self.config = default_config
        else:
            # Use defaults and save to file
            self.config = default_config
            self._save_config()
            self.log_info("Default configuration created")

    def _save_config(self):
        """Save current configuration to file."""
        import json

        # Define a function to fix None values
        def fix_none_values(obj):
            if isinstance(obj, dict):
                return {k: fix_none_values(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [fix_none_values(i) for i in obj]
            elif obj == "":
                return None  # Convert empty strings back to None
            else:
                return obj
        
        # Apply the fix to the config object
        fixed_config = fix_none_values(self.config)

        try:
            with open(self.config_path, 'w') as f:
                json.dump(fixed_config, f, indent=4)
            self.log_info("Configuration saved to file")
        except Exception as e:
            self.log_error(f"Error saving configuration: {e}")

    def _open_config_dialog(self):
        """Open the configuration dialog."""
        safe_print("Opening configuration dialog...")
        
        # Check if any transcription is active
        if self.current_mode:
            safe_print(f"Warning: Transcription in {self.current_mode} mode is active.")
            # We'll still allow opening the dialog, but warn the user
        
        # Import the configuration dialog module
        try:
            # Add the script directory to sys.path if it's not already there
            script_dir = os.path.dirname(os.path.abspath(__file__))
            if script_dir not in sys.path:
                sys.path.append(script_dir)
                
            from configuration_dialog_box_module import ConfigurationDialog
            
            # Create and show the dialog
            dialog = ConfigurationDialog(
                config_path=self.config_path,
                callback=self._config_updated
            )
            
            result = dialog.show_dialog()
            
            # If the user clicked Apply
            if result:
                self.log_info("Configuration dialog closed with Apply")
            else:
                self.log_info("Configuration dialog closed without saving")
                
        except Exception as e:
            self.log_error(f"Error opening configuration dialog: {e}")
            safe_print(f"Error opening configuration dialog: {e}")

    def _config_updated(self, new_config):
        """Handle configuration updates."""
        self.log_info("Configuration updated")
        self.config = new_config
        
        # If any transcribers are active, inform the user about restart
        if self.current_mode:
            safe_print("Configuration updated. Changes will take effect after restarting transcribers.")
        else:
            safe_print("Configuration updated successfully.")

    def import_module_lazily(self, module_name):
        """Import a module only when needed."""
        if module_name in self.modules and self.modules[module_name]:
            return self.modules[module_name]
            
        filepath = os.path.join(self.script_dir, MODULE_PATHS.get(module_name, ""))
        
        try:
            # First check if the file exists
            if not os.path.exists(filepath):
                self.log_error(f"Module file not found: {filepath}")
                return None
                
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None:
                self.log_error(f"Could not find module: {module_name} at {filepath}")
                return None
                
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module  # Add to sys.modules to avoid import errors
            spec.loader.exec_module(module)
            
            # Store the imported module
            self.modules[module_name] = module
            self.log_info(f"Successfully imported module: {module_name}")
            return module
        except Exception as e:
            self.log_error(f"Error importing {module_name} from {filepath}: {e}")
            return None
    
    def initialize_transcriber(self, module_type):
        """Initialize a transcriber only when needed with improved cleanup."""
        # If we already have this transcriber type loaded and ready
        if module_type in self.transcribers and self.transcribers[module_type]:
            self.current_loaded_model_type = module_type
            return self.transcribers[module_type]

        module = self.import_module_lazily(module_type)
        if not module:
            self.log_error(f"Failed to import {module_type} module")
            return None

        try:
            # Get configuration for this module
            module_config = self.config.get(module_type, {})

            # Check if we can reuse an existing model
            current_model_name = module_config.get("model", "Systran/faster-whisper-large-v3")
            preinitialized_model = None

            # Look for an existing model with the same name
            for model_type, model_info in self.loaded_models.items():
                if model_info['name'] == current_model_name:
                    safe_print(f"Reusing already loaded {model_type} model for {module_type}")

                    # Get the model instance from the existing transcriber
                    if model_type == "longform":
                        # For longform transcriber
                        if hasattr(model_info['transcriber'], 'recorder') and model_info['transcriber'].recorder:
                            preinitialized_model = True  # Just a flag that we're reusing

                    elif model_type == "realtime":
                        # For realtime transcriber
                        if hasattr(model_info['transcriber'], 'recorder') and model_info['transcriber'].recorder:
                            preinitialized_model = True  # Just a flag that we're reusing

                    elif model_type == "static":
                        # For static transcriber
                        if hasattr(model_info['transcriber'], 'whisper_model'):
                            preinitialized_model = model_info['transcriber'].whisper_model

                    break

            # Use a different initialization approach for each module type
            if module_type == "realtime":
                safe_print(f"Initializing real-time transcriber...")
                # Force disable real-time preview functionality
                module_config["enable_realtime_transcription"] = False

                # Pass all configuration parameters
                self.transcribers[module_type] = module.LongFormTranscriber(
                    model=module_config.get("model", "Systran/faster-whisper-large-v3"),
                    language=module_config.get("language", "en"),
                    compute_type=module_config.get("compute_type", "default"),
                    device=module_config.get("device", "cuda"),
                    input_device_index=self.get_default_input_device_index() if module_config.get("use_default_input", True) else module_config.get("input_device_index"),
                    gpu_device_index=module_config.get("gpu_device_index", 0),
                    silero_sensitivity=module_config.get("silero_sensitivity", 0.4),
                    silero_use_onnx=module_config.get("silero_use_onnx", False),
                    silero_deactivity_detection=module_config.get("silero_deactivity_detection", False),
                    webrtc_sensitivity=module_config.get("webrtc_sensitivity", 3),
                    post_speech_silence_duration=module_config.get("post_speech_silence_duration", 0.6),
                    min_length_of_recording=module_config.get("min_length_of_recording", 1.0),
                    min_gap_between_recordings=module_config.get("min_gap_between_recordings", 1.0),
                    pre_recording_buffer_duration=module_config.get("pre_recording_buffer_duration", 0.2),
                    ensure_sentence_starting_uppercase=module_config.get("ensure_sentence_starting_uppercase", True),
                    ensure_sentence_ends_with_period=module_config.get("ensure_sentence_ends_with_period", True),
                    batch_size=module_config.get("batch_size", 16),
                    beam_size=module_config.get("beam_size", 5),
                    beam_size_realtime=module_config.get("beam_size_realtime", 3),
                    initial_prompt=module_config.get("initial_prompt"),
                    allowed_latency_limit=module_config.get("allowed_latency_limit", 100),
                    early_transcription_on_silence=module_config.get("early_transcription_on_silence", 0),
                    enable_realtime_transcription=False,
                    realtime_processing_pause=module_config.get("realtime_processing_pause", 0.2),
                    realtime_model_type=module_config.get("realtime_model_type", "tiny.en"),
                    realtime_batch_size=module_config.get("realtime_batch_size", 16),
                    preinitialized_model=preinitialized_model  # Pass the model or flag
                )

            elif module_type == "longform":
                safe_print(f"Initializing long-form transcriber...")
                # Pass all configuration parameters
                self.transcribers[module_type] = module.LongFormTranscriber(
                    model=module_config.get("model", "Systran/faster-whisper-large-v3"),
                    language=module_config.get("language", "en"),
                    compute_type=module_config.get("compute_type", "default"),
                    device=module_config.get("device", "cuda"),
                    input_device_index=self.get_default_input_device_index() if module_config.get("use_default_input", True) else module_config.get("input_device_index"),
                    gpu_device_index=module_config.get("gpu_device_index", 0),
                    silero_sensitivity=module_config.get("silero_sensitivity", 0.4),
                    silero_use_onnx=module_config.get("silero_use_onnx", False),
                    silero_deactivity_detection=module_config.get("silero_deactivity_detection", False),
                    webrtc_sensitivity=module_config.get("webrtc_sensitivity", 3),
                    post_speech_silence_duration=module_config.get("post_speech_silence_duration", 0.6),
                    min_length_of_recording=module_config.get("min_length_of_recording", 1.0),
                    min_gap_between_recordings=module_config.get("min_gap_between_recordings", 1.0),
                    pre_recording_buffer_duration=module_config.get("pre_recording_buffer_duration", 0.2),
                    ensure_sentence_starting_uppercase=module_config.get("ensure_sentence_starting_uppercase", True),
                    ensure_sentence_ends_with_period=module_config.get("ensure_sentence_ends_with_period", True),
                    batch_size=module_config.get("batch_size", 16),
                    beam_size=module_config.get("beam_size", 5),
                    initial_prompt=module_config.get("initial_prompt"),
                    allowed_latency_limit=module_config.get("allowed_latency_limit", 100),
                    preload_model=True,
                    preinitialized_model=preinitialized_model  # Pass the model or flag
                )

            elif module_type == "static":
                safe_print(f"Initializing static file transcriber...")
                self.transcribers[module_type] = module.DirectFileTranscriber(
                    use_tk_mainloop=False,
                    model=module_config.get("model", "Systran/faster-whisper-large-v3"),
                    language=module_config.get("language", "en"),
                    compute_type=module_config.get("compute_type", "float16"),
                    device=module_config.get("device", "cuda"),
                    device_index=module_config.get("gpu_device_index", 0),
                    beam_size=module_config.get("beam_size", 5),
                    batch_size=module_config.get("batch_size", 16),
                    vad_aggressiveness=module_config.get("vad_aggressiveness", 2),
                    preinitialized_model=preinitialized_model  # Pass the actual model instance
                )

            # Store the loaded model information
            if module_type not in self.loaded_models:
                self.loaded_models[module_type] = {
                    'name': current_model_name,
                    'transcriber': self.transcribers[module_type]
                }

            self.log_info(f"{module_type.capitalize()} transcriber initialized successfully")
            self.current_loaded_model_type = module_type  # Update the tracking variable
            return self.transcribers[module_type]

        except Exception as e:
            self.log_error(f"Error initializing {module_type} transcriber: {e}")
            return None
    
    def _unload_current_model(self):
        """Unload the currently loaded model to free up memory more aggressively."""
        if not self.current_loaded_model_type:
            return
            
        try:
            self.log_info(f"Aggressively unloading {self.current_loaded_model_type} model...")
            safe_print(f"Unloading {self.current_loaded_model_type} model...")
            
            if self.current_loaded_model_type in self.transcribers:
                transcriber = self.transcribers[self.current_loaded_model_type]
                
                # Handle different transcribers differently with more aggressive cleanup
                if self.current_loaded_model_type == "realtime":
                    if hasattr(transcriber, 'recorder') and transcriber.recorder:
                        # Call shutdown explicitly to clean up multiprocessing resources
                        try:
                            # Redirect stdout temporarily to suppress messages
                            original_stdout = sys.stdout
                            sys.stdout = io.StringIO()
                            
                            transcriber.recorder.abort()
                            transcriber.recorder.shutdown()
                            
                            # Restore stdout
                            sys.stdout = original_stdout
                        except Exception as e:
                            self.log_error(f"Error during recorder shutdown: {e}")
                    
                elif self.current_loaded_model_type == "longform":
                    if hasattr(transcriber, 'recorder') and transcriber.recorder:
                        # Clean up the recorder properly
                        try:
                            transcriber.recorder.abort()
                            transcriber.recorder.shutdown()
                        except Exception as e:
                            self.log_error(f"Error during recorder shutdown: {e}")
                        transcriber.recorder = None
                    
                elif self.current_loaded_model_type == "static":
                    if hasattr(transcriber, 'whisper_model'):
                        # Explicitly delete the model
                        del transcriber.whisper_model
                        transcriber.whisper_model = None
                
                # Remove from transcribers dictionary to ensure complete cleanup
                self.transcribers[self.current_loaded_model_type] = None
                
                # Remove from loaded_models dictionary
                if self.current_loaded_model_type in self.loaded_models:
                    del self.loaded_models[self.current_loaded_model_type]
                    
                self.log_info(f"Successfully unloaded {self.current_loaded_model_type} model")
            
            # Clear the tracking variable
            self.current_loaded_model_type = None
            
            # Force garbage collection multiple times to ensure memory is freed
            import gc
            gc.collect()
            gc.collect()  # Second collection often helps with circular references
            
            # On CUDA systems, try to release CUDA memory explicitly
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    self.log_info("CUDA cache emptied")
            except ImportError:
                pass
            
        except Exception as e:
            self.log_error(f"Error unloading model: {e}")
    
    def log_info(self, message):
        """Log an info message."""
        logging.info(message)
    
    def log_error(self, message):
        """Log an error message."""
        logging.error(message)

    def get_default_input_device_index(self):
        """Get the index of the default input device."""
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            
            # Get default input device index from PyAudio
            default_index = p.get_default_input_device_info()['index']
            
            device_name = p.get_device_info_by_index(default_index)['name']
            safe_print(f"Using default input device: {device_name} (index: {default_index})")
            
            p.terminate()
            return default_index
        except Exception as e:
            self.log_error(f"Error getting default input device: {e}")
            return None  # Return None to use system default
    
    def start_server(self):
        """Start the TCP server to listen for commands from AutoHotkey."""
        self.running = True
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()
        self.log_info(f"TCP server started on {SERVER_HOST}:{SERVER_PORT}")
    
    def _run_server(self):
        """Run the TCP server loop."""
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            server_socket.bind((SERVER_HOST, SERVER_PORT))
            server_socket.listen(5)
            server_socket.settimeout(1)  # Allow checking self.running every second
            
            while self.running:
                try:
                    client_socket, addr = server_socket.accept()
                    data = client_socket.recv(1024).decode('utf-8').strip()
                    self.log_info(f"Received command: {data}")
                    
                    # Process command
                    self._handle_command(data)
                    
                    client_socket.close()
                except socket.timeout:
                    continue  # Just a timeout, check self.running and continue
                except Exception as e:
                    self.log_error(f"Error handling client connection: {e}")
        except Exception as e:
            self.log_error(f"Server error: {e}")
        finally:
            server_socket.close()
            self.log_info("TCP server stopped")
    
    def _handle_command(self, command):
        """Process commands received from AutoHotkey."""
        try:
            if command == "OPEN_CONFIG":
                self._open_config_dialog()
            elif command == "TOGGLE_REALTIME":
                # Unload current model if it's not realtime
                if self.current_loaded_model_type and self.current_loaded_model_type != "realtime":
                    self._unload_current_model()
                self._toggle_realtime()
            elif command == "START_LONGFORM":
                # Unload current model if it's not longform
                if self.current_loaded_model_type and self.current_loaded_model_type != "longform":
                    self._unload_current_model()
                self._start_longform()
            elif command == "STOP_LONGFORM":
                self._stop_longform()
            elif command == "RUN_STATIC":
                # Unload current model if it's not static
                if self.current_loaded_model_type and self.current_loaded_model_type != "static":
                    self._unload_current_model()
                self._run_static()
            elif command == "QUIT":
                self._quit()
            else:
                self.log_error(f"Unknown command: {command}")
        except Exception as e:
            self.log_error(f"Error handling command {command}: {e}")
    
    def _toggle_realtime(self):
        """Toggle real-time transcription on/off."""
        # Check if another mode is running
        if self.current_mode and self.current_mode != "realtime":
            safe_print(f"Cannot start real-time mode while in {self.current_mode} mode. Please finish the current operation first.")
            return

        if self.current_mode == "realtime":
            # Real-time transcription is already running, so stop it
            safe_print("Stopping real-time transcription...")

            try:
                transcriber = self.transcribers.get("realtime")
                if transcriber:
                    transcriber.running = False
                self.current_mode = None
                
                # Unload the model when turning off real-time mode
                self._unload_current_model()
                
            except Exception as e:
                self.log_error(f"Error stopping real-time transcription: {e}")
        else:
            # Start real-time transcription
            try:
                # Make sure we're using the real-time model
                if self.current_loaded_model_type != "realtime":
                    self._unload_current_model()
                    
                # Initialize the real-time transcriber if not already done
                transcriber = self.initialize_transcriber("realtime")
                if not transcriber:
                    safe_print("Failed to initialize real-time transcriber.")
                    return

                safe_print("Starting real-time transcription...")
                self.current_mode = "realtime"

                # Start real-time transcription in a separate thread
                threading.Thread(target=self._run_realtime, daemon=True).start()
            except Exception as e:
                self.log_error(f"Error starting real-time transcription: {e}")
                self.current_mode = None
    
    def _run_realtime(self):
        """Run real-time transcription in a separate thread."""
        try:
            transcriber = self.transcribers.get("realtime")
            if not transcriber:
                safe_print("Realtime transcriber not available.")
                self.current_mode = None
                return
                
            # Clear any previous text
            transcriber.text_buffer = ""
            
            # Start transcription
            transcriber.start()
            
            self.log_info("Real-time transcription stopped")
            self.current_mode = None
            
        except Exception as e:
            self.log_error(f"Error in _run_realtime: {e}")
            
            # Make sure to clean up properly
            try:
                if "realtime" in self.transcribers and self.transcribers["realtime"]:
                    self.transcribers["realtime"].stop()
            except Exception as cleanup_e:
                self.log_error(f"Error during cleanup: {cleanup_e}")
            
            self.current_mode = None
    
    def _start_longform(self):
        """Start long-form recording."""
        # Check if another mode is running
        if self.current_mode:
            safe_print(f"Cannot start long-form mode while in {self.current_mode} mode. Please finish the current operation first.")
            return
            
        try:
            # Make sure we're using the long-form model
            if self.current_loaded_model_type != "longform":
                self._unload_current_model()
                
            # Initialize the long-form transcriber if not already done
            transcriber = self.initialize_transcriber("longform")
            if not transcriber:
                safe_print("Failed to initialize long-form transcriber.")
                return
                
            safe_print("Starting long-form recording...")
            self.current_mode = "longform"
            transcriber.start_recording()
            
        except Exception as e:
            self.log_error(f"Error starting long-form recording: {e}")
            self.current_mode = None
    
    def _stop_longform(self):
        """Stop long-form recording and transcribe."""
        if self.current_mode != "longform":
            safe_print("No active long-form recording to stop.")
            return
            
        try:
            transcriber = self.transcribers.get("longform")
            if not transcriber:
                safe_print("Long-form transcriber not available.")
                self.current_mode = None
                return
                
            safe_print("Stopping long-form recording and transcribing...")
            transcriber.stop_recording()
            self.current_mode = None
            
        except Exception as e:
            self.log_error(f"Error stopping long-form recording: {e}")
            self.current_mode = None
    
    def _run_static(self):
        """Run static file transcription."""
        # Check if another mode is running
        if self.current_mode:
            safe_print(f"Cannot start static mode while in {self.current_mode} mode. Please finish the current operation first.")
            return
            
        try:
            # Make sure we're using the static model
            if self.current_loaded_model_type != "static":
                self._unload_current_model()
                
            # Initialize the static transcriber if not already done
            transcriber = self.initialize_transcriber("static")
            if not transcriber:
                safe_print("Failed to initialize static transcriber.")
                return
                
            safe_print("Opening file selection dialog...")
            self.current_mode = "static"
            
            # Run in a separate thread to avoid blocking
            threading.Thread(target=self._run_static_thread, daemon=True).start()
            
        except Exception as e:
            self.log_error(f"Error starting static transcription: {e}")
            self.current_mode = None
    
    def _run_static_thread(self):
        """Run static transcription in a separate thread."""
        try:
            transcriber = self.transcribers.get("static")
            if not transcriber:
                safe_print("Static transcriber not available.")
                self.current_mode = None
                return
                
            # Select and process the file
            transcriber.select_file()
            
            # Wait until transcription is complete
            while transcriber.transcribing:
                time.sleep(0.5)
                
            self.log_info("Static file transcription completed")
            self.current_mode = None
            
        except Exception as e:
            self.log_error(f"Error in static transcription: {e}")
            self.current_mode = None
    
    def _quit(self):
        """Stop all processes and exit with improved cleanup."""
        safe_print("Quitting application...")
        
        # Make sure any active mode is stopped first
        if self.current_mode:
            if self.current_mode == "realtime":
                self._toggle_realtime()  # This will stop it if running
            elif self.current_mode == "longform":
                self._stop_longform()
            elif self.current_mode == "static" and hasattr(self.transcribers.get("static", None), 'request_abort'):
                self.transcribers["static"].request_abort()
        
        # Allow time for mode to stop
        time.sleep(0.5)
        
        # Now do the full shutdown
        self.stop()
        
        # Force exit after a short delay to ensure clean shutdown
        time.sleep(0.5)
        os._exit(0)
    
    def _kill_leftover_ahk(self):
        """Kill any existing AHK processes using our script."""
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if (
                    proc.info['name'] == 'AutoHotkeyU64.exe'
                    and proc.info['cmdline'] is not None
                    and "STT_hotkeys.ahk" in ' '.join(proc.info['cmdline'])
                ):
                    self.log_info(f"Killing leftover AHK process with PID={proc.pid}")
                    psutil.Process(proc.pid).kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
    
    def start_ahk_script(self):
        """Start the AutoHotkey script."""
        # First kill any leftover AHK processes
        self._kill_leftover_ahk()
        
        # Record existing AHK PIDs before launching
        pre_pids = set()
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] == 'AutoHotkeyU64.exe':
                    pre_pids.add(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Launch the AHK script
        ahk_path = os.path.join(self.script_dir, "STT_hotkeys.ahk")
        self.log_info("Launching AHK script...")
        subprocess.Popen(
            [ahk_path],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            shell=True
        )

        # Give it a moment to start
        time.sleep(1.0)
        
        # Find the new AHK process
        post_pids = set()
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] == 'AutoHotkeyU64.exe':
                    post_pids.add(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Store the PID of the new process
        new_pids = post_pids - pre_pids
        if len(new_pids) == 1:
            self.ahk_pid = new_pids.pop()
            self.log_info(f"Detected new AHK script PID: {self.ahk_pid}")
        else:
            self.log_info("Could not detect a single new AHK script PID. No PID stored.")
            self.ahk_pid = None
    
    def stop_ahk_script(self):
        """Kill AHK script if we know its PID."""
        if self.ahk_pid is not None:
            self.log_info(f"Killing AHK script with PID={self.ahk_pid}")
            try:
                psutil.Process(self.ahk_pid).kill()
            except Exception as e:
                self.log_error(f"Failed to kill AHK process: {e}")

    def _display_info(self) -> None:
        """Display startup information."""
        if HAS_RICH:
            console.print(Panel(
                "[bold]Speech-to-Text Orchestrator[/bold]\n\n"
                "Control the system using these hotkeys:\n"
                "  [cyan]F1[/cyan]:  Open configuration dialogue box\n"
                "  [cyan]F2[/cyan]:  Toggle real-time transcription\n"
                "  [cyan]F3[/cyan]:  Start long-form recording\n"
                "  [cyan]F4[/cyan]:  Stop long-form recording and transcribe\n"
                "  [cyan]F10[/cyan]: Run static file transcription\n"
                "  [cyan]F7[/cyan]:  Quit application\n\n"
                f"[bold yellow]Selected Languages:[/bold yellow]\n"
                f"  Long Form: {self.config['longform']['language']}\n"
                f"  Real-time: {self.config['realtime']['language']}\n"
                f"  Static: {self.config['static']['language']}",
                title="Speech-to-Text System",
                border_style="green"
            ))
        else:
            safe_print("="*50)
            safe_print("Speech-to-Text Orchestrator Running")
            safe_print("="*50)
            safe_print("Hotkeys:")
            safe_print("  F2: Toggle real-time transcription")
            safe_print("  F3: Start long-form recording")
            safe_print("  F4: Stop long-form recording and transcribe")
            safe_print("  F10: Run static file transcription")
            safe_print("  F7: Quit application")
            safe_print("="*50)
            safe_print("Selected Languages:")
            safe_print(f"  Long Form: {self.config['longform']['language']}")
            safe_print(f"  Real-time: {self.config['realtime']['language']}")
            safe_print(f"  Static: {self.config['static']['language']}")
            safe_print("="*50)

    def run(self):
        """Run the orchestrator."""
        # Start the TCP server
        self.start_server()
        
        # Start the AutoHotkey script
        self.start_ahk_script()
        
        # Pre-load the longform transcription model at startup as requested
        safe_print("Pre-loading the long-form transcription model...")
        longform_transcriber = self.initialize_transcriber("longform")
        if longform_transcriber:
            # Force complete initialization including the AudioToTextRecorder
            if hasattr(longform_transcriber, 'force_initialize'):
                if longform_transcriber.force_initialize():
                    # Set the current loaded model type
                    self.current_loaded_model_type = "longform"
                    # Add to loaded_models dictionary
                    self.loaded_models['longform'] = {
                        'name': self.config['longform']['model'],
                        'transcriber': longform_transcriber
                    }
                    safe_print("Long-form transcription model fully loaded and ready to use.")
        
        # Display startup banner
        self._display_info()
        
        # Keep the main thread running
        try:
            while self.running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            safe_print("\nKeyboard interrupt received, shutting down...")
        except Exception as e:
            self.log_error(f"Error in main loop: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """Stop all processes and clean up with improved resource handling."""
        try:
            if not self.running:
                return

            self.log_info("Beginning graceful shutdown sequence...")
            self.running = False

            # First, stop any active transcription mode
            try:
                if self.current_mode == "longform" and "longform" in self.transcribers:
                    safe_print("Stopping longform transcription...")
                    # Add a try-except block around stopping
                    try:
                        self.transcribers["longform"].stop()
                    except Exception as e:
                        self.log_error(f"Error stopping longform transcription: {e}")
                    # Give it a moment to finish cleanup
                    time.sleep(0.5)
                
                if self.current_mode == "realtime" and "realtime" in self.transcribers:
                    safe_print("Stopping realtime transcription...")
                    # Add a try-except block around stopping
                    try:
                        self.transcribers["realtime"].stop()
                    except Exception as e:
                        self.log_error(f"Error stopping realtime transcription: {e}")
                    # Give it a moment to finish cleanup
                    time.sleep(0.5)
                    
                if self.current_mode == "static" and "static" in self.transcribers:
                    safe_print("Stopping static transcription...")
                    # Add a try-except block around stopping
                    try:
                        self.transcribers["static"].stop()
                    except Exception as e:
                        self.log_error(f"Error stopping static transcription: {e}")
                    # Give it a moment to finish cleanup
                    time.sleep(0.5)
            
            except Exception as e:
                self.log_error(f"Error stopping active mode: {e}")

            # Explicitly unload any active model
            if self.current_loaded_model_type:
                self._unload_current_model()
                time.sleep(0.5)  # Give it time to release resources

            # Stop the AutoHotkey script
            self.stop_ahk_script()

            # Only try to join the server thread if we're not currently in it
            current_thread_id = threading.get_ident()
            server_thread_id = self.server_thread.ident if self.server_thread else None

            try:
                if (self.server_thread and self.server_thread.is_alive() and 
                    current_thread_id != server_thread_id):
                    self.server_thread.join(timeout=2)
            except Exception as e:
                self.log_error(f"Error joining server thread: {e}")

            # Clean up any remaining resources
            for module_type, transcriber in list(self.transcribers.items()):
                try:
                    if transcriber is not None:
                        safe_print(f"Final cleanup of {module_type} transcriber...")
                        
                        if module_type == "realtime":
                            if hasattr(transcriber, 'stop'):
                                transcriber.stop()
                        
                        elif module_type == "longform":
                            if hasattr(transcriber, 'clean_up'):
                                transcriber.clean_up()
                        
                        elif module_type == "static":
                            if hasattr(transcriber, 'cleanup'):
                                transcriber.cleanup()
                        
                        # Remove the reference
                        self.transcribers[module_type] = None
                except Exception as e:
                    self.log_error(f"Error during final cleanup of {module_type} transcriber: {e}")

            # Final garbage collection
            try:
                import gc
                gc.collect()
                gc.collect()
                
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

            self.log_info("Orchestrator stopped successfully")

        except Exception as e:
            self.log_error(f"Error during shutdown: {e}")

if __name__ == "__main__":
    orchestrator = STTOrchestrator()
    orchestrator.run()