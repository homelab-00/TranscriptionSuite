"""
Main orchestrator for the native client.

Coordinates tray, audio recording, and server communication.
This is the central controller for all client operations.
"""

import asyncio
import concurrent.futures
import logging
import threading
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dashboard.common.api_client import APIClient, ServerBusyError
from dashboard.common.audio_recorder import AudioRecorder
from dashboard.common.config import ClientConfig
from dashboard.common.models import TrayAction, TrayState

if TYPE_CHECKING:
    from dashboard.common.tray_base import AbstractTray

logger = logging.getLogger(__name__)

# Maximum number of automatic reconnection attempts
MAX_RECONNECT_ATTEMPTS = 10


class ClientOrchestrator:
    """
    Native client orchestrator.

    Manages:
    - System tray lifecycle
    - Audio recording
    - Server communication
    - Clipboard operations
    - State transitions
    """

    def __init__(
        self,
        config: ClientConfig,
        auto_connect: bool = True,
        auto_copy_clipboard: bool = True,
    ):
        """
        Initialize the orchestrator.

        Args:
            config: Client configuration
            auto_connect: Automatically connect to server on start
            auto_copy_clipboard: Copy transcription to clipboard automatically
        """
        self.config = config
        self.auto_connect = auto_connect
        self.auto_copy_clipboard = auto_copy_clipboard

        # Components
        self.tray: AbstractTray | None = None
        self.api_client: APIClient | None = None
        self.recorder: AudioRecorder | None = None

        # Async event loop management
        self.event_loop: asyncio.AbstractEventLoop | None = None
        self.async_thread: threading.Thread | None = None
        self._loop_ready = threading.Event()

        # State (protected by lock for thread safety)
        self._state_lock = threading.Lock()
        self.is_recording = False
        self.is_transcribing = False  # Track if transcription is in progress
        self.last_transcription: str | None = None
        self._reconnect_task: concurrent.futures.Future[Any] | None = None
        self._is_initial_connection = (
            True  # Track if this is the first connection attempt
        )

    def start(self, tray: "AbstractTray") -> None:
        """
        Start the native client with the given tray implementation.

        Args:
            tray: Platform-specific tray implementation
        """
        logger.info("Starting TranscriptionSuite Native Client")
        self.tray = tray

        # Register callbacks
        self._register_callbacks()

        # Start async event loop in background thread
        self.async_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.async_thread.start()

        # Wait for event loop to be ready
        if not self._loop_ready.wait(timeout=5.0):
            logger.error("Event loop failed to start")
            return

        # Connect to server if auto_connect is enabled
        if self.auto_connect:
            self._schedule_async(self._connect_to_server())

        # Run tray (blocks until quit)
        self.tray.run()

    def _register_callbacks(self) -> None:
        """Register action callbacks with the tray."""
        if not self.tray:
            return

        self.tray.register_callback(
            TrayAction.START_RECORDING, self._on_start_recording
        )
        self.tray.register_callback(TrayAction.STOP_RECORDING, self._on_stop_recording)
        self.tray.register_callback(
            TrayAction.CANCEL_RECORDING, self._on_cancel_recording
        )
        self.tray.register_callback(
            TrayAction.TRANSCRIBE_FILE, self._on_transcribe_file
        )
        self.tray.register_callback(
            TrayAction.OPEN_AUDIO_NOTEBOOK, self._on_open_notebook
        )
        self.tray.register_callback(TrayAction.SETTINGS, self._on_settings)
        self.tray.register_callback(TrayAction.RECONNECT, self._on_reconnect)
        self.tray.register_callback(TrayAction.QUIT, self._on_quit)

    def _run_async_loop(self) -> None:
        """Run the asyncio event loop in a background thread."""
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)
        self._loop_ready.set()
        self.event_loop.run_forever()

    def _schedule_async(self, coro) -> concurrent.futures.Future[Any]:
        """Schedule a coroutine on the async event loop."""
        if self.event_loop:
            return asyncio.run_coroutine_threadsafe(coro, self.event_loop)
        raise RuntimeError("Event loop not running")

    # =========================================================================
    # Server Connection
    # =========================================================================

    async def _connect_to_server(self) -> None:
        """Connect to the container server."""
        if self.tray:
            self.tray.set_state(TrayState.CONNECTING)

        # Create API client
        self.api_client = APIClient(
            host=self.config.server_host,
            port=self.config.server_port,
            use_https=self.config.use_https,
            token=self.config.token,
            timeout=self.config.get("server", "timeout", default=30),
            transcription_timeout=self.config.get(
                "server", "transcription_timeout", default=300
            ),
            tls_verify=self.config.get("server", "tls_verify", default=True),
            allow_insecure_http=self.config.get(
                "server", "allow_insecure_http", default=False
            ),
        )

        # Test connection
        if await self.api_client.health_check():
            # In HTTPS mode, validate token before proceeding
            if self.config.use_https:
                is_valid, error_msg = await self.api_client.validate_token()
                if not is_valid:
                    logger.error(f"Authentication failed: {error_msg}")
                    if self.tray:
                        self.tray.set_state(TrayState.DISCONNECTED)
                        self.tray.show_notification(
                            "Authentication Failed",
                            error_msg or "Invalid or missing token",
                        )
                    return
                logger.info("Token authentication successful")

            if self.tray:
                self.tray.set_state(TrayState.STANDBY)
                self.tray.show_notification(
                    "Connected",
                    f"Connected to TranscriptionSuite at {self.config.server_host}",
                )

            # Optionally preload the model
            logger.info("Preloading transcription model...")
            await self.api_client.preload_model()

        else:
            if self.tray:
                self.tray.set_state(TrayState.DISCONNECTED)
                self.tray.show_notification(
                    "Connection Failed",
                    f"Could not connect to {self.config.server_host}:{self.config.server_port}",
                )

            # Mark that we've attempted initial connection
            self._is_initial_connection = False

            # Start reconnection attempts if enabled
            if self.config.get("server", "auto_reconnect", default=True):
                self._start_reconnect_loop()

    def _start_reconnect_loop(self) -> None:
        """Start automatic reconnection attempts."""
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = self._schedule_async(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Periodically attempt to reconnect (up to MAX_RECONNECT_ATTEMPTS times)."""
        interval = self.config.get("server", "reconnect_interval", default=10)
        attempt = 0

        while attempt < MAX_RECONNECT_ATTEMPTS:
            await asyncio.sleep(interval)

            if self.api_client and self.api_client.is_connected:
                break  # Already connected

            attempt += 1
            logger.info(
                f"Attempting to reconnect ({attempt}/{MAX_RECONNECT_ATTEMPTS})..."
            )

            if self.api_client and await self.api_client.health_check():
                if self.tray:
                    self.tray.set_state(TrayState.STANDBY)
                    self.tray.show_notification("Reconnected", "Connection restored")
                break
        else:
            # Max retries reached
            logger.warning(
                f"Max reconnection attempts ({MAX_RECONNECT_ATTEMPTS}) reached"
            )
            if self.tray:
                self.tray.show_notification(
                    "Connection Failed",
                    f"Could not connect after {MAX_RECONNECT_ATTEMPTS} attempts. "
                    "Use Settings to reconfigure.",
                )

    # =========================================================================
    # Recording Actions
    # =========================================================================

    def _on_start_recording(self) -> None:
        """Handle start recording action."""
        with self._state_lock:
            if self.is_recording:
                logger.warning("Already recording")
                return

            if not self.api_client or not self.api_client.is_connected:
                if self.tray:
                    self.tray.show_notification(
                        "Not Connected",
                        "Please wait for server connection",
                    )
                return

            self.is_recording = True

        if self.tray:
            self.tray.set_state(TrayState.RECORDING)

        # Initialize recorder
        try:
            device_index = self.config.get("recording", "device_index")
            sample_rate = self.config.get("recording", "sample_rate", default=16000)

            self.recorder = AudioRecorder(
                sample_rate=sample_rate,
                device_index=device_index,
            )
            self.recorder.start()
            logger.info("Recording started")

        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            with self._state_lock:
                self.is_recording = False
            if self.tray:
                self.tray.set_state(TrayState.ERROR)
                self.tray.show_notification("Error", f"Failed to start recording: {e}")

    def _on_stop_recording(self) -> None:
        """Handle stop recording action."""
        with self._state_lock:
            if not self.is_recording or not self.recorder:
                return
            self.is_recording = False

        if self.tray:
            self.tray.set_state(TrayState.UPLOADING)

        # Get recorded audio as WAV bytes
        try:
            audio_data = self.recorder.stop()
            self.recorder = None

            # Transcribe
            self._schedule_async(self._transcribe_audio(audio_data))

        except Exception as e:
            logger.error(f"Failed to stop recording: {e}")
            if self.tray:
                self.tray.set_state(TrayState.ERROR)
                self.tray.show_notification("Error", str(e))

    def _on_cancel_recording(self) -> None:
        """Handle cancel recording/transcription action."""
        # Cancel recording if in progress
        with self._state_lock:
            if self.is_recording and self.recorder:
                self.is_recording = False
                try:
                    self.recorder.cancel()
                except Exception:
                    logger.debug("Failed to cancel recorder during cleanup")
                self.recorder = None

            if self.tray:
                self.tray.set_state(TrayState.STANDBY)
                self.tray.show_notification("Cancelled", "Recording cancelled")

            logger.info("Recording cancelled")
            return

        # Cancel transcription if in progress
        with self._state_lock:
            is_transcribing = self.is_transcribing

        if is_transcribing:
            self._schedule_async(self._cancel_transcription())

    async def _cancel_transcription(self) -> None:
        """Request cancellation of the current transcription."""
        if not self.api_client:
            return

        logger.info("Requesting transcription cancellation...")
        result = await self.api_client.cancel_transcription()

        if result.get("success"):
            logger.info(f"Cancellation requested: {result.get('message')}")
            if self.tray:
                self.tray.show_notification(
                    "Cancelling", "Transcription cancellation requested"
                )
        else:
            logger.warning(f"Cancellation failed: {result.get('message')}")
            if self.tray:
                self.tray.show_notification(
                    "Cancel Failed", result.get("message", "Unknown error")
                )

    async def _transcribe_audio(self, audio_data: bytes) -> None:
        """Send audio to server for transcription."""
        if not self.api_client:
            return

        with self._state_lock:
            self.is_transcribing = True

        try:
            if self.tray:
                self.tray.set_state(TrayState.TRANSCRIBING)

            result = await self.api_client.transcribe_audio_data(
                audio_data,
                on_progress=lambda msg: logger.info(msg),
            )

            self.last_transcription = result.get("text", "")

            # Copy to clipboard
            if self.last_transcription and self.auto_copy_clipboard:
                self._copy_to_clipboard(self.last_transcription)

                # Show notification with preview
                preview = self.last_transcription[:100]
                if len(self.last_transcription) > 100:
                    preview += "..."

                if self.tray:
                    self.tray.show_notification(
                        "Transcription Complete",
                        f"Copied to clipboard: {preview}",
                    )

            if self.tray:
                self.tray.set_state(TrayState.STANDBY)

        except ServerBusyError as e:
            logger.warning(f"Server busy: {e}")
            if self.tray:
                self.tray.set_state(TrayState.ERROR)
                self.tray.show_notification(
                    "Server Busy",
                    f"A transcription is already running for {e.active_user}. "
                    "Please try again shortly.",
                )

                # Reset to standby after a delay
                await asyncio.sleep(3)
                if self.api_client and self.api_client.is_connected:
                    self.tray.set_state(TrayState.STANDBY)
                else:
                    self.tray.set_state(TrayState.DISCONNECTED)

        except Exception as e:
            error_msg = str(e)
            # Check if this was a cancellation
            if "499" in error_msg or "cancelled" in error_msg.lower():
                logger.info("Transcription was cancelled")
                if self.tray:
                    self.tray.set_state(TrayState.STANDBY)
                    self.tray.show_notification("Cancelled", "Transcription cancelled")
            else:
                logger.error(f"Transcription failed: {e}")

                # Provide user-friendly error messages based on error type
                user_message = self._format_user_error(error_msg)

                if self.tray:
                    self.tray.set_state(TrayState.ERROR)
                    self.tray.show_notification("Transcription Error", user_message)

                    # Reset to standby after a delay
                    await asyncio.sleep(3)
                    if self.api_client and self.api_client.is_connected:
                        self.tray.set_state(TrayState.STANDBY)
                    else:
                        self.tray.set_state(TrayState.DISCONNECTED)

        finally:
            with self._state_lock:
                self.is_transcribing = False

    # =========================================================================
    # File Transcription
    # =========================================================================

    def _on_transcribe_file(self) -> None:
        """Handle file transcription action."""
        if not self.tray:
            return

        path = self.tray.open_file_dialog(
            "Select Audio File",
            [
                ("Audio Files", "*.wav *.mp3 *.flac *.ogg *.m4a *.webm"),
                ("All Files", "*.*"),
            ],
        )

        if path:
            self._schedule_async(self._transcribe_file(Path(path)))

    async def _transcribe_file(self, path: Path) -> None:
        """Transcribe a selected file."""
        if not self.api_client:
            return

        with self._state_lock:
            self.is_transcribing = True

        try:
            if self.tray:
                self.tray.set_state(TrayState.TRANSCRIBING)

            result = await self.api_client.transcribe_file(
                path,
                on_progress=lambda msg: logger.info(msg),
            )

            self.last_transcription = result.get("text", "")

            if self.last_transcription and self.auto_copy_clipboard:
                self._copy_to_clipboard(self.last_transcription)

                preview = self.last_transcription[:100]
                if len(self.last_transcription) > 100:
                    preview += "..."

                if self.tray:
                    self.tray.show_notification(
                        "Transcription Complete",
                        f"Copied to clipboard: {preview}",
                    )

            if self.tray:
                self.tray.set_state(TrayState.STANDBY)

        except Exception as e:
            error_msg = str(e)
            # Check if this was a cancellation
            if "499" in error_msg or "cancelled" in error_msg.lower():
                logger.info("File transcription was cancelled")
                if self.tray:
                    self.tray.set_state(TrayState.STANDBY)
                    self.tray.show_notification("Cancelled", "Transcription cancelled")
            else:
                logger.error(f"File transcription failed: {e}")

                # Provide user-friendly error messages
                user_message = self._format_user_error(error_msg)

                if self.tray:
                    self.tray.set_state(TrayState.ERROR)
                    self.tray.show_notification("Transcription Error", user_message)

                    await asyncio.sleep(3)
                    self.tray.set_state(TrayState.STANDBY)

        finally:
            with self._state_lock:
                self.is_transcribing = False

    # =========================================================================
    # Error Handling Helpers
    # =========================================================================

    def _format_user_error(self, error_msg: str) -> str:
        """
        Format error messages to be user-friendly for non-technical users.

        Args:
            error_msg: Raw error message

        Returns:
            User-friendly error message with troubleshooting hints
        """
        error_lower = error_msg.lower()

        # Connection errors
        if "connection" in error_lower and "refused" in error_lower:
            return (
                "Cannot reach the server. "
                "Make sure the server is running (check Server view in Dashboard)."
            )

        if "timeout" in error_lower or "timed out" in error_lower:
            return (
                "Server took too long to respond. "
                "Try again, or check if the server is overloaded."
            )

        # SSL/Certificate errors
        if "ssl" in error_lower or "certificate" in error_lower:
            return (
                "Secure connection failed. "
                "Check your HTTPS settings in Settings > Connection."
            )

        # Network errors
        if "network" in error_lower or "unreachable" in error_lower:
            return "Network error. Check your internet connection and Tailscale status."

        # File errors
        if "file not found" in error_lower or "no such file" in error_lower:
            return "The selected file could not be found."

        # Permission errors
        if "permission" in error_lower or "access denied" in error_lower:
            return "Permission denied. Check file permissions."

        # Default: show simplified error
        # Remove technical details like tracebacks, just show the main message
        lines = error_msg.split("\n")
        main_error = lines[0] if lines else error_msg

        # Truncate if too long
        if len(main_error) > 150:
            main_error = main_error[:147] + "..."

        return main_error

    # =========================================================================
    # Clipboard
    # =========================================================================

    def _copy_to_clipboard(self, text: str) -> bool:
        """Copy text to clipboard using the tray's platform-specific implementation."""
        if self.tray:
            return self.tray.copy_to_clipboard(text)
        logger.warning("No tray available for clipboard operation")
        return False

    # =========================================================================
    # Other Actions
    # =========================================================================

    def _on_open_notebook(self) -> None:
        """Open Audio Notebook in browser."""
        scheme = "https" if self.config.use_https else "http"
        url = f"{scheme}://{self.config.server_host}:{self.config.server_port}/notebook"
        logger.info(f"Opening Audio Notebook: {url}")
        webbrowser.open(url)

    def _on_settings(self) -> None:
        """Handle settings action."""
        # Settings dialog is now handled directly by the tray implementation
        if self.tray and hasattr(self.tray, "show_settings_dialog"):
            self.tray.show_settings_dialog()
        else:
            logger.warning("Settings dialog not available for this tray implementation")

    def _on_reconnect(self) -> None:
        """Handle reconnect action."""
        if self.tray:
            self.tray.set_state(TrayState.CONNECTING)
        self._schedule_async(self._connect_to_server())

    def _on_quit(self) -> None:
        """Handle quit action."""
        logger.info("Shutting down native client...")

        # Cancel reconnect task
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None

        # Stop recording if active
        with self._state_lock:
            is_recording = self.is_recording

        if self.recorder and is_recording:
            try:
                self.recorder.cancel()
            except Exception:
                logger.debug("Failed to cancel recorder during shutdown")
            self.recorder = None

        # Close API client
        if self.api_client:
            self._schedule_async(self.api_client.close())

        # Stop event loop
        if self.event_loop:
            self.event_loop.call_soon_threadsafe(self.event_loop.stop)

        logger.info("Native client shutdown complete")
