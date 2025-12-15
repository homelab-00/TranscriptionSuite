"""
WebSocket-based remote transcription server.

Provides a dual-channel architecture:
- Control channel (port 8011): Commands, auth, status
- Data channel (port 8012): Audio streaming, transcription results

Features:
- Token-based authentication
- Single-user mode with busy lock
- Real-time transcription feedback
- Final transcription with word timestamps
"""

import asyncio
import logging
import os
import signal
import ssl
import threading
from typing import Any, Callable, Dict, Optional

import numpy as np
import websockets
from websockets.asyncio.server import Server, ServerConnection
from websockets.exceptions import ConnectionClosed

from .auth import AuthManager
from .token_store import StoredToken
from .protocol import (
    AudioChunk,
    AudioProtocol,
    ControlMessage,
    ControlProtocol,
    MessageType,
    SAMPLE_RATE,
)

logger = logging.getLogger(__name__)

# Default ports
DEFAULT_CONTROL_PORT = 8011
DEFAULT_DATA_PORT = 8012


class RemoteTranscriptionServer:
    """
    WebSocket server for remote transcription.

    Implements the dual-channel architecture:
    - Control WebSocket: JSON messages for commands/status
    - Data WebSocket: Binary audio data and transcription results
    """

    def __init__(
        self,
        config: Dict[str, Any],
        transcribe_callback: Optional[
            Callable[[np.ndarray, Optional[str]], Dict[str, Any]]
        ] = None,
        realtime_callback: Optional[Callable[[np.ndarray], Optional[str]]] = None,
    ):
        """
        Initialize the remote transcription server.

        Args:
            config: Server configuration dict from config.yaml
            transcribe_callback: Callback for final transcription
                Signature: (audio_data: np.ndarray, language: Optional[str]) -> dict
                Returns: {"text": str, "words": list, "duration": float, ...}
            realtime_callback: Callback for real-time transcription
                Signature: (audio_chunk: np.ndarray) -> Optional[str]
                Returns: Partial transcription text or None
        """
        self.config = config.get("remote_server", {})

        # Network configuration
        self.host = self.config.get("host", "0.0.0.0")
        self.control_port = self.config.get("control_port", DEFAULT_CONTROL_PORT)
        self.data_port = self.config.get("data_port", DEFAULT_DATA_PORT)

        # Authentication
        secret_key = self.config.get("secret_key")
        self.auth_manager = AuthManager(secret_key)
        self.auth_timeout = self.config.get("auth_timeout", 10.0)

        # TLS configuration
        self._ssl_context = self._create_ssl_context()

        # Callbacks
        self._transcribe_callback = transcribe_callback
        self._realtime_callback = realtime_callback

        # Protocol handler
        self.audio_protocol = AudioProtocol(target_sample_rate=SAMPLE_RATE)

        # Session state
        self._is_running = False
        self._is_transcribing = False
        self._current_session: Optional[StoredToken] = None
        self._session_config: Dict[str, Any] = {}

        # WebSocket connections
        self._control_connection: Optional[ServerConnection] = None
        self._data_connection: Optional[ServerConnection] = None

        # Servers
        self._control_server: Optional[Server] = None
        self._data_server: Optional[Server] = None

        # Audio accumulator for final transcription
        self._audio_accumulator: list[np.ndarray] = []

        # Event loop reference
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        tls_status = "TLS enabled" if self._ssl_context else "TLS disabled"
        logger.info(
            f"RemoteTranscriptionServer initialized "
            f"(control:{self.control_port}, data:{self.data_port}, {tls_status})"
        )

    def _create_ssl_context(self) -> Optional[ssl.SSLContext]:
        """
        Create SSL context if TLS is configured.

        Returns:
            SSLContext if TLS enabled, None otherwise
        """
        tls_config = self.config.get("tls", {})

        if not tls_config.get("enabled", False):
            return None

        cert_file = tls_config.get("cert_file")
        key_file = tls_config.get("key_file")

        if not cert_file or not key_file:
            logger.warning(
                "TLS enabled but cert_file or key_file not specified. "
                "Running without TLS."
            )
            return None

        # Check files exist
        if not os.path.exists(cert_file):
            logger.error(f"TLS cert_file not found: {cert_file}")
            return None
        if not os.path.exists(key_file):
            logger.error(f"TLS key_file not found: {key_file}")
            return None

        try:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(
                certfile=cert_file,
                keyfile=key_file,
            )

            # Optional: set minimum TLS version for security
            ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

            logger.info(f"TLS enabled with cert: {cert_file}")
            return ssl_context

        except ssl.SSLError as e:
            logger.error(f"Failed to load TLS certificates: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating SSL context: {e}")
            return None

    def generate_token(
        self, client_id: str = "default", expiry_seconds: int = 3600
    ) -> str:
        """
        Generate an authentication token for a client.

        Args:
            client_id: Identifier for the client
            expiry_seconds: Token validity duration

        Returns:
            Token string for client authentication
        """
        # Note: expiry_seconds is kept for backward compatibility but ignored.
        stored = self.auth_manager.generate_token(client_id, is_admin=False)
        return stored.token

    async def _handle_control(self, websocket: ServerConnection) -> None:
        """Handle control channel connection."""
        client_addr = websocket.remote_address
        logger.info(f"Control connection from {client_addr}")

        token: Optional[StoredToken] = None

        try:
            # Wait for authentication
            try:
                auth_message = await asyncio.wait_for(
                    websocket.recv(), timeout=self.auth_timeout
                )

                # Parse authentication request
                msg = ControlMessage.from_json(auth_message)  # type: ignore

                if msg.type != MessageType.AUTH:
                    response = ControlProtocol.create_auth_response(
                        False, "Expected authentication message"
                    )
                    await websocket.send(response.to_json())
                    return

                # Validate token
                token = self.auth_manager.validate_token(msg.data.get("token", ""))
                if token is None:
                    response = ControlProtocol.create_auth_response(
                        False, "Invalid or expired token"
                    )
                    await websocket.send(response.to_json())
                    return

                # Try to acquire session (single-user enforcement)
                if not self.auth_manager.acquire_session(token):
                    active_client = (
                        self.auth_manager.get_active_client_name() or "unknown"
                    )
                    response = ControlProtocol.create_session_busy_response(active_client)
                    await websocket.send(response.to_json())
                    logger.warning(
                        f"Session denied for {token.client_name}: "
                        f"another user ({active_client}) is active"
                    )
                    return

                # Authentication successful
                self._current_session = token
                self._control_connection = websocket
                response = ControlProtocol.create_auth_response(
                    True, f"Welcome, {token.client_name}"
                )
                await websocket.send(response.to_json())
                logger.info(f"Client authenticated: {token.client_name}")

            except asyncio.TimeoutError:
                logger.warning(f"Authentication timeout from {client_addr}")
                response = ControlProtocol.create_auth_response(
                    False, "Authentication timeout"
                )
                await websocket.send(response.to_json())
                return

            # Main control message loop
            async for message in websocket:
                try:
                    msg = ControlMessage.from_json(message)  # type: ignore
                    await self._process_control_message(msg, websocket)
                except ValueError as e:
                    error_msg = ControlProtocol.create_error(str(e), "parse_error")
                    await websocket.send(error_msg.to_json())

        except ConnectionClosed:
            logger.info(f"Control connection closed from {client_addr}")
        except Exception as e:
            logger.error(f"Error in control handler: {e}", exc_info=True)
        finally:
            # Cleanup
            if token and self._current_session == token:
                self.auth_manager.release_session(token.token)
                self._current_session = None
                self._control_connection = None
                self._is_transcribing = False
                self.audio_protocol.clear_buffer()
                self._audio_accumulator.clear()
                logger.info(f"Session released for {token.client_name}")

    async def _process_control_message(
        self, msg: ControlMessage, websocket: ServerConnection
    ) -> None:
        """Process a control message."""
        logger.debug(f"Control message: {msg.type}")

        if msg.type == MessageType.PING:
            await websocket.send(ControlProtocol.create_pong().to_json())

        elif msg.type == MessageType.START:
            if self._is_transcribing:
                error = ControlProtocol.create_error(
                    "Transcription already in progress", "already_started"
                )
                await websocket.send(error.to_json())
                return

            # Store session configuration
            self._session_config = {
                "language": msg.data.get("language"),
                "enable_realtime": msg.data.get("enable_realtime", True),
                "word_timestamps": msg.data.get("word_timestamps", False),
            }

            self._is_transcribing = True
            self._audio_accumulator.clear()
            self.audio_protocol.clear_buffer()

            response = ControlMessage(
                type=MessageType.SESSION_STARTED,
                data={"config": self._session_config},
            )
            await websocket.send(response.to_json())
            logger.info("Transcription session started")

        elif msg.type == MessageType.STOP:
            if not self._is_transcribing:
                error = ControlProtocol.create_error(
                    "No active transcription session", "not_started"
                )
                await websocket.send(error.to_json())
                return

            # Perform final transcription
            await self._finalize_transcription(websocket)

        elif msg.type == MessageType.CONFIG:
            # Update session configuration
            self._session_config.update(msg.data)
            response = ControlMessage(
                type=MessageType.STATUS,
                data={"config_updated": True, "config": self._session_config},
            )
            await websocket.send(response.to_json())

        else:
            error = ControlProtocol.create_error(
                f"Unknown message type: {msg.type}", "unknown_type"
            )
            await websocket.send(error.to_json())

    async def _handle_data(self, websocket: ServerConnection) -> None:
        """Handle data channel connection."""
        client_addr = websocket.remote_address
        logger.info(f"Data connection from {client_addr}")

        token: Optional[StoredToken] = None

        try:
            # Wait for authentication (same process as control)
            try:
                auth_message = await asyncio.wait_for(
                    websocket.recv(), timeout=self.auth_timeout
                )

                # Parse authentication request (text message)
                msg = ControlMessage.from_json(auth_message)  # type: ignore

                if msg.type != MessageType.AUTH:
                    response = ControlProtocol.create_auth_response(
                        False, "Expected authentication message"
                    )
                    await websocket.send(response.to_json())
                    return

                # Validate token
                token = self.auth_manager.validate_token(msg.data.get("token", ""))

                if token is None:
                    response = ControlProtocol.create_auth_response(
                        False, "Invalid or expired token"
                    )
                    await websocket.send(response.to_json())
                    return

                # Verify this token matches the active session
                if (
                    self._current_session is None
                    or self._current_session.token != token.token
                ):
                    response = ControlProtocol.create_auth_response(
                        False, "No matching control session"
                    )
                    await websocket.send(response.to_json())
                    return

                self._data_connection = websocket
                response = ControlProtocol.create_auth_response(
                    True, "Data channel connected"
                )
                await websocket.send(response.to_json())
                logger.info(f"Data channel authenticated for {token.client_name}")

            except asyncio.TimeoutError:
                logger.warning(f"Data channel auth timeout from {client_addr}")
                return

            # Main data receive loop
            async for message in websocket:
                if isinstance(message, bytes):
                    await self._process_audio_data(message, websocket)
                else:
                    # Text message on data channel (shouldn't happen normally)
                    logger.warning(f"Unexpected text message on data channel: {message}")

        except ConnectionClosed:
            logger.info(f"Data connection closed from {client_addr}")
        except Exception as e:
            logger.error(f"Error in data handler: {e}", exc_info=True)
        finally:
            if self._data_connection == websocket:
                self._data_connection = None

    async def _process_audio_data(self, data: bytes, websocket: ServerConnection) -> None:
        """Process incoming audio data."""
        if not self._is_transcribing:
            logger.debug("Received audio data but not transcribing, ignoring")
            return

        try:
            # Parse audio chunk
            chunk = AudioChunk.from_bytes(data)

            # Process and buffer audio
            audio_float = self.audio_protocol.process_incoming_audio(chunk)
            self._audio_accumulator.append(audio_float)

            # Real-time transcription if enabled and callback available
            if (
                self._session_config.get("enable_realtime", True)
                and self._realtime_callback is not None
            ):
                partial_text = self._realtime_callback(audio_float)
                if partial_text:
                    result = ControlMessage(
                        type=MessageType.REALTIME,
                        data={"text": partial_text, "is_final": False},
                    )
                    # Send on control channel if available
                    if self._control_connection:
                        await self._control_connection.send(result.to_json())

        except Exception as e:
            logger.error(f"Error processing audio data: {e}", exc_info=True)

    async def _finalize_transcription(self, websocket: ServerConnection) -> None:
        """Finalize transcription and send results."""
        self._is_transcribing = False

        if not self._audio_accumulator:
            response = ControlMessage(
                type=MessageType.SESSION_STOPPED,
                data={"message": "No audio received"},
            )
            await websocket.send(response.to_json())
            return

        # Combine all audio chunks
        combined_audio = np.concatenate(self._audio_accumulator)
        self._audio_accumulator.clear()

        # Perform transcription if callback available
        if self._transcribe_callback is not None:
            try:
                language = self._session_config.get("language")
                result = self._transcribe_callback(combined_audio, language)

                # Send final result
                final_msg = ControlMessage(
                    type=MessageType.FINAL,
                    data={
                        "text": result.get("text", ""),
                        "words": result.get("words", []),
                        "duration": result.get("duration", 0.0),
                        "language": result.get("language", language),
                        "is_final": True,
                    },
                )
                await websocket.send(final_msg.to_json())

            except Exception as e:
                logger.error(f"Transcription error: {e}", exc_info=True)
                error_msg = ControlProtocol.create_error(
                    f"Transcription failed: {e}", "transcription_error"
                )
                await websocket.send(error_msg.to_json())
        else:
            # No callback - just acknowledge
            response = ControlMessage(
                type=MessageType.SESSION_STOPPED,
                data={
                    "message": "Session stopped",
                    "audio_duration": len(combined_audio) / SAMPLE_RATE,
                },
            )
            await websocket.send(response.to_json())

        logger.info("Transcription session finalized")

    async def _run_servers(self) -> None:
        """Run both WebSocket servers."""
        tls_status = "with TLS" if self._ssl_context else "without TLS"
        logger.info(
            f"Starting servers on {self.host} "
            f"(control:{self.control_port}, data:{self.data_port}) {tls_status}"
        )

        # Determine WebSocket scheme for logging
        ws_scheme = "wss" if self._ssl_context else "ws"

        async with (
            websockets.serve(
                self._handle_control,
                self.host,
                self.control_port,
                ssl=self._ssl_context,
            ) as control_server,
            websockets.serve(
                self._handle_data,
                self.host,
                self.data_port,
                ssl=self._ssl_context,
            ) as data_server,
        ):
            self._control_server = control_server
            self._data_server = data_server
            self._is_running = True

            logger.info("Remote transcription server started")
            logger.info(
                f"  Control channel: {ws_scheme}://{self.host}:{self.control_port}"
            )
            logger.info(f"  Data channel: {ws_scheme}://{self.host}:{self.data_port}")

            # Wait until shutdown
            stop_event = asyncio.Event()

            def signal_handler():
                stop_event.set()

            # Register signal handlers
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    loop.add_signal_handler(sig, signal_handler)
                except NotImplementedError:
                    # Windows doesn't support add_signal_handler
                    pass

            await stop_event.wait()

        self._is_running = False
        logger.info("Remote transcription server stopped")

    def start(self, blocking: bool = True) -> Optional[threading.Thread]:
        """
        Start the remote transcription server.

        Args:
            blocking: If True, blocks until server stops.
                     If False, runs in a background thread.

        Returns:
            Thread object if non-blocking, None otherwise
        """
        if blocking:
            asyncio.run(self._run_servers())
            return None
        else:
            thread = threading.Thread(target=lambda: asyncio.run(self._run_servers()))
            thread.daemon = True
            thread.start()
            return thread

    def stop(self) -> None:
        """Stop the server."""
        self._is_running = False
        if self._control_server:
            self._control_server.close()
        if self._data_server:
            self._data_server.close()

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._is_running

    @property
    def is_transcribing(self) -> bool:
        """Check if a transcription is in progress."""
        return self._is_transcribing

    def get_status(self) -> Dict[str, Any]:
        """Get server status."""
        return {
            "is_running": self._is_running,
            "is_transcribing": self._is_transcribing,
            "active_client": self.auth_manager.get_active_client_name(),
            "control_port": self.control_port,
            "data_port": self.data_port,
        }
