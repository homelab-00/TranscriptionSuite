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

# =============================================================================
# CUDA 12.6 Configuration (for ctranslate2/faster-whisper compatibility)
# =============================================================================
# The system has CUDA 13.0 installed, but ctranslate2 requires CUDA 12.x libraries.
# This configures the environment to use CUDA 12.6 installed at /opt/cuda-12.6
#
# IMPORTANT: LD_LIBRARY_PATH must be set BEFORE the Python interpreter starts,
# not during runtime. We use a re-exec pattern: if the environment isn't set,
# we set it and re-execute ourselves so the dynamic linker picks up the change.
# =============================================================================
import os
import sys
from pathlib import Path

_CUDA_12_PATH = "/opt/cuda-12.6"
_ENV_MARKER = "_TRANSCRIPTION_SUITE_CONFIGURED"

if os.environ.get(_ENV_MARKER) != "1":
    # Set the marker to prevent infinite re-exec loop
    os.environ[_ENV_MARKER] = "1"

    # Configure CUDA 12.6 paths (if available)
    if os.path.exists(_CUDA_12_PATH):
        os.environ["CUDA_HOME"] = _CUDA_12_PATH
        os.environ["CUDA_PATH"] = _CUDA_12_PATH
        os.environ["PATH"] = f"{_CUDA_12_PATH}/bin:{os.environ.get('PATH', '')}"
        os.environ["LD_LIBRARY_PATH"] = (
            f"{_CUDA_12_PATH}/lib64:{os.environ.get('LD_LIBRARY_PATH', '')}"
        )

    # Configure temp directory for NeMo model extraction
    # Use /var/tmp which persists across reboots and has no user quotas (unlike /tmp)
    _project_root = Path(__file__).resolve().parent.parent
    _nemo_tmp = _project_root / ".cache" / "nemo_tmp"
    _nemo_tmp.mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = str(_nemo_tmp)
    os.environ["TEMP"] = str(_nemo_tmp)
    os.environ["TMP"] = str(_nemo_tmp)

    # Re-exec this script with the updated environment
    # This ensures the dynamic linker sees the new LD_LIBRARY_PATH
    # and tempfile module uses the correct TMPDIR
    os.execv(sys.executable, [sys.executable] + sys.argv)
# =============================================================================

# ruff: noqa: E402
# The imports below MUST come after the CUDA configuration block above.
# The re-exec pattern requires setting LD_LIBRARY_PATH before Python loads
# native libraries like ctranslate2/faster-whisper.

import argparse
import atexit
import logging
import sys
import threading
import time
import sys
from pathlib import Path
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

# Import viewer storage functions from the backend database module
_backend_path = Path(__file__).parent.parent / "AUDIO_NOTEBOOK" / "backend"
if str(_backend_path) not in sys.path:
    sys.path.insert(0, str(_backend_path))
from database import save_longform_recording, get_word_timestamps_from_audio  # type: ignore[import-not-found]

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

# Canary transcription service (NeMo backend)
try:
    from CANARY import CanaryService, transcribe_audio as canary_transcribe

    HAS_CANARY = True
except ImportError:
    HAS_CANARY = False
    CanaryService = None  # type: ignore
    canary_transcribe = None  # type: ignore

# Simple audio recorder for Canary mode (no ML model required)
try:
    from canary_recorder import CanaryRecorder

    HAS_CANARY_RECORDER = True
except ImportError as e:
    logging.warning(f"CanaryRecorder not available: {e}")
    HAS_CANARY_RECORDER = False
    CanaryRecorder = None  # type: ignore

setup_logging()


class STTOrchestrator:
    """
    Main orchestrator for the Speech-to-Text system.
    Coordinates between different transcription modes and handles hotkey commands.

    Modes:
        - tray: System tray icon with longform + static transcription + web viewer (default)
        - static: CLI transcription of a single file
    """

    def __init__(
        self,
        mode: str = "tray",
        static_file: Optional[str] = None,
        api_port: int = 8000,
    ):
        """
        Initialize the orchestrator.

        Args:
            mode: Operating mode - "tray" or "static"
            static_file: Path to file for static transcription mode
            api_port: Port for web viewer backend (default 8000)
        """
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        # Use relative path - ConfigManager will look in project root
        self.config_path = "config.yaml"

        # Mode configuration
        self.mode = mode
        self.static_file = static_file
        self.api_port = api_port
        self.api_server = None
        self.open_browser = True  # Always open browser when starting web viewer

        # Application state (combining related attributes)
        self.app_state: dict[str, Optional[bool | str]] = {
            "running": False,
            "current_mode": None,  # Tracks "longform" or "static" or "api_transcription"
            "is_transcribing": False,  # Flag to manage audio feeding during transcription
            "models_loaded": False,  # Track if models are currently loaded
            "canary_mode": False,  # Track if Canary is active transcription backend
        }

        # Instances for transcription components
        self.main_transcriber: Optional[LongFormRecorder] = None
        self.preview_transcriber: Optional[LongFormRecorder] = None
        self.console_display: Optional[ConsoleDisplay] = None
        self.tray_manager: Optional["TrayIconManager"] = None
        self.static_transcriber: Optional[StaticFileTranscriber] = None

        # Canary transcription service (alternative to faster-whisper)
        self.canary_service: Optional[Any] = None  # CanaryService when available

        # Simple audio recorder for Canary mode (no ML model needed)
        self.canary_recorder: Optional[Any] = None  # CanaryRecorder when available

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
        self._audio_notebook_stop_handled = False  # Flag to coordinate shutdown

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
                toggle_canary_callback=self._toggle_canary_mode,
            )
        elif mode == "tray" and not HAS_TRAY:
            safe_print(
                "Could not initialize system tray icon. Please install PyQt6.", "warning"
            )

        # Initialize model manager with the loaded config
        self.model_manager = ModelManager(self.config, self.script_dir)

        # Register cleanup handler
        atexit.register(self.stop)

    def _get_standby_state(self) -> str:
        """Return the appropriate standby state based on current mode."""
        if self.app_state.get("canary_mode"):
            return "canary_standby"
        return "standby"

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

        # Check if audio notebook is running
        if self.audio_notebook_server is not None:
            safe_print(
                "Cannot start static transcription while Audio Notebook is running. "
                "Please stop the Audio Notebook first.",
                "warning",
            )
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
        def _worker():
            self.app_state["current_mode"] = "static"
            if self.tray_manager:
                self.tray_manager.set_state("static_transcribing")
                self.tray_manager.set_audio_notebook_enabled(False)
                self.tray_manager.set_recording_actions_enabled(False)

            try:
                # Check if we're in Canary mode - use Canary for transcription
                if self.app_state.get("canary_mode") and self.canary_service:
                    # Generate output file path
                    from pathlib import Path

                    source_path = Path(file_path)
                    output_file = str(
                        source_path.parent / f"{source_path.stem}_transcription.json"
                    )

                    success = self._transcribe_static_with_canary(file_path, output_file)
                    if self.tray_manager:
                        if success:
                            self.tray_manager.set_state("canary_standby")
                        else:
                            self.tray_manager.set_state("error")
                        self.tray_manager.set_recording_actions_enabled(True)
                        self.tray_manager.set_static_transcription_enabled(True)
                    return

                # Standard faster-whisper static transcription
                # Handle model switching/loading
                current_model_type = self.app_state.get("loaded_model_type")
                if current_model_type == "longform":
                    # Switching from longform to static
                    safe_print("Switching from longform to static model...", "info")
                    if self.tray_manager:
                        self.tray_manager.set_state("loading")
                    self._unload_all_models_sync()
                    self._load_static_model_sync()
                    self.app_state["loaded_model_type"] = "static"
                    if self.tray_manager:
                        self.tray_manager.set_state("static_transcribing")
                elif current_model_type != "static":
                    # No model loaded yet - load static model
                    safe_print("Loading static model...", "info")
                    if self.tray_manager:
                        self.tray_manager.set_state("loading")
                    self._load_static_model_sync()
                    self.app_state["loaded_model_type"] = "static"
                    if self.tray_manager:
                        self.tray_manager.set_state("static_transcribing")
                # else: already have static model loaded, keep it

                # Instantiate the transcriber WITHOUT main_transcriber
                # Pass config so it can get model settings
                self.static_transcriber = StaticFileTranscriber(
                    main_transcriber=None,
                    console_display=self.console_display,
                    config=self.config,
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
                # DON'T unload the static model - keep it for potential next static transcription
                # Model will only be unloaded when switching back to longform

                # Reset state after completion or failure
                self.app_state["current_mode"] = None
                self.static_transcriber = None
                if self.tray_manager:
                    # Check again because another operation might have started
                    if self.app_state["current_mode"] is None:
                        self.tray_manager.set_state(self._get_standby_state())
                    self.tray_manager.set_audio_notebook_enabled(True)
                    self.tray_manager.set_recording_actions_enabled(True)

        # Start thread - no longer needs transcriber argument
        threading.Thread(target=_worker, daemon=True).start()

    def _start_longform(self):
        """Start long-form recording."""
        if self.app_state["current_mode"]:
            safe_print(
                f"Cannot start long-form mode while in {self.app_state['current_mode']} "
                "mode. Please finish the current operation first."
            )
            return

        # Check if audio notebook is running
        if self.audio_notebook_server is not None:
            safe_print(
                "Cannot start recording while Audio Notebook is running. "
                "Please stop the Audio Notebook first.",
                "warning",
            )
            return

        # Check if we're in Canary mode
        if self.app_state.get("canary_mode"):
            self._start_longform_canary()
            return

        # Standard faster-whisper longform recording
        self._start_longform_whisper()

    def _start_longform_canary(self):
        """Start long-form recording using Canary mode (simple audio recorder)."""
        if not HAS_CANARY_RECORDER:
            safe_print("CanaryRecorder not available.", "error")
            return

        if not self.canary_service:
            safe_print(
                "Canary service not initialized. Please enable Canary mode first.",
                "error",
            )
            return

        # Initialize the Canary recorder if needed
        if not self.canary_recorder:
            if not HAS_CANARY_RECORDER or CanaryRecorder is None:
                safe_print("CanaryRecorder not available.", "error")
                return
            audio_config = self.config.get("audio", {})
            self.canary_recorder = CanaryRecorder(audio_config)

        if self.tray_manager:
            self.tray_manager.set_state("recording")
            self.tray_manager.set_static_transcription_enabled(False)
            self.tray_manager.set_audio_notebook_enabled(False)

        # Start console display
        try:
            if self.console_display:
                self.console_display.start(time.monotonic())
        except RuntimeError as error:
            logging.warning("Could not start console display: %s", error)
            safe_print(
                f"Terminal display too small. {error} Please resize your terminal and try again.",
                "error",
            )
            if self.tray_manager:
                self.tray_manager.set_state("canary_standby")
                self.tray_manager.set_audio_notebook_enabled(True)
            return

        safe_print("Starting long-form recording (Canary mode)...", "success")
        self.app_state["current_mode"] = "longform"

        # Start recording
        if not self.canary_recorder.start_recording():
            safe_print("Failed to start audio recording.", "error")
            self.app_state["current_mode"] = None
            if self.tray_manager:
                self.tray_manager.set_state("error")
                self.tray_manager.set_audio_notebook_enabled(True)
                self.tray_manager.set_static_transcription_enabled(True)
            return

    def _start_longform_whisper(self):
        """Start long-form recording using faster-whisper."""
        # Check if we need to switch models (from static to longform)
        current_model_type = self.app_state.get("loaded_model_type")

        if current_model_type == "static":
            # Need to switch from static to longform
            if self.tray_manager:
                self.tray_manager.set_state("loading")
                self.tray_manager.set_static_transcription_enabled(False)
                self.tray_manager.set_audio_notebook_enabled(False)

            safe_print("Switching from static to longform model...", "info")
            self._unload_all_models_sync()

            # Load the longform models
            try:
                self._load_longform_models_sync()
                self.app_state["loaded_model_type"] = "longform"
            except Exception as e:
                logging.error(f"Failed to load longform models: {e}", exc_info=True)
                safe_print(f"Error loading models: {e}", "error")
                if self.tray_manager:
                    self.tray_manager.set_state("error")
                    self.tray_manager.set_static_transcription_enabled(True)
                    self.tray_manager.set_audio_notebook_enabled(True)
                return

        elif current_model_type != "longform":
            # No model loaded, need to load longform
            if self.tray_manager:
                self.tray_manager.set_state("loading")
                self.tray_manager.set_static_transcription_enabled(False)
                self.tray_manager.set_audio_notebook_enabled(False)

            safe_print("Loading longform model...", "info")
            try:
                self._load_longform_models_sync()
                self.app_state["loaded_model_type"] = "longform"
            except Exception as e:
                logging.error(f"Failed to load longform models: {e}", exc_info=True)
                safe_print(f"Error loading models: {e}", "error")
                if self.tray_manager:
                    self.tray_manager.set_state("error")
                    self.tray_manager.set_static_transcription_enabled(True)
                    self.tray_manager.set_audio_notebook_enabled(True)
                return
        # else: longform model already loaded, just proceed

        active_transcriber = (
            self.preview_transcriber if self.preview_enabled else self.main_transcriber
        )

        if not self.main_transcriber or (self.preview_enabled and not active_transcriber):
            safe_print("Transcription models not available. Please check logs.", "error")
            if self.tray_manager:
                self.tray_manager.set_state("error")
                self.tray_manager.set_static_transcription_enabled(True)
                self.tray_manager.set_audio_notebook_enabled(True)
            return

        if self.tray_manager:
            self.tray_manager.set_state("recording")
            self.tray_manager.set_static_transcription_enabled(False)
            self.tray_manager.set_audio_notebook_enabled(False)

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
                self.tray_manager.set_audio_notebook_enabled(True)
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

        # Check if we're in Canary mode
        if self.app_state.get("canary_mode"):
            self._stop_longform_canary()
            return

        # Standard faster-whisper stop
        self._stop_longform_whisper()

    def _stop_longform_canary(self):
        """Stop long-form recording and transcribe using Canary."""

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

                if not self.canary_recorder:
                    safe_print("Canary recorder not available.", "error")
                    self.app_state["current_mode"] = None
                    if self.tray_manager:
                        self.tray_manager.set_state("error")
                        self.tray_manager.set_audio_notebook_enabled(True)
                    return

                safe_print("Stopping recording and transcribing with Canary...")

                # Stop recording and get audio
                audio_data = self.canary_recorder.stop_recording()

                if audio_data is None or len(audio_data) == 0:
                    safe_print("No audio captured.", "warning")
                    self.app_state["current_mode"] = None
                    if self.tray_manager:
                        self.tray_manager.set_state("canary_standby")
                        self.tray_manager.set_audio_notebook_enabled(True)
                        self.tray_manager.set_static_transcription_enabled(True)
                    return

                # Save audio to temp file
                temp_audio_path = self.canary_recorder.save_to_temp_file(audio_data)
                if not temp_audio_path:
                    safe_print("Failed to save audio to temp file.", "error")
                    self.app_state["current_mode"] = None
                    if self.tray_manager:
                        self.tray_manager.set_state("error")
                    return

                # Transcribe with Canary
                final_text = self._transcribe_with_canary(temp_audio_path)

                # Clean up temp file
                try:
                    os.remove(temp_audio_path)
                except Exception:
                    pass

                self.app_state["current_mode"] = None

                if self.console_display:
                    self.console_display.display_final_transcription(final_text or "")
                else:
                    rendered_text = final_text or "[No transcription captured]"
                    safe_print(
                        "\n--- Transcription (Canary) ---\n"
                        f"{rendered_text}\n"
                        "------------------------------\n"
                    )

                # Copy to clipboard
                if final_text and HAS_CANARY_RECORDER and CanaryRecorder is not None:
                    CanaryRecorder.copy_to_clipboard(final_text)

                if self.tray_manager:
                    self.tray_manager.set_state("canary_standby")

            except Exception as error:
                logging.error("Error stopping Canary recording: %s", error, exc_info=True)
                safe_print(f"Error during Canary transcription: {error}", "error")
            finally:
                self.app_state["is_transcribing"] = False
                self.app_state["current_mode"] = None

                if self.tray_manager:
                    self.tray_manager.set_state("canary_standby")
                    self.tray_manager.set_audio_notebook_enabled(True)
                    self.tray_manager.set_static_transcription_enabled(True)

        threading.Thread(target=_worker, daemon=True).start()

    def _stop_longform_whisper(self):
        """Stop long-form recording and transcribe using faster-whisper."""
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
                        self.tray_manager.set_audio_notebook_enabled(True)
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

                # DON'T unload longform models - keep them for potential next recording
                # Model will only be unloaded when switching to static/audio notebook

                if self.tray_manager:
                    self.tray_manager.set_state("standby")
                    self.tray_manager.set_audio_notebook_enabled(True)
                    self.tray_manager.set_static_transcription_enabled(True)

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
            from DIARIZATION.service import DiarizationService

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

    def _unload_all_models_sync(self) -> None:
        """
        Synchronously unload ALL models from GPU memory.

        This is a blocking call that waits until all models are unloaded.
        Used before switching between different transcription modes to ensure
        only one model is loaded at a time.
        """
        logging.info("Synchronous model unload starting...")

        # Clean up preview transcriber if it exists
        if self.preview_transcriber:
            try:
                logging.info("Cleaning up preview transcriber")
                self.preview_transcriber.clean_up()
                self.preview_transcriber = None
            except Exception as e:
                logging.error(f"Error unloading preview transcriber: {e}", exc_info=True)

        # Clean up main transcriber (longform model)
        if self.main_transcriber:
            try:
                logging.info("Cleaning up main transcriber")
                self.main_transcriber.clean_up()
                self.main_transcriber = None
            except Exception as e:
                logging.error(f"Error unloading main transcriber: {e}", exc_info=True)

        # Clean up cached static transcriber model
        try:
            from static_transcriber import unload_cached_whisper_model

            logging.info("Unloading cached static transcriber model")
            unload_cached_whisper_model()
        except Exception as e:
            logging.error(f"Error unloading static transcriber model: {e}", exc_info=True)

        # Clean up models in model manager
        try:
            logging.info("Cleaning up model manager")
            self.model_manager.cleanup_all_models()
        except Exception as e:
            logging.error(f"Error in model manager cleanup: {e}", exc_info=True)

        # Force GPU cache clear
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                logging.info("GPU cache cleared")
        except Exception as e:
            logging.debug(f"Could not clear GPU cache: {e}")

        self.app_state["models_loaded"] = False
        logging.info("Synchronous model unload completed")

    def _load_longform_models_sync(self) -> None:
        """
        Synchronously load longform transcription models.

        This is a blocking call that loads the main_transcriber (and optionally
        preview_transcriber if preview is enabled).
        """
        logging.info("Synchronous longform model load starting...")

        try:
            # Load models based on configuration
            if self.preview_enabled:
                safe_print("Loading preview + main transcriber models...", "info")
                self._load_dual_transcriber_mode()
            else:
                safe_print("Loading main transcriber model...", "info")
                self._load_single_transcriber_mode()

            if self.main_transcriber:
                self.app_state["models_loaded"] = True
                safe_print("Longform models loaded successfully.", "success")
                logging.info("Longform models loaded")

                # Restart preview transcription if enabled
                if self.preview_enabled and self.preview_transcriber:
                    self.preview_transcriber.start_chunked_transcription(
                        self._handle_preview_sentence
                    )

                if self.tray_manager:
                    self.tray_manager.update_models_menu_item(models_loaded=True)
            else:
                raise RuntimeError("Main transcriber failed to initialize")

        except Exception as e:
            logging.error(f"Failed to load longform models: {e}", exc_info=True)
            raise

    def _load_static_model_sync(self) -> None:
        """
        Synchronously load the static transcription model.

        This pre-loads the cached Whisper model used by StaticFileTranscriber
        so it's ready for immediate use when transcription is requested.
        """
        logging.info("Synchronous static model load starting...")

        try:
            from static_transcriber import get_cached_whisper_model

            # Get model configuration from main_transcriber config
            main_config = self.config.get("main_transcriber", {})
            model_path = main_config.get("model", "Systran/faster-whisper-large-v3")
            compute_type = main_config.get("compute_type", "default")
            device = main_config.get("device", "cuda")

            safe_print(f"Loading static model '{model_path}'...", "info")

            # This will load and cache the model
            get_cached_whisper_model(model_path, device, compute_type)

            self.app_state["models_loaded"] = True
            safe_print("Static model loaded successfully.", "success")
            logging.info("Static model loaded and cached")

            if self.tray_manager:
                self.tray_manager.update_models_menu_item(models_loaded=True)

        except Exception as e:
            logging.error(f"Failed to load static model: {e}", exc_info=True)
            raise

    def _unload_models(self):
        """Unload all transcription models to free GPU memory (async version for menu)."""
        if not self.app_state["models_loaded"]:
            safe_print("Models are already unloaded.", "info")
            return

        def _worker():
            try:
                if self.tray_manager:
                    self.tray_manager.set_state("loading")

                safe_print("Unloading transcription models...", "info")

                # Use the synchronous unload
                self._unload_all_models_sync()

                # Clear the loaded model type since nothing is loaded now
                self.app_state["loaded_model_type"] = None

                safe_print("All models unloaded successfully.", "success")

                if self.tray_manager:
                    self.tray_manager.set_state("unloaded")
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
        """Start the Audio Notebook server in a background thread.

        Uses lazy model loading: the static Whisper model is NOT loaded on startup.
        Instead, it will be loaded on-demand when a transcription is requested,
        and unloaded immediately after completion to free VRAM for LLM usage.
        """
        if self.audio_notebook_thread and self.audio_notebook_thread.is_alive():
            safe_print("Audio Notebook is already running.", "warning")
            return

        # Handle model unloading - we DON'T load static model here anymore (lazy loading)
        current_model_type = self.app_state.get("loaded_model_type")

        if current_model_type is not None:
            # Unload any currently loaded model to free VRAM
            if self.tray_manager:
                self.tray_manager.set_state("loading")
                self.tray_manager.set_recording_actions_enabled(False)

            safe_print(
                f"Unloading {current_model_type} model for Audio Notebook (lazy loading enabled)...",
                "info",
            )
            self._unload_all_models_sync()
            self.app_state["loaded_model_type"] = None
            self.app_state["models_loaded"] = False
            safe_print(
                "Model unloaded. Whisper will load on-demand when transcription is requested.",
                "info",
            )
        # If no model was loaded, we're ready to go with lazy loading

        def server_worker():
            try:
                from fastapi import FastAPI
                from fastapi.middleware.cors import CORSMiddleware
                from fastapi.staticfiles import StaticFiles
                from fastapi.responses import FileResponse
                from pydantic import BaseModel
                import uvicorn
            except ImportError as e:
                safe_print(f"FastAPI or uvicorn not installed: {e}", "error")
                return

            # Import the AUDIO_NOTEBOOK/backend modules
            import sys

            backend_path = os.path.join(
                self.script_dir, "..", "AUDIO_NOTEBOOK", "backend"
            )
            if backend_path not in sys.path:
                sys.path.insert(0, backend_path)

            try:
                from database import init_db  # type: ignore[import-not-found]
                from routers import recordings, search, transcribe, llm  # type: ignore[import-not-found]
                from webapp_logging import setup_webapp_logging  # type: ignore[import-not-found]
            except ImportError as e:
                safe_print(
                    f"Failed to import AUDIO_NOTEBOOK/backend modules: {e}", "error"
                )
                return

            # Initialize webapp logging (creates webapp.log in project root, wiped on each start)
            webapp_logger = setup_webapp_logging()

            # Initialize database
            webapp_logger.info("Initializing database...")
            init_db()
            webapp_logger.info("Database initialized")

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

            # Include routers from AUDIO_NOTEBOOK/backend
            app.include_router(
                recordings.router, prefix="/api/recordings", tags=["recordings"]
            )
            app.include_router(search.router, prefix="/api/search", tags=["search"])
            app.include_router(
                transcribe.router, prefix="/api/transcribe", tags=["transcribe"]
            )
            app.include_router(llm.router, prefix="/api/llm", tags=["llm"])

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
                # Models are loaded on-demand, so status is always "ok" when server is running
                return HealthResponse(
                    status="ok",
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

            # Serve the built frontend static files
            frontend_dist = os.path.join(self.script_dir, "..", "AUDIO_NOTEBOOK", "dist")
            if os.path.exists(frontend_dist):
                # Mount static assets (JS, CSS, etc.)
                app.mount(
                    "/assets",
                    StaticFiles(directory=os.path.join(frontend_dist, "assets")),
                    name="assets",
                )

                # Serve index.html for root and SPA fallback routes
                @app.get("/")
                async def serve_root():
                    return FileResponse(os.path.join(frontend_dist, "index.html"))

                # SPA fallback - catch all non-API routes
                @app.get("/{full_path:path}")
                async def serve_spa(full_path: str):
                    # Don't intercept API routes or docs
                    if full_path.startswith(("api/", "docs", "openapi.json")):
                        return None
                    file_path = os.path.join(frontend_dist, full_path)
                    if os.path.exists(file_path) and os.path.isfile(file_path):
                        return FileResponse(file_path)
                    # Return index.html for SPA routes
                    return FileResponse(os.path.join(frontend_dist, "index.html"))
            else:
                safe_print(
                    "Frontend not built. Run 'npm run build' in AUDIO_NOTEBOOK/",
                    "warning",
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

            # Update tray menu and icon state, disable other operations
            if self.tray_manager:
                self.tray_manager.update_audio_notebook_menu_item(True)
                self.tray_manager.set_state("audio_notebook")
                self.tray_manager.set_recording_actions_enabled(False)
                self.tray_manager.set_static_transcription_enabled(False)

            safe_print(
                f"Audio Notebook started on http://localhost:{self.api_port}", "success"
            )
            safe_print(f"  API Docs: http://localhost:{self.api_port}/docs", "info")

            # Open browser to frontend (or docs if frontend not built)
            if self.open_browser:
                import webbrowser

                frontend_dist = os.path.join(
                    self.script_dir, "..", "AUDIO_NOTEBOOK", "dist"
                )
                if os.path.exists(frontend_dist):
                    webbrowser.open(f"http://localhost:{self.api_port}/")
                else:
                    webbrowser.open(f"http://localhost:{self.api_port}/docs")

            # Run the server (blocks until stopped)
            server.run()

            # Cleanup after server stops
            # Check if _stop_audio_notebook already handled the model reload
            if getattr(self, "_audio_notebook_stop_handled", False):
                # Reset the flag and skip - _stop_audio_notebook is handling the reload
                self._audio_notebook_stop_handled = False
                self.audio_notebook_server = None
                logging.info(
                    "Server stopped - model reload handled by _stop_audio_notebook"
                )
                return

            # If we get here, the server stopped on its own (e.g., error or external signal)
            # We need to handle the cleanup ourselves
            self.audio_notebook_server = None
            if self.tray_manager:
                self.tray_manager.update_audio_notebook_menu_item(False)
                self.tray_manager.set_state("loading")

            safe_print("Audio Notebook stopped. Switching to longform model...", "info")

            try:
                # Unload the static model
                self._unload_all_models_sync()

                # Load the longform models
                self._load_longform_models_sync()
                self.app_state["loaded_model_type"] = "longform"

                if self.tray_manager:
                    self.tray_manager.set_state("standby")
                    self.tray_manager.set_recording_actions_enabled(True)
                    self.tray_manager.set_static_transcription_enabled(True)

                safe_print("Longform model loaded. Ready for recording.", "success")
            except Exception as e:
                logging.error(
                    f"Failed to load longform models after Audio Notebook: {e}",
                    exc_info=True,
                )
                safe_print(f"Error loading longform model: {e}", "error")
                if self.tray_manager:
                    self.tray_manager.set_state("unloaded")
                    self.tray_manager.set_recording_actions_enabled(True)
                    self.tray_manager.set_static_transcription_enabled(True)

        self.audio_notebook_thread = threading.Thread(target=server_worker, daemon=True)
        self.audio_notebook_thread.start()

    def _stop_audio_notebook(self):
        """Stop the Audio Notebook server, eject LLM model, and reload the main (longform) model."""
        if self.audio_notebook_server:
            safe_print("Stopping Audio Notebook...", "info")

            # Set flag to indicate we're handling the model reload here
            # This prevents the server_worker cleanup code from also trying to reload
            self._audio_notebook_stop_handled = True

            self.audio_notebook_server.should_exit = True
            self.audio_notebook_server = None

            if self.tray_manager:
                self.tray_manager.update_audio_notebook_menu_item(False)

            # Eject LM Studio model to free VRAM for Whisper
            safe_print("Ejecting LM Studio model...", "info")
            try:
                import shutil
                import subprocess

                if shutil.which("lms"):
                    result = subprocess.run(
                        ["lms", "unload", "--all"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if result.returncode == 0:
                        safe_print("LM Studio model ejected.", "success")
                    else:
                        # Not an error - model may not have been loaded
                        logging.debug(
                            f"lms unload output: {result.stdout} {result.stderr}"
                        )
            except Exception as e:
                # Don't fail the whole operation if LM Studio isn't available
                logging.debug(f"Could not eject LM Studio model: {e}")

            # Switch from static to longform model automatically
            safe_print("Switching back to longform model...", "info")
            if self.tray_manager:
                self.tray_manager.set_state("loading")

            try:
                # Unload the static model
                self._unload_all_models_sync()

                # Load the longform models
                self._load_longform_models_sync()
                self.app_state["loaded_model_type"] = "longform"

                if self.tray_manager:
                    self.tray_manager.set_state("standby")
                    self.tray_manager.set_recording_actions_enabled(True)
                    self.tray_manager.set_static_transcription_enabled(True)

                safe_print("Longform model loaded. Ready for recording.", "success")
            except Exception as e:
                logging.error(
                    f"Failed to load longform models after stopping Audio Notebook: {e}",
                    exc_info=True,
                )
                safe_print(f"Error loading longform model: {e}", "error")
                if self.tray_manager:
                    self.tray_manager.set_state("unloaded")
                    self.tray_manager.set_recording_actions_enabled(True)
                    self.tray_manager.set_static_transcription_enabled(True)

    # =========================================================================
    # Canary Transcription Mode Methods
    # =========================================================================

    def _toggle_canary_mode(self) -> None:
        """Toggle Canary transcription mode on/off."""
        if self.app_state.get("canary_mode"):
            self._deactivate_canary_mode()
        else:
            self._activate_canary_mode()

    def _activate_canary_mode(self) -> None:
        """Activate Canary as the transcription backend."""
        if not HAS_CANARY:
            safe_print(
                "Canary service not available. Make sure CANARY module is installed.",
                "error",
            )
            return

        # Check if Canary is enabled in config
        canary_config = self.config.get("canary_transcriber", {})
        if not canary_config.get("enabled", False):
            safe_print(
                "Canary is disabled in config.yaml. "
                "Set canary_transcriber.enabled: true to use it.",
                "warning",
            )
            return

        # Don't allow switching during active recording or transcription
        if self.app_state.get("current_mode"):
            safe_print(
                f"Cannot switch to Canary while in {self.app_state['current_mode']} mode. "
                "Please finish the current operation first.",
                "warning",
            )
            return

        safe_print("Activating Canary transcription mode...", "info")

        if self.tray_manager:
            self.tray_manager.set_state("loading")
            self.tray_manager.set_recording_actions_enabled(False)
            self.tray_manager.set_static_transcription_enabled(False)

        def _activate_worker():
            try:
                # First, unload any existing faster-whisper models to free VRAM
                safe_print("Unloading faster-whisper models to free VRAM...", "info")
                self._unload_all_models_sync()

                # Get Canary settings from config
                language = canary_config.get("language", "en")
                device = canary_config.get("device", "cuda")
                beam_size = canary_config.get("beam_size", 1)

                # Initialize Canary service
                if CanaryService is None:
                    raise RuntimeError("CanaryService class not available")
                self.canary_service = CanaryService(default_language=language)

                # Start the Canary server (loads the model)
                safe_print(
                    "Starting Canary server (this may take ~20 seconds)...", "info"
                )
                if self.canary_service is None or not self.canary_service.start_server(
                    device=device,
                    beam_size=beam_size,
                    wait_ready=True,
                ):
                    raise RuntimeError("Canary server failed to start")

                self.app_state["canary_mode"] = True

                if self.tray_manager:
                    self.tray_manager.update_canary_menu_item(True)
                    self.tray_manager.set_state("canary_standby")
                    self.tray_manager.set_recording_actions_enabled(True)
                    self.tray_manager.set_static_transcription_enabled(True)

                safe_print("Canary mode activated! Ready for transcription.", "success")

            except Exception as e:
                logging.error(f"Failed to activate Canary mode: {e}", exc_info=True)
                safe_print(f"Error activating Canary: {e}", "error")

                if self.canary_service:
                    self.canary_service.stop_server()
                    self.canary_service = None

                if self.tray_manager:
                    self.tray_manager.update_canary_menu_item(False)
                    self.tray_manager.set_state("standby")
                    self.tray_manager.set_recording_actions_enabled(True)
                    self.tray_manager.set_static_transcription_enabled(True)

        threading.Thread(target=_activate_worker, daemon=True).start()

    def _deactivate_canary_mode(self) -> None:
        """Deactivate Canary and return to faster-whisper."""
        if not self.app_state.get("canary_mode"):
            return

        # Don't allow switching during active recording or transcription
        if self.app_state.get("current_mode"):
            safe_print(
                f"Cannot deactivate Canary while in {self.app_state['current_mode']} mode. "
                "Please finish the current operation first.",
                "warning",
            )
            return

        safe_print("Deactivating Canary mode...", "info")

        if self.tray_manager:
            self.tray_manager.set_state("loading")

        def _deactivate_worker():
            try:
                # Clean up Canary recorder
                if self.canary_recorder:
                    self.canary_recorder.clean_up()
                    self.canary_recorder = None

                # Stop the Canary server
                if self.canary_service:
                    self.canary_service.stop_server()
                    self.canary_service = None

                self.app_state["canary_mode"] = False

                if self.tray_manager:
                    self.tray_manager.update_canary_menu_item(False)
                    self.tray_manager.set_state("standby")

                safe_print("Canary mode deactivated. Using faster-whisper.", "success")

            except Exception as e:
                logging.error(f"Error deactivating Canary mode: {e}", exc_info=True)
                safe_print(f"Error deactivating Canary: {e}", "error")

                if self.tray_manager:
                    self.tray_manager.set_state("standby")

        threading.Thread(target=_deactivate_worker, daemon=True).start()

    def _transcribe_with_canary(self, audio_path: str) -> Optional[str]:
        """
        Transcribe audio using the Canary service.

        Args:
            audio_path: Path to the audio file

        Returns:
            Transcription text or None on error
        """
        if not self.canary_service:
            safe_print("Canary service not initialized", "error")
            return None

        canary_config = self.config.get("canary_transcriber", {})
        language = canary_config.get("language", "en")
        pnc = canary_config.get("punctuation", True)

        try:
            result = self.canary_service.transcribe(
                audio_path,
                language=language,
                pnc=pnc,
            )
            return result.text
        except Exception as e:
            logging.error(f"Canary transcription error: {e}", exc_info=True)
            safe_print(f"Canary transcription failed: {e}", "error")
            return None

    def _transcribe_static_with_canary(self, file_path: str, output_file: str) -> bool:
        """
        Transcribe a static file using Canary and save the result.

        Args:
            file_path: Path to the audio file
            output_file: Path for the output JSON file

        Returns:
            True if successful, False otherwise
        """
        if not self.canary_service:
            safe_print("Canary service not initialized", "error")
            return False

        canary_config = self.config.get("canary_transcriber", {})
        language = canary_config.get("language", "en")
        pnc = canary_config.get("punctuation", True)

        try:
            safe_print(f"Transcribing with Canary (language: {language})...", "info")

            result = self.canary_service.transcribe(
                file_path,
                language=language,
                pnc=pnc,
            )

            # Build output similar to faster-whisper format
            import json

            output_data = {
                "text": result.text,
                "language": result.language,
                "duration": result.duration,
                "processing_time": result.processing_time,
                "engine": "canary",
                "word_timestamps": [w.to_dict() for w in result.word_timestamps],
            }

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)

            safe_print(f"Transcription saved to: {output_file}", "success")
            safe_print(
                f"Duration: {result.duration:.1f}s, "
                f"Processing: {result.processing_time:.1f}s, "
                f"Speed: {result.duration / result.processing_time:.1f}x realtime",
                "info",
            )

            return True

        except Exception as e:
            logging.error(f"Canary static transcription error: {e}", exc_info=True)
            safe_print(f"Canary transcription failed: {e}", "error")
            return False

    def _deactivate_canary_mode_sync(self) -> None:
        """Synchronously deactivate Canary mode."""
        if not self.app_state.get("canary_mode"):
            return

        try:
            if self.canary_recorder:
                self.canary_recorder.clean_up()
                self.canary_recorder = None

            if self.canary_service:
                self.canary_service.stop_server()
                self.canary_service = None

            self.app_state["canary_mode"] = False

            if self.tray_manager:
                self.tray_manager.update_canary_menu_item(False)

        except Exception as e:
            logging.error(f"Error in sync Canary deactivation: {e}", exc_info=True)

    def _quit(self):
        """Signals the application to stop and exit gracefully."""
        if self.app_state.get("shutdown_in_progress"):
            return
        self.app_state["shutdown_in_progress"] = True
        safe_print("Quit requested, shutting down...")

        def shutdown_worker():
            # Clean up Canary recorder if running
            if self.canary_recorder:
                self.canary_recorder.clean_up()
                self.canary_recorder = None
            # Stop Canary service if running
            if self.canary_service:
                self.canary_service.stop_server()
                self.canary_service = None
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

        safe_print("Transcribing: {input_path.name}", "info")

        # Create static transcriber with config (no main_transcriber needed)
        # The static transcriber will load its own model via get_cached_whisper_model
        self.static_transcriber = StaticFileTranscriber(
            main_transcriber=None,
            console_display=self.console_display,
            config=self.config,
        )

        # Get static transcription settings from config
        static_config = self.config.get("static_transcription", {})
        enable_diarization = static_config.get("enable_diarization", False)
        max_segment_chars = static_config.get("max_segment_chars", 500)
        language = self.config.get("transcription_options", {}).get("language")

        # Generate output file path
        output_file = str(input_path.parent / f"{input_path.stem}_transcription.json")

        if enable_diarization and self.static_transcriber.is_diarization_available():
            safe_print("Diarization enabled - will identify speakers", "info")
            self.static_transcriber.transcribe_file_with_diarization(
                str(input_path),
                output_file=output_file,
                output_format="json",
                language=language,
                max_segment_chars=max_segment_chars,
            )
        else:
            self.static_transcriber.transcribe_file_with_word_timestamps(
                str(input_path),
                output_file=output_file,
                language=language,
                max_segment_chars=max_segment_chars,
            )

        # Unload models before exiting
        self._unload_all_models_sync()

        safe_print(f"Output saved to: {output_file}", "success")
        self.stop()

    def _run_tray_mode(self):
        """Run the traditional tray icon mode."""

        # Preload longform models at startup
        def preload_startup_models():
            if self.tray_manager:
                self.tray_manager.set_state("loading")  # Grey icon

            try:
                show_waveform = self.config.get("display", {}).get("show_waveform", True)
                self.console_display = ConsoleDisplay(
                    show_waveform=show_waveform, show_preview=self.preview_enabled
                )
            except Exception as exc:
                logging.error("Failed to initialise console display: %s", exc)
                self.console_display = None

            # Preload longform models at startup
            if self.preview_enabled:
                safe_print("Pre-loading transcription models (with preview)...", "info")
                self._load_dual_transcriber_mode()
            else:
                safe_print(
                    "Pre-loading transcription model (preview disabled)...", "info"
                )
                self._load_single_transcriber_mode()

            success = self.main_transcriber is not None

            if success:
                self.app_state["models_loaded"] = True
                self.app_state["loaded_model_type"] = (
                    "longform"  # Track which model is loaded
                )
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

    async def _api_transcribe(
        self,
        wav_path: str,
        enable_diarization: bool,
        enable_word_timestamps: bool,
        language: Optional[str],
    ) -> dict:
        """
        Transcribe an audio file via the API.

        This uses the StaticFileTranscriber which handles model loading internally
        via get_cached_whisper_model(). No pre-loaded models are required.
        """
        from pathlib import Path
        import asyncio

        wav_file = Path(wav_path)
        if not wav_file.exists():
            raise RuntimeError(f"Audio file not found: {wav_path}")

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

        # Set tray icon to pastel mauve during transcription
        if self.tray_manager:
            self.tray_manager.set_state("static_transcribing")

        try:
            # Read audio file to get duration
            audio_data, sample_rate = sf.read(wav_path, dtype="float32")
            audio_duration = len(audio_data) / sample_rate
            logging.info(f"Audio duration: {audio_duration:.2f} seconds")

            # Get static transcription settings
            static_config = self.config.get("static_transcription", {})
            max_segment_chars = static_config.get("max_segment_chars", 500)

            # Create static transcriber with config (no main_transcriber needed)
            # The static transcriber loads its own model via get_cached_whisper_model()
            static_transcriber = StaticFileTranscriber(
                main_transcriber=None,
                console_display=self.console_display,
                config=self.config,
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

        finally:
            # Unload the Whisper model immediately after transcription to free VRAM for LLM
            # This is part of lazy loading - model is loaded on-demand and unloaded after use
            from static_transcriber import unload_cached_whisper_model

            safe_print("Unloading Whisper model to free VRAM for LLM...", "info")
            unload_cached_whisper_model()
            self.app_state["models_loaded"] = False
            self.app_state["loaded_model_type"] = None
            logging.info("Whisper model unloaded after transcription (lazy loading)")

            # Restore tray icon to audio_notebook state after transcription
            if self.tray_manager and self.audio_notebook_server is not None:
                self.tray_manager.set_state("audio_notebook")

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
  (default)        Run with system tray (longform + static transcription + web viewer)
  --static FILE    Transcribe a single file and exit

Examples:
  %(prog)s                        Run in tray icon mode (default)
  %(prog)s --static recording.wav Transcribe file to .txt
""",
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
        help="Port for web viewer backend (default: 8000)",
    )

    args = parser.parse_args()

    # Determine mode
    if args.static:
        mode = "static"
    else:
        mode = "tray"

    orchestrator = STTOrchestrator(
        mode=mode,
        static_file=args.static,
        api_port=args.port,
    )
    orchestrator.run()
