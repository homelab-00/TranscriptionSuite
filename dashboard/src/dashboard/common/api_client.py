"""
API client for TranscriptionSuite server communication.

Handles:
- HTTP requests to the unified API
- WebSocket connections for real-time streaming
- Authentication with tokens
- Connection state management
- Client type identification for server-side feature detection
"""

import asyncio
import json
import logging
import platform
import socket
import ssl
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiohttp

from dashboard.common.version import __version__

logger = logging.getLogger(__name__)


class ServerBusyError(Exception):
    """Raised when the server is busy processing another transcription."""

    def __init__(self, message: str, active_user: str = "another user"):
        self.active_user = active_user
        super().__init__(message)


# Client identification
CLIENT_VERSION = __version__
CLIENT_TYPE = "standalone"  # Identifies this as the native desktop client

# Audio constants
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit audio


class APIClient:
    """
    HTTP/WebSocket client for TranscriptionSuite server.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8000,
        use_https: bool = False,
        token: str | None = None,
        timeout: int = 30,
        transcription_timeout: int = 300,
        tls_verify: bool = True,
        allow_insecure_http: bool = False,
    ):
        """
        Initialize the API client.

        Args:
            host: Server hostname
            port: Server port
            use_https: Use HTTPS/WSS
            token: Authentication token
            timeout: Default request timeout in seconds
            transcription_timeout: Timeout for transcription requests
            tls_verify: Verify TLS certificates (set False for self-signed)
            allow_insecure_http: Allow HTTP to non-localhost hosts
        """
        self.host = host
        self.port = port
        self.use_https = use_https
        self.token = token
        self.timeout = timeout
        self.transcription_timeout = transcription_timeout
        self.tls_verify = tls_verify
        self.allow_insecure_http = allow_insecure_http

        self._session: aiohttp.ClientSession | None = None
        self._connected = False

        # Tailscale IP fallback state
        self._original_hostname: str | None = (
            None  # For SSL server_hostname when using IP
        )
        self._using_fallback_ip: bool = False

        # Log initialization with connection details
        logger.info(f"API Client initialized: {self.base_url}")
        if use_https:
            logger.debug(f"HTTPS mode enabled for host: {host}")

    def __del__(self):
        """Cleanup method to ensure session is closed."""
        if self._session and not self._session.closed:
            logger.warning(
                "APIClient being destroyed with unclosed session. "
                "Please call close() explicitly."
            )
            # Note: We can't await in __del__, but we can close the session synchronously
            # This will trigger the asyncio warning but prevents resource leaks
            try:
                if self._session.connector:
                    self._session.connector._close()
            except Exception:
                pass

    @property
    def base_url(self) -> str:
        """Get the base URL for API requests."""
        scheme = "https" if self.use_https else "http"
        return f"{scheme}://{self.host}:{self.port}"

    @property
    def ws_url(self) -> str:
        """Get the WebSocket URL."""
        scheme = "wss" if self.use_https else "ws"
        return f"{scheme}://{self.host}:{self.port}"

    def _get_headers(self) -> dict[str, str]:
        """Get request headers including auth token and client identification."""
        headers = {
            "Content-Type": "application/json",
            "X-Client-Type": CLIENT_TYPE,
            "User-Agent": f"TranscriptionSuite-Client/{CLIENT_VERSION} ({platform.system()})",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get_ssl_kwargs(self) -> dict:
        """
        Get SSL kwargs for requests, handling IP fallback and TLS verification.

        When using Tailscale IP fallback, we need to specify server_hostname
        so that SSL certificate validation works with the original hostname.
        """
        if not self.use_https:
            return {}

        ssl_context = ssl.create_default_context()

        if not self.tls_verify:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            logger.warning(
                "TLS certificate verification DISABLED - connection encrypted but not verified"
            )
        else:
            ssl_context.check_hostname = True
            ssl_context.verify_mode = ssl.CERT_REQUIRED

        kwargs: dict = {"ssl": ssl_context}
        if self._using_fallback_ip and self._original_hostname:
            # Tell SSL to verify certificate for original hostname, not IP
            kwargs["server_hostname"] = self._original_hostname
        return kwargs

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session with SSL configuration."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout)

            # Configure SSL context for HTTPS connections
            ssl_context = None
            if self.use_https:
                ssl_context = ssl.create_default_context()

                if not self.tls_verify:
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                    logger.debug("SSL context created with verification DISABLED")
                else:
                    # For Tailscale HTTPS certs, enable hostname validation
                    ssl_context.check_hostname = True
                    ssl_context.verify_mode = ssl.CERT_REQUIRED
                    logger.debug("SSL context created with hostname verification")

                logger.debug(f"SSL version: {ssl.OPENSSL_VERSION}")

            connector = aiohttp.TCPConnector(
                ssl=ssl_context,
                force_close=False,
                enable_cleanup_closed=True,
            )

            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
            )

            logger.debug(f"New aiohttp session created (HTTPS: {self.use_https})")

        return self._session

    async def close(self) -> None:
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        self._connected = False

    async def update_connection(
        self,
        host: str | None = None,
        port: int | None = None,
        use_https: bool | None = None,
        token: str | None = None,
        tls_verify: bool | None = None,
        allow_insecure_http: bool | None = None,
    ) -> None:
        """
        Update connection settings, properly closing old session.

        This method should be used instead of creating a new APIClient
        when changing connection settings to avoid resource leaks.
        """
        # Close existing session if any
        await self.close()

        # Update settings
        if host is not None:
            self.host = host
        if port is not None:
            self.port = port
        if use_https is not None:
            self.use_https = use_https
        if token is not None:
            self.token = token
        if tls_verify is not None:
            self.tls_verify = tls_verify
        if allow_insecure_http is not None:
            self.allow_insecure_http = allow_insecure_http

        # Reset fallback state
        self._original_hostname = None
        self._using_fallback_ip = False
        self._connected = False

        logger.info(f"API Client updated: {self.base_url}")

    def _is_localhost(self) -> bool:
        """Check if the current host is localhost."""
        return self.host in ("localhost", "127.0.0.1", "::1")

    async def health_check(self) -> bool:
        """Check if server is healthy with detailed diagnostics."""
        url = f"{self.base_url}/health"
        logger.debug(f"Health check: {url}")

        # Block HTTP to remote hosts without explicit opt-in
        if not self.use_https and not self._is_localhost():
            if not self.allow_insecure_http:
                logger.error(
                    f"HTTP to remote host {self.host} blocked. "
                    "Enable 'Allow HTTP to remote hosts' in settings or use --allow-insecure-http"
                )
                return False
            logger.info(
                f"HTTP to remote host {self.host} - WireGuard provides network encryption"
            )

        try:
            # Pre-connection DNS/network check (may switch to fallback IP)
            await self._diagnose_connection()

            session = await self._get_session()
            async with session.get(url, **self._get_ssl_kwargs()) as resp:
                logger.debug(f"Health check response: {resp.status}")

                if resp.status == 200:
                    self._connected = True
                    logger.info(f"Server connection successful: {self.base_url}")
                    return True
                else:
                    logger.warning(f"Health check failed with status {resp.status}")
                    return False

        except aiohttp.ClientSSLError as e:
            logger.error(f"SSL/TLS error connecting to {self.base_url}")
            logger.error(f"SSL error details: {type(e).__name__}: {e}")
            if self.use_https:
                logger.error("HTTPS connection failed. Check:")
                logger.error("  1. Server certificate is valid for this hostname")
                logger.error("  2. Tailscale HTTPS is properly configured")
                logger.error("  3. Certificate files are readable")
            self._connected = False
            return False

        except aiohttp.ClientConnectorError as e:
            logger.error(f"Connection error to {self.base_url}")
            logger.error(f"Connector error: {type(e).__name__}: {e}")
            logger.error("Possible causes:")
            logger.error("  1. Server is not running")
            logger.error("  2. Wrong host/port combination")
            logger.error("  3. Firewall blocking connection")
            logger.error("  4. Tailscale network issue")
            self._connected = False
            return False

        except asyncio.TimeoutError:
            logger.error(f"Connection timeout to {self.base_url}")
            logger.error(f"Timeout after {self.timeout} seconds")
            self._connected = False
            return False

        except Exception as e:
            logger.error(f"Health check failed: {type(e).__name__}: {e}")
            logger.debug("Full traceback:", exc_info=True)
            self._connected = False
            return False

    async def _diagnose_connection(self) -> None:
        """
        Perform pre-connection diagnostics and attempt fallback if needed.

        If DNS resolution fails for a .ts.net hostname, attempts to resolve
        the IP via `tailscale status --json` and switches to using the IP
        directly while preserving the original hostname for SSL verification.
        """
        # Lazy import to avoid overhead when not needed
        from dashboard.common.tailscale_resolver import TailscaleResolver

        try:
            # DNS resolution check (async, non-blocking)
            logger.debug(f"Resolving hostname: {self.host}")
            dns_failed = False

            try:
                # Use async DNS resolution with timeout to avoid blocking
                async with asyncio.timeout(2.0):
                    loop = asyncio.get_running_loop()
                    addr_info = await loop.getaddrinfo(
                        self.host,
                        self.port,
                        family=socket.AF_UNSPEC,
                        type=socket.SOCK_STREAM,
                    )
                    for _, _, _, _, sockaddr in addr_info:
                        logger.debug(f"  Resolved to: {sockaddr[0]}:{sockaddr[1]}")
            except asyncio.TimeoutError:
                dns_failed = True
                logger.warning(f"DNS resolution timeout for {self.host} (2s)")
            except socket.gaierror as e:
                dns_failed = True
                logger.warning(f"DNS pre-check failed for {self.host}: {e}")

            # Attempt Tailscale IP fallback if DNS failed for a .ts.net hostname
            if dns_failed and TailscaleResolver.is_tailscale_hostname(self.host):
                logger.info(f"Attempting Tailscale IP fallback for {self.host}")
                ip, original_hostname = await TailscaleResolver.resolve_ip(self.host)

                if ip:
                    logger.info(f"Tailscale IP fallback: {self.host} -> {ip}")
                    self._original_hostname = original_hostname
                    self.host = ip
                    self._using_fallback_ip = True
                else:
                    logger.warning(
                        "Tailscale IP fallback failed - device not found in tailscale status. "
                        "Check that Tailscale is running and the device is online."
                    )
            elif dns_failed:
                logger.debug(
                    "DNS failed but not a .ts.net hostname - no fallback available"
                )

            # SSL certificate check (only for HTTPS)
            if self.use_https:
                if self._using_fallback_ip:
                    logger.debug(
                        f"HTTPS mode with IP fallback - SSL will verify hostname: {self._original_hostname}"
                    )
                else:
                    logger.debug(
                        f"HTTPS mode - will verify SSL certificate for {self.host}"
                    )

        except Exception as e:
            logger.debug(f"Connection diagnostics failed: {e}")

    async def get_status(self) -> dict[str, Any]:
        """Get server status."""
        session = await self._get_session()
        async with session.get(
            f"{self.base_url}/api/status",
            headers=self._get_headers(),
            **self._get_ssl_kwargs(),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def transcribe_file(
        self,
        file_path: Path,
        language: str | None = None,
        word_timestamps: bool = True,
        diarization: bool = False,
        on_progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """
        Transcribe an audio file.

        Args:
            file_path: Path to the audio file
            language: Language code (None for auto-detect)
            word_timestamps: Include word-level timestamps
            diarization: Enable speaker diarization
            on_progress: Optional callback for progress updates

        Returns:
            Transcription result dict
        """
        session = await self._get_session()

        # Prepare form data - read file contents asynchronously to avoid blocking
        file_contents = await asyncio.to_thread(file_path.read_bytes)

        data = aiohttp.FormData()
        data.add_field(
            "file",
            file_contents,
            filename=file_path.name,
        )
        if language:
            data.add_field("language", language)
        data.add_field("word_timestamps", str(word_timestamps).lower())
        data.add_field("diarization", str(diarization).lower())

        # Use longer timeout for transcription
        timeout = aiohttp.ClientTimeout(total=self.transcription_timeout)

        if on_progress:
            on_progress("Uploading audio...")

        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        async with session.post(
            f"{self.base_url}/api/transcribe/audio",
            data=data,
            headers=headers,
            timeout=timeout,
            **self._get_ssl_kwargs(),
        ) as resp:
            if on_progress:
                on_progress("Transcribing...")

            resp.raise_for_status()
            result = await resp.json()

            if on_progress:
                on_progress("Complete")

            return result

    async def get_recordings(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list:
        """Get recordings from Audio Notebook."""
        session = await self._get_session()

        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        async with session.get(
            f"{self.base_url}/api/notebook/recordings",
            headers=self._get_headers(),
            params=params,
            **self._get_ssl_kwargs(),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def search(
        self,
        query: str,
        search_type: str = "all",
        limit: int = 50,
    ) -> dict[str, Any]:
        """Search transcriptions."""
        session = await self._get_session()

        async with session.get(
            f"{self.base_url}/api/search/",
            headers=self._get_headers(),
            params={"q": query, "type": search_type, "limit": limit},
            **self._get_ssl_kwargs(),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def transcribe_audio_data(
        self,
        audio_data: bytes,
        language: str | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """
        Transcribe raw audio data (WAV format).

        Args:
            audio_data: WAV audio bytes
            language: Language code (None for auto-detect)
            on_progress: Optional callback for progress updates

        Returns:
            Transcription result dict
        """
        session = await self._get_session()

        if on_progress:
            on_progress("Uploading audio...")

        # Prepare form data
        data = aiohttp.FormData()
        data.add_field(
            "file",
            audio_data,
            filename="recording.wav",
            content_type="audio/wav",
        )
        if language:
            data.add_field("language", language)
        data.add_field("word_timestamps", "true")

        # Use longer timeout for transcription
        timeout = aiohttp.ClientTimeout(total=self.transcription_timeout)

        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        if on_progress:
            on_progress("Transcribing...")

        try:
            logger.debug(
                f"Sending transcription request to {self.base_url}/api/transcribe/audio"
            )

            async with session.post(
                f"{self.base_url}/api/transcribe/audio",
                data=data,
                headers=headers,
                timeout=timeout,
                **self._get_ssl_kwargs(),
            ) as resp:
                logger.debug(f"Transcription response status: {resp.status}")

                if resp.status == 409:
                    # Server is busy with another transcription
                    try:
                        error_data = await resp.json()
                        detail = error_data.get("detail", "Server is busy")

                        # Parse active user from detail message
                        # Format: "A transcription is already running for <user>"
                        active_user = "another user"
                        if isinstance(detail, str) and " for " in detail:
                            # Extract text after last " for " occurrence
                            parts = detail.rsplit(" for ", 1)
                            if len(parts) == 2:
                                active_user = parts[1].strip()

                        logger.warning(f"Server busy: {detail}")
                        raise ServerBusyError(detail, active_user=active_user)
                    except (json.JSONDecodeError, aiohttp.ContentTypeError) as e:
                        error = await resp.text()
                        logger.warning(f"Server busy (parse error: {e}): {error}")
                        raise ServerBusyError(f"Server is busy: {error}") from None

                if resp.status != 200:
                    error = await resp.text()
                    logger.error(f"Transcription failed (HTTP {resp.status}): {error}")
                    raise RuntimeError(f"Transcription failed: {error}")

                result = await resp.json()

                if on_progress:
                    on_progress("Complete")

                return result

        except aiohttp.ClientSSLError as e:
            logger.error(f"SSL error during transcription: {e}")
            raise RuntimeError(f"SSL/TLS error: {e}") from e
        except aiohttp.ClientConnectorError as e:
            logger.error(f"Connection error during transcription: {e}")
            raise RuntimeError(f"Connection error: {e}") from e
        except asyncio.TimeoutError as e:
            logger.error(f"Transcription timeout after {self.transcription_timeout}s")
            raise RuntimeError("Request timeout") from e
        except aiohttp.ClientError as e:
            logger.error(f"Transcription request failed: {type(e).__name__}: {e}")
            raise RuntimeError(f"Network error: {e}") from e

    async def upload_to_notebook(
        self,
        audio_data: bytes,
        language: str | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """
        Upload audio to Audio Notebook for transcription and storage.

        This uses the notebook endpoint which transcribes with diarization
        and saves both audio and transcription to the Audio Notebook database.

        Args:
            audio_data: WAV audio bytes
            language: Language code (None for auto-detect)
            on_progress: Optional callback for progress updates

        Returns:
            Recording result dict with id, transcription, etc.
        """
        session = await self._get_session()

        if on_progress:
            on_progress("Uploading to Audio Notebook...")

        # Prepare form data
        data = aiohttp.FormData()
        data.add_field(
            "file",
            audio_data,
            filename="recording.wav",
            content_type="audio/wav",
        )
        if language:
            data.add_field("language", language)

        # Use longer timeout for transcription with diarization
        timeout = aiohttp.ClientTimeout(total=self.transcription_timeout)

        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        if on_progress:
            on_progress("Transcribing with diarization...")

        try:
            logger.debug(
                f"Sending notebook upload request to {self.base_url}/api/notebook/transcribe/upload"
            )

            async with session.post(
                f"{self.base_url}/api/notebook/transcribe/upload",
                data=data,
                headers=headers,
                timeout=timeout,
                **self._get_ssl_kwargs(),
            ) as resp:
                logger.debug(f"Notebook upload response status: {resp.status}")

                if resp.status == 409:
                    # Server is busy with another transcription
                    try:
                        error_data = await resp.json()
                        detail = error_data.get("detail", "Server is busy")
                        active_user = "another user"
                        if isinstance(detail, str) and " for " in detail:
                            parts = detail.rsplit(" for ", 1)
                            if len(parts) == 2:
                                active_user = parts[1].strip()
                        logger.warning(f"Server busy: {detail}")
                        raise ServerBusyError(detail, active_user=active_user)
                    except (json.JSONDecodeError, aiohttp.ContentTypeError) as e:
                        error = await resp.text()
                        logger.warning(f"Server busy (parse error: {e}): {error}")
                        raise ServerBusyError(f"Server is busy: {error}") from None

                if resp.status != 200:
                    error = await resp.text()
                    logger.error(
                        f"Notebook upload failed (HTTP {resp.status}): {error}"
                    )
                    raise RuntimeError(f"Upload failed: {error}")

                result = await resp.json()

                if on_progress:
                    on_progress("Saved to Audio Notebook")

                return result

        except aiohttp.ClientSSLError as e:
            logger.error(f"SSL error during notebook upload: {e}")
            raise RuntimeError(f"SSL/TLS error: {e}") from e
        except aiohttp.ClientConnectorError as e:
            logger.error(f"Connection error during notebook upload: {e}")
            raise RuntimeError(f"Connection error: {e}") from e
        except asyncio.TimeoutError as e:
            logger.error(f"Notebook upload timeout after {self.transcription_timeout}s")
            raise RuntimeError("Request timeout") from e
        except aiohttp.ClientError as e:
            logger.error(f"Notebook upload request failed: {type(e).__name__}: {e}")
            raise RuntimeError(f"Network error: {e}") from e

    async def preload_model(self) -> bool:
        """Request server to preload the transcription model."""
        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/api/admin/models/load",
                headers=self._get_headers(),
                **self._get_ssl_kwargs(),
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"Model preload failed: {e}")
            return False

    async def unload_models(self) -> dict[str, Any]:
        """
        Request server to unload all transcription models to free GPU memory.

        Returns:
            Dict with 'success' and 'message' keys
        """
        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/api/admin/models/unload",
                headers=self._get_headers(),
                **self._get_ssl_kwargs(),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "success": True,
                        "message": "Models unloaded successfully",
                        "status": data.get("status", "unloaded"),
                    }
                elif resp.status == 409:
                    # Server is busy
                    data = await resp.json()
                    return {
                        "success": False,
                        "message": data.get("detail", "Server is busy"),
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Unload failed (HTTP {resp.status})",
                    }
        except Exception as e:
            logger.error(f"Model unload failed: {e}")
            return {"success": False, "message": str(e)}

    async def reload_models(self) -> dict[str, Any]:
        """
        Request server to reload the transcription models.

        Returns:
            Dict with 'success' and 'message' keys
        """
        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/api/admin/models/load",
                headers=self._get_headers(),
                **self._get_ssl_kwargs(),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "success": True,
                        "message": "Models loaded successfully",
                        "status": data.get("status", "loaded"),
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Reload failed (HTTP {resp.status})",
                    }
        except Exception as e:
            logger.error(f"Model reload failed: {e}")
            return {"success": False, "message": str(e)}

    async def load_models_with_progress(
        self,
        progress_callback: Callable[[str], None],
    ) -> dict[str, Any]:
        """
        Load transcription models with streaming progress updates.

        Uses WebSocket to receive real-time progress messages from the server
        during model loading (which can take several minutes for large models
        that need to be downloaded from HuggingFace).

        Args:
            progress_callback: Called with progress message strings.
                              These messages come from the server and describe
                              the current loading status.

        Returns:
            Dict with 'success' and 'message' keys
        """
        ws_url = f"{self.ws_url}/api/admin/models/load/stream"

        try:
            session = await self._get_session()

            # Connect to WebSocket
            async with session.ws_connect(
                ws_url,
                headers=self._get_headers(),
                **self._get_ssl_kwargs(),
            ) as ws:
                logger.info(f"Connected to model load WebSocket: {ws_url}")

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = json.loads(msg.data)
                            msg_type = data.get("type", "")

                            if msg_type == "progress":
                                # Report progress to callback
                                message = data.get("message", "")
                                if message:
                                    progress_callback(message)

                            elif msg_type == "complete":
                                # Loading finished successfully
                                logger.info("Model loading completed via WebSocket")
                                return {
                                    "success": True,
                                    "message": "Models loaded successfully",
                                    "status": data.get("status", "loaded"),
                                }

                            elif msg_type == "error":
                                # Loading failed
                                error_msg = data.get("message", "Unknown error")
                                logger.error(f"Model loading error: {error_msg}")
                                return {
                                    "success": False,
                                    "message": error_msg,
                                }

                        except json.JSONDecodeError:
                            logger.warning(f"Invalid JSON from WebSocket: {msg.data}")

                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(f"WebSocket error: {ws.exception()}")
                        return {
                            "success": False,
                            "message": f"WebSocket error: {ws.exception()}",
                        }

                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        logger.info("WebSocket closed by server")
                        break

                # If we got here without complete/error, something went wrong
                return {
                    "success": False,
                    "message": "WebSocket closed unexpectedly",
                }

        except aiohttp.ClientError as e:
            logger.error(f"WebSocket connection failed: {e}")
            return {"success": False, "message": f"Connection failed: {e}"}
        except Exception as e:
            logger.error(f"Model loading with progress failed: {e}")
            return {"success": False, "message": str(e)}

    async def cancel_transcription(self) -> dict[str, Any]:
        """
        Request cancellation of the currently running transcription job.

        Returns:
            Dict with 'success', 'cancelled_user', and 'message' keys
        """
        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/api/transcribe/cancel",
                headers=self._get_headers(),
                **self._get_ssl_kwargs(),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    return {
                        "success": False,
                        "cancelled_user": None,
                        "message": f"Cancel request failed (HTTP {resp.status})",
                    }
        except Exception as e:
            logger.error(f"Cancel transcription failed: {e}")
            return {
                "success": False,
                "cancelled_user": None,
                "message": str(e),
            }

    async def validate_token(self) -> tuple[bool, str | None]:
        """
        Validate the current token with the server.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not self.token:
            return False, "No authentication token configured"

        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/api/auth/login",
                headers={"Content-Type": "application/json"},
                json={"token": self.token},
                **self._get_ssl_kwargs(),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("success"):
                        logger.info(
                            f"Token validated for user: {data.get('user', {}).get('name', 'unknown')}"
                        )
                        return True, None
                    return False, data.get("message", "Invalid token")
                return False, f"Authentication failed (HTTP {resp.status})"
        except Exception as e:
            logger.error(f"Token validation failed: {e}")
            return False, str(e)

    @property
    def is_connected(self) -> bool:
        """Check if client is connected to server."""
        return self._connected


class LiveModeClient:
    """
    WebSocket client for Live Mode.

    Connects to /ws/live endpoint for continuous sentence transcription.
    Audio is streamed from the client to the server, and completed sentences
    are returned via callback.
    """

    def __init__(
        self,
        api_client: APIClient,
        on_sentence: Callable[[str], None] | None = None,
        on_partial: Callable[[str], None] | None = None,
        on_state: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ):
        """
        Initialize Live Mode client.

        Args:
            api_client: Base API client for connection info
            on_sentence: Callback for completed sentences
            on_partial: Callback for partial/real-time updates
            on_state: Callback for state changes
            on_error: Callback for errors
        """
        self.api_client = api_client
        self.on_sentence = on_sentence
        self.on_partial = on_partial
        self.on_state = on_state
        self.on_error = on_error

        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._running = False
        self._muted = False

    async def connect(self) -> bool:
        """Connect to the Live Mode WebSocket endpoint."""
        try:
            session = await self.api_client._get_session()
            url = f"{self.api_client.ws_url}/ws/live"

            # Use SSL kwargs for HTTPS WebSocket connections
            ssl_kwargs = self.api_client._get_ssl_kwargs()
            self._ws = await session.ws_connect(url, **ssl_kwargs)

            # Send authentication message
            await self._ws.send_json(
                {"type": "auth", "data": {"token": self.api_client.token or ""}}
            )

            # Wait for auth response
            auth_response = await asyncio.wait_for(
                self._ws.receive_json(), timeout=10.0
            )
            if auth_response.get("type") == "error":
                error_msg = auth_response.get("data", {}).get(
                    "message", "Unknown error"
                )
                logger.error(f"Live Mode error: {error_msg}")
                await self._ws.close()
                if self.on_error:
                    self.on_error(error_msg)
                return False
            if auth_response.get("type") != "auth_ok":
                error_msg = auth_response.get("data", {}).get(
                    "message", "Authentication failed"
                )
                logger.error(f"Live Mode auth failed: {error_msg}")
                await self._ws.close()
                if self.on_error:
                    self.on_error(f"Authentication failed: {error_msg}")
                return False

            logger.debug("Live Mode auth successful")
            self._running = True
            return True

        except asyncio.TimeoutError:
            logger.error("Live Mode authentication timeout")
            if self.on_error:
                self.on_error("Authentication timeout")
            return False

        except Exception as e:
            logger.error(f"Live Mode connection failed: {e}")
            if self.on_error:
                self.on_error(str(e))
            return False

    async def start(self, config: dict[str, Any] | None = None) -> None:
        """Send start command to begin Live Mode."""
        if self._ws and not self._ws.closed:
            await self._ws.send_json(
                {"type": "start", "data": {"config": config or {}}}
            )

    async def stop(self) -> None:
        """Send stop command to end Live Mode."""
        if self._ws and not self._ws.closed:
            await self._ws.send_json({"type": "stop"})

    async def receive_messages(self) -> None:
        """Receive and handle WebSocket messages."""
        if not self._ws:
            return

        try:
            async for msg in self._ws:
                if not self._running:
                    break

                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")
                    msg_data = data.get("data", {})

                    if msg_type == "sentence" and self.on_sentence:
                        self.on_sentence(msg_data.get("text", ""))
                    elif msg_type == "partial" and self.on_partial:
                        self.on_partial(msg_data.get("text", ""))
                    elif msg_type == "state" and self.on_state:
                        self.on_state(msg_data.get("state", ""))
                    elif msg_type == "error" and self.on_error:
                        self.on_error(msg_data.get("message", "Unknown error"))
                    elif msg_type == "pong":
                        pass  # Ping response
                    else:
                        logger.debug(f"Live Mode unhandled message: {msg_type}")

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    if self.on_error:
                        self.on_error(f"WebSocket error: {self._ws.exception()}")
                    break

        except Exception as e:
            logger.error(f"Live Mode receive error: {e}")
            if self.on_error:
                self.on_error(str(e))

        finally:
            self._running = False

    async def send_audio(self, audio_data: bytes) -> None:
        """
        Send audio data to the server.

        Args:
            audio_data: PCM Int16 audio data (already formatted with metadata header)
        """
        if self._ws and not self._ws.closed and not self._muted:
            await self._ws.send_bytes(audio_data)

    def set_muted(self, muted: bool) -> None:
        """Set mute state - when muted, audio is not sent to server."""
        self._muted = muted
        logger.debug(f"Live Mode muted: {muted}")

    @property
    def is_muted(self) -> bool:
        """Check if audio sending is muted."""
        return self._muted

    async def close(self) -> None:
        """Close the WebSocket connection."""
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
            self._ws = None

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._ws is not None and not self._ws.closed


class StreamingClient:
    """
    WebSocket client for real-time audio streaming.
    """

    def __init__(
        self,
        api_client: APIClient,
        on_preview: Callable[[str], None] | None = None,
        on_final: Callable[[dict[str, Any]], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ):
        """
        Initialize streaming client.

        Args:
            api_client: Base API client for connection info
            on_preview: Callback for live transcription text updates
            on_final: Callback for final transcription result
            on_error: Callback for errors
        """
        self.api_client = api_client
        self.on_live_transcription = (
            on_preview  # Store as new name, param name kept for backwards compat
        )
        self.on_final = on_final
        self.on_error = on_error

        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._running = False

    async def connect(self) -> bool:
        """Connect to the streaming endpoint."""
        try:
            session = await self.api_client._get_session()
            url = f"{self.api_client.ws_url}/ws"

            # Include client identification headers
            headers = {
                "X-Client-Type": CLIENT_TYPE,
                "User-Agent": f"TranscriptionSuite-Client/{CLIENT_VERSION} ({platform.system()})",
            }

            # Use SSL kwargs for HTTPS WebSocket connections (handles IP fallback)
            ssl_kwargs = self.api_client._get_ssl_kwargs()
            self._ws = await session.ws_connect(url, headers=headers, **ssl_kwargs)

            # Send authentication message
            await self._ws.send_json(
                {"type": "auth", "data": {"token": self.api_client.token or ""}}
            )

            # Wait for auth response
            auth_response = await asyncio.wait_for(
                self._ws.receive_json(), timeout=10.0
            )
            if auth_response.get("type") != "auth_ok":
                error_msg = auth_response.get("data", {}).get(
                    "message", "Authentication failed"
                )
                logger.error(f"WebSocket auth failed: {error_msg}")
                await self._ws.close()
                if self.on_error:
                    self.on_error(f"Authentication failed: {error_msg}")
                return False

            logger.debug("WebSocket auth successful")
            self._running = True

            # Start receiving messages
            asyncio.create_task(self._receive_loop())

            return True

        except asyncio.TimeoutError:
            logger.error("WebSocket authentication timeout")
            if self.on_error:
                self.on_error("Authentication timeout")
            return False

        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            if self.on_error:
                self.on_error(str(e))
            return False

    async def _receive_loop(self) -> None:
        """Receive and handle WebSocket messages."""
        if not self._ws:
            return

        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")

                    if msg_type == "realtime" and self.on_live_transcription:
                        # Real-time live transcription text from server
                        text = data.get("data", {}).get("text", "")
                        self.on_live_transcription(text)
                    elif msg_type == "preview" and self.on_live_transcription:
                        # Legacy preview format (backwards compat with older servers)
                        self.on_live_transcription(data.get("text", ""))
                    elif msg_type == "final" and self.on_final:
                        self.on_final(data)
                    elif msg_type == "session_started":
                        # Server confirmed recording started
                        live_transcriber_enabled = data.get("data", {}).get(
                            "preview_enabled",
                            False,  # Keep old key name for server compat
                        )
                        logger.info(
                            f"Session started: live_transcriber_enabled={live_transcriber_enabled}"
                        )
                    elif msg_type == "session_stopped":
                        logger.info("Session stopped")
                    elif msg_type == "session_busy" and self.on_error:
                        active_user = data.get("data", {}).get(
                            "active_user", "another user"
                        )
                        self.on_error(
                            f"Server busy - transcription in progress for {active_user}"
                        )
                    elif msg_type == "error" and self.on_error:
                        error_msg = data.get("data", {}).get(
                            "message", data.get("message", "Unknown error")
                        )
                        self.on_error(error_msg)
                    elif msg_type in (
                        "vad_start",
                        "vad_stop",
                        "vad_recording_start",
                        "vad_recording_stop",
                    ):
                        # VAD events - log for debugging
                        logger.debug(f"VAD event: {msg_type}")
                    elif msg_type == "pong":
                        # Ping response - ignore
                        pass
                    else:
                        logger.debug(f"Unhandled message type: {msg_type}")

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    if self.on_error:
                        self.on_error(f"WebSocket error: {self._ws.exception()}")
                    break

        except Exception as e:
            logger.error(f"WebSocket receive error: {e}")
            if self.on_error:
                self.on_error(str(e))

        finally:
            self._running = False

    async def send_audio(self, audio_data: bytes) -> None:
        """Send audio data to the server."""
        if self._ws and not self._ws.closed:
            await self._ws.send_bytes(audio_data)

    async def send_control(
        self, action: str, data: dict[str, Any] | None = None
    ) -> None:
        """Send a control message (start, stop, cancel)."""
        if self._ws and not self._ws.closed:
            msg: dict[str, Any] = {"type": action}
            if data:
                msg["data"] = data
            await self._ws.send_json(msg)

    async def close(self) -> None:
        """Close the WebSocket connection."""
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
            self._ws = None

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._ws is not None and not self._ws.closed
