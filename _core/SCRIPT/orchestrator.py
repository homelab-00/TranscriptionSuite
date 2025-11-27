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
- Can run as an API server for the webapp (--serve-api flag)

Use the system tray menu to open configuration, start/stop long-form recording,
run static transcription, and quit.
"""

import argparse
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
from viewer_storage import save_longform_recording, get_word_timestamps_from_audio

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

    Modes:
        - tray: System tray icon with longform + static transcription (default)
        - audio-notebook: Web-based viewer with transcription API
        - static: CLI transcription of a single file
    """

    def __init__(
        self,
        mode: str = "tray",
        static_file: Optional[str] = None,
        api_port: int = 8000,
        open_browser: bool = True,
    ):
        """
        Initialize the orchestrator.

        Args:
            mode: Operating mode - "tray", "audio-notebook", or "static"
            static_file: Path to file for static transcription mode
            api_port: Port for audio notebook backend (default 8000)
            open_browser: Whether to open browser in audio-notebook mode
        """
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        # Use relative path - ConfigManager will look in project root
        self.config_path = "config.yaml"

        # Mode configuration
        self.mode = mode
        self.static_file = static_file
        self.api_port = api_port
        self.open_browser = open_browser
        self.api_server = None

        # Application state (combining related attributes)
        self.app_state: dict[str, Optional[bool | str]] = {
            "running": False,
            "current_mode": None,  # Tracks "longform" or "static" or "api_transcription"
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

        # Check if preview is enabled (only for tray mode)
        self.preview_enabled = self.config.get("transcription_options", {}).get(
            "enable_preview_transcriber", True
        )

        # Audio notebook server state
        self.audio_notebook_server = None
        self.audio_notebook_thread = None

        # Initialize Tray Icon Manager only for tray mode
        if mode == "tray" and HAS_TRAY:
            self.tray_manager = TrayIconManager(  # type: ignore[assignment]
                name="STT Orchestrator",
                start_callback=self._start_longform,
                stop_callback=self._stop_longform,
                quit_callback=self._quit,
                static_transcribe_callback=self._start_static_transcription,
                toggle_models_callback=self._toggle_models_loaded,
                audio_notebook_callback=self._toggle_audio_notebook,
            )
        elif mode == "tray" and not HAS_TRAY:
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

                # Get static transcription settings from config
                static_config = self.config.get("static_transcription", {})
                enable_diarization = static_config.get("enable_diarization", False)
                max_segment_chars = static_config.get("max_segment_chars", 500)

                # Get language from transcription options
                language = self.config.get("transcription_options", {}).get("language")

                # Generate output file path in same directory as source audio
                from pathlib import Path

                source_path = Path(file_path)
                output_file = str(
                    source_path.parent / f"{source_path.stem}_transcription.json"
                )

                # Check if diarization is enabled AND available
                if (
                    enable_diarization
                    and self.static_transcriber.is_diarization_available()
                ):
                    safe_print("Diarization enabled - will identify speakers", "info")
                    self.static_transcriber.transcribe_file_with_diarization(
                        file_path,
                        output_file=output_file,
                        output_format="json",
                        language=language,
                        max_segment_chars=max_segment_chars,
                    )
                else:
                    if enable_diarization:
                        safe_print(
                            "Diarization enabled but not available - using word timestamps only",
                            "warning",
                        )
                    else:
                        safe_print(
                            "Transcribing with word timestamps (diarization disabled)",
                            "info",
                        )
                    # Use the word-timestamp-only transcription
                    self.static_transcriber.transcribe_file_with_word_timestamps(
                        file_path,
                        output_file=output_file,
                        language=language,
                        max_segment_chars=max_segment_chars,
                    )

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

                # Check if we should save to viewer app
                self._maybe_save_to_viewer(final_text)

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

    def _maybe_save_to_viewer(self, transcription_text: str):
        """
        Save longform recording to viewer app if configured.

        Checks config for include_in_viewer, word_timestamps, and enable_diarization
        flags to determine if and how to save the recording.
        """
        longform_config = self.config.get("longform_recording", {})

        # Check if we should save to viewer
        if not longform_config.get("include_in_viewer", True):
            logging.debug("Longform recording not configured to save to viewer")
            return

        # Check if word_timestamps or diarization is enabled
        word_timestamps_enabled = longform_config.get("word_timestamps", False)
        diarization_enabled = longform_config.get("enable_diarization", False)

        if not (word_timestamps_enabled or diarization_enabled):
            logging.debug(
                "Neither word_timestamps nor diarization enabled, skipping viewer save"
            )
            return

        if not self.main_transcriber:
            logging.warning("No transcriber available for viewer save")
            return

        # Get audio data from the last recording
        audio_data = self.main_transcriber.get_last_audio_data()
        if audio_data is None or len(audio_data) == 0:
            logging.warning("No audio data available for viewer save")
            return

        safe_print("Saving recording to viewer app...", "info")

        try:
            word_timestamps = None
            diarization_segments = None

            # Get word timestamps if enabled
            if word_timestamps_enabled:
                safe_print("Extracting word-level timestamps...", "info")
                _, word_timestamps = get_word_timestamps_from_audio(
                    audio_data,
                    language=self.config.get("main_transcriber", {}).get("language"),
                )
                if word_timestamps:
                    safe_print(
                        f"Extracted {len(word_timestamps)} words with timestamps",
                        "success",
                    )

            # Get diarization if enabled
            if diarization_enabled:
                safe_print("Running speaker diarization...", "info")
                diarization_segments = self._run_diarization(audio_data)
                if diarization_segments:
                    safe_print(
                        f"Identified {len(diarization_segments)} speaker segments",
                        "success",
                    )

            # Save to viewer database
            recording_id = save_longform_recording(
                audio_data=audio_data,
                transcription_text=transcription_text,
                sample_rate=16000,
                word_timestamps=word_timestamps,
                diarization_segments=diarization_segments,
            )

            if recording_id:
                safe_print(
                    f"Recording saved to viewer app (ID: {recording_id})", "success"
                )
            else:
                safe_print("Failed to save recording to viewer app", "warning")

        except Exception as e:
            logging.error(f"Error saving to viewer: {e}", exc_info=True)
            safe_print(f"Error saving to viewer: {e}", "error")

    def _run_diarization(self, audio_data) -> list[dict]:
        """
        Run speaker diarization on audio data.

        Returns list of segments with speaker labels.
        """
        import tempfile
        import wave
        import numpy as np

        try:
            # Import diarization module dynamically
            from DIARIZATION_SERVICE.service import DiarizationService

            # Write audio to temp file for diarization service
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

                # Convert float32 [-1.0, 1.0] to int16
                audio_int16 = (audio_data * 32767).astype(np.int16)

                with wave.open(tmp_path, "wb") as wav_file:
                    wav_file.setnchannels(1)  # Mono
                    wav_file.setsampwidth(2)  # 16-bit
                    wav_file.setframerate(16000)  # 16kHz
                    wav_file.writeframes(audio_int16.tobytes())

            # Run diarization
            diarization_config = self.config.get("diarization", {})
            min_speakers = diarization_config.get("min_speakers")
            max_speakers = diarization_config.get("max_speakers")

            service = DiarizationService()
            segments = service.diarize(tmp_path, min_speakers, max_speakers)

            # Clean up temp file
            import os

            os.unlink(tmp_path)

            # Convert to dict format
            return [seg.to_dict() for seg in segments]

        except ImportError:
            logging.warning("Diarization service not available")
            return []
        except Exception as e:
            logging.error(f"Error during diarization: {e}", exc_info=True)
            return []

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
                "warning",
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
                        logging.error(
                            f"Error unloading preview transcriber: {e}", exc_info=True
                        )
                        safe_print(
                            f"Warning: Could not fully unload preview transcriber: {e}",
                            "warning",
                        )

                # Clean up main transcriber
                if self.main_transcriber:
                    try:
                        logging.info("Cleaning up main transcriber")
                        self.main_transcriber.clean_up()
                        self.main_transcriber = None
                        safe_print("Main transcriber unloaded.", "success")
                    except Exception as e:
                        logging.error(
                            f"Error unloading main transcriber: {e}", exc_info=True
                        )
                        safe_print(
                            f"Warning: Could not fully unload main transcriber: {e}",
                            "warning",
                        )

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

    def _toggle_audio_notebook(self):
        """Toggle the Audio Notebook server on/off from tray menu."""
        # Check if we're in an active mode
        if self.app_state["current_mode"] is not None:
            safe_print(
                f"Cannot start Audio Notebook while {self.app_state['current_mode']} mode is active.",
                "warning",
            )
            return

        if self.audio_notebook_server is not None:
            # Stop the audio notebook
            self._stop_audio_notebook()
        else:
            # Start the audio notebook
            self._start_audio_notebook()

    def _start_audio_notebook(self):
        """Start the Audio Notebook server in a background thread."""
        if self.audio_notebook_thread and self.audio_notebook_thread.is_alive():
            safe_print("Audio Notebook is already running.", "warning")
            return

        def server_worker():
            try:
                from fastapi import FastAPI
                from fastapi.middleware.cors import CORSMiddleware
                from pydantic import BaseModel
                import uvicorn
            except ImportError as e:
                safe_print(f"FastAPI or uvicorn not installed: {e}", "error")
                return

            # Import the APP_VIEWER/backend modules
            import sys

            backend_path = os.path.join(self.script_dir, "..", "APP_VIEWER", "backend")
            if backend_path not in sys.path:
                sys.path.insert(0, backend_path)

            try:
                from database import init_db  # type: ignore[import-not-found]
                from routers import recordings, search, transcribe  # type: ignore[import-not-found]
            except ImportError as e:
                safe_print(f"Failed to import APP_VIEWER/backend modules: {e}", "error")
                return

            # Initialize database
            init_db()

            # Create the app
            app = FastAPI(
                title="Audio Notebook API",
                description="Transcription viewer and manager",
                version="1.0.0",
            )

            app.add_middleware(
                CORSMiddleware,
                allow_origins=[
                    "http://localhost:5173",
                    "http://localhost:1420",
                    "http://localhost:3000",
                    "tauri://localhost",
                ],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

            # Include routers from APP_VIEWER/backend
            app.include_router(
                recordings.router, prefix="/api/recordings", tags=["recordings"]
            )
            app.include_router(search.router, prefix="/api/search", tags=["search"])
            app.include_router(
                transcribe.router, prefix="/api/transcribe", tags=["transcribe"]
            )

            # Transcription API endpoint (uses loaded model)
            class TranscribeRequest(BaseModel):
                wav_path: str
                enable_diarization: bool = False
                enable_word_timestamps: bool = True
                language: Optional[str] = None

            class TranscribeResponse(BaseModel):
                segments: list
                audio_duration: float
                num_speakers: int

            class HealthResponse(BaseModel):
                status: str
                models_loaded: bool

            @app.get("/api/health", response_model=HealthResponse)
            async def health_check():
                return HealthResponse(
                    status="ok" if self.app_state["models_loaded"] else "loading",
                    models_loaded=bool(self.app_state["models_loaded"]),
                )

            @app.post("/api/orchestrator/transcribe", response_model=TranscribeResponse)
            async def transcribe_file(request: TranscribeRequest):
                return await self._api_transcribe(
                    request.wav_path,
                    request.enable_diarization,
                    request.enable_word_timestamps,
                    request.language,
                )

            # Create uvicorn config with graceful shutdown
            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=self.api_port,
                log_level="warning",
            )
            server = uvicorn.Server(config)
            self.audio_notebook_server = server

            # Update tray menu
            if self.tray_manager:
                self.tray_manager.update_audio_notebook_menu_item(True)

            safe_print(
                f"Audio Notebook started on http://localhost:{self.api_port}", "success"
            )
            safe_print(f"  API Docs: http://localhost:{self.api_port}/docs", "info")

            # Open browser
            if self.open_browser:
                import webbrowser

                webbrowser.open(f"http://localhost:{self.api_port}/docs")

            # Run the server (blocks until stopped)
            server.run()

            # Cleanup after server stops
            self.audio_notebook_server = None
            if self.tray_manager:
                self.tray_manager.update_audio_notebook_menu_item(False)
            safe_print("Audio Notebook stopped.", "info")

        self.audio_notebook_thread = threading.Thread(target=server_worker, daemon=True)
        self.audio_notebook_thread.start()

    def _stop_audio_notebook(self):
        """Stop the Audio Notebook server."""
        if self.audio_notebook_server:
            safe_print("Stopping Audio Notebook...", "info")
            self.audio_notebook_server.should_exit = True
            self.audio_notebook_server = None
            if self.tray_manager:
                self.tray_manager.update_audio_notebook_menu_item(False)

    def _quit(self):
        """Signals the application to stop and exit gracefully."""
        if self.app_state.get("shutdown_in_progress"):
            return
        self.app_state["shutdown_in_progress"] = True
        safe_print("Quit requested, shutting down...")

        def shutdown_worker():
            # Stop audio notebook if running
            self._stop_audio_notebook()
            self.stop()
            # The application will now exit naturally when the tray_manager's
            # event loop is quit. os._exit(0) is no longer needed.

        threading.Thread(target=shutdown_worker, daemon=True).start()

    def run(self):
        """Run the orchestrator based on the configured mode."""
        self.diagnostics.display_system_info()
        self._check_startup_dependencies()

        if self.mode == "static":
            self._run_static_mode()
        elif self.mode == "audio-notebook":
            self._run_audio_notebook_mode()
        else:
            self._run_tray_mode()

    def _run_static_mode(self):
        """Run static file transcription and exit."""
        if not self.static_file:
            safe_print("No file specified for static transcription.", "error")
            return

        from pathlib import Path

        input_path = Path(self.static_file)
        if not input_path.exists():
            safe_print(f"File not found: {self.static_file}", "error")
            return

        safe_print("Loading model for static transcription...", "info")
        self._load_single_transcriber_mode_for_api()

        if not self.main_transcriber:
            safe_print("Failed to load transcription model.", "error")
            return

        self.app_state["models_loaded"] = True
        safe_print("Model loaded successfully.", "success")

        # Create static transcriber and run
        self.static_transcriber = StaticFileTranscriber(
            self.main_transcriber, self.console_display
        )

        safe_print(f"Transcribing: {input_path.name}", "info")
        self.static_transcriber.transcribe_file(str(input_path))

        # Output path is same as input but .txt
        output_path = input_path.with_suffix(".txt")
        safe_print(f"Output saved to: {output_path}", "success")

        self.stop()

    def _run_audio_notebook_mode(self):
        """Run the audio notebook webapp with transcription API."""
        safe_print("Starting Audio Notebook...", "info")

        # Load model for transcription API
        safe_print("Loading transcription model...", "info")
        self._load_single_transcriber_mode_for_api()

        if not self.main_transcriber:
            safe_print("Failed to load transcription model.", "error")
            return

        self.app_state["models_loaded"] = True
        safe_print("Model loaded successfully.", "success")

        # Start the FastAPI backend
        self._run_audio_notebook_server()

    def _run_audio_notebook_server(self):
        """Start the FastAPI server for audio notebook."""
        try:
            from fastapi import FastAPI
            from fastapi.middleware.cors import CORSMiddleware
            from pydantic import BaseModel
            import uvicorn
        except ImportError as e:
            safe_print(f"FastAPI or uvicorn not installed: {e}", "error")
            return

        # Import the APP_VIEWER/backend modules
        import sys

        backend_path = os.path.join(self.script_dir, "..", "APP_VIEWER", "backend")
        sys.path.insert(0, backend_path)

        try:
            from database import init_db  # type: ignore[import-not-found]
            from routers import recordings, search, transcribe  # type: ignore[import-not-found]
        except ImportError as e:
            safe_print(f"Failed to import APP_VIEWER/backend modules: {e}", "error")
            return

        # Initialize database
        init_db()

        # Create the app
        app = FastAPI(
            title="Audio Notebook API",
            description="Transcription viewer and manager",
            version="1.0.0",
        )

        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:5173",
                "http://localhost:1420",
                "http://localhost:3000",
                "tauri://localhost",
            ],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Include routers from APP_VIEWER/backend
        app.include_router(
            recordings.router, prefix="/api/recordings", tags=["recordings"]
        )
        app.include_router(search.router, prefix="/api/search", tags=["search"])
        app.include_router(
            transcribe.router, prefix="/api/transcribe", tags=["transcribe"]
        )

        # Transcription API endpoint (uses loaded model)
        class TranscribeRequest(BaseModel):
            wav_path: str
            enable_diarization: bool = False
            enable_word_timestamps: bool = True
            language: Optional[str] = None

        class TranscribeResponse(BaseModel):
            segments: list
            audio_duration: float
            num_speakers: int

        class HealthResponse(BaseModel):
            status: str
            models_loaded: bool

        @app.get("/api/health", response_model=HealthResponse)
        async def health_check():
            return HealthResponse(
                status="ok" if self.app_state["models_loaded"] else "loading",
                models_loaded=bool(self.app_state["models_loaded"]),
            )

        @app.post("/api/orchestrator/transcribe", response_model=TranscribeResponse)
        async def transcribe_file(request: TranscribeRequest):
            return await self._api_transcribe(
                request.wav_path,
                request.enable_diarization,
                request.enable_word_timestamps,
                request.language,
            )

        self.app_state["running"] = True
        self.api_server = app

        safe_print(
            f"Audio Notebook starting on http://localhost:{self.api_port}", "success"
        )
        safe_print("Endpoints:", "info")
        safe_print(f"  API:  http://localhost:{self.api_port}/docs", "info")
        safe_print("  App:  http://localhost:1420 (run frontend separately)", "info")
        safe_print("", "info")
        safe_print("Press Ctrl+C to stop", "info")

        if self.open_browser:
            import webbrowser

            webbrowser.open(f"http://localhost:{self.api_port}/docs")

        try:
            uvicorn.run(app, host="127.0.0.1", port=self.api_port, log_level="warning")
        except KeyboardInterrupt:
            safe_print("\nShutting down Audio Notebook...", "info")
        finally:
            self.stop()

    def _run_tray_mode(self):
        """Run the traditional tray icon mode."""

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

    def _load_single_transcriber_mode_for_api(self):
        """Load transcriber for API mode (no microphone needed)."""
        self.preview_transcriber = None
        self.main_transcriber = self.model_manager.initialize_transcriber(
            "main_transcriber",
            instance_name="main_transcriber",
            callbacks=None,
            use_microphone=False,  # No microphone for API mode
        )

    async def _api_transcribe(
        self,
        wav_path: str,
        enable_diarization: bool,
        enable_word_timestamps: bool,
        language: Optional[str],
    ) -> dict:
        """
        Transcribe an audio file via the API.

        This uses the StaticFileTranscriber which handles model loading internally.
        """
        from pathlib import Path
        import asyncio

        wav_file = Path(wav_path)
        if not wav_file.exists():
            raise RuntimeError(f"Audio file not found: {wav_path}")

        if not self.main_transcriber:
            raise RuntimeError("Transcription model not loaded")

        logging.info(f"API transcription request: {wav_path}")
        logging.info(
            f"  Diarization: {enable_diarization}, Word timestamps: {enable_word_timestamps}"
        )

        # Run transcription in a thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self._do_transcription,
            wav_path,
            enable_diarization,
            enable_word_timestamps,
            language,
        )

        return result

    def _do_transcription(
        self,
        wav_path: str,
        enable_diarization: bool,
        enable_word_timestamps: bool,
        language: Optional[str],
    ) -> dict:
        """Perform the actual transcription (blocking)."""
        import soundfile as sf
        from static_transcriber import StaticFileTranscriber, HAS_DIARIZATION

        try:
            # Read audio file to get duration
            audio_data, sample_rate = sf.read(wav_path, dtype="float32")
            audio_duration = len(audio_data) / sample_rate
            logging.info(f"Audio duration: {audio_duration:.2f} seconds")

            # Get static transcription settings
            static_config = self.config.get("static_transcription", {})
            max_segment_chars = static_config.get("max_segment_chars", 500)

            # Create static transcriber using the main transcriber
            # Assert non-None so the type checker recognizes the value is valid
            assert self.main_transcriber is not None
            static_transcriber = StaticFileTranscriber(
                self.main_transcriber, self.console_display
            )

            # Transcribe based on options
            logging.info("Starting transcription...")
            segments = []

            if enable_diarization and HAS_DIARIZATION:
                # Full diarization with word timestamps
                diar_config = self.config.get("diarization", {})
                min_speakers = diar_config.get("min_speakers")
                max_speakers = diar_config.get("max_speakers")

                result = static_transcriber.transcribe_file_with_diarization(
                    wav_path,
                    min_speakers=min_speakers,
                    max_speakers=max_speakers,
                    language=language,
                    max_segment_chars=max_segment_chars,
                )
                if result:
                    segments = [seg.to_dict() for seg in result]
            elif enable_word_timestamps:
                # Word timestamps without diarization
                result = static_transcriber.transcribe_file_with_word_timestamps(
                    wav_path,
                    language=language,
                    max_segment_chars=max_segment_chars,
                )
                if result:
                    segments = [seg.to_dict() for seg in result]
            else:
                # Basic transcription (will still get word timestamps from the method)
                result = static_transcriber.transcribe_file_with_word_timestamps(
                    wav_path,
                    language=language,
                    max_segment_chars=max_segment_chars,
                )
                if result:
                    # Strip word-level data for basic mode
                    segments = [
                        {
                            "text": seg.text,
                            "start": round(seg.start, 3),
                            "end": round(seg.end, 3),
                            "duration": round(seg.duration, 3),
                        }
                        for seg in result
                    ]

            num_speakers = 0
            if enable_diarization:
                speakers = set(
                    seg.get("speaker") for seg in segments if seg.get("speaker")
                )
                num_speakers = len(speakers)

            logging.info(f"Transcription complete: {len(segments)} segments")

            return {
                "segments": segments,
                "audio_duration": round(audio_duration, 2),
                "num_speakers": num_speakers,
            }

        except Exception as e:
            logging.error(f"Transcription error: {e}", exc_info=True)
            raise RuntimeError(f"Transcription failed: {e}")

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
    parser = argparse.ArgumentParser(
        description="TranscriptionSuite Orchestrator - STT system controller",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  (default)        Run with system tray (longform + static transcription)
  --audio-notebook Launch web-based audio notebook viewer
  --static FILE    Transcribe a single file and exit

Examples:
  %(prog)s                        Run in tray icon mode (default)
  %(prog)s --audio-notebook       Launch audio notebook webapp
  %(prog)s --static recording.wav Transcribe file to .txt
""",
    )
    parser.add_argument(
        "--audio-notebook",
        action="store_true",
        help="Launch the audio notebook webapp (backend + frontend)",
    )
    parser.add_argument(
        "--static",
        metavar="FILE",
        type=str,
        help="Transcribe a single audio file and save result as .txt",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for audio notebook backend (default: 8000)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open browser automatically (audio-notebook mode)",
    )

    args = parser.parse_args()

    # Determine mode
    if args.static:
        mode = "static"
    elif args.audio_notebook:
        mode = "audio-notebook"
    else:
        mode = "tray"

    orchestrator = STTOrchestrator(
        mode=mode,
        static_file=args.static,
        api_port=args.port,
        open_browser=not args.no_browser,
    )
    orchestrator.run()
