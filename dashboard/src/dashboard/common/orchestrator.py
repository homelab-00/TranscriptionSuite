"""
Main orchestrator for the native client.

Coordinates tray, audio recording, and server communication.
This is the central controller for all client operations.
"""

import asyncio
import concurrent.futures
import logging
import os
import threading
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dashboard.common.api_client import (
    APIClient,
    LiveModeClient,
    ServerBusyError,
    StreamingClient,
)
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
        self.models_loaded = (
            True  # Track if models are loaded (assume loaded initially)
        )
        self.last_transcription: str | None = None
        self._reconnect_task: concurrent.futures.Future[Any] | None = None
        self._is_initial_connection = (
            True  # Track if this is the first connection attempt
        )

        # WebSocket streaming for live transcription
        self._streaming_client: StreamingClient | None = None
        self._live_transcription_text: str = ""
        self._use_websocket_streaming: bool = False

        # Live Mode (RealtimeSTT) state
        self._live_mode_active: bool = False
        self._live_mode_client: LiveModeClient | None = None
        self._live_mode_auto_paste: bool = False

    @property
    def auto_add_to_notebook(self) -> bool:
        """Get auto-add to notebook setting (reads from config each time)."""
        return self.config.get_server_config(
            "longform_recording", "auto_add_to_audio_notebook", default=False
        )

    def start(self, tray: "AbstractTray") -> None:
        """
        Start the native client with the given tray implementation.

        Args:
            tray: Platform-specific tray implementation
        """
        logger.info("Starting TranscriptionSuite Native Client")
        self.tray = tray
        self.tray.orchestrator = self  # Allow tray to sync state back to orchestrator

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
        self.tray.register_callback(TrayAction.TOGGLE_MODELS, self._on_toggle_models)
        self.tray.register_callback(TrayAction.SETTINGS, self._on_settings)
        self.tray.register_callback(TrayAction.RECONNECT, self._on_reconnect)
        self.tray.register_callback(TrayAction.DISCONNECT, self._on_disconnect)
        self.tray.register_callback(TrayAction.QUIT, self._on_quit)
        # Live Mode callbacks
        self.tray.register_callback(
            TrayAction.START_LIVE_MODE, self._on_start_live_mode
        )
        self.tray.register_callback(TrayAction.STOP_LIVE_MODE, self._on_stop_live_mode)

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

    @property
    def is_local_connection(self) -> bool:
        """Check if the current server connection is to localhost."""
        if self.api_client is None:
            return False
        return self.api_client._is_localhost()

    @property
    def live_transcriber_enabled(self) -> bool:
        """Check if live transcriber is enabled in server config."""
        return self.config.get_server_config(
            "transcription_options", "enable_live_transcriber", default=False
        )

    @property
    def sample_rate(self) -> int:
        """Get the configured sample rate."""
        return self.config.get("recording", "sample_rate", default=16000)

    def _on_live_transcription_text(self, text: str) -> None:
        """Handle live transcription text from WebSocket."""
        self._live_transcription_text = text
        if self.tray:
            self.tray.update_live_transcription_text(text)

    # =========================================================================
    # Server Connection
    # =========================================================================

    async def _connect_to_server(self) -> None:
        """Connect to the container server."""
        if self.tray:
            self.tray.set_state(TrayState.CONNECTING)

        # Close existing API client if present
        if self.api_client:
            logger.debug("Closing existing API client before reconnecting")
            await self.api_client.close()
            self.api_client = None

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
                # Notify tray of connection type (local vs remote)
                self.tray.update_connection_type(self.is_local_connection)
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

        # Check if we should use WebSocket streaming for live transcription
        # Live transcriber mode is only used when: live transcriber enabled AND not notebook mode
        if self.live_transcriber_enabled and not self.auto_add_to_notebook:
            self._use_websocket_streaming = True
            self._schedule_async(self._start_websocket_recording())
        else:
            self._use_websocket_streaming = False
            self._start_http_recording()

    def _start_http_recording(self) -> None:
        """Start recording with HTTP batch upload (default mode)."""
        if self.tray:
            self.tray.set_state(TrayState.RECORDING)

        # Initialize recorder
        try:
            device_index = self.config.get("recording", "device_index")

            self.recorder = AudioRecorder(
                sample_rate=self.sample_rate,
                device_index=device_index,
            )
            self.recorder.start()
            logger.info("Recording started (HTTP batch mode)")

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
            if not self.is_recording:
                return
            # For WebSocket mode, recorder might be None (chunks sent directly)
            if not self._use_websocket_streaming and not self.recorder:
                return
            self.is_recording = False

        if self._use_websocket_streaming:
            # WebSocket streaming mode - send stop command
            self._schedule_async(self._stop_websocket_recording())
        else:
            # HTTP batch mode - upload recorded audio
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
            if self.is_recording:
                self.is_recording = False

                # Cancel WebSocket streaming if active
                if self._use_websocket_streaming and self._streaming_client:
                    self._schedule_async(self._cancel_websocket_recording())
                elif self.recorder:
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

    # =========================================================================
    # WebSocket Streaming (Live Transcriber Mode)
    # =========================================================================

    async def _start_websocket_recording(self) -> None:
        """Start recording with WebSocket streaming for real-time live transcription."""
        if not self.api_client:
            with self._state_lock:
                self.is_recording = False
            return

        self._live_transcription_text = ""
        if self.tray:
            self.tray.set_state(TrayState.RECORDING)
            self.tray.update_live_transcription_text("")

        # Create streaming client with callbacks
        self._streaming_client = StreamingClient(
            self.api_client,
            on_preview=self._on_live_transcription_text,
            on_final=self._on_websocket_final,
            on_error=self._on_websocket_error,
        )

        # Connect to WebSocket
        if not await self._streaming_client.connect():
            logger.warning("WebSocket connect failed, falling back to HTTP batch mode")
            with self._state_lock:
                self.is_recording = False
                self._use_websocket_streaming = False
            # Fall back to HTTP batch mode
            self._start_http_recording()
            with self._state_lock:
                self.is_recording = True
            return

        # Send start command with VAD enabled for server-side processing
        await self._streaming_client.send_control("start", {"use_vad": True})

        # Start audio recorder with chunk callback for streaming
        try:
            device_index = self.config.get("recording", "device_index")

            self.recorder = AudioRecorder(
                sample_rate=self.sample_rate,
                device_index=device_index,
                on_audio_chunk=self._on_audio_chunk,
            )
            self.recorder.start()
            logger.info(
                "Recording started (WebSocket streaming mode with live transcriber)"
            )

        except Exception as e:
            logger.error(f"Failed to start WebSocket recording: {e}")
            await self._cleanup_websocket()
            with self._state_lock:
                self.is_recording = False
            if self.tray:
                self.tray.set_state(TrayState.ERROR)
                self.tray.show_notification("Error", f"Failed to start recording: {e}")

    def _on_audio_chunk(self, chunk: bytes) -> None:
        """Forward audio chunk to WebSocket (called from AudioRecorder thread)."""
        if self._streaming_client and self._streaming_client.is_connected:
            # Format and send via WebSocket
            formatted = self._format_audio_for_websocket(chunk)
            self._schedule_async(self._streaming_client.send_audio(formatted))

    def _format_audio_for_websocket(self, pcm_data: bytes) -> bytes:
        """Format audio chunk for WebSocket binary protocol."""
        import json
        import struct

        metadata = json.dumps({"sample_rate": self.sample_rate, "channels": 1})
        metadata_bytes = metadata.encode("utf-8")
        header = struct.pack("<I", len(metadata_bytes))
        return header + metadata_bytes + pcm_data

    async def _stop_websocket_recording(self) -> None:
        """Stop WebSocket recording and wait for final transcription."""
        if self.tray:
            self.tray.set_state(TrayState.TRANSCRIBING)

        # Stop the audio recorder
        if self.recorder:
            try:
                self.recorder.stop()
            except Exception as e:
                logger.debug(f"Error stopping recorder: {e}")
            self.recorder = None

        # Send stop command to server
        if self._streaming_client and self._streaming_client.is_connected:
            await self._streaming_client.send_control("stop")
            logger.info(
                "WebSocket stop command sent, waiting for final transcription..."
            )
            # The final result will be handled by _on_websocket_final callback

    async def _cancel_websocket_recording(self) -> None:
        """Cancel WebSocket recording without waiting for transcription."""
        if self.recorder:
            try:
                self.recorder.cancel()
            except Exception:
                pass
            self.recorder = None

        await self._cleanup_websocket()

    async def _cleanup_websocket(self) -> None:
        """Clean up WebSocket resources."""
        if self._streaming_client:
            await self._streaming_client.close()
            self._streaming_client = None
        self._live_transcription_text = ""
        self._use_websocket_streaming = False

    def _on_websocket_final(self, result: dict[str, Any]) -> None:
        """Handle final transcription result from WebSocket (callback from receive loop)."""
        # Schedule the processing on the async loop
        self._schedule_async(self._process_websocket_result(result))

    async def _process_websocket_result(self, result: dict[str, Any]) -> None:
        """Process final WebSocket transcription result."""
        # Extract text from result (handle both formats)
        text = result.get("data", {}).get("text", "") or result.get("text", "")
        self.last_transcription = text

        # Clean up WebSocket
        await self._cleanup_websocket()

        # Flash icon then set to STANDBY
        if self.tray:
            if hasattr(self.tray, "flash_then_set_state"):
                self.tray.flash_then_set_state(TrayState.STANDBY, flash_duration_ms=500)
            else:
                self.tray.set_state(TrayState.STANDBY)

        # Copy to clipboard (only when NOT in notebook mode)
        # Note: WebSocket streaming should not be used in notebook mode (see _on_start_recording),
        # but we check anyway for robustness.
        if text and self.auto_copy_clipboard and not self.auto_add_to_notebook:
            self._copy_to_clipboard(text)

            # Show notification with preview
            preview = text[:100]
            if len(text) > 100:
                preview += "..."

            if self.tray:
                self.tray.show_notification(
                    "Transcription Complete",
                    f"Copied to clipboard: {preview}",
                )
        elif not text:
            if self.tray:
                self.tray.show_notification(
                    "Transcription Complete",
                    "No speech detected",
                )

        logger.info("WebSocket transcription complete")

    def _on_websocket_error(self, error: str) -> None:
        """Handle WebSocket error (callback from receive loop)."""
        logger.error(f"WebSocket error: {error}")

        # Schedule cleanup and error handling
        self._schedule_async(self._handle_websocket_error(error))

    async def _handle_websocket_error(self, error: str) -> None:
        """Handle WebSocket error and clean up."""
        await self._cleanup_websocket()

        with self._state_lock:
            self.is_recording = False

        if self.tray:
            self.tray.set_state(TrayState.ERROR)
            self.tray.show_notification("Transcription Error", error)

            # Reset to standby after a delay
            await asyncio.sleep(3)
            if self.api_client and self.api_client.is_connected:
                self.tray.set_state(TrayState.STANDBY)

    async def _transcribe_audio(self, audio_data: bytes) -> None:
        """Send audio to server for transcription."""
        if not self.api_client:
            return

        with self._state_lock:
            self.is_transcribing = True

        try:
            if self.tray:
                self.tray.set_state(TrayState.TRANSCRIBING)

            # Branch based on notebook mode
            if self.auto_add_to_notebook:
                # Use notebook endpoint - saves to notebook with diarization, no clipboard
                result = await self.api_client.upload_to_notebook(
                    audio_data,
                    on_progress=lambda msg: logger.info(msg),
                )
                self.last_transcription = result.get("transcription", "")

                # Flash icon then set to STANDBY
                if self.tray:
                    if hasattr(self.tray, "flash_then_set_state"):
                        self.tray.flash_then_set_state(
                            TrayState.STANDBY, flash_duration_ms=500
                        )
                    else:
                        self.tray.set_state(TrayState.STANDBY)

                    self.tray.show_notification(
                        "Saved to Notebook",
                        "Recording saved to Audio Notebook",
                    )
            else:
                # Regular flow - transcribe and copy to clipboard
                result = await self.api_client.transcribe_audio_data(
                    audio_data,
                    on_progress=lambda msg: logger.info(msg),
                )

                self.last_transcription = result.get("text", "")

                # Flash icon then set to STANDBY, before clipboard copy (fixes delay)
                if self.tray:
                    if hasattr(self.tray, "flash_then_set_state"):
                        self.tray.flash_then_set_state(
                            TrayState.STANDBY, flash_duration_ms=500
                        )
                    else:
                        self.tray.set_state(TrayState.STANDBY)

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

            # Flash icon then set to STANDBY, before clipboard copy (fixes delay)
            if self.tray:
                if hasattr(self.tray, "flash_then_set_state"):
                    self.tray.flash_then_set_state(
                        TrayState.STANDBY, flash_duration_ms=500
                    )
                else:
                    self.tray.set_state(TrayState.STANDBY)

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
    # Model Management
    # =========================================================================

    def _on_toggle_models(self) -> None:
        """Handle toggle models action from tray menu."""
        self._schedule_async(self._toggle_models())

    async def _toggle_models(self) -> None:
        """Toggle model loading state - unload to free GPU memory or reload."""
        if not self.api_client:
            if self.tray:
                self.tray.show_notification("Error", "Not connected to server")
            return

        # Only allow toggling models on local connections
        if not self.is_local_connection:
            if self.tray:
                self.tray.show_notification(
                    "Error", "Model management only available for local connections"
                )
            return

        try:
            if self.models_loaded:
                result = await self.api_client.unload_models()
            else:
                result = await self.api_client.reload_models()

            if result.get("success"):
                self.models_loaded = not self.models_loaded

                # Update tray menu state
                if self.tray and hasattr(self.tray, "update_models_menu_state"):
                    self.tray.update_models_menu_state(self.models_loaded)

                if self.models_loaded:
                    if self.tray:
                        self.tray.show_notification(
                            "Models Loaded", "Models ready for transcription"
                        )
                else:
                    if self.tray:
                        self.tray.show_notification(
                            "Models Unloaded",
                            "GPU memory freed. Use menu to reload.",
                        )
            else:
                if self.tray:
                    self.tray.show_notification(
                        "Operation Failed", result.get("message", "Unknown error")
                    )
        except Exception as e:
            logger.error(f"Model toggle failed: {e}")
            if self.tray:
                self.tray.show_notification("Error", f"Failed to toggle models: {e}")

    def sync_models_state(self, loaded: bool) -> None:
        """
        Sync the models loaded state from external source (e.g., dashboard GUI).

        This is called by the tray when the dashboard changes the model state,
        ensuring the orchestrator stays in sync with the UI.

        Args:
            loaded: True if models are loaded, False if unloaded
        """
        self.models_loaded = loaded
        logger.debug(f"Orchestrator models_loaded synced to: {loaded}")

    # =========================================================================
    # Live Mode (RealtimeSTT)
    # =========================================================================

    def _on_start_live_mode(self) -> None:
        """Handle start live mode action."""
        if self._live_mode_active:
            logger.warning("Live Mode already active")
            return

        if not self.api_client or not self.api_client.is_connected:
            if self.tray:
                self.tray.show_notification(
                    "Not Connected",
                    "Please wait for server connection",
                )
            return

        self._schedule_async(self._start_live_mode())

    def _on_stop_live_mode(self) -> None:
        """Handle stop live mode action."""
        if not self._live_mode_active:
            return

        self._schedule_async(self._stop_live_mode())

    async def _start_live_mode(self) -> None:
        """Start Live Mode WebSocket connection."""
        if not self.api_client:
            return

        try:
            # Create Live Mode client with callbacks
            self._live_mode_client = LiveModeClient(
                self.api_client,
                on_sentence=self._on_live_sentence,
                on_partial=self._on_live_partial,
                on_state=self._on_live_state,
                on_error=self._on_live_error,
            )

            # Connect
            if not await self._live_mode_client.connect():
                return

            self._live_mode_active = True

            # Update tray state
            if self.tray and hasattr(self.tray, "set_live_mode_active"):
                self.tray.set_live_mode_active(True)
            if self.tray:
                self.tray.show_notification("Live Mode", "Live Mode started")

            # Send start command with config
            config = {
                "model": self.config.get_server_config(
                    "transcription_options", "model_id", default="base"
                ),
                "language": self.config.get_server_config(
                    "transcription_options", "target_language", default=""
                ),
            }
            await self._live_mode_client.start(config)

            logger.info("Live Mode started")

            # Start listening for messages (this blocks until done)
            await self._live_mode_client.receive_messages()

        except Exception as e:
            logger.error(f"Failed to start Live Mode: {e}")
            self._live_mode_active = False
            if self.tray:
                self.tray.show_notification("Error", f"Failed to start Live Mode: {e}")
                if hasattr(self.tray, "set_live_mode_active"):
                    self.tray.set_live_mode_active(False)

    async def _stop_live_mode(self) -> None:
        """Stop Live Mode WebSocket connection."""
        if not self._live_mode_client:
            return

        try:
            # Send stop command
            await self._live_mode_client.stop()

            # Close connection
            await self._live_mode_client.close()
        except Exception as e:
            logger.error(f"Error stopping Live Mode: {e}")
        finally:
            self._live_mode_client = None
            self._live_mode_active = False

            # Update tray state
            if self.tray and hasattr(self.tray, "set_live_mode_active"):
                self.tray.set_live_mode_active(False)
            if self.tray:
                self.tray.show_notification("Live Mode", "Live Mode stopped")

            logger.info("Live Mode stopped")

    def _on_live_sentence(self, text: str) -> None:
        """Callback for completed Live Mode sentences."""
        if not text:
            return
        logger.debug(f"Live Mode sentence: {text}")
        # Update live transcription text in tray/dashboard
        if self.tray:
            self.tray.update_live_transcription_text(text)
        # Auto-paste if enabled
        if self._live_mode_auto_paste:
            self._auto_paste_text(text)

    def _on_live_partial(self, text: str) -> None:
        """Callback for Live Mode partial/real-time updates."""
        # Could update a "typing" indicator if desired
        pass

    def _on_live_state(self, state: str) -> None:
        """Callback for Live Mode state changes."""
        logger.debug(f"Live Mode state: {state}")

    def _on_live_error(self, error_msg: str) -> None:
        """Callback for Live Mode errors."""
        logger.error(f"Live Mode error: {error_msg}")
        if self.tray:
            self.tray.show_notification("Live Mode Error", error_msg)

    def _auto_paste_text(self, text: str) -> None:
        """Auto-paste text at cursor position."""
        import shutil
        import subprocess

        # Detect display server
        session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()

        try:
            if session_type == "wayland":
                # Wayland: use wl-copy and wtype
                if shutil.which("wl-copy") and shutil.which("wtype"):
                    subprocess.run(
                        ["wl-copy", "--", text],
                        check=True,
                        capture_output=True,
                    )
                    subprocess.run(
                        ["wtype", "--", text],
                        check=True,
                        capture_output=True,
                    )
                else:
                    logger.warning("wl-copy/wtype not found for Wayland auto-paste")
            else:
                # X11: use xclip and xdotool
                if shutil.which("xclip") and shutil.which("xdotool"):
                    subprocess.run(
                        ["xclip", "-selection", "clipboard"],
                        input=text.encode(),
                        check=True,
                        capture_output=True,
                    )
                    subprocess.run(
                        ["xdotool", "type", "--", text],
                        check=True,
                        capture_output=True,
                    )
                else:
                    logger.warning("xclip/xdotool not found for X11 auto-paste")
        except subprocess.CalledProcessError as e:
            logger.error(f"Auto-paste failed: {e}")
        except Exception as e:
            logger.error(f"Auto-paste error: {e}")

    def set_live_mode_auto_paste(self, enabled: bool) -> None:
        """Set auto-paste mode for Live Mode."""
        self._live_mode_auto_paste = enabled
        logger.debug(f"Live Mode auto-paste set to: {enabled}")

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

    def _on_disconnect(self) -> None:
        """Handle disconnect action - stop client and clean up resources."""
        logger.info("Disconnecting client...")
        self._schedule_async(self._disconnect_from_server())

    async def _disconnect_from_server(self) -> None:
        """Disconnect from server and clean up resources."""
        # Stop any active recording
        with self._state_lock:
            is_recording = self.is_recording

        if self.recorder and is_recording:
            try:
                self.recorder.cancel()
                logger.debug("Recording cancelled during disconnect")
            except Exception:
                logger.debug("Failed to cancel recorder during disconnect")
            self.recorder = None
            with self._state_lock:
                self.is_recording = False

        # Cancel reconnect task if running
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            self._reconnect_task = None
            logger.debug("Cancelled reconnect task")

        # Close API client
        if self.api_client:
            logger.debug("Closing API client")
            await self.api_client.close()
            self.api_client = None

        # Update tray state
        if self.tray:
            self.tray.set_state(TrayState.IDLE)
            # Reset connection type
            self.tray.update_connection_type(False)
            logger.info("Client disconnected")

    def _on_quit(self) -> None:
        """Handle quit action."""
        logger.info("Shutting down native client...")

        # Cancel reconnect task
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None

        # Stop Live Mode if active
        if self._live_mode_active and self._live_mode_client:
            self._schedule_async(self._stop_live_mode())

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
