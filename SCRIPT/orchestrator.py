#!/usr/bin/env python3
"""
orchestrator.py - Main controller for the Speech-to-Text system

This script:
- Imports and integrates the three transcription modules:
  * Real-time transcription for immediate feedback
  * Long-form transcription for extended dictation
  * Static file transcription for pre-recorded audio/video
- Sets up a TCP server to listen for commands from the AutoHotkey script
- Manages the state of different transcription modes
- Provides a clean interface for hotkey-based control
- Handles command processing and module coordination
- Implements lazy loading of transcription models

The system is designed to be controlled via the following hotkeys:
- F1: Open configuration dialog box
- F2: Toggle real-time transcription on/off
- F3: Start long-form recording
- F4: Stop long-form recording and transcribe
- F10: Run static file transcription
- F7: Quit application
"""

import os
import threading
import time
import logging
import atexit
import sys

from model_manager import ModelManager, safe_print
from command_server import CommandServer
from system_utils import SystemUtils
from hotkey_manager import HotkeyManager
from depenency_checker import DependencyChecker

# Configure logging to file only (not to console)
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

    CONSOLE = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    CONSOLE = None

# TCP server settings
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 35000


class STTOrchestrator:
    """
    Main orchestrator for the Speech-to-Text system.
    Coordinates between different transcription modes and handles hotkey commands.
    """

    def __init__(self):
        """Initialize the orchestrator."""
        self.script_dir = os.path.dirname(os.path.abspath(__file__))

        # Application state (combining related attributes)
        self.app_state = {
            "running": False,
            "current_mode": None,  # Can be "realtime", "longform", or "static"
            "config_path": os.path.join(self.script_dir, "config.json"),
        }

        # Initialize system utilities
        self.system_utils = SystemUtils(self.app_state["config_path"])

        # Initialize configuration
        self.config = self.system_utils.load_or_create_config()

        # Initialize model manager
        self.model_manager = ModelManager(self.config, self.script_dir)

        # Initialize command server
        self.command_server = CommandServer(SERVER_HOST, SERVER_PORT)

        # Initialize hotkey manager
        self.hotkey_manager = HotkeyManager(self._handle_hotkey_command)

        # Register command handlers
        self._register_command_handlers()

        # Register cleanup handler
        atexit.register(self.stop)

    def _handle_hotkey_command(self, command: str):
        """Handle commands from the hotkey system."""
        try:
            if command in self.command_server.command_handlers:
                self.command_server.command_handlers[command]()
            else:
                logging.error(f"Unknown hotkey command: {command}")
                safe_print(f"Unknown hotkey command: {command}", "error")
        except Exception as e:
            logging.error(f"Error handling hotkey command {command}: {e}")
            safe_print(f"Error handling hotkey command {command}: {e}", "error")

    def _check_startup_dependencies(self):
        """Check dependencies during startup and warn about issues."""
        try:
            safe_print("Checking system dependencies...", "info")

            checker = DependencyChecker()
            results = checker.check_all_dependencies()

            summary = results.get('summary', {})
            status = summary.get('overall_status', 'unknown')

            if status == 'critical_issues':
                safe_print("Critical dependencies are missing!", "error")
                for item in summary.get('critical_missing', []):
                    safe_print(f"  Missing: {item}", "error")

                # Ask user if they want to continue anyway
                response = input("\nContinue anyway? (y/N): ").strip().lower()
                if response != 'y':
                    safe_print("Exiting due to missing dependencies.", "error")
                    sys.exit(1)

            elif status == 'warnings_present':
                safe_print("Some non-critical issues detected:", "warning")
                for item in summary.get('warnings', []):
                    safe_print(f"  Warning: {item}", "warning")

                if summary.get('recommendations'):
                    safe_print("Recommendations:", "info")
                    for item in summary['recommendations']:
                        safe_print(f"  • {item}", "info")

            else:
                safe_print("All dependencies satisfied ✓", "success")

        except Exception as e:
            logging.error(f"Error during dependency check: {e}")
            safe_print(f"Warning: Could not complete dependency check: {e}", "warning")

    def _register_command_handlers(self):
        """Register handlers for different commands."""
        handlers = {
            "OPEN_CONFIG": self._open_config_dialog,
            "TOGGLE_REALTIME": self._toggle_realtime,
            "START_LONGFORM": self._start_longform,
            "STOP_LONGFORM": self._stop_longform,
            "RUN_STATIC": self._run_static,
            "QUIT": self._quit,
        }
        self.command_server.register_handlers(handlers)

    def _config_updated(self, new_config):
        """Handle configuration updates."""
        logging.info("Configuration updated")
        self.config = new_config
        self.model_manager.config = new_config

        # If any transcribers are active, inform the user about restart
        if self.app_state["current_mode"]:
            safe_print(
                "Configuration updated. Changes will take effect after "
                "restarting transcribers."
            )
        else:
            safe_print("Configuration updated successfully.")

    def _open_config_dialog(self):
        """Open the configuration dialog."""
        # Check if any transcription is active
        if self.app_state["current_mode"]:
            safe_print(
                f"Warning: Transcription in {self.app_state['current_mode']} mode is active."
            )
            # We'll still allow opening the dialog, but warn the user

        # Open the dialog using system utilities
        self.system_utils.open_config_dialog(self._config_updated)

    def _toggle_realtime(self):
        """Toggle real-time transcription on/off."""
        # Check if another mode is running
        if (
            self.app_state["current_mode"]
            and self.app_state["current_mode"] != "realtime"
        ):
            safe_print(
                f"Cannot start real-time mode while in {self.app_state['current_mode']} "
                "mode. Please finish the current operation first."
            )
            return

        if self.app_state["current_mode"] == "realtime":
            # Real-time transcription is already running, so stop it
            safe_print("Stopping real-time transcription...")

            try:
                transcriber = self.model_manager.transcribers.get("realtime")
                if transcriber:
                    transcriber.running = False
                self.app_state["current_mode"] = None

                # Unload the model when turning off real-time mode
                self.model_manager.unload_current_model()

            except (AttributeError, KeyError, RuntimeError) as error:
                logging.error(
                    "Error stopping real-time transcription: %s", error
                )
        else:
            # Start real-time transcription
            try:
                # Check if we can reuse the current model
                if not self.model_manager.can_reuse_model("realtime"):
                    # Make sure we're using the real-time model
                    if (
                        self.model_manager.current_loaded_model_type
                        != "realtime"
                    ):
                        self.model_manager.unload_current_model()
                else:
                    safe_print(
                        f"Reusing {self.model_manager.current_loaded_model_type} "
                        "model for realtime",
                        "success",
                    )

                # Initialize the real-time transcriber if not already done
                transcriber = self.model_manager.initialize_transcriber(
                    "realtime"
                )
                if not transcriber:
                    safe_print(
                        "Failed to initialize real-time transcriber.", "error"
                    )
                    return

                safe_print("Starting real-time transcription...", "success")
                self.app_state["current_mode"] = "realtime"

                # Start real-time transcription in a separate thread
                threading.Thread(target=self._run_realtime, daemon=True).start()
            except (RuntimeError, OSError, ImportError) as error:
                logging.error(
                    "Error starting real-time transcription: %s", error
                )
                self.app_state["current_mode"] = None

    def _run_realtime(self):
        """Run real-time transcription in a separate thread."""
        try:
            transcriber = self.model_manager.transcribers.get("realtime")
            if not transcriber:
                safe_print("Realtime transcriber not available.", "error")
                self.app_state["current_mode"] = None
                return

            # Clear any previous text
            transcriber.text_buffer = ""

            # Start transcription
            transcriber.start()

            logging.info("Real-time transcription stopped")
            self.app_state["current_mode"] = None

        except (RuntimeError, OSError, AttributeError) as error:
            logging.error("Error in _run_realtime: %s", error)

            # Make sure to clean up properly
            try:
                if (
                    "realtime" in self.model_manager.transcribers
                    and self.model_manager.transcribers["realtime"]
                ):
                    self.model_manager.transcribers["realtime"].stop()
            except (AttributeError, RuntimeError) as cleanup_error:
                logging.error("Error during cleanup: %s", cleanup_error)

            self.app_state["current_mode"] = None

    def _start_longform(self):
        """Start long-form recording."""
        # Check if another mode is running
        if self.app_state["current_mode"]:
            safe_print(
                f"Cannot start long-form mode while in {self.app_state['current_mode']} "
                "mode. Please finish the current operation first."
            )
            return

        try:
            # Check if we can reuse the current model
            if not self.model_manager.can_reuse_model("longform"):
                # Make sure we're using the long-form model
                if self.model_manager.current_loaded_model_type != "longform":
                    self.model_manager.unload_current_model()
            else:
                safe_print(
                    f"Reusing {self.model_manager.current_loaded_model_type} "
                    "model for longform",
                    "success",
                )

            # Initialize the long-form transcriber if not already done
            transcriber = self.model_manager.initialize_transcriber("longform")
            if not transcriber:
                safe_print(
                    "Failed to initialize long-form transcriber.", "error"
                )
                return

            safe_print("Starting long-form recording...", "success")
            self.app_state["current_mode"] = "longform"
            transcriber.start_recording()

        except (RuntimeError, OSError, ImportError) as error:
            logging.error("Error starting long-form recording: %s", error)
            self.app_state["current_mode"] = None

    def _stop_longform(self):
        """Stop long-form recording and transcribe."""
        if self.app_state["current_mode"] != "longform":
            safe_print("No active long-form recording to stop.")
            return

        try:
            transcriber = self.model_manager.transcribers.get("longform")
            if not transcriber:
                safe_print("Long-form transcriber not available.")
                self.app_state["current_mode"] = None
                return

            safe_print("Stopping long-form recording and transcribing...")
            transcriber.stop_recording()
            self.app_state["current_mode"] = None

        except (AttributeError, RuntimeError) as error:
            logging.error("Error stopping long-form recording: %s", error)
            self.app_state["current_mode"] = None

    def _run_static(self):
        """Run static file transcription."""
        # Check if another mode is running
        if self.app_state["current_mode"]:
            safe_print(
                f"Cannot start static mode while in {self.app_state['current_mode']} mode. "
                "Please finish the current operation first."
            )
            return

        try:
            # Check if we can reuse the current model
            if not self.model_manager.can_reuse_model("static"):
                # Make sure we're using the static model
                if self.model_manager.current_loaded_model_type != "static":
                    self.model_manager.unload_current_model()
            else:
                safe_print(
                    f"Reusing {self.model_manager.current_loaded_model_type} "
                    "model for static",
                    "success",
                )

            # Initialize the static transcriber if not already done
            transcriber = self.model_manager.initialize_transcriber("static")
            if not transcriber:
                safe_print("Failed to initialize static transcriber.", "error")
                return

            safe_print("Opening file selection dialog...")
            self.app_state["current_mode"] = "static"

            # Run in a separate thread to avoid blocking
            threading.Thread(
                target=self._run_static_thread, daemon=True
            ).start()

        except (RuntimeError, OSError, ImportError) as error:
            logging.error("Error starting static transcription: %s", error)
            self.app_state["current_mode"] = None

    def _run_static_thread(self):
        """Run static transcription in a separate thread."""
        try:
            transcriber = self.model_manager.transcribers.get("static")
            if not transcriber:
                safe_print("Static transcriber not available.")
                self.app_state["current_mode"] = None
                return

            # Select and process the file
            transcriber.select_file()

            # Wait until transcription is complete
            while transcriber.transcribing:
                time.sleep(0.5)

            logging.info("Static file transcription completed")
            self.app_state["current_mode"] = None

        except (RuntimeError, AttributeError, OSError) as error:
            logging.error("Error in static transcription: %s", error)
            self.app_state["current_mode"] = None

    def _quit(self):
        """Stop all processes and exit with improved cleanup."""
        safe_print("Quitting application...")

        # Make sure any active mode is stopped first
        if self.app_state["current_mode"]:
            if self.app_state["current_mode"] == "realtime":
                self._toggle_realtime()  # This will stop it if running
            elif self.app_state["current_mode"] == "longform":
                self._stop_longform()
            elif self.app_state["current_mode"] == "static" and hasattr(
                self.model_manager.transcribers.get("static", None),
                "request_abort",
            ):
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

        # Initialize and start the hotkey system
        if not self.hotkey_manager.initialize():
            safe_print("Warning: Hotkey system could not be initialized. Manual control only.", "warning")
        else:
            if not self.hotkey_manager.start():
                safe_print("Warning: Hotkey system failed to start. Manual control only.", "warning")
            else:
                hotkey_info = self.hotkey_manager.get_backend_info()
                safe_print(f"Hotkey system started using {hotkey_info['backend']}", "success")

        # Display startup banner with system information
        self.system_utils.display_system_info()

        # Perform dependency check
        self._check_startup_dependencies()

        # Set the running flag
        self.app_state["running"] = True

        # Keep the main thread running
        try:
            while self.app_state["running"]:
                time.sleep(0.1)
        except KeyboardInterrupt:
            safe_print("\nKeyboard interrupt received, shutting down...")
        except (RuntimeError, OSError) as error:
            logging.error("Error in main loop: %s", error)
        finally:
            self.stop()

    def stop(self):
        """Stop all processes and clean up with improved resource handling."""
        try:
            if not self.app_state["running"]:
                return

            logging.info("Beginning graceful shutdown sequence...")
            self.app_state["running"] = False

            # Stop the command server
            self.command_server.stop()

            # Clean up all models
            self.model_manager.cleanup_all_models()

            # Stop the hotkey system
            self.hotkey_manager.stop()

            logging.info("Orchestrator stopped successfully")

        except (RuntimeError, OSError, AttributeError) as error:
            logging.error("Error during shutdown: %s", error)


if __name__ == "__main__":
    orchestrator = STTOrchestrator()
    orchestrator.run()
