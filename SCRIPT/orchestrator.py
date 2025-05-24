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
# - F1: Open configuration dialog box
# - F2: Toggle real-time transcription on/off
# - F3: Start long-form recording
# - F4: Stop long-form recording and transcribe
# - F10: Run static file transcription
# - F7: Quit application

import os
import threading
import time
import logging
import atexit

# Configure logging to file only (not to console)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("stt_orchestrator.log"),
    ]
)

# Import the sub-modules we've created
from model_manager import ModelManager, safe_print
from command_server import CommandServer
from system_utils import SystemUtils

# Try to import Rich for prettier console output
try:
    from rich.console import Console
    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    console = None

# TCP server settings
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 35000

class STTOrchestrator:
    """
    Main orchestrator for the Speech-to-Text system.
    Coordinates between different transcription modes and handles hotkey commands.
    """
    
    def __init__(self):
        """Initialize the orchestrator."""
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(self.script_dir, "config.json")
        
        # Application state
        self.running = False
        self.current_mode = None  # Can be "realtime", "longform", or "static"

        # Initialize system utilities
        self.system_utils = SystemUtils(self.config_path)
        
        # Initialize configuration
        self.config = self.system_utils.load_or_create_config()
        
        # Initialize model manager
        self.model_manager = ModelManager(self.config, self.script_dir)
        
        # Initialize command server
        self.command_server = CommandServer(SERVER_HOST, SERVER_PORT)
        
        # Register command handlers
        self._register_command_handlers()
        
        # Register cleanup handler
        atexit.register(self.stop)

    def _register_command_handlers(self):
        """Register handlers for different commands."""
        handlers = {
            "OPEN_CONFIG": self._open_config_dialog,
            "TOGGLE_REALTIME": self._toggle_realtime,
            "START_LONGFORM": self._start_longform,
            "STOP_LONGFORM": self._stop_longform,
            "RUN_STATIC": self._run_static,
            "QUIT": self._quit
        }
        self.command_server.register_handlers(handlers)
    
    def _config_updated(self, new_config):
        """Handle configuration updates."""
        logging.info("Configuration updated")
        self.config = new_config
        self.model_manager.config = new_config
        
        # If any transcribers are active, inform the user about restart
        if self.current_mode:
            safe_print("Configuration updated. Changes will take effect after restarting transcribers.")
        else:
            safe_print("Configuration updated successfully.")
    
    def _open_config_dialog(self):
        """Open the configuration dialog."""
        # Check if any transcription is active
        if self.current_mode:
            safe_print(f"Warning: Transcription in {self.current_mode} mode is active.")
            # We'll still allow opening the dialog, but warn the user
        
        # Open the dialog using system utilities
        self.system_utils.open_config_dialog(self._config_updated)
    
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
                transcriber = self.model_manager.transcribers.get("realtime")
                if transcriber:
                    transcriber.running = False
                self.current_mode = None
                
                # Unload the model when turning off real-time mode
                self.model_manager.unload_current_model()
                
            except Exception as e:
                logging.error(f"Error stopping real-time transcription: {e}")
        else:
            # Start real-time transcription
            try:
                # Check if we can reuse the current model
                if not self.model_manager.can_reuse_model("realtime"):
                    # Make sure we're using the real-time model
                    if self.model_manager.current_loaded_model_type != "realtime":
                        self.model_manager.unload_current_model()
                else:
                    safe_print(f"Reusing {self.model_manager.current_loaded_model_type} model for realtime", "success")
                    
                # Initialize the real-time transcriber if not already done
                transcriber = self.model_manager.initialize_transcriber("realtime")
                if not transcriber:
                    safe_print("Failed to initialize real-time transcriber.", "error")
                    return

                safe_print("Starting real-time transcription...", "success")
                self.current_mode = "realtime"

                # Start real-time transcription in a separate thread
                threading.Thread(target=self._run_realtime, daemon=True).start()
            except Exception as e:
                logging.error(f"Error starting real-time transcription: {e}")
                self.current_mode = None
    
    def _run_realtime(self):
        """Run real-time transcription in a separate thread."""
        try:
            transcriber = self.model_manager.transcribers.get("realtime")
            if not transcriber:
                safe_print("Realtime transcriber not available.", "error")
                self.current_mode = None
                return
                
            # Clear any previous text
            transcriber.text_buffer = ""
            
            # Start transcription
            transcriber.start()
            
            logging.info("Real-time transcription stopped")
            self.current_mode = None
            
        except Exception as e:
            logging.error(f"Error in _run_realtime: {e}")
            
            # Make sure to clean up properly
            try:
                if "realtime" in self.model_manager.transcribers and self.model_manager.transcribers["realtime"]:
                    self.model_manager.transcribers["realtime"].stop()
            except Exception as cleanup_e:
                logging.error(f"Error during cleanup: {cleanup_e}")
            
            self.current_mode = None
    
    def _start_longform(self):
        """Start long-form recording."""
        # Check if another mode is running
        if self.current_mode:
            safe_print(f"Cannot start long-form mode while in {self.current_mode} mode. Please finish the current operation first.")
            return
                
        try:
            # Check if we can reuse the current model
            if not self.model_manager.can_reuse_model("longform"):
                # Make sure we're using the long-form model
                if self.model_manager.current_loaded_model_type != "longform":
                    self.model_manager.unload_current_model()
            else:
                safe_print(f"Reusing {self.model_manager.current_loaded_model_type} model for longform", "success")
                    
            # Initialize the long-form transcriber if not already done
            transcriber = self.model_manager.initialize_transcriber("longform")
            if not transcriber:
                safe_print("Failed to initialize long-form transcriber.", "error")
                return
                    
            safe_print("Starting long-form recording...", "success")
            self.current_mode = "longform"
            transcriber.start_recording()
                
        except Exception as e:
            logging.error(f"Error starting long-form recording: {e}")
            self.current_mode = None
    
    def _stop_longform(self):
        """Stop long-form recording and transcribe."""
        if self.current_mode != "longform":
            safe_print("No active long-form recording to stop.")
            return
            
        try:
            transcriber = self.model_manager.transcribers.get("longform")
            if not transcriber:
                safe_print("Long-form transcriber not available.")
                self.current_mode = None
                return
                
            safe_print("Stopping long-form recording and transcribing...")
            transcriber.stop_recording()
            self.current_mode = None
            
        except Exception as e:
            logging.error(f"Error stopping long-form recording: {e}")
            self.current_mode = None
    
    def _run_static(self):
        """Run static file transcription."""
        # Check if another mode is running
        if self.current_mode:
            safe_print(f"Cannot start static mode while in {self.current_mode} mode. Please finish the current operation first.")
            return
                
        try:
            # Check if we can reuse the current model
            if not self.model_manager.can_reuse_model("static"):
                # Make sure we're using the static model
                if self.model_manager.current_loaded_model_type != "static":
                    self.model_manager.unload_current_model()
            else:
                safe_print(f"Reusing {self.model_manager.current_loaded_model_type} model for static", "success")
                    
            # Initialize the static transcriber if not already done
            transcriber = self.model_manager.initialize_transcriber("static")
            if not transcriber:
                safe_print("Failed to initialize static transcriber.", "error")
                return
                    
            safe_print("Opening file selection dialog...")
            self.current_mode = "static"
                
            # Run in a separate thread to avoid blocking
            threading.Thread(target=self._run_static_thread, daemon=True).start()
                
        except Exception as e:
            logging.error(f"Error starting static transcription: {e}")
            self.current_mode = None
    
    def _run_static_thread(self):
        """Run static transcription in a separate thread."""
        try:
            transcriber = self.model_manager.transcribers.get("static")
            if not transcriber:
                safe_print("Static transcriber not available.")
                self.current_mode = None
                return
                
            # Select and process the file
            transcriber.select_file()
            
            # Wait until transcription is complete
            while transcriber.transcribing:
                time.sleep(0.5)
                
            logging.info("Static file transcription completed")
            self.current_mode = None
            
        except Exception as e:
            logging.error(f"Error in static transcription: {e}")
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
            elif self.current_mode == "static" and hasattr(self.model_manager.transcribers.get("static", None), 'request_abort'):
                self.model_manager.transcribers["static"].request_abort()
        
        # Allow time for mode to stop
        time.sleep(0.5)
        
        # Now do the full shutdown
        self.stop()
        
        # Force exit after a short delay to ensure clean shutdown
        time.sleep(0.5)
        os._exit(0)
    
    def run(self):
        """Run the orchestrator."""
        # Start the TCP server
        self.command_server.start()
        
        # Start the AutoHotkey script
        ahk_path = os.path.join(self.script_dir, "STT_hotkeys.ahk")
        self.system_utils.start_ahk_script(ahk_path)
        
        # Display startup banner with system information
        self.system_utils.display_system_info()
        
        # Set the running flag
        self.running = True
        
        # Keep the main thread running
        try:
            while self.running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            safe_print("\nKeyboard interrupt received, shutting down...")
        except Exception as e:
            logging.error(f"Error in main loop: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """Stop all processes and clean up with improved resource handling."""
        try:
            if not self.running:
                return

            logging.info("Beginning graceful shutdown sequence...")
            self.running = False

            # Stop the command server
            self.command_server.stop()
            
            # Clean up all models
            self.model_manager.cleanup_all_models()
            
            # Stop the AutoHotkey script
            self.system_utils.stop_ahk_script()

            logging.info("Orchestrator stopped successfully")

        except Exception as e:
            logging.error(f"Error during shutdown: {e}")

if __name__ == "__main__":
    orchestrator = STTOrchestrator()
    orchestrator.run()