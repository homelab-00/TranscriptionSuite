#!/usr/bin/env python3
"""
orchestrator.py - Main controller for the Speech-to-Text system

This script:
- Manages two transcriber instances: one for live, chunked preview and
  one for final, high-accuracy long-form transcription.
- Provides a clean interface via the system tray icon.
- Handles the audio pipeline by routing audio from the preview transcriber
  to the main transcriber.
"""

import os
import threading
import time
import logging
import atexit
import sys
from typing import Optional

from model_manager import ModelManager
from logging_setup import setup_logging
from dependency_checker import DependencyChecker
from utils import safe_print
from config_manager import ConfigManager
from recorder import LongFormRecorder as TranscriptionInstance
from console_display import ConsoleDisplay
from diagnostics import SystemDiagnostics
from platform_utils import get_platform_manager

try:
    from tray_manager import TrayIconManager

    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

setup_logging()


class STTOrchestrator:
    """
    Main orchestrator for the Speech-to-Text system.
    Coordinates between different transcription modes and handles hotkey commands.
    """

    def __init__(self):
        """Initialize the orchestrator."""
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.app_state = {
            "running": False,
            "current_mode": None,
            "is_transcribing": False,
            "config_path": os.path.join(self.script_dir, "config.yaml"),
        }

        self.main_transcriber: Optional[TranscriptionInstance] = None
        self.preview_transcriber: Optional[TranscriptionInstance] = None
        self.console_display: Optional[ConsoleDisplay] = None

        self.platform_manager_instance = get_platform_manager()
        self.config_manager = ConfigManager(self.app_state["config_path"])
        self.config = self.config_manager.load_or_create_config()
        self.diagnostics = SystemDiagnostics(self.config, self.platform_manager_instance)
        setup_logging(self.config)

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

        self.model_manager = ModelManager(self.config, self.script_dir)
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
                if input("\nContinue anyway? (y/N): ").strip().lower() != "y":
                    sys.exit(1)
            elif status == "warnings_present":
                safe_print("Some non-critical issues detected:", "warning")
                for item in summary.get("warnings", []):
                    safe_print(f"  Warning: {item}", "warning")
            else:
                safe_print("All dependencies satisfied ✓", "success")
        except Exception as e:
            logging.error(f"Error during dependency check: {e}")
            safe_print(f"Warning: Could not complete dependency check: {e}", "warning")

    def _start_longform(self):
        """Start long-form recording."""
        if self.app_state["current_mode"]:
            safe_print(f"Cannot start while in {self.app_state['current_mode']} mode.")
            return

        if not self.main_transcriber or not self.preview_transcriber:
            safe_print("Transcribers are not ready. Please wait.", "warning")
            return

        if self.tray_manager:
            self.tray_manager.set_state("recording")

        try:
            if self.console_display:
                self.console_display.start(time.monotonic())
        except RuntimeError as error:
            logging.warning("Could not start console display: %s", error)
            if self.tray_manager:
                self.tray_manager.set_state("standby")
            return

        safe_print("Starting long-form recording...", "success")
        self.app_state["current_mode"] = "longform"
        # The preview transcriber controls the microphone and VAD
        self.preview_transcriber.start_recording()
        self.main_transcriber.start_recording()

    def _stop_longform(self):
        """Stop long-form recording and transcribe."""
        if self.app_state["current_mode"] != "longform":
            return

        def _worker():
            if self.tray_manager:
                self.tray_manager.set_state("transcribing")
            self.app_state["is_transcribing"] = True
            try:
                if self.console_display:
                    self.console_display.stop()

                if not self.main_transcriber or not self.preview_transcriber:
                    safe_print("Transcribers not available.", "error")
                    return

                # Stop the master transcriber, which stops the mic
                self.preview_transcriber.stop_recording()
                safe_print("Stopping long-form recording and transcribing...")
                final_text, metrics = self.main_transcriber.stop_and_transcribe()

                if self.console_display:
                    self.console_display.display_final_transcription(final_text)
                    if metrics:
                        self.console_display.display_metrics(**metrics)
                else:
                    safe_print(
                        f"\n--- Transcription ---\n{final_text or '[No text]'}\n---------------------\n"
                    )

            except Exception as error:
                logging.error(
                    "Error stopping long-form recording: %s", error, exc_info=True
                )
            finally:
                self.app_state["is_transcribing"] = False
                self.app_state["current_mode"] = None
                if self.tray_manager:
                    self.tray_manager.set_state("standby")

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_audio_chunk(self, chunk: bytes):
        """Callback to feed audio from the previewer to the main transcriber and UI."""
        if self.main_transcriber and not self.app_state["is_transcribing"]:
            self.main_transcriber.feed_audio(chunk)
        if self.console_display:
            self.console_display.update_waveform_data(chunk)

    def _handle_preview_sentence(self, sentence: str):
        """Receives a transcribed sentence from the previewer and displays it."""
        if self.console_display:
            self.console_display.add_preview_sentence(sentence)

    def _quit(self):
        """Stop all processes and exit."""
        if self.app_state.get("shutdown_in_progress"):
            return
        self.app_state["shutdown_in_progress"] = True
        safe_print("Quit requested, shutting down...")
        threading.Thread(target=lambda: (self.stop(), os._exit(0)), daemon=True).start()

    def run(self):
        """Run the orchestrator."""
        self.diagnostics.display_system_info()
        self._check_startup_dependencies()

        def preload_startup_models():
            if self.tray_manager:
                self.tray_manager.set_state("loading")

            try:
                self.console_display = ConsoleDisplay()
            except Exception as exc:
                logging.error("Failed to initialize console display: %s", exc)
                self.console_display = None

            # --- Architecture Fix ---
            # 1. Main transcriber is PASSIVE (use_microphone=False)
            main_callbacks = {
                "on_recording_start": (
                    self.console_display.start if self.console_display else None
                ),
                "on_recording_stop": (
                    self.console_display.stop if self.console_display else None
                ),
            }
            self.main_transcriber = self.model_manager.initialize_transcriber(
                "main_transcriber", main_callbacks, use_microphone=False
            )

            # 2. Preview transcriber is ACTIVE (use_microphone=True) and feeds everyone else
            preview_callbacks = {
                "on_recorded_chunk": self._handle_audio_chunk,
            }
            self.preview_transcriber = self.model_manager.initialize_transcriber(
                "preview_transcriber", preview_callbacks, use_microphone=True
            )

            success = self.main_transcriber and self.preview_transcriber

            if success:
                safe_print("Models loaded successfully.", "success")
                # Start the previewer in its continuous chunking mode
                self.preview_transcriber.start_chunked_transcription(
                    self._handle_preview_sentence
                )
            else:
                safe_print("Failed to initialize models.", "error")

            if self.tray_manager:
                self.tray_manager.set_state("standby" if success else "error")

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
        """Stop all processes and clean up."""
        if not self.app_state.get("running"):
            return
        logging.info("Beginning graceful shutdown sequence...")
        self.app_state["running"] = False

        if self.tray_manager:
            self.tray_manager.stop()
        if self.console_display:
            self.console_display.stop()
        if self.main_transcriber:
            self.main_transcriber.clean_up()
        if self.preview_transcriber:
            self.preview_transcriber.clean_up()

        self.model_manager.cleanup_all_models()
        logging.info("Orchestrator stopped successfully")


if __name__ == "__main__":
    orchestrator = STTOrchestrator()
    orchestrator.run()
