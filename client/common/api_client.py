"""
API client for TranscriptionSuite server communication.

Handles:
- HTTP requests to the unified API
- WebSocket connections for real-time streaming
- Authentication with tokens
- Connection state management
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


class APIClient:
    """
    HTTP/WebSocket client for TranscriptionSuite server.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8000,
        use_https: bool = False,
        token: Optional[str] = None,
        timeout: int = 30,
        transcription_timeout: int = 300,
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
        """
        self.host = host
        self.port = port
        self.use_https = use_https
        self.token = token
        self.timeout = timeout
        self.transcription_timeout = transcription_timeout

        self._session: Optional[aiohttp.ClientSession] = None
        self._connected = False

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

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers including auth token."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def health_check(self) -> bool:
        """Check if server is healthy."""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/health") as resp:
                if resp.status == 200:
                    self._connected = True
                    return True
                return False
        except Exception as e:
            logger.debug(f"Health check failed: {e}")
            self._connected = False
            return False

    async def get_status(self) -> Dict[str, Any]:
        """Get server status."""
        session = await self._get_session()
        async with session.get(
            f"{self.base_url}/api/status",
            headers=self._get_headers(),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def transcribe_file(
        self,
        file_path: Path,
        language: Optional[str] = None,
        word_timestamps: bool = True,
        diarization: bool = False,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
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

        # Prepare form data
        data = aiohttp.FormData()
        data.add_field(
            "file",
            open(file_path, "rb"),
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
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
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
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def search(
        self,
        query: str,
        search_type: str = "all",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Search transcriptions."""
        session = await self._get_session()

        async with session.get(
            f"{self.base_url}/api/search/",
            headers=self._get_headers(),
            params={"q": query, "type": search_type, "limit": limit},
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    @property
    def is_connected(self) -> bool:
        """Check if client is connected to server."""
        return self._connected


class StreamingClient:
    """
    WebSocket client for real-time audio streaming.
    """

    def __init__(
        self,
        api_client: APIClient,
        on_preview: Optional[Callable[[str], None]] = None,
        on_final: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize streaming client.

        Args:
            api_client: Base API client for connection info
            on_preview: Callback for preview transcription text
            on_final: Callback for final transcription result
            on_error: Callback for errors
        """
        self.api_client = api_client
        self.on_preview = on_preview
        self.on_final = on_final
        self.on_error = on_error

        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._running = False

    async def connect(self) -> bool:
        """Connect to the streaming endpoint."""
        try:
            session = await self.api_client._get_session()
            url = f"{self.api_client.ws_url}/api/transcribe/stream"

            headers = {}
            if self.api_client.token:
                headers["Authorization"] = f"Bearer {self.api_client.token}"

            self._ws = await session.ws_connect(url, headers=headers)
            self._running = True

            # Start receiving messages
            asyncio.create_task(self._receive_loop())

            return True

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

                    if msg_type == "preview" and self.on_preview:
                        self.on_preview(data.get("text", ""))
                    elif msg_type == "final" and self.on_final:
                        self.on_final(data)
                    elif msg_type == "error" and self.on_error:
                        self.on_error(data.get("message", "Unknown error"))

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

    async def send_control(self, action: str) -> None:
        """Send a control message (start, stop, cancel)."""
        if self._ws and not self._ws.closed:
            await self._ws.send_json({"action": action})

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
