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
from utils import safe_print

if not TYPE_CHECKING:
    # Try to import the tray manager at runtime
    try:
        from PyQt6.QtWidgets import QFileDialog
        from tray_manager import TrayIconManager

        HAS_TRAY = True
    except ImportError:
        HAS_TRAY = False
        TrayIconManager = None
        QFileDialog = None
else:
    from PyQt6.QtWidgets import QFileDialog
    from tray_manager import TrayIconManager

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
            "current_mode": None,  # Tracks "longform" or "static"
            "is_transcribing": False,  # Flag to manage audio feeding during transcription
            "models_loaded": False,  # Track if models are currently loaded
        }

        # Instances for transcription components
        self.main_transcriber: Optional[LongFormRecorder] = None
        self.preview_transcriber: Optional[LongFormRecorder] = None
        self.console_display: Optional[ConsoleDisplay] = None
        self.tray_manager: Optional["TrayIconManager"] = None
        self.static_transcriber: Optional[StaticFileTranscriber] = None

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

        # Initialize Tray Icon Manager with all necessary callbacks
        if HAS_TRAY:
            self.tray_manager = TrayIconManager(  # type: ignore[assignment]
                name="STT Orchestrator",
                start_callback=self._start_longform,
                stop_callback=self._stop_longform,
                quit_callback=self._quit,
                static_transcribe_callback=self._start_static_transcription,
                toggle_models_callback=self._toggle_models_loaded,
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

    def _start_static_transcription(self):
        """
        Initiates the static file transcription process.
        This method is called from the main GUI thread.
        """
        if self.app_state["current_mode"]:
            safe_print(
                f"Cannot start static transcription while in "
                f"'{self.app_state['current_mode']}' mode. "
                "Please finish the current operation first.",
                "warning",
            )
            return

        # Capture the active transcriber here to ensure it's not None for the worker
        active_transcriber = self.main_transcriber
        if not active_transcriber:
            safe_print("Transcription models are not ready. Please wait.", "warning")
            return

        if not QFileDialog:
            safe_print("PyQt6 not available, cannot open file dialog.", "error")
            return

        # Supported audio formats for the dialog filter
        supported_formats = "Audio Files (*.wav *.flac *.ogg *.mp3 *.opus *.m4a)"
        file_path, _ = QFileDialog.getOpenFileName(
            None, "Select an Audio File to Transcribe", "", supported_formats
        )

        if not file_path:
            safe_print("No file selected. Aborting static transcription.", "info")
            return

        # Now, dispatch the actual work to a background thread
        # Pass the captured active_transcriber to the worker
        def _worker(transcriber_instance: LongFormRecorder):
            self.app_state["current_mode"] = "static"
            if self.tray_manager:
                self.tray_manager.set_state("transcribing")

            try:
                # Instantiate the transcriber using the captured instance
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
                # Reset state after completion or failure
                self.app_state["current_mode"] = None
                self.static_transcriber = None
                if self.tray_manager:
                    # Check again because another operation might have started
                    if self.app_state["current_mode"] is None:
                        self.tray_manager.set_state("standby")

        # Start thread, passing the captured transcriber as an argument
        threading.Thread(target=_worker, args=(active_transcriber,), daemon=True).start()

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

        # The part that can fail (display start) must be handled first.
        try:
            if self.console_display:
                self.console_display.start(time.monotonic())
        except RuntimeError as error:
            # This specifically catches the "Terminal too small" error.
            logging.warning("Could not start console display: %s", error)
            safe_print(
                f"Terminal display too small. {error} Please resize your terminal and try again.",
                "error",
            )
            # Abort the start-up process cleanly.
            if self.tray_manager:
                self.tray_manager.set_state("standby")
            return

        # If the display started successfully, now we can set the state
        # and start the recorder.
        safe_print("Starting long-form recording...", "success")
        self.app_state["current_mode"] = "longform"

        # The active transcriber controls the microphone and VAD
        if active_transcriber:
            active_transcriber.start_recording()
        if self.preview_enabled and self.main_transcriber:
            self.main_transcriber.start_recording()

    def _stop_longform(self):
        """Stop long-form recording and transcribe."""
        if self.app_state["current_mode"] != "longform":
            safe_print("No active long-form recording to stop.", "info")
            return
        # Dispatch to a worker thread so the Qt event loop can update the icon

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

                # When preview is enabled, we need to stop the previewer explicitly
                # to stop the microphone feed.
                if self.preview_enabled and self.preview_transcriber:
                    self.preview_transcriber.stop_recording()

                safe_print("Stopping long-form recording and transcribing...")

                # The main transcriber's stop_and_transcribe is now the sole command
                # for stopping and processing.
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

    def _handle_preview_sentence(self, sentence: str):
        """Receives a transcribed sentence from the previewer and displays it."""
        if self.console_display:
            self.console_display.add_preview_sentence(sentence)

    def _handle_audio_chunk(self, chunk: bytes):
        """Callback to feed audio from the previewer to the main transcriber."""
        # The console display now uses CAVA and handles its own audio input,
        # so we no longer need to pass audio chunks to it.
        if self.main_transcriber and not self.app_state["is_transcribing"]:
            self.main_transcriber.feed_audio(chunk)

    def _toggle_models_loaded(self):
        """Toggle between unloading and reloading models."""
        # Check if any transcription is in progress
        if self.app_state["current_mode"] is not None:
            safe_print(
                f"Cannot unload models while {self.app_state['current_mode']} mode is active.",
                "warning"
            )
            return

        if self.app_state["models_loaded"]:
            # Unload models
            self._unload_models()
        else:
            # Reload models
            self._reload_models()

    def _unload_models(self):
        """Unload all transcription models to free GPU memory."""
        if not self.app_state["models_loaded"]:
            safe_print("Models are already unloaded.", "info")
            return

        def _worker():
            try:
                if self.tray_manager:
                    self.tray_manager.set_state("loading")

                safe_print("Unloading transcription models...", "info")
                logging.info("Starting model unload sequence")

                # Clean up preview transcriber if it exists
                if self.preview_transcriber:
                    try:
                        logging.info("Cleaning up preview transcriber")
                        self.preview_transcriber.clean_up()
                        self.preview_transcriber = None
                        safe_print("Preview transcriber unloaded.", "success")
                    except Exception as e:
                        logging.error(f"Error unloading preview transcriber: {e}", exc_info=True)
                        safe_print(f"Warning: Could not fully unload preview transcriber: {e}", "warning")

                # Clean up main transcriber
                if self.main_transcriber:
                    try:
                        logging.info("Cleaning up main transcriber")
                        self.main_transcriber.clean_up()
                        self.main_transcriber = None
                        safe_print("Main transcriber unloaded.", "success")
                    except Exception as e:
                        logging.error(f"Error unloading main transcriber: {e}", exc_info=True)
                        safe_print(f"Warning: Could not fully unload main transcriber: {e}", "warning")

                # Clean up models in model manager
                try:
                    logging.info("Cleaning up model manager")
                    self.model_manager.cleanup_all_models()
                    safe_print("GPU memory cleared.", "success")
                except Exception as e:
                    logging.error(f"Error in model manager cleanup: {e}", exc_info=True)

                self.app_state["models_loaded"] = False
                safe_print("All models unloaded successfully.", "success")
                logging.info("Model unload sequence completed")

                if self.tray_manager:
                    self.tray_manager.set_state("standby")
                    self.tray_manager.update_models_menu_item(models_loaded=False)

            except Exception as e:
                logging.error(f"Unexpected error during model unload: {e}", exc_info=True)
                safe_print(f"Error unloading models: {e}", "error")
                if self.tray_manager:
                    self.tray_manager.set_state("error")

        threading.Thread(target=_worker, daemon=True).start()

    def _reload_models(self):
        """Reload transcription models from configuration."""
        if self.app_state["models_loaded"]:
            safe_print("Models are already loaded.", "info")
            return

        def _worker():
            try:
                if self.tray_manager:
                    self.tray_manager.set_state("loading")

                safe_print("Reloading transcription models...", "info")
                logging.info("Starting model reload sequence")

                # Load models based on configuration
                if self.preview_enabled:
                    self._load_dual_transcriber_mode()
                else:
                    self._load_single_transcriber_mode()

                success = self.main_transcriber is not None

                if success:
                    self.app_state["models_loaded"] = True
                    safe_print("Models reloaded successfully.", "success")
                    logging.info("Model reload sequence completed")

                    # Restart preview transcription if enabled
                    if self.preview_enabled and self.preview_transcriber:
                        self.preview_transcriber.start_chunked_transcription(
                            self._handle_preview_sentence
                        )

                    if self.tray_manager:
                        self.tray_manager.set_state("standby")
                        self.tray_manager.update_models_menu_item(models_loaded=True)
                else:
                    safe_print("Failed to reload models.", "error")
                    logging.error("Model reload failed")
                    if self.tray_manager:
                        self.tray_manager.set_state("error")

            except Exception as e:
                logging.error(f"Unexpected error during model reload: {e}", exc_info=True)
                safe_print(f"Error reloading models: {e}", "error")
                if self.tray_manager:
                    self.tray_manager.set_state("error")

        threading.Thread(target=_worker, daemon=True).start()

    def _quit(self):
        """Signals the application to stop and exit gracefully."""
        if self.app_state.get("shutdown_in_progress"):
            return
        self.app_state["shutdown_in_progress"] = True
        safe_print("Quit requested, shutting down...")

        def shutdown_worker():
            self.stop()
            # The application will now exit naturally when the tray_manager's
            # event loop is quit. os._exit(0) is no longer needed.

        threading.Thread(target=shutdown_worker, daemon=True).start()

    def run(self):
        """Run the orchestrator."""
        # Only the tray icon will control the application now.

        self.diagnostics.display_system_info()
        self._check_startup_dependencies()

        # Proactively load the longform model in a separate thread
        def preload_startup_models():
            if self.tray_manager:
                self.tray_manager.set_state("loading")  # Grey icon

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

            # --- Architecture Logic ---
            if self.preview_enabled:
                self._load_dual_transcriber_mode()
            else:
                self._load_single_transcriber_mode()

            success = self.main_transcriber is not None

            if success:
                self.app_state["models_loaded"] = True
                safe_print("Models loaded successfully.", "success")
                if self.preview_enabled and self.preview_transcriber:
                    self.preview_transcriber.start_chunked_transcription(
                        self._handle_preview_sentence
                    )
            else:
                safe_print("Failed to initialize models.", "error")

            if self.tray_manager:
                self.tray_manager.set_state("standby" if success else "error")
                self.tray_manager.update_models_menu_item(models_loaded=success)

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
        # 1. Main transcriber is PASSIVE (use_microphone=False)
        self.main_transcriber = self.model_manager.initialize_transcriber(
            "main_transcriber",
            instance_name="main_transcriber",
            callbacks=None,
            use_microphone=False,
        )

        # 2. Preview transcriber is ACTIVE (use_microphone=True)
        #    and feeds everyone else
        preview_callbacks: dict[str, Callable[..., Any]] = {
            "on_recorded_chunk": self._handle_audio_chunk,
        }
        self.preview_transcriber = self.model_manager.initialize_transcriber(
            "preview_transcriber",
            instance_name="preview_transcriber",
            callbacks=preview_callbacks,
            use_microphone=True,
        )

    def _load_single_transcriber_mode(self):
        """Loads only the main transcriber in active mode, merging VAD settings."""
        self.preview_transcriber = None  # Ensure it's null

        # Create a hybrid config for the main transcriber to handle VAD
        main_config = self.config.get("main_transcriber", {}).copy()
        preview_config = self.config.get("preview_transcriber", {})

        # VAD-related keys to merge from the preview config
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

        # CAVA handles the waveform display independently, so no audio chunk
        # callback to the console display is needed.
        main_callbacks: dict[str, Callable[..., Any]] = {}

        self.main_transcriber = self.model_manager.initialize_transcriber(
            main_config,
            instance_name="main_transcriber",
            callbacks=main_callbacks,
            use_microphone=True,
        )

    def stop(self):
        """Stop all processes and clean up gracefully."""
        if not self.app_state.get("running"):
            return

        logging.info("Beginning graceful shutdown sequence...")
        self.app_state["running"] = False

        # Stop the console display first to prevent it from trying to render
        if self.console_display:
            try:
                self.console_display.stop()
            except Exception as e:
                logging.debug("Error stopping console display: %s", e)

        # The preview transcriber is the 'master' and uses the mic.
        # Shutting it down first stops the audio source.
        if self.preview_transcriber:
            try:
                self.preview_transcriber.clean_up()
            except Exception as e:
                logging.debug("Error cleaning up preview transcriber: %s", e)

        # The main transcriber is the 'slave'.
        if self.main_transcriber:
            try:
                self.main_transcriber.clean_up()
            except Exception as e:
                logging.debug("Error cleaning up main transcriber: %s", e)

        # Stop the UI event loop
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
