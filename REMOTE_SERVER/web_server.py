"""
Combined HTTPS + WebSocket server for remote transcription.

Provides:
- HTTPS server for REST API and static file serving (React frontend)
- WSS server for real-time audio streaming (on same port as HTTPS)
- Token-based authentication with expiration
- Rate limiting on authentication endpoints
- Admin panel for token management
"""

import asyncio
import json
import mimetypes
import os
import signal
import ssl
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Optional, cast

import numpy as np
from aiohttp import web, WSMsgType
from aiohttp.multipart import BodyPartReader

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

# Default port (single port for both HTTPS and WSS)
DEFAULT_HTTPS_PORT = 8443

# Static files directory
WEB_DIST_DIR = Path(__file__).parent / "web" / "dist"


def _safe_static_file(base_dir: Path, requested_path: str) -> Optional[Path]:
    """Safely resolve a static file path, preventing directory traversal.

    Returns the resolved path if it's safe and exists, None otherwise.
    This function acts as a sanitizer for CodeQL path-injection analysis.
    """
    if not requested_path:
        requested_path = "index.html"
    # Reject obviously malicious patterns early
    if ".." in requested_path or requested_path.startswith("/"):
        return None
    try:
        base_resolved = base_dir.resolve(strict=True)
        candidate = (base_dir / requested_path).resolve()
        if candidate.is_relative_to(base_resolved) and candidate.is_file():
            return candidate
    except (ValueError, RuntimeError, OSError):
        pass
    return None


# Maximum file upload size (500MB)
MAX_UPLOAD_SIZE = 500 * 1024 * 1024

# Rate limiting settings
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX_ATTEMPTS = 5  # max failed attempts per window
RATE_LIMIT_LOCKOUT_TIME = 300  # 5 minutes lockout after exceeding limit


class RateLimiter:
    """
    Simple in-memory rate limiter for authentication attempts.

    Tracks failed login attempts per IP address and temporarily blocks
    IPs that exceed the limit.
    """

    def __init__(
        self,
        window: int = RATE_LIMIT_WINDOW,
        max_attempts: int = RATE_LIMIT_MAX_ATTEMPTS,
        lockout_time: int = RATE_LIMIT_LOCKOUT_TIME,
    ):
        self.window = window
        self.max_attempts = max_attempts
        self.lockout_time = lockout_time
        # {ip: [timestamp1, timestamp2, ...]}
        self._attempts: Dict[str, list[float]] = defaultdict(list)
        # {ip: lockout_until_timestamp}
        self._lockouts: Dict[str, float] = {}

    def _cleanup_old_attempts(self, ip: str) -> None:
        """Remove attempts older than the window."""
        cutoff = time.time() - self.window
        self._attempts[ip] = [t for t in self._attempts[ip] if t > cutoff]

    def is_blocked(self, ip: str) -> tuple[bool, Optional[int]]:
        """
        Check if an IP is blocked.

        Returns:
            (is_blocked, seconds_remaining) - seconds_remaining is None if not blocked
        """
        if ip in self._lockouts:
            remaining = self._lockouts[ip] - time.time()
            if remaining > 0:
                return True, int(remaining)
            else:
                # Lockout expired
                del self._lockouts[ip]
                self._attempts.pop(ip, None)

        return False, None

    def record_attempt(self, ip: str, success: bool) -> None:
        """
        Record a login attempt.

        Args:
            ip: Client IP address
            success: Whether the login was successful
        """
        if success:
            # Successful login clears the attempts
            self._attempts.pop(ip, None)
            self._lockouts.pop(ip, None)
            return

        # Record failed attempt
        self._cleanup_old_attempts(ip)
        self._attempts[ip].append(time.time())

        # Check if we should lock out this IP
        if len(self._attempts[ip]) >= self.max_attempts:
            self._lockouts[ip] = time.time() + self.lockout_time
            logger.warning(
                f"Rate limit exceeded for {ip}: {len(self._attempts[ip])} failed attempts. "
                f"Locked out for {self.lockout_time} seconds."
            )

    def get_remaining_attempts(self, ip: str) -> int:
        """Get the number of remaining attempts for an IP."""
        self._cleanup_old_attempts(ip)
        return max(0, self.max_attempts - len(self._attempts[ip]))


class WebTranscriptionServer:
    """
    Combined HTTPS + WebSocket server for remote transcription.

    Architecture:
    - Port 8443: Both HTTPS (React web UI, REST API) and WSS (streaming audio)
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

        # Token store path
        token_store_path = self.config.get("token_store")
        if token_store_path:
            token_store_path = Path(token_store_path)

        # Authentication
        self.auth_manager = AuthManager(token_store_path)

        # Rate limiter for auth endpoints
        self._rate_limiter = RateLimiter()

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
        self._stop_event: Optional[asyncio.Event] = None

        # WebSocket connection (only one at a time)
        self._ws_connection: Optional[web.WebSocketResponse] = None
        self._ws_token: Optional[str] = None

        # Audio accumulator
        self._audio_accumulator: list[np.ndarray] = []

        # aiohttp app
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None

        tls_status = "TLS enabled" if self._ssl_context else "TLS disabled"
        logger.info(
            f"WebTranscriptionServer initialized "
            f"(https/wss:{self.https_port}, {tls_status})"
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
            logger.error(f"Failed to create SSL context: {e}", exc_info=True)
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
        # Get client IP for rate limiting
        client_ip = request.remote or "unknown"

        # Check if IP is rate limited
        is_blocked, remaining_seconds = self._rate_limiter.is_blocked(client_ip)
        if is_blocked:
            api_logger.warning(f"Rate limited login attempt from {client_ip}")
            return web.json_response(
                {
                    "success": False,
                    "message": f"Too many failed attempts. Try again in {remaining_seconds} seconds.",
                    "retry_after": remaining_seconds,
                },
                status=429,
            )

        try:
            data = await request.json()
            token = data.get("token", "")

            stored_token = self.auth_manager.validate_token(token)
            if stored_token is None:
                # Record failed attempt
                self._rate_limiter.record_attempt(client_ip, success=False)
                remaining = self._rate_limiter.get_remaining_attempts(client_ip)

                api_logger.warning(
                    f"Failed login attempt from {client_ip} ({remaining} attempts remaining)"
                )

                return web.json_response(
                    {
                        "success": False,
                        "message": "Invalid, revoked, or expired token",
                        "remaining_attempts": remaining,
                    },
                    status=401,
                )

            # Successful login - clear rate limit tracking
            self._rate_limiter.record_attempt(client_ip, success=True)

            return web.json_response(
                {
                    "success": True,
                    "user": {
                        "name": stored_token.client_name,
                        "is_admin": stored_token.is_admin,
                        "created_at": stored_token.created_at,
                        "expires_at": stored_token.expires_at,
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
                        "token_id": t.token_id,  # Non-secret ID for operations
                        "token": t.token[:8]
                        + "..."
                        + t.token[-4:],  # Masked for security
                        # Note: full_token removed for security - tokens only shown at creation
                        "client_name": t.client_name,
                        "created_at": t.created_at,
                        "expires_at": t.expires_at,
                        "is_admin": t.is_admin,
                        "is_revoked": t.is_revoked,
                        "is_expired": t.is_expired(),
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
            expiry_days = data.get("expiry_days")  # Optional: custom expiry

            # generate_token returns (StoredToken with hash, plaintext token)
            stored_token, plaintext_token = self.auth_manager.generate_token(
                client_name, is_admin, expiry_days
            )

            # Full token shown ONLY at creation time - this is the only chance to copy it
            return web.json_response(
                {
                    "success": True,
                    "message": "Save this token now! It will only be shown once.",
                    "token": {
                        "token_id": stored_token.token_id,  # ID for future operations
                        "token": plaintext_token,  # Plaintext token - only shown at creation
                        "client_name": stored_token.client_name,
                        "created_at": stored_token.created_at,
                        "expires_at": stored_token.expires_at,
                        "is_admin": stored_token.is_admin,
                    },
                }
            )
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

    async def _handle_revoke_token(self, request: web.Request) -> web.Response:
        """DELETE /api/auth/tokens/{token_id} - Revoke a token by ID (admin only)."""
        # Check authorization
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return web.json_response({"error": "Unauthorized"}, status=401)

        admin_token = auth_header[7:]
        if not self.auth_manager.is_admin(admin_token):
            return web.json_response({"error": "Admin required"}, status=403)

        token_id = request.match_info.get("token", "")

        if self.auth_manager.revoke_token_by_id(token_id):
            return web.json_response({"success": True})
        else:
            return web.json_response(
                {"error": "Token not found or is active session"}, status=404
            )

    # Audio file magic bytes for validation
    AUDIO_MAGIC_BYTES = {
        b"ID3": "mp3",  # MP3 with ID3 tag
        b"\xff\xfb": "mp3",  # MP3 frame sync
        b"\xff\xfa": "mp3",  # MP3 frame sync
        b"\xff\xf3": "mp3",  # MP3 frame sync
        b"\xff\xf2": "mp3",  # MP3 frame sync
        b"RIFF": "wav",  # WAV
        b"fLaC": "flac",  # FLAC
        b"OggS": "ogg",  # OGG/Vorbis/Opus
        b"\x1aE\xdf\xa3": "webm",  # WebM/Matroska
        b"\x00\x00\x00": "mp4",  # MP4/M4A (ftyp follows)
    }

    def _validate_audio_magic(self, header: bytes) -> bool:
        """Validate file header against known audio magic bytes."""
        # Check 4-byte signatures first
        if header[:4] in (b"RIFF", b"fLaC", b"OggS", b"\x1aE\xdf\xa3"):
            return True
        # Check 3-byte signatures
        if header[:3] == b"ID3":
            return True
        # Check 2-byte signatures (MP3 frame sync)
        if header[:2] in (b"\xff\xfb", b"\xff\xfa", b"\xff\xf3", b"\xff\xf2"):
            return True
        # Check for MP4/M4A (starts with size bytes, then 'ftyp')
        if header[:3] == b"\x00\x00\x00" or header[4:8] == b"ftyp":
            return True
        return False

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
                        # Read first chunk to validate magic bytes
                        first_chunk = await part.read_chunk()
                        if not first_chunk:
                            return web.json_response({"error": "Empty file"}, status=400)

                        # Validate audio file magic bytes (need at least 8 bytes)
                        header = (
                            first_chunk[:12] if len(first_chunk) >= 12 else first_chunk
                        )
                        if not self._validate_audio_magic(header):
                            api_logger.warning(
                                f"File upload rejected: invalid audio format "
                                f"(header: {header[:8].hex()})"
                            )
                            return web.json_response(
                                {"error": "Invalid audio file format"}, status=400
                            )

                        # Write first chunk and continue
                        tmp.write(first_chunk)
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
        # Determine the scheme based on whether TLS is enabled
        scheme = "wss" if self._ssl_context else "ws"
        host = request.host.split(":")[0]

        return web.json_response(
            {
                "running": self._is_running,
                "transcribing": self._is_transcribing,
                "active_user": self.auth_manager.get_active_client_name(),
                "https_port": self.https_port,
                "wss_url": f"{scheme}://{host}:{self.https_port}/ws",
            }
        )

    async def _handle_static(self, request: web.Request) -> web.Response:
        """Serve static files from web/dist."""
        requested_path = request.match_info.get("path", "") or "index.html"

        # Use sanitizer function to get safe path
        safe_path = _safe_static_file(WEB_DIST_DIR, requested_path)

        if safe_path is None:
            # SPA fallback - serve index.html for client-side routing
            index_path = WEB_DIST_DIR / "index.html"
            if not index_path.exists():
                return web.Response(status=404, text="Not Found")
            safe_path = index_path

        content_type, _ = mimetypes.guess_type(str(safe_path))
        if content_type is None:
            content_type = "application/octet-stream"

        return web.FileResponse(safe_path, headers={"Content-Type": content_type})  # type: ignore[return-value]

    # =========================================================================
    # WebSocket Handler (aiohttp)
    # =========================================================================

    def _is_valid_origin(self, origin: Optional[str], request: web.Request) -> bool:
        """Validate WebSocket origin to prevent CSWSH attacks."""
        if not origin:
            # Allow connections without Origin header (non-browser clients)
            return True

        # Get the host from the request
        host = request.host.split(":")[0] if request.host else "localhost"
        port = self.https_port
        scheme = "https" if self._ssl_context else "http"

        # Build list of allowed origins
        allowed_origins = [
            f"{scheme}://{host}:{port}",
            f"{scheme}://{host}",
            f"{scheme}://localhost:{port}",
            f"{scheme}://localhost",
            f"{scheme}://127.0.0.1:{port}",
            f"{scheme}://127.0.0.1",
        ]

        # Also allow Tailscale IPs (100.x.x.x range)
        if host.startswith("100."):
            allowed_origins.append(f"{scheme}://{host}:{port}")
            allowed_origins.append(f"{scheme}://{host}")

        return origin in allowed_origins

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket connection for audio streaming (aiohttp route)."""
        # Validate Origin header to prevent Cross-Site WebSocket Hijacking
        origin = request.headers.get("Origin")
        if not self._is_valid_origin(origin, request):
            ws_logger.warning(f"WebSocket connection rejected: invalid origin '{origin}'")
            return web.Response(status=403, text="Origin not allowed")  # type: ignore[return-value]

        ws = web.WebSocketResponse()
        await ws.prepare(request)

        client_addr = request.remote
        ws_logger.info(f"WebSocket connection established from {client_addr}")

        token: Optional[str] = None
        stored_token: Optional[StoredToken] = None

        try:
            # Wait for authentication
            try:
                ws_logger.debug(f"Waiting for auth message from {client_addr}...")
                msg = await asyncio.wait_for(ws.receive(), timeout=10.0)

                if msg.type == WSMsgType.TEXT:
                    auth_message = msg.data
                    ws_logger.debug(f"Received message: {auth_message[:100]}...")

                    ctrl_msg = ControlMessage.from_json(auth_message)
                    ws_logger.debug(f"Parsed message type: {ctrl_msg.type}")

                    if ctrl_msg.type != MessageType.AUTH:
                        ws_logger.warning(f"Expected AUTH, got {ctrl_msg.type}")
                        response = ControlProtocol.create_auth_response(
                            False, "Expected authentication message"
                        )
                        await ws.send_str(response.to_json())
                        return ws

                    token_value = ctrl_msg.data.get("token")
                    token = token_value if isinstance(token_value, str) else ""
                    if token:
                        ws_logger.debug(f"Validating token: {token[:16]}...")
                    stored_token = self.auth_manager.validate_token(token)

                    if stored_token is None:
                        ws_logger.warning(f"Token validation failed for {client_addr}")
                        response = ControlProtocol.create_auth_response(
                            False, "Invalid or revoked token"
                        )
                        await ws.send_str(response.to_json())
                        return ws

                    # Try to acquire session
                    ws_logger.debug(
                        f"Attempting to acquire session for {stored_token.client_name}"
                    )
                    if not self.auth_manager.acquire_session(stored_token):
                        active_user = (
                            self.auth_manager.get_active_client_name() or "unknown"
                        )
                        ws_logger.warning(
                            f"Session denied: {active_user} is already active"
                        )
                        response = ControlProtocol.create_session_busy_response(
                            active_user
                        )
                        await ws.send_str(response.to_json())
                        return ws

                    # Success
                    self._ws_connection = ws
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
                    await ws.send_str(response.to_json())
                    ws_logger.info(f"WebSocket authenticated: {stored_token.client_name}")

                elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                    ws_logger.warning(f"WebSocket closed during auth from {client_addr}")
                    return ws

            except asyncio.TimeoutError:
                ws_logger.warning(f"WebSocket auth timeout from {client_addr}")
                response = ControlProtocol.create_auth_response(False, "Auth timeout")
                await ws.send_str(response.to_json())
                return ws

            # Main message loop
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    await self._process_audio_data_aiohttp(msg.data, ws)
                elif msg.type == WSMsgType.TEXT:
                    await self._process_control_message_aiohttp(msg.data, ws)
                elif msg.type == WSMsgType.ERROR:
                    ws_logger.error(f"WebSocket error: {ws.exception()}")
                    break

        except Exception as e:
            ws_logger.error(
                f"WebSocket error from {client_addr}: {type(e).__name__}", exc_info=True
            )
            # Send generic error to client, log details server-side only
            try:
                error = ControlProtocol.create_error(
                    "An internal error occurred", "server_error"
                )
                await ws.send_str(error.to_json())
            except Exception:
                pass  # Connection may be closed
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

        return ws

    async def _process_control_message_aiohttp(
        self, message: str, ws: web.WebSocketResponse
    ) -> None:
        """Process a control message from aiohttp WebSocket."""
        try:
            msg = ControlMessage.from_json(message)
        except ValueError as e:
            error = ControlProtocol.create_error(str(e), "parse_error")
            await ws.send_str(error.to_json())
            return

        logger.debug(f"Control message: {msg.type}")

        if msg.type == MessageType.PING:
            await ws.send_str(ControlProtocol.create_pong().to_json())

        elif msg.type == MessageType.START:
            ws_logger.info(f"START command received, language={msg.data.get('language')}")
            if self._is_transcribing:
                error = ControlProtocol.create_error(
                    "Transcription already in progress", "already_started"
                )
                await ws.send_str(error.to_json())
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
            await ws.send_str(response.to_json())
            ws_logger.info("Recording session started, waiting for audio...")

        elif msg.type == MessageType.STOP:
            ws_logger.info("STOP command received")
            if not self._is_transcribing:
                ws_logger.warning("STOP received but no active recording session")
                error = ControlProtocol.create_error(
                    "No active recording session", "not_started"
                )
                await ws.send_str(error.to_json())
                return

            await self._finalize_transcription_aiohttp(ws)

        else:
            error = ControlProtocol.create_error(
                f"Unknown message type: {msg.type}", "unknown_type"
            )
            await ws.send_str(error.to_json())

    async def _process_audio_data_aiohttp(
        self, data: bytes, ws: web.WebSocketResponse
    ) -> None:
        """Process incoming audio data from aiohttp WebSocket."""
        if not self._is_transcribing:
            logger.debug("Received audio but not recording, ignoring")
            return

        try:
            chunk = AudioChunk.from_bytes(data)
            audio_float = self.audio_protocol.process_incoming_audio(chunk)
            self._audio_accumulator.append(audio_float)

            # Log audio chunk reception periodically
            total_samples = sum(len(a) for a in self._audio_accumulator)
            if len(self._audio_accumulator) % 10 == 1:  # Log every 10 chunks
                duration_secs = total_samples / 16000
                ws_logger.debug(
                    f"Audio received: {len(self._audio_accumulator)} chunks, {duration_secs:.1f}s total"
                )

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
                    await ws.send_str(result.to_json())

        except Exception as e:
            logger.error(
                f"Error processing audio chunk ({len(data)} bytes): {type(e).__name__}",
                exc_info=True,
            )
            # Don't send error to client during streaming, just log it

    async def _finalize_transcription_aiohttp(self, ws: web.WebSocketResponse) -> None:
        """Finalize recording and send transcription result (aiohttp)."""
        self._is_transcribing = False

        ws_logger.info(
            f"Finalizing transcription with {len(self._audio_accumulator)} audio chunks"
        )

        if not self._audio_accumulator:
            ws_logger.warning("No audio data accumulated - sending session_stopped")
            response = ControlMessage(
                type=MessageType.SESSION_STOPPED, data={"message": "No audio received"}
            )
            await ws.send_str(response.to_json())
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
                await ws.send_str(final_msg.to_json())
                logger.info("Transcription completed")

            except Exception as e:
                logger.error(f"Transcription error: {type(e).__name__}", exc_info=True)
                # Send generic error to client, details logged server-side
                error = ControlProtocol.create_error(
                    "Transcription failed", "transcription_error"
                )
                await ws.send_str(error.to_json())
        else:
            response = ControlMessage(
                type=MessageType.SESSION_STOPPED,
                data={
                    "message": "Recording stopped (no transcriber)",
                    "duration": len(combined_audio) / SAMPLE_RATE,
                },
            )
            await ws.send_str(response.to_json())

    # =========================================================================
    # Server Lifecycle
    # =========================================================================

    @web.middleware
    async def _security_headers_middleware(
        self, request: web.Request, handler: Any
    ) -> web.Response:
        """Add security headers to all responses."""
        response = await handler(request)

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # HSTS - enforce HTTPS for 1 year
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

        # Content Security Policy - stricter in production
        is_production = os.getenv("ENVIRONMENT", "development") == "production"
        if is_production:
            # Production: no unsafe-inline (requires built assets with nonces)
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self'; "
                "connect-src 'self' wss:; "
                "img-src 'self' data:; "
                "frame-ancestors 'none'"
            )
        else:
            # Development: allow unsafe-inline for Vite dev mode
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "connect-src 'self' wss: ws:; "
                "img-src 'self' data:; "
                "frame-ancestors 'none'"
            )

        return response

    def _setup_routes(self) -> web.Application:
        """Set up aiohttp routes."""
        app = web.Application(
            client_max_size=MAX_UPLOAD_SIZE,
            middlewares=[self._security_headers_middleware],
        )

        # API routes
        app.router.add_post("/api/auth/login", self._handle_login)
        app.router.add_get("/api/auth/tokens", self._handle_list_tokens)
        app.router.add_post("/api/auth/tokens", self._handle_create_token)
        app.router.add_delete("/api/auth/tokens/{token}", self._handle_revoke_token)
        app.router.add_post("/api/transcribe/file", self._handle_transcribe_file)
        app.router.add_get("/api/status", self._handle_server_status)

        # WebSocket route (same port as HTTPS)
        app.router.add_get("/ws", self._handle_websocket)

        # Static files (SPA) - must be last
        app.router.add_get("/{path:.*}", self._handle_static)

        return app

    async def _run_servers(self) -> None:
        """Run the HTTPS server (with WebSocket on same port)."""
        scheme = "https" if self._ssl_context else "http"
        ws_scheme = "wss" if self._ssl_context else "ws"

        logger.info(f"Starting server on {self.host}:{self.https_port}")
        logger.info(f"  Web UI: {scheme}://{self.host}:{self.https_port}")
        logger.info(f"  WebSocket: {ws_scheme}://{self.host}:{self.https_port}/ws")

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

        # Start server
        await site.start()
        self._is_running = True
        logger.info("Server started")

        # Wait for shutdown
        stop_event = asyncio.Event()
        self._stop_event = stop_event

        def signal_handler():
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, signal_handler)
            except (NotImplementedError, RuntimeError):
                # NotImplementedError: signal handlers not implemented on this platform
                # RuntimeError: signal handlers only work in main thread
                pass

        await stop_event.wait()
        self._stop_event = None

        # Cleanup
        await self._runner.cleanup()
        self._is_running = False
        logger.info("Server stopped")

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
        if self._stop_event:
            # Trigger the stop event in a thread-safe way
            try:
                # Access the internal loop attribute (type: ignore because it's internal)
                loop = getattr(self._stop_event, "_loop", None)  # type: ignore[attr-defined]
                if loop:
                    loop.call_soon_threadsafe(self._stop_event.set)
            except (AttributeError, RuntimeError):
                # Event loop may be closed or not running
                pass

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
        }
