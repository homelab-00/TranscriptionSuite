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

import atexit
import logging
import os
import queue
import sys
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Optional

from config_manager import ConfigManager
from console_display import ConsoleDisplay
from dependency_checker import DependencyChecker
from diagnostics import SystemDiagnostics
from logging_setup import setup_logging
from model_manager import ModelManager
from platform_utils import get_platform_manager
from recorder import LongFormRecorder
from static_transcriber import StaticFileTranscriber
from live_transcriber import LiveTranscriber
from utils import safe_print

if not TYPE_CHECKING:
    # Try to import the tray manager at runtime
    try:
        from tray_manager import TrayIconManager
        from PyQt6.QtWidgets import QFileDialog

        HAS_TRAY = True
    except ImportError:
        HAS_TRAY = False
        TrayIconManager = None
        QFileDialog = None
else:
    from tray_manager import TrayIconManager
    from PyQt6.QtWidgets import QFileDialog

    HAS_TRAY = True

setup_logging()


class STTOrchestrator:
    """
    Main orchestrator for the Speech-to-Text system.
    Coordinates between different transcription modes and handles hotkey commands.
    """

    def __init__(self):
        """Initialize the orchestrator."""
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(self.script_dir, "config.yaml")

        # Application state (combining related attributes)
        self.app_state: dict[str, Optional[bool | str]] = {
            "running": False,
            "current_mode": None,  # Tracks "longform", "static", or "live"
            "is_transcribing": False,  # Flag to manage audio feeding during transcription
        }

        # Instances for transcription components
        self.main_transcriber: Optional[LongFormRecorder] = None
        self.preview_transcriber: Optional[LongFormRecorder] = None
        self.console_display: Optional[ConsoleDisplay] = None
        self.tray_manager: Optional["TrayIconManager"] = None
        self.static_transcriber: Optional[StaticFileTranscriber] = None
        self.live_transcriber: Optional[LiveTranscriber] = None
        self._live_display_stop_event: Optional[threading.Event] = None

        # Initialize core components
        self.platform_manager_instance = get_platform_manager()
        self.config_manager = ConfigManager(self.config_path)
        self.config = self.config_manager.load_or_create_config()
        self.diagnostics = SystemDiagnostics(self.config, self.platform_manager_instance)

        # Now that config is loaded, re-initialize logging with it
        setup_logging(self.config)

        # Check if preview is enabled
        self.preview_enabled = self.config.get("transcription_options", {}).get(
            "enable_preview_transcriber", True
        )

        # CHANGED: Initialize Tray Icon Manager with the new generic stop callback
        if HAS_TRAY:
            self.tray_manager = TrayIconManager(  # type: ignore[assignment]
                name="STT Orchestrator",
                start_callback=self._start_longform,
                stop_callback=self._stop_current_activity,  # This is the crucial change
                quit_callback=self._quit,
                static_transcribe_callback=self._start_static_transcription,
                live_transcribe_callback=self._start_live_transcription,
            )
        else:
            safe_print(
                "Could not initialize system tray icon. Please install PyQt6.", "warning"
            )

        # Initialize model manager with the loaded config
        self.model_manager = ModelManager(self.config, self.script_dir)

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

    def _start_longform(self):
        """Start long-form recording."""
        if self.app_state["current_mode"]:
            safe_print(
                f"Cannot start long-form mode while in {self.app_state['current_mode']} "
                "mode. Please finish the current operation first."
            )
            return

        active_transcriber = (
            self.preview_transcriber if self.preview_enabled else self.main_transcriber
        )

        if not self.main_transcriber or (self.preview_enabled and not active_transcriber):
            safe_print("Transcription models are not ready. Please wait.", "warning")
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

        if active_transcriber:
            active_transcriber.start_recording()
        if self.preview_enabled and self.main_transcriber:
            self.main_transcriber.start_recording()

    def _stop_longform(self):
        """Stop long-form recording and transcribe."""
        if self.app_state["current_mode"] != "longform":
            safe_print("No active long-form recording to stop.", "info")
            return

        def _worker():
            if self.tray_manager:
                self.tray_manager.set_state("transcribing")
            self.app_state["is_transcribing"] = True
            try:
                if self.console_display:
                    try:
                        self.console_display.stop()
                    except Exception as stop_error:
                        logging.debug("Console display stop error: %s", stop_error)

                if not self.main_transcriber:
                    safe_print("Transcriber not available.", "error")
                    self.app_state["current_mode"] = None
                    if self.tray_manager:
                        self.tray_manager.set_state("error")
                    return

                if self.preview_enabled and self.preview_transcriber:
                    self.preview_transcriber.stop_recording()

                safe_print("Stopping long-form recording and transcribing...")

                final_text, metrics = self.main_transcriber.stop_and_transcribe()
                self.app_state["current_mode"] = None

                if self.console_display:
                    self.console_display.display_final_transcription(final_text)
                    if metrics:
                        self.console_display.display_metrics(**metrics)
                else:
                    rendered_text = final_text or "[No transcription captured]"
                    safe_print(
                        "\n--- Transcription ---\n"
                        f"{rendered_text}\n"
                        "---------------------\n"
                    )

                if self.tray_manager:
                    self.tray_manager.set_state("standby")

            except (AttributeError, RuntimeError) as error:
                logging.error(
                    "Error stopping long-form recording: %s", error, exc_info=True
                )
            finally:
                self.app_state["is_transcribing"] = False
                self.app_state["current_mode"] = None
                if self.tray_manager and self.app_state["current_mode"] is None:
                    self.tray_manager.set_state("standby")

        threading.Thread(target=_worker, daemon=True).start()

    def _start_static_transcription(self):
        """Initiates the static file transcription process."""
        if self.app_state["current_mode"]:
            safe_print(
                f"Cannot start static transcription while in "
                f"'{self.app_state['current_mode']}' mode.",
                "warning",
            )
            return

        active_transcriber = self.main_transcriber
        if not active_transcriber:
            safe_print("Transcription models are not ready. Please wait.", "warning")
            return

        if not QFileDialog:
            safe_print("PyQt6 not available, cannot open file dialog.", "error")
            return

        supported_formats = "Audio Files (*.wav *.flac *.ogg *.mp3 *.opus *.m4a)"
        file_path, _ = QFileDialog.getOpenFileName(
            None, "Select an Audio File to Transcribe", "", supported_formats
        )

        if not file_path:
            safe_print("No file selected. Aborting static transcription.", "info")
            return

        def _worker(transcriber_instance: LongFormRecorder):
            self.app_state["current_mode"] = "static"
            if self.tray_manager:
                self.tray_manager.set_state("transcribing")
            try:
                self.static_transcriber = StaticFileTranscriber(
                    transcriber_instance, self.console_display
                )
                self.static_transcriber.transcribe_file(file_path)
            except Exception as e:
                logging.error(f"Static transcription worker failed: {e}", exc_info=True)
                safe_print(f"An unexpected error occurred: {e}", "error")
                if self.tray_manager:
                    self.tray_manager.set_state("error")
            finally:
                self.app_state["current_mode"] = None
                self.static_transcriber = None
                if self.tray_manager:
                    if self.app_state["current_mode"] is None:
                        self.tray_manager.set_state("standby")

        threading.Thread(target=_worker, args=(active_transcriber,), daemon=True).start()

    def _stop_current_activity(self):
        """Stops whatever transcription mode is currently active."""
        mode = self.app_state.get("current_mode")
        if mode == "longform":
            self._stop_longform()
        elif mode == "live":
            self._stop_live_transcription()
        elif mode is None:
            safe_print("No activity is currently in progress.", "info")
        else:
            safe_print(f"Cannot stop '{mode}' mode from here.", "warning")

    def _start_live_transcription(self):
        """Initializes and starts the live system audio transcription mode."""
        if self.app_state["current_mode"]:
            safe_print(
                f"Cannot start live transcription while in "
                f"'{self.app_state['current_mode']}' mode.",
                "warning",
            )
            return

        live_config = self.config.get("live_transcriber_mode", {})
        if not live_config.get("enabled"):
            safe_print("Live transcription mode is disabled in the config.", "info")
            return

        device_index = live_config.get("input_device_index")
        if device_index is None:
            safe_print(
                "Error: No 'input_device_index' set for live_transcriber_mode "
                "in config.yaml.",
                "error",
            )
            safe_print(
                "Please run list_audio_devices.py and set the index for your system's "
                "'Monitor' or 'Loopback' device.",
                "info",
            )
            return

        def _worker():
            self.app_state["current_mode"] = "live"
            if self.tray_manager:
                self.tray_manager.set_state("recording")

            live_instance_config = self.config.get("preview_transcriber", {}).copy()
            live_instance_config["input_device_index"] = device_index
            live_instance_config["use_default_input"] = False

            live_mode_recorder = self.model_manager.initialize_transcriber(
                live_instance_config, callbacks=None, use_microphone=True
            )

            if not live_mode_recorder:
                safe_print("Failed to initialize recorder for live mode.", "error")
                self.app_state["current_mode"] = None
                if self.tray_manager:
                    self.tray_manager.set_state("error")
                return

            self.live_transcriber = LiveTranscriber(live_mode_recorder)

            text_queue = queue.Queue[str]()
            self._live_display_stop_event = threading.Event()

            # Guard clause for type safety
            if self.console_display:
                display_thread = threading.Thread(
                    target=self.console_display.run_live_transcription_display,
                    args=(self._live_display_stop_event, text_queue),
                    daemon=True,
                )
                display_thread.start()
            else:
                safe_print(
                    "Console display not available for live transcription.", "warning"
                )
                # Fallback to allow functionality without the display
                self.app_state["current_mode"] = None
                if self.tray_manager:
                    self.tray_manager.set_state("error")
                return

            def sentence_callback(sentence: str):
                text_queue.put(sentence)

            # Guard clause for type safety
            if self.live_transcriber:
                self.live_transcriber.start_session(sentence_callback)

        threading.Thread(target=_worker, daemon=True).start()

    def _stop_live_transcription(self):
        """Stops and cleans up the live transcription mode."""
        if self.app_state["current_mode"] != "live" or not self.live_transcriber:
            safe_print("Live transcription is not running.", "info")
            return

        safe_print("Stopping live transcription...", "info")

        if self._live_display_stop_event:
            self._live_display_stop_event.set()

        self.live_transcriber.stop_session()

        self.live_transcriber = None
        self.app_state["current_mode"] = None
        if self.tray_manager:
            self.tray_manager.set_state("standby")

    def _handle_preview_sentence(self, sentence: str):
        """Receives a transcribed sentence from the previewer and displays it."""
        if self.console_display:
            self.console_display.add_preview_sentence(sentence)

    def _handle_audio_chunk(self, chunk: bytes):
        """Callback to feed audio from the previewer to the main transcriber."""
        if self.main_transcriber and not self.app_state["is_transcribing"]:
            self.main_transcriber.feed_audio(chunk)

    def _quit(self):
        """Signals the application to stop and exit gracefully."""
        if self.app_state.get("shutdown_in_progress"):
            return
        self.app_state["shutdown_in_progress"] = True
        safe_print("Quit requested, shutting down...")

        def shutdown_worker():
            self.stop()

        threading.Thread(target=shutdown_worker, daemon=True).start()

    def run(self):
        """Run the orchestrator."""
        self.diagnostics.display_system_info()
        self._check_startup_dependencies()

        def preload_startup_models():
            if self.tray_manager:
                self.tray_manager.set_state("loading")

            if self.preview_enabled:
                safe_print("Pre-loading transcription models (with preview)...", "info")
            else:
                safe_print(
                    "Pre-loading transcription model (preview disabled)...", "info"
                )

            try:
                show_waveform = self.config.get("display", {}).get("show_waveform", True)
                self.console_display = ConsoleDisplay(
                    show_waveform=show_waveform, show_preview=self.preview_enabled
                )
            except Exception as exc:
                logging.error("Failed to initialise console display: %s", exc)
                self.console_display = None

            if self.preview_enabled:
                self._load_dual_transcriber_mode()
            else:
                self._load_single_transcriber_mode()

            success = self.main_transcriber is not None

            if success:
                safe_print("Models loaded successfully.", "success")
                if self.preview_enabled and self.preview_transcriber:
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

    def _load_dual_transcriber_mode(self):
        """Loads both main and preview transcribers."""
        self.main_transcriber = self.model_manager.initialize_transcriber(
            "main_transcriber", callbacks=None, use_microphone=False
        )
        preview_callbacks: dict[str, Callable[..., Any]] = {
            "on_recorded_chunk": self._handle_audio_chunk,
        }
        self.preview_transcriber = self.model_manager.initialize_transcriber(
            "preview_transcriber", preview_callbacks, use_microphone=True
        )

    def _load_single_transcriber_mode(self):
        """Loads only the main transcriber in active mode, merging VAD settings."""
        self.preview_transcriber = None
        main_config = self.config.get("main_transcriber", {}).copy()
        preview_config = self.config.get("preview_transcriber", {})
        vad_keys = [
            "silero_sensitivity",
            "silero_use_onnx",
            "silero_deactivity_detection",
            "webrtc_sensitivity",
            "post_speech_silence_duration",
            "min_length_of_recording",
        ]
        for key in vad_keys:
            if key in preview_config:
                main_config[key] = preview_config[key]
        logging.info("Running in single-transcriber mode with merged VAD config.")
        main_callbacks: dict[str, Callable[..., Any]] = {}
        self.main_transcriber = self.model_manager.initialize_transcriber(
            main_config, main_callbacks, use_microphone=True
        )

    def stop(self):
        """Stop all processes and clean up gracefully."""
        if not self.app_state.get("running"):
            return
        logging.info("Beginning graceful shutdown sequence...")
        self.app_state["running"] = False
        if self.console_display:
            try:
                self.console_display.stop()
            except Exception as e:
                logging.debug("Error stopping console display: %s", e)
        if self.preview_transcriber:
            try:
                self.preview_transcriber.clean_up()
            except Exception as e:
                logging.debug("Error cleaning up preview transcriber: %s", e)
        if self.main_transcriber:
            try:
                self.main_transcriber.clean_up()
            except Exception as e:
                logging.debug("Error cleaning up main transcriber: %s", e)
        if self.tray_manager:
            try:
                self.tray_manager.stop()
            except Exception as e:
                logging.debug("Error stopping tray manager: %s", e)
        try:
            self.model_manager.cleanup_all_models()
        except Exception as e:
            logging.debug("Error cleaning up models: %s", e)
        logging.info("Orchestrator stopped successfully")


if __name__ == "__main__":
    orchestrator = STTOrchestrator()
    orchestrator.run()
