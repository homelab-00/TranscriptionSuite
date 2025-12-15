"""
Combined HTTPS + WebSocket server for remote transcription.

Provides:
- HTTPS server for REST API and static file serving (React frontend)
- WSS server for real-time audio streaming
- Token-based authentication (no expiry, manual revocation)
- Admin panel for token management
"""

import asyncio
import json
import mimetypes
import signal
import ssl
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional, cast

import numpy as np
from aiohttp import web
from aiohttp.multipart import BodyPartReader
from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed
import websockets

from .auth import AuthManager
from .token_store import StoredToken
from .server_logging import get_server_logger, get_websocket_logger, get_api_logger
from .protocol import (
    AudioChunk,
    AudioProtocol,
    ControlMessage,
    ControlProtocol,
    MessageType,
    SAMPLE_RATE,
)

# Initialize logger from server_logging (writes to server_mode.log)
logger = get_server_logger()
ws_logger = get_websocket_logger()
api_logger = get_api_logger()

# Default ports
DEFAULT_HTTPS_PORT = 8443
DEFAULT_WSS_PORT = 8444

# Static files directory
WEB_DIST_DIR = Path(__file__).parent / "web" / "dist"

# Maximum file upload size (500MB)
MAX_UPLOAD_SIZE = 500 * 1024 * 1024


class WebTranscriptionServer:
    """
    Combined HTTPS + WebSocket server for remote transcription.

    Architecture:
    - Port 8443 (HTTPS): React web UI, REST API for auth/tokens/file upload
    - Port 8444 (WSS): WebSocket for streaming audio transcription
    """

    def __init__(
        self,
        config: Dict[str, Any],
        transcribe_callback: Optional[
            Callable[[np.ndarray, Optional[str]], Dict[str, Any]]
        ] = None,
        transcribe_file_callback: Optional[
            Callable[[Path, Optional[str]], Dict[str, Any]]
        ] = None,
        realtime_callback: Optional[Callable[[np.ndarray], Optional[str]]] = None,
    ):
        """
        Initialize the web transcription server.

        Args:
            config: Server configuration from config.yaml
            transcribe_callback: Callback for transcribing audio array
            transcribe_file_callback: Callback for transcribing audio file
            realtime_callback: Callback for real-time preview
        """
        self.config = config.get("remote_server", {})

        # Network configuration
        self.host = self.config.get("host", "0.0.0.0")
        self.https_port = self.config.get("https_port", DEFAULT_HTTPS_PORT)
        self.wss_port = self.config.get("wss_port", DEFAULT_WSS_PORT)

        # Token store path
        token_store_path = self.config.get("token_store")
        if token_store_path:
            token_store_path = Path(token_store_path)

        # Authentication
        self.auth_manager = AuthManager(token_store_path)

        # TLS configuration
        self._ssl_context = self._create_ssl_context()

        # Callbacks
        self._transcribe_callback = transcribe_callback
        self._transcribe_file_callback = transcribe_file_callback
        self._realtime_callback = realtime_callback

        # Protocol handler
        self.audio_protocol = AudioProtocol(target_sample_rate=SAMPLE_RATE)

        # Session state
        self._is_running = False
        self._is_transcribing = False
        self._session_config: Dict[str, Any] = {}

        # WebSocket connection (only one at a time)
        self._ws_connection: Optional[ServerConnection] = None
        self._ws_token: Optional[str] = None

        # Audio accumulator
        self._audio_accumulator: list[np.ndarray] = []

        # aiohttp app
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None

        tls_status = "TLS enabled" if self._ssl_context else "TLS disabled"
        logger.info(
            f"WebTranscriptionServer initialized "
            f"(https:{self.https_port}, wss:{self.wss_port}, {tls_status})"
        )

    def _create_ssl_context(self) -> Optional[ssl.SSLContext]:
        """Create SSL context, auto-generating certificates if needed."""
        tls_config = self.config.get("tls", {})

        if not tls_config.get("enabled", False):
            return None

        cert_file = tls_config.get("cert_file")
        key_file = tls_config.get("key_file")
        auto_generate = tls_config.get("auto_generate", True)

        # Convert to absolute paths if relative
        if cert_file and not Path(cert_file).is_absolute():
            cert_file = Path(__file__).parent.parent / cert_file
        if key_file and not Path(key_file).is_absolute():
            key_file = Path(__file__).parent.parent / key_file

        # Auto-generate self-signed certificate if missing
        if auto_generate and (not cert_file or not Path(cert_file).exists()):
            cert_file, key_file = self._generate_self_signed_cert()

        if not cert_file or not key_file:
            logger.warning("TLS enabled but certificates not available")
            return None

        cert_path = Path(cert_file)
        key_path = Path(key_file)

        if not cert_path.exists() or not key_path.exists():
            logger.error("TLS cert or key file not found")
            return None

        try:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
            ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
            logger.info(f"TLS enabled with cert: {cert_path}")
            return ssl_context
        except Exception as e:
            logger.error(f"Failed to create SSL context: {e}")
            return None

    def _generate_self_signed_cert(self) -> tuple[Path, Path]:
        """Generate a self-signed certificate."""
        data_dir = Path(__file__).parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        cert_file = data_dir / "cert.pem"
        key_file = data_dir / "key.pem"

        if cert_file.exists() and key_file.exists():
            logger.info("Using existing self-signed certificate")
            return cert_file, key_file

        logger.info("Generating self-signed certificate...")

        try:
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:4096",
                    "-nodes",
                    "-keyout",
                    str(key_file),
                    "-out",
                    str(cert_file),
                    "-days",
                    "3650",
                    "-subj",
                    "/CN=transcription-server",
                ],
                check=True,
                capture_output=True,
            )
            logger.info(f"Self-signed certificate generated at {cert_file}")
            return cert_file, key_file
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to generate certificate: {e.stderr.decode()}")
            raise RuntimeError("Failed to generate self-signed certificate")
        except FileNotFoundError:
            logger.error(
                "openssl not found. Please install openssl or provide certificates."
            )
            raise RuntimeError("openssl not found")

    # =========================================================================
    # REST API Handlers
    # =========================================================================

    async def _handle_login(self, request: web.Request) -> web.Response:
        """POST /api/auth/login - Validate token and return user info."""
        try:
            data = await request.json()
            token = data.get("token", "")

            stored_token = self.auth_manager.validate_token(token)
            if stored_token is None:
                return web.json_response(
                    {"success": False, "message": "Invalid or revoked token"}, status=401
                )

            return web.json_response(
                {
                    "success": True,
                    "user": {
                        "name": stored_token.client_name,
                        "is_admin": stored_token.is_admin,
                        "created_at": stored_token.created_at,
                    },
                }
            )
        except json.JSONDecodeError:
            return web.json_response(
                {"success": False, "message": "Invalid JSON"}, status=400
            )

    async def _handle_list_tokens(self, request: web.Request) -> web.Response:
        """GET /api/auth/tokens - List all tokens (admin only)."""
        # Check authorization
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return web.json_response({"error": "Unauthorized"}, status=401)

        token = auth_header[7:]
        if not self.auth_manager.is_admin(token):
            return web.json_response({"error": "Admin required"}, status=403)

        tokens = self.auth_manager.list_tokens()
        return web.json_response(
            {
                "tokens": [
                    {
                        "token": t.token[:8] + "..." + t.token[-4:],  # Masked
                        "full_token": t.token,  # Full token for copy
                        "client_name": t.client_name,
                        "created_at": t.created_at,
                        "is_admin": t.is_admin,
                        "is_revoked": t.is_revoked,
                    }
                    for t in tokens
                ]
            }
        )

    async def _handle_create_token(self, request: web.Request) -> web.Response:
        """POST /api/auth/tokens - Generate new token (admin only)."""
        # Check authorization
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return web.json_response({"error": "Unauthorized"}, status=401)

        admin_token = auth_header[7:]
        if not self.auth_manager.is_admin(admin_token):
            return web.json_response({"error": "Admin required"}, status=403)

        try:
            data = await request.json()
            client_name = data.get("client_name", "unnamed")
            is_admin = data.get("is_admin", False)

            new_token = self.auth_manager.generate_token(client_name, is_admin)

            return web.json_response(
                {
                    "success": True,
                    "token": {
                        "token": new_token.token,
                        "client_name": new_token.client_name,
                        "created_at": new_token.created_at,
                        "is_admin": new_token.is_admin,
                    },
                }
            )
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

    async def _handle_revoke_token(self, request: web.Request) -> web.Response:
        """DELETE /api/auth/tokens/{token} - Revoke a token (admin only)."""
        # Check authorization
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return web.json_response({"error": "Unauthorized"}, status=401)

        admin_token = auth_header[7:]
        if not self.auth_manager.is_admin(admin_token):
            return web.json_response({"error": "Admin required"}, status=403)

        token_to_revoke = request.match_info.get("token", "")

        if self.auth_manager.revoke_token(token_to_revoke):
            return web.json_response({"success": True})
        else:
            return web.json_response(
                {"error": "Token not found or is active session"}, status=404
            )

    async def _handle_transcribe_file(self, request: web.Request) -> web.Response:
        """POST /api/transcribe/file - Upload and transcribe audio file."""
        # Check authorization
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return web.json_response({"error": "Unauthorized"}, status=401)

        token = auth_header[7:]
        if self.auth_manager.validate_token(token) is None:
            return web.json_response({"error": "Invalid token"}, status=401)

        if self._transcribe_file_callback is None:
            return web.json_response({"error": "Transcription not available"}, status=503)

        # Check if another transcription is in progress
        if self._is_transcribing:
            return web.json_response(
                {"error": "Another transcription is in progress"}, status=409
            )

        try:
            self._is_transcribing = True

            # Read multipart form data
            reader = await request.multipart()

            audio_file: Optional[Path] = None
            language: Optional[str] = None

            async for field in reader:
                # Cast field to BodyPartReader (aiohttp's multipart field type)
                part = cast(BodyPartReader, field)
                if part.name == "file":
                    # Save to temp file
                    suffix = Path(part.filename or "audio").suffix or ".wav"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        while True:
                            chunk = await part.read_chunk()
                            if not chunk:
                                break
                            tmp.write(chunk)
                        audio_file = Path(tmp.name)
                elif part.name == "language":
                    language = (await part.read()).decode()

            if audio_file is None:
                return web.json_response({"error": "No file uploaded"}, status=400)

            # Perform transcription
            try:
                result = self._transcribe_file_callback(audio_file, language)
                return web.json_response(
                    {
                        "success": True,
                        "text": result.get("text", ""),
                        "segments": result.get("segments", []),
                        "duration": result.get("duration", 0.0),
                        "language": result.get("language"),
                    }
                )
            finally:
                # Clean up temp file
                if audio_file.exists():
                    audio_file.unlink()

        finally:
            self._is_transcribing = False

    async def _handle_server_status(self, request: web.Request) -> web.Response:
        """GET /api/status - Get server status."""
        return web.json_response(
            {
                "running": self._is_running,
                "transcribing": self._is_transcribing,
                "active_user": self.auth_manager.get_active_client_name(),
                "https_port": self.https_port,
                "wss_port": self.wss_port,
            }
        )

    async def _handle_static(self, request: web.Request) -> web.Response:
        """Serve static files from web/dist."""
        path = request.match_info.get("path", "")

        if not path or path == "/":
            path = "index.html"

        file_path = WEB_DIST_DIR / path

        # Security: prevent directory traversal
        try:
            file_path = file_path.resolve()
            if not str(file_path).startswith(str(WEB_DIST_DIR.resolve())):
                return web.Response(status=403)
        except (ValueError, RuntimeError):
            return web.Response(status=403)

        if not file_path.exists():
            # SPA fallback - serve index.html for client-side routing
            file_path = WEB_DIST_DIR / "index.html"
            if not file_path.exists():
                return web.Response(status=404, text="Not Found")

        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"

        return web.FileResponse(file_path, headers={"Content-Type": content_type})  # type: ignore[return-value]

    # =========================================================================
    # WebSocket Handler
    # =========================================================================

    async def _handle_websocket(self, websocket: ServerConnection) -> None:
        """Handle WebSocket connection for audio streaming."""
        client_addr = websocket.remote_address
        ws_logger.info(f"WebSocket connection established from {client_addr}")

        token: Optional[str] = None
        stored_token: Optional[StoredToken] = None

        try:
            # Wait for authentication
            try:
                ws_logger.debug(f"Waiting for auth message from {client_addr}...")
                auth_message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                ws_logger.debug(
                    f"Received message: {auth_message[:100]}..."
                )  # Log first 100 chars

                msg = ControlMessage.from_json(auth_message)  # type: ignore
                ws_logger.debug(f"Parsed message type: {msg.type}")

                if msg.type != MessageType.AUTH:
                    ws_logger.warning(f"Expected AUTH, got {msg.type}")
                    response = ControlProtocol.create_auth_response(
                        False, "Expected authentication message"
                    )
                    await websocket.send(response.to_json())
                    return

                token_value = msg.data.get("token")
                token = token_value if isinstance(token_value, str) else ""
                if token:
                    ws_logger.debug(
                        f"Validating token: {token[:16]}..."
                    )  # Log first 16 chars
                stored_token = self.auth_manager.validate_token(token)

                if stored_token is None:
                    ws_logger.warning(f"Token validation failed for {client_addr}")
                    response = ControlProtocol.create_auth_response(
                        False, "Invalid or revoked token"
                    )
                    await websocket.send(response.to_json())
                    return

                # Try to acquire session
                ws_logger.debug(
                    f"Attempting to acquire session for {stored_token.client_name}"
                )
                if not self.auth_manager.acquire_session(stored_token):
                    active_user = self.auth_manager.get_active_client_name() or "unknown"
                    ws_logger.warning(f"Session denied: {active_user} is already active")
                    response = ControlProtocol.create_session_busy_response(active_user)
                    await websocket.send(response.to_json())
                    return

                # Success
                self._ws_connection = websocket
                self._ws_token = token

                response = ControlMessage(
                    type=MessageType.AUTH_OK,
                    data={
                        "user": {
                            "name": stored_token.client_name,
                            "is_admin": stored_token.is_admin,
                        }
                    },
                )
                await websocket.send(response.to_json())
                ws_logger.info(f"WebSocket authenticated: {stored_token.client_name}")

            except asyncio.TimeoutError:
                ws_logger.warning(f"WebSocket auth timeout from {client_addr}")
                response = ControlProtocol.create_auth_response(False, "Auth timeout")
                await websocket.send(response.to_json())
                return

            # Main message loop
            async for message in websocket:
                if isinstance(message, bytes):
                    await self._process_audio_data(message, websocket)
                elif isinstance(message, str):
                    await self._process_control_message(message, websocket)

        except ConnectionClosed as e:
            ws_logger.info(f"WebSocket closed from {client_addr}: {e.code} {e.reason}")
        except Exception as e:
            ws_logger.error(f"WebSocket error from {client_addr}: {e}", exc_info=True)
        finally:
            # Cleanup
            if token and self._ws_token == token:
                self.auth_manager.release_session(token)
                self._ws_connection = None
                self._ws_token = None
                self._is_transcribing = False
                self.audio_protocol.clear_buffer()
                self._audio_accumulator.clear()
                ws_logger.info("Session released")

    async def _process_control_message(
        self, message: str, websocket: ServerConnection
    ) -> None:
        """Process a control message from WebSocket."""
        try:
            msg = ControlMessage.from_json(message)
        except ValueError as e:
            error = ControlProtocol.create_error(str(e), "parse_error")
            await websocket.send(error.to_json())
            return

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

            self._session_config = {
                "language": msg.data.get("language"),
                "enable_realtime": msg.data.get("enable_realtime", False),
            }

            self._is_transcribing = True
            self._audio_accumulator.clear()
            self.audio_protocol.clear_buffer()

            response = ControlMessage(
                type=MessageType.SESSION_STARTED, data={"config": self._session_config}
            )
            await websocket.send(response.to_json())
            logger.info("Recording session started")

        elif msg.type == MessageType.STOP:
            if not self._is_transcribing:
                error = ControlProtocol.create_error(
                    "No active recording session", "not_started"
                )
                await websocket.send(error.to_json())
                return

            await self._finalize_transcription(websocket)

        else:
            error = ControlProtocol.create_error(
                f"Unknown message type: {msg.type}", "unknown_type"
            )
            await websocket.send(error.to_json())

    async def _process_audio_data(self, data: bytes, websocket: ServerConnection) -> None:
        """Process incoming audio data."""
        if not self._is_transcribing:
            logger.debug("Received audio but not recording, ignoring")
            return

        try:
            chunk = AudioChunk.from_bytes(data)
            audio_float = self.audio_protocol.process_incoming_audio(chunk)
            self._audio_accumulator.append(audio_float)

            # Real-time preview if enabled
            if (
                self._session_config.get("enable_realtime", False)
                and self._realtime_callback is not None
            ):
                partial = self._realtime_callback(audio_float)
                if partial:
                    result = ControlMessage(
                        type=MessageType.REALTIME,
                        data={"text": partial, "is_final": False},
                    )
                    await websocket.send(result.to_json())

        except Exception as e:
            logger.error(f"Error processing audio: {e}", exc_info=True)

    async def _finalize_transcription(self, websocket: ServerConnection) -> None:
        """Finalize recording and send transcription result."""
        self._is_transcribing = False

        if not self._audio_accumulator:
            response = ControlMessage(
                type=MessageType.SESSION_STOPPED, data={"message": "No audio received"}
            )
            await websocket.send(response.to_json())
            return

        # Combine audio
        combined_audio = np.concatenate(self._audio_accumulator)
        self._audio_accumulator.clear()

        if self._transcribe_callback is not None:
            try:
                language = self._session_config.get("language")
                result = self._transcribe_callback(combined_audio, language)

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
                logger.info("Transcription completed")

            except Exception as e:
                logger.error(f"Transcription error: {e}", exc_info=True)
                error = ControlProtocol.create_error(
                    f"Transcription failed: {e}", "transcription_error"
                )
                await websocket.send(error.to_json())
        else:
            response = ControlMessage(
                type=MessageType.SESSION_STOPPED,
                data={
                    "message": "Recording stopped (no transcriber)",
                    "duration": len(combined_audio) / SAMPLE_RATE,
                },
            )
            await websocket.send(response.to_json())

    # =========================================================================
    # Server Lifecycle
    # =========================================================================

    def _setup_routes(self) -> web.Application:
        """Set up aiohttp routes."""
        app = web.Application(client_max_size=MAX_UPLOAD_SIZE)

        # API routes
        app.router.add_post("/api/auth/login", self._handle_login)
        app.router.add_get("/api/auth/tokens", self._handle_list_tokens)
        app.router.add_post("/api/auth/tokens", self._handle_create_token)
        app.router.add_delete("/api/auth/tokens/{token}", self._handle_revoke_token)
        app.router.add_post("/api/transcribe/file", self._handle_transcribe_file)
        app.router.add_get("/api/status", self._handle_server_status)

        # Static files (SPA)
        app.router.add_get("/{path:.*}", self._handle_static)

        return app

    async def _run_servers(self) -> None:
        """Run both HTTPS and WSS servers."""
        scheme = "https" if self._ssl_context else "http"
        ws_scheme = "wss" if self._ssl_context else "ws"

        logger.info(f"Starting servers on {self.host}")
        logger.info(f"  HTTPS: {scheme}://{self.host}:{self.https_port}")
        logger.info(f"  WSS:   {ws_scheme}://{self.host}:{self.wss_port}")

        # Set up aiohttp app
        self._app = self._setup_routes()
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        site = web.TCPSite(
            self._runner,
            self.host,
            self.https_port,
            ssl_context=self._ssl_context,
        )

        # Start HTTPS server
        await site.start()

        # Start WebSocket server
        async with websockets.serve(
            self._handle_websocket,
            self.host,
            self.wss_port,
            ssl=self._ssl_context,
        ):
            self._is_running = True
            logger.info("Servers started")

            # Wait for shutdown
            stop_event = asyncio.Event()

            def signal_handler():
                stop_event.set()

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    loop.add_signal_handler(sig, signal_handler)
                except NotImplementedError:
                    pass

            await stop_event.wait()

        # Cleanup
        await self._runner.cleanup()
        self._is_running = False
        logger.info("Servers stopped")

    def start(self, blocking: bool = True) -> None:
        """Start the servers."""
        if blocking:
            asyncio.run(self._run_servers())
        else:
            import threading

            thread = threading.Thread(target=lambda: asyncio.run(self._run_servers()))
            thread.daemon = True
            thread.start()

    def stop(self) -> None:
        """Stop the servers."""
        self._is_running = False

    @property
    def is_running(self) -> bool:
        """Check if servers are running."""
        return self._is_running

    def get_status(self) -> Dict[str, Any]:
        """Get server status."""
        return {
            "running": self._is_running,
            "transcribing": self._is_transcribing,
            "active_user": self.auth_manager.get_active_client_name(),
            "https_port": self.https_port,
            "wss_port": self.wss_port,
        }
