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
import queue
import contextlib
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
    import pyaudio

    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False

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
            "is_transcribing": False,  # Flag to manage audio feeding during transcription
            "config_path": os.path.join(self.script_dir, "config.yaml"),
        }

        # Instances for transcription components
        self.main_transcriber: Optional[TranscriptionInstance] = None
        self.preview_transcriber: Optional[TranscriptionInstance] = None
        self.console_display: Optional[ConsoleDisplay] = None

        # Audio processing attributes
        self.audio_queue: queue.Queue[bytes] = queue.Queue()
        self.audio_threads: list[threading.Thread] = []
        self.stop_audio_event = threading.Event()

        # Initialize core components
        self.platform_manager_instance = get_platform_manager()
        self.config_manager = ConfigManager(self.app_state["config_path"])
        self.config = self.config_manager.load_or_create_config()
        self.diagnostics = SystemDiagnostics(self.config, self.platform_manager_instance)

        # Now that config is loaded, re-initialize logging with it
        setup_logging(self.config)

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

        if not self.main_transcriber:
            safe_print("Long-form model is not ready. Please wait.", "warning")
            return

        if self.tray_manager:
            self.tray_manager.set_state("recording")

        # The part that can fail (display start) must be handled first.
        try:
            # Manually trigger the on_recording_start callback to test the display.
            # This will raise the "Terminal too small" error if needed.
            if (
                self.main_transcriber
                and self.main_transcriber.external_on_recording_start
            ):
                start_time = time.monotonic()
                self.main_transcriber.external_on_recording_start(start_time)
        except RuntimeError as error:
            # This specifically catches the "Terminal too small" error.
            logging.warning("Could not start console display: %s", error)
            # Abort the start-up process cleanly.
            if self.tray_manager:
                self.tray_manager.set_state("standby")
            return

        # If the display started successfully, now we can set the state
        # and start the recorder.
        safe_print("Starting long-form recording...", "success")
        self.app_state["current_mode"] = "longform"
        if self.main_transcriber:
            self.main_transcriber.start_recording()
        else:
            logging.error("Recorder not available at the time of starting.")
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
            self.app_state["is_transcribing"] = True
            try:
                if self.console_display:
                    try:
                        self.console_display.stop()
                    except Exception as stop_error:
                        logging.debug("Console display stop error: %s", stop_error)

                if not self.main_transcriber:
                    safe_print("Long-form transcriber not available.", "error")
                    self.app_state["current_mode"] = None
                    if self.tray_manager:
                        self.tray_manager.set_state("error")
                    return

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
                logging.error("Error stopping long-form recording: %s", error)
            finally:
                self.app_state["is_transcribing"] = False
                self.app_state["current_mode"] = None
                if self.tray_manager:
                    self.tray_manager.set_state("error")

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_preview_sentence(self, sentence: str):
        """Receives a transcribed sentence from the previewer and displays it."""
        if self.console_display:
            self.console_display.add_preview_sentence(sentence)

    def _audio_reader_worker(self):
        """
        The single point of contact for the microphone. Reads audio chunks and
        puts them into a queue for distribution.
        """
        if not HAS_PYAUDIO:
            logging.error("PyAudio not found, cannot read from microphone.")
            return

        audio_config = self.config.get("audio", {})
        if audio_config.get("use_default_input", True):
            device_index = self.model_manager.get_default_input_device_index()
        else:
            device_index = audio_config.get("input_device_index")

        if device_index is None:
            safe_print("No suitable audio input device found. Cannot record.", "error")
            if self.tray_manager:
                self.tray_manager.set_state("error")
            return

        suppress_ctx = getattr(
            self.platform_manager_instance, "suppress_audio_warnings", None
        )
        context_manager = suppress_ctx() if suppress_ctx else contextlib.nullcontext()

        with context_manager:
            p = pyaudio.PyAudio()
            try:
                stream = p.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=16000,
                    input=True,
                    input_device_index=device_index,
                    frames_per_buffer=1024,
                )
                safe_print(
                    f"Microphone stream opened on device index {device_index}.",
                    "info",
                )
                while not self.stop_audio_event.is_set():
                    try:
                        chunk = stream.read(1024, exception_on_overflow=False)
                        self.audio_queue.put(chunk)
                    except OSError as e:
                        logging.error(f"Error reading from audio stream: {e}")
                        time.sleep(0.1)
            except Exception as e:
                logging.error(f"Failed to open audio stream: {e}")
                if self.tray_manager:
                    self.tray_manager.set_state("error")
            finally:
                if "stream" in locals() and stream.is_active():
                    stream.stop_stream()
                    stream.close()
                p.terminate()
                logging.info("Audio reader worker has shut down.")

    def _audio_feeder_worker(self):
        """Takes audio from the queue and feeds it to both transcribers."""
        while not self.stop_audio_event.is_set():
            try:
                chunk = self.audio_queue.get(timeout=0.1)
                if self.main_transcriber and not self.app_state["is_transcribing"]:
                    self.main_transcriber.feed_audio(chunk)
                if self.preview_transcriber:
                    self.preview_transcriber.feed_audio(chunk)
            except queue.Empty:
                continue

    def _quit(self):
        """Stop all processes and exit with improved cleanup."""
        # This method MUST be non-blocking as it's called from the UI thread.
        # Offload the entire shutdown sequence to a new thread.
        if self.app_state.get("shutdown_in_progress"):
            return  # Prevent multiple shutdown attempts
        self.app_state["shutdown_in_progress"] = True
        safe_print("Quit requested, shutting down...")

        def shutdown_worker():
            self.stop()  # This is the main blocking call
            os._exit(0)  # Force exit after cleanup

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

            safe_print("Pre-loading transcription models...", "info")

            try:
                self.console_display = ConsoleDisplay()
            except Exception as exc:
                logging.error("Failed to initialise console display: %s", exc)
                self.console_display = None

            main_callbacks = {}
            if self.console_display:
                main_callbacks["on_recording_start"] = self.console_display.start
                main_callbacks["on_recorded_chunk"] = (
                    self.console_display.update_waveform_data
                )
                main_callbacks["on_recording_stop"] = self.console_display.stop

            preview_callbacks = {}

            try:
                self.main_transcriber = self.model_manager.initialize_transcriber(
                    "main_transcriber", main_callbacks
                )
                self.preview_transcriber = self.model_manager.initialize_transcriber(
                    "preview_transcriber", preview_callbacks
                )
            except Exception as exc:
                logging.error("Failed to initialize a transcriber: %s", exc)

            success = self.main_transcriber and self.preview_transcriber

            if success:
                safe_print("Models loaded successfully.", "success")

                # Start the audio processing threads
                reader = threading.Thread(target=self._audio_reader_worker, daemon=True)
                feeder = threading.Thread(target=self._audio_feeder_worker, daemon=True)
                self.audio_threads.extend([reader, feeder])
                reader.start()
                feeder.start()

                # Start the previewer in its continuous chunking mode
                if self.preview_transcriber:
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
        """Stop all processes and clean up with improved resource handling."""
        try:
            if not self.app_state.get("running"):
                return

            logging.info("Beginning graceful shutdown sequence...")
            self.app_state["running"] = False

            # Signal audio threads to stop
            self.stop_audio_event.set()

            if self.tray_manager:
                self.tray_manager.stop()

            # Wait for audio threads to finish
            for thread in self.audio_threads:
                if thread.is_alive():
                    thread.join(timeout=1.0)

            if self.console_display:
                try:
                    self.console_display.stop()
                except Exception as error:
                    logging.debug("Console display stop error during shutdown: %s", error)

            if self.main_transcriber:
                try:
                    self.main_transcriber.clean_up()
                except Exception as error:
                    logging.debug("Main transcriber cleanup error: %s", error)
            if self.preview_transcriber:
                try:
                    self.preview_transcriber.clean_up()
                except Exception as error:
                    logging.debug("Preview transcriber cleanup error: %s", error)

            self.model_manager.cleanup_all_models()

            logging.info("Orchestrator stopped successfully")

        except (RuntimeError, OSError, AttributeError) as error:
            logging.error("Error during shutdown: %s", error)


if __name__ == "__main__":
    orchestrator = STTOrchestrator()
    orchestrator.run()
