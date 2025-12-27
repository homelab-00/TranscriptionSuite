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

from client.common.api_client import APIClient
from client.common.audio_recorder import AudioRecorder
from client.common.config import ClientConfig
from client.common.models import TrayAction, TrayState

if TYPE_CHECKING:
    from client.common.tray_base import AbstractTray

logger = logging.getLogger(__name__)


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

        # State
        self.is_recording = False
        self.last_transcription: str | None = None
        self._reconnect_task: concurrent.futures.Future[Any] | None = None

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

        self.tray.register_callback(TrayAction.START_RECORDING, self._on_start_recording)
        self.tray.register_callback(TrayAction.STOP_RECORDING, self._on_stop_recording)
        self.tray.register_callback(
            TrayAction.CANCEL_RECORDING, self._on_cancel_recording
        )
        self.tray.register_callback(TrayAction.TRANSCRIBE_FILE, self._on_transcribe_file)
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

            # Start reconnection attempts if enabled
            if self.config.get("server", "auto_reconnect", default=True):
                self._start_reconnect_loop()

    def _start_reconnect_loop(self) -> None:
        """Start automatic reconnection attempts."""
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = self._schedule_async(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Periodically attempt to reconnect."""
        interval = self.config.get("server", "reconnect_interval", default=10)

        while True:
            await asyncio.sleep(interval)

            if self.api_client and self.api_client.is_connected:
                break  # Already connected

            logger.info("Attempting to reconnect...")
            if self.api_client and await self.api_client.health_check():
                if self.tray:
                    self.tray.set_state(TrayState.STANDBY)
                    self.tray.show_notification("Reconnected", "Connection restored")
                break

    # =========================================================================
    # Recording Actions
    # =========================================================================

    def _on_start_recording(self) -> None:
        """Handle start recording action."""
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
            self.is_recording = False
            if self.tray:
                self.tray.set_state(TrayState.ERROR)
                self.tray.show_notification("Error", f"Failed to start recording: {e}")

    def _on_stop_recording(self) -> None:
        """Handle stop recording action."""
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
        """Handle cancel recording action."""
        if not self.is_recording or not self.recorder:
            return

        self.is_recording = False
        try:
            self.recorder.cancel()
        except Exception:
            pass
        self.recorder = None

        if self.tray:
            self.tray.set_state(TrayState.STANDBY)
            self.tray.show_notification("Cancelled", "Recording cancelled")

        logger.info("Recording cancelled")

    async def _transcribe_audio(self, audio_data: bytes) -> None:
        """Send audio to server for transcription."""
        if not self.api_client:
            return

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

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            if self.tray:
                self.tray.set_state(TrayState.ERROR)
                self.tray.show_notification("Transcription Error", str(e))

                # Reset to standby after a delay
                await asyncio.sleep(3)
                if self.api_client and self.api_client.is_connected:
                    self.tray.set_state(TrayState.STANDBY)
                else:
                    self.tray.set_state(TrayState.DISCONNECTED)

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
            logger.error(f"File transcription failed: {e}")
            if self.tray:
                self.tray.set_state(TrayState.ERROR)
                self.tray.show_notification("Error", str(e))

                await asyncio.sleep(3)
                self.tray.set_state(TrayState.STANDBY)

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
        if self.recorder and self.is_recording:
            try:
                self.recorder.cancel()
            except Exception:
                pass
            self.recorder = None

        # Close API client
        if self.api_client:
            self._schedule_async(self.api_client.close())

        # Stop event loop
        if self.event_loop:
            self.event_loop.call_soon_threadsafe(self.event_loop.stop)

        logger.info("Native client shutdown complete")
