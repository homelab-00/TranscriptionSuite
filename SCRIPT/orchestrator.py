#!/usr/bin/env python3
"""
orchestrator.py - Main controller for the Speech-to-Text system

This script:
- Imports and integrates the three transcription modules:
  * Long-form transcription for extended dictation
  * Static file transcription for pre-recorded audio/video
- Manages the state of different transcription modes
- Provides a clean interface via the system tray icon
- Handles command processing and module coordination
- Implements lazy loading of transcription models

Use the system tray menu to open configuration, start/stop long-form recording,
run static transcription, and quit.
"""

import os
import threading
import time
import logging
import atexit
import sys

# REMOVED: KDE DBus/global hotkeys support; only tray controls remain

from model_manager import ModelManager, safe_print
from system_utils import SystemUtils, setup_logging
from depenency_checker import DependencyChecker

# Try to import the tray manager
try:
    from tray_manager import TrayIconManager

    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

setup_logging()

# Try to import Rich for prettier console output
try:
    from rich.console import Console

    CONSOLE = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    CONSOLE = None

# REMOVED: TCP command server settings; system tray provides all control


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
            "current_mode": None,  # Tracks "longform" or "static"
            "config_path": os.path.join(self.script_dir, "config.json"),
        }

        # Initialize system utilities
        self.system_utils = SystemUtils(self.app_state["config_path"])

        # CHANGED: Initialize Tray Icon Manager with all necessary callbacks
        if HAS_TRAY:
            self.tray_manager = TrayIconManager(
                name="STT Orchestrator",
                start_callback=self._start_longform,
                stop_callback=self._stop_longform,
                quit_callback=self._quit,
            )
        else:
            self.tray_manager = None
            safe_print(
                "Could not initialize system tray icon. Please install PyQt6.", "warning"
            )

        # Initialize configuration
        self.config = self.system_utils.load_or_create_config()

        # Initialize model manager
        self.model_manager = ModelManager(self.config, self.script_dir)

        # NOTE: Non-tray triggers (DBus hotkeys, TCP server) have been removed.

        # Register cleanup handler
        atexit.register(self.stop)

    def _check_startup_dependencies(self):
        """Check dependencies during startup and warn about issues."""
        try:
            safe_print("Checking system dependencies...", "info")

            checker = DependencyChecker()
            results = checker.check_all_dependencies()

            summary = results.get("summary", {})
            status = summary.get("overall_status", "unknown")

            if status == "critical_issues":
                safe_print("Critical dependencies are missing!", "error")
                for item in summary.get("critical_missing", []):
                    safe_print(f"  Missing: {item}", "error")

                # Ask user if they want to continue anyway
                response = input("\nContinue anyway? (y/N): ").strip().lower()
                if response != "y":
                    safe_print("Exiting due to missing dependencies.", "error")
                    sys.exit(1)

            elif status == "warnings_present":
                safe_print("Some non-critical issues detected:", "warning")
                for item in summary.get("warnings", []):
                    safe_print(f"  Warning: {item}", "warning")

                if summary.get("recommendations"):
                    safe_print("Recommendations:", "info")
                    for item in summary["recommendations"]:
                        safe_print(f"  • {item}", "info")

            else:
                safe_print("All dependencies satisfied ✓", "success")

        except Exception as e:
            logging.error(f"Error during dependency check: {e}")
            safe_print(f"Warning: Could not complete dependency check: {e}", "warning")

    # REMOVED: TCP command handler registration

    # REMOVED: KDE DBus hotkey setup; only tray controls remain

    # REMOVED: Hotkey signal handler

    def _start_longform(self):
        """Start long-form recording."""
        if self.app_state["current_mode"]:
            safe_print(
                f"Cannot start long-form mode while in {self.app_state['current_mode']} "
                "mode. Please finish the current operation first."
            )
            return

        transcriber = self.model_manager.transcribers.get("longform")
        if not transcriber:
            safe_print("Long-form model is not ready. Please wait.", "warning")
            return

        if self.tray_manager:
            self.tray_manager.set_state("recording")

        try:
            safe_print("Starting long-form recording...", "success")
            self.app_state["current_mode"] = "longform"
            transcriber.start_recording()
        except (RuntimeError, OSError, ImportError) as error:
            logging.error("Error starting long-form recording: %s", error)
            self.app_state["current_mode"] = None
            if self.tray_manager:
                self.tray_manager.set_state("standby")

    def _stop_longform(self):
        """Stop long-form recording and transcribe."""
        if self.app_state["current_mode"] != "longform":
            safe_print("No active long-form recording to stop.", "info")
            return
        # Dispatch to a worker thread so the Qt event loop can update the icon

        def _worker():
            if self.tray_manager:
                self.tray_manager.set_state("transcribing")
            try:
                transcriber = self.model_manager.transcribers.get("longform")
                if not transcriber:
                    safe_print("Long-form transcriber not available.")
                    self.app_state["current_mode"] = None
                    if self.tray_manager:
                        self.tray_manager.set_state("standby")
                    return

                safe_print("Stopping long-form recording and transcribing...")
                transcriber.stop_recording()
                self.app_state["current_mode"] = None

                if self.tray_manager:
                    self.tray_manager.set_state("standby")

            except (AttributeError, RuntimeError) as error:
                logging.error("Error stopping long-form recording: %s", error)
                self.app_state["current_mode"] = None
                if self.tray_manager:
                    self.tray_manager.set_state("error")

        threading.Thread(target=_worker, daemon=True).start()

    def _quit(self):
        """Stop all processes and exit with improved cleanup."""
        safe_print("Quitting application...")
        if self.app_state["current_mode"] == "longform":
            self._stop_longform()
        time.sleep(0.5)
        self.stop()
        # Add a more forceful exit in case the tray event loop hangs
        os._exit(0)

    def run(self):
        """Run the orchestrator."""
        # Only the tray icon will control the application now.

        self.system_utils.display_system_info()
        self._check_startup_dependencies()

        # Proactively load the longform model in a separate thread
        def preload_startup_models():
            if self.tray_manager:
                self.tray_manager.set_state("loading")  # Grey icon

            overall_success = True
            safe_print("Pre-loading the long-form transcription model...", "info")

            transcriber = self.model_manager.initialize_transcriber("longform")
            if not transcriber:
                safe_print("Failed to initialise the long-form model.", "error")
                success = False
            else:
                # The model is now loaded during the transcriber's __init__
                # so if we get an object back, it's ready.
                success = True

            overall_success = success

            if self.tray_manager:
                self.tray_manager.set_state("standby" if overall_success else "error")

        threading.Thread(target=preload_startup_models, daemon=True).start()

        self.app_state["running"] = True

        if self.tray_manager:
            self.tray_manager.run()
        else:
            safe_print("Running in headless mode without a tray icon.", "info")
            try:
                while self.app_state["running"]:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                safe_print("\nKeyboard interrupt received, shutting down...")
            finally:
                self.stop()

    def stop(self):
        """Stop all processes and clean up with improved resource handling."""
        try:
            if not self.app_state.get("running"):
                return

            logging.info("Beginning graceful shutdown sequence...")
            self.app_state["running"] = False

            # DBus loop removed

            if self.tray_manager:
                self.tray_manager.stop()

            self.model_manager.cleanup_all_models()

            logging.info("Orchestrator stopped successfully")

        except (RuntimeError, OSError, AttributeError) as error:
            logging.error("Error during shutdown: %s", error)

    # REMOVED: The entire _manage_hotkeys function is deleted.
    # def _manage_hotkeys(self, enable: bool) -> None: ...


if __name__ == "__main__":
    orchestrator = STTOrchestrator()
    orchestrator.run()
