"""
Main orchestrator for the native client.
Coordinates tray, audio recording, and server communication.
"""

import asyncio
import logging
import threading
import webbrowser
from pathlib import Path
from typing import Optional

try:
    import pyperclip

    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False

from .audio_recorder import AudioRecorder
from .server_connection import ServerConfig, ServerConnection
from .tray.base import AbstractTray, TrayAction, TrayState
from .tray.factory import create_tray

logger = logging.getLogger(__name__)


class ClientOrchestrator:
    """
    Native client orchestrator.

    Manages:
    - System tray lifecycle
    - Audio recording
    - Server communication
    - Clipboard operations
    """

    def __init__(
        self,
        server_config: Optional[ServerConfig] = None,
        auto_connect: bool = True,
        auto_copy_clipboard: bool = True,
    ):
        self.server_config = server_config or ServerConfig()
        self.auto_connect = auto_connect
        self.auto_copy_clipboard = auto_copy_clipboard

        self.tray: Optional[AbstractTray] = None
        self.connection: Optional[ServerConnection] = None
        self.recorder: Optional[AudioRecorder] = None
        self.event_loop: Optional[asyncio.AbstractEventLoop] = None
        self.async_thread: Optional[threading.Thread] = None

        # State
        self.is_recording = False
        self.last_transcription: Optional[str] = None

    def start(self) -> None:
        """Start the native client."""
        logger.info("Starting TranscriptionSuite Native Client")

        # Create tray (platform-specific)
        self.tray = create_tray()

        # Register callbacks
        self.tray.register_callback(TrayAction.START_RECORDING, self._on_start_recording)
        self.tray.register_callback(TrayAction.STOP_RECORDING, self._on_stop_recording)
        self.tray.register_callback(TrayAction.TRANSCRIBE_FILE, self._on_transcribe_file)
        self.tray.register_callback(
            TrayAction.OPEN_AUDIO_NOTEBOOK, self._on_open_notebook
        )
        self.tray.register_callback(TrayAction.OPEN_REMOTE_SERVER, self._on_open_remote)
        self.tray.register_callback(TrayAction.SETTINGS, self._on_settings)
        self.tray.register_callback(TrayAction.QUIT, self._on_quit)

        # Start async event loop in background thread
        self.async_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.async_thread.start()

        # Connect to server if auto_connect is enabled
        if self.auto_connect:
            self._schedule_async(self._connect_to_server())

        # Run tray (blocks until quit)
        self.tray.run()

    def _run_async_loop(self) -> None:
        """Run the asyncio event loop in a background thread."""
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)
        self.event_loop.run_forever()

    def _schedule_async(self, coro) -> None:
        """Schedule a coroutine on the async event loop."""
        if self.event_loop:
            asyncio.run_coroutine_threadsafe(coro, self.event_loop)

    async def _connect_to_server(self) -> None:
        """Connect to the container server."""
        if self.tray:
            self.tray.set_state(TrayState.CONNECTING)

        self.connection = ServerConnection(self.server_config)

        if await self.connection.connect():
            if self.tray:
                self.tray.set_state(TrayState.STANDBY)
                self.tray.show_notification(
                    "Connected",
                    f"Connected to TranscriptionSuite at {self.server_config.host}",
                )

            # Optionally preload the model
            logger.info("Preloading transcription model...")
            await self.connection.preload_model()

        else:
            if self.tray:
                self.tray.set_state(TrayState.DISCONNECTED)
                self.tray.show_notification(
                    "Connection Failed",
                    f"Could not connect to {self.server_config.host}:{self.server_config.audio_notebook_port}",
                )

    def _on_start_recording(self) -> None:
        """Handle start recording action."""
        if self.is_recording:
            return

        if not self.connection or not self.connection.is_connected():
            if self.tray:
                self.tray.show_notification(
                    "Not Connected", "Please wait for server connection"
                )
            return

        self.is_recording = True
        if self.tray:
            self.tray.set_state(TrayState.RECORDING)

        # Initialize recorder
        try:
            self.recorder = AudioRecorder()
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

    async def _transcribe_audio(self, audio_data: bytes) -> None:
        """Send audio to server for transcription."""
        if not self.connection:
            return

        try:
            if self.tray:
                self.tray.set_state(TrayState.TRANSCRIBING)

            result = await self.connection.transcribe_audio_data(
                audio_data, progress_callback=lambda msg: logger.info(msg)
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
                        "Transcription Complete", f"Copied to clipboard: {preview}"
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
                self.tray.set_state(TrayState.STANDBY)

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
        if not self.connection:
            return

        try:
            if self.tray:
                self.tray.set_state(TrayState.TRANSCRIBING)

            result = await self.connection.transcribe_file(
                path, progress_callback=lambda msg: logger.info(msg)
            )

            self.last_transcription = result.get("text", "")

            if self.last_transcription and self.auto_copy_clipboard:
                self._copy_to_clipboard(self.last_transcription)

                preview = self.last_transcription[:100]
                if len(self.last_transcription) > 100:
                    preview += "..."

                if self.tray:
                    self.tray.show_notification(
                        "Transcription Complete", f"Copied to clipboard: {preview}"
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

    def _copy_to_clipboard(self, text: str) -> None:
        """Copy text to clipboard."""
        if HAS_PYPERCLIP:
            try:
                pyperclip.copy(text)
                logger.debug("Copied to clipboard")
            except Exception as e:
                logger.warning(f"Clipboard copy failed: {e}")
        else:
            logger.warning("pyperclip not available, clipboard disabled")

    def _on_open_notebook(self) -> None:
        """Open Audio Notebook in browser."""
        url = self.server_config.audio_notebook_url
        logger.info(f"Opening Audio Notebook: {url}")
        webbrowser.open(url)

    def _on_open_remote(self) -> None:
        """Open Remote Server UI in browser."""
        url = self.server_config.remote_server_url
        logger.info(f"Opening Remote Server: {url}")
        webbrowser.open(url)

    def _on_settings(self) -> None:
        """Handle settings action."""
        # TODO: Implement settings dialog
        if self.tray:
            self.tray.show_notification("Settings", "Settings dialog not yet implemented")

    def _on_quit(self) -> None:
        """Handle quit action."""
        logger.info("Shutting down native client...")

        # Stop recording if active
        if self.recorder and self.is_recording:
            try:
                self.recorder.stop()
            except Exception:
                pass
            self.recorder = None

        # Disconnect from server
        if self.connection:
            self._schedule_async(self.connection.disconnect())

        # Stop event loop
        if self.event_loop:
            self.event_loop.call_soon_threadsafe(self.event_loop.stop)

        logger.info("Native client shutdown complete")
