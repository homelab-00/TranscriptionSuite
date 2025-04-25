#!/usr/bin/env python3
# model_manager.py
#
# Handles model loading, unloading, and reuse for the Speech-to-Text system
#
# This module:
# - Manages the initialization of transcription models
# - Handles efficient model reuse between different transcription modes
# - Ensures proper cleanup of model resources when switching modes
# - Provides a clean interface for model interaction

import os
import sys
import time
import gc
from typing import Optional, Dict, Any

# Import from utility module
from utils import (
    safe_print, setup_logging, force_gc_collect, get_default_input_device_index,
    run_in_thread, HAS_RICH, console, STTConstants
)

# Setup logging
logger = setup_logging(log_file="stt_orchestrator.log")

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
            "static": "static_module.py"
        }
        
        filepath = os.path.join(self.script_dir, module_paths.get(module_name, ""))
        
        try:
            # First check if the file exists
            if not os.path.exists(filepath):
                self._log_error(f"Module file not found: {filepath}")
                return None
                
            import importlib.util
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None:
                self._log_error(f"Could not find module: {module_name} at {filepath}")
                return None
                
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module  # Add to sys.modules to avoid import errors
            spec.loader.exec_module(module)
            
            # Store the imported module
            self.modules[module_name] = module
            self._log_info(f"Successfully imported module: {module_name}")
            return module
        except Exception as e:
            self._log_error(f"Error importing {module_name} from {filepath}: {e}")
            return None
    
    def get_default_input_device_index(self):
        """Get the index of the default input device."""
        return get_default_input_device_index()
    
    def initialize_transcriber(self, module_type):
        """Initialize a transcriber only when needed with improved cleanup."""
        # If we already have this transcriber type loaded and ready
        if module_type in self.transcribers and self.transcribers[module_type]:
            self.current_loaded_model_type = module_type
            return self.transcribers[module_type]

        module = self.import_module_lazily(module_type)
        if not module:
            self._log_error(f"Failed to import {module_type} module")
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
                    safe_print(f"Reusing already loaded {model_type} model for {module_type}", "success")

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
                safe_print(f"Initializing real-time transcriber...", "info")
                # Initialize with the refactored class name
                self.transcribers[module_type] = module.RealtimeTranscriber(
                    model=module_config.get("model", "Systran/faster-whisper-large-v3"),
                    language=module_config.get("language", "en"),
                    # Add other parameters from module_config...
                    preinitialized_model=preinitialized_model
                )

            elif module_type == "longform":
                safe_print(f"Initializing long-form transcriber...", "info")
                # Initialize with the refactored class name
                self.transcribers[module_type] = module.LongFormTranscriber(
                    model=module_config.get("model", "Systran/faster-whisper-large-v3"),
                    language=module_config.get("language", "en"),
                    # Add other parameters from module_config...
                    preinitialized_model=preinitialized_model
                )

            elif module_type == "static":
                safe_print(f"Initializing static file transcriber...", "info")
                # Initialize with the refactored class name
                self.transcribers[module_type] = module.StaticTranscriber(
                    model=module_config.get("model", "Systran/faster-whisper-large-v3"),
                    language=module_config.get("language", "en"),
                    # Add other parameters from module_config...
                    preinitialized_model=preinitialized_model
                )

            # Store the loaded model information
            if module_type not in self.loaded_models:
                self.loaded_models[module_type] = {
                    'name': current_model_name,
                    'transcriber': self.transcribers[module_type]
                }

            self._log_info(f"{module_type.capitalize()} transcriber initialized successfully")
            self.current_loaded_model_type = module_type  # Update the tracking variable
            return self.transcribers[module_type]

        except Exception as e:
            self._log_error(f"Error initializing {module_type} transcriber: {e}")
            return None
   
    def can_reuse_model(self, target_mode):
        """Check if we can reuse the currently loaded model for the target mode."""
        if not self.current_loaded_model_type:
            return False
        
        current_model = self.config[self.current_loaded_model_type].get("model")
        target_model = self.config[target_mode].get("model")
        
        if current_model == target_model:
            self._log_info(f"Can reuse {self.current_loaded_model_type} model for {target_mode} (both using {current_model})")
            return True
        
        return False
    
    def unload_current_model(self):
        """Unload the currently loaded model to free up memory more aggressively."""
        if not self.current_loaded_model_type:
            return
            
        try:
            self._log_info(f"Aggressively unloading {self.current_loaded_model_type} model...")
            safe_print(f"Unloading {self.current_loaded_model_type} model...", "info")
            
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
                            self._log_error(f"Error during recorder shutdown: {e}")
                    
                elif self.current_loaded_model_type == "longform":
                    if hasattr(transcriber, 'recorder') and transcriber.recorder:
                        # Clean up the recorder properly
                        try:
                            transcriber.recorder.abort()
                            transcriber.recorder.shutdown()
                        except Exception as e:
                            self._log_error(f"Error during recorder shutdown: {e}")
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
                    
                self._log_info(f"Successfully unloaded {self.current_loaded_model_type} model")
            
            # Clear the tracking variable
            self.current_loaded_model_type = None
            
            # Force garbage collection
            force_gc_collect()
            self._log_info("Memory cleaned up via force_gc_collect")
            
        except Exception as e:
            self._log_error(f"Error unloading model: {e}")
    
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
                    safe_print(f"Final cleanup of {module_type} transcriber...", "info")
                    
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
                self._log_error(f"Error during final cleanup of {module_type} transcriber: {e}")

        # Force garbage collection
        force_gc_collect()
        
        self._log_info("All models cleaned up")
        
    def _log_info(self, message):
        """Log an info message."""
        logging.info(message)
    
    def _log_error(self, message):
        """Log an error message."""
        logging.error(message)