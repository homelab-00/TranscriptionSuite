"""
HTTP/WebSocket client for communicating with the container.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    """Container server configuration."""

    host: str = "localhost"
    audio_notebook_port: int = 8000
    remote_server_port: int = 8443
    use_https: bool = False
    timeout: int = 30
    auto_reconnect: bool = True
    reconnect_interval: int = 5

    @property
    def audio_notebook_url(self) -> str:
        protocol = "https" if self.use_https else "http"
        return f"{protocol}://{self.host}:{self.audio_notebook_port}"

    @property
    def remote_server_url(self) -> str:
        protocol = "https" if self.use_https else "http"
        return f"{protocol}://{self.host}:{self.remote_server_port}"

    @property
    def websocket_url(self) -> str:
        protocol = "wss" if self.use_https else "ws"
        return f"{protocol}://{self.host}:{self.remote_server_port}/ws"


class ServerConnection:
    """Manages connection to the TranscriptionSuite container."""

    def __init__(self, config: ServerConfig):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.connected = False
        self._reconnect_task: Optional[asyncio.Task] = None

    async def connect(self) -> bool:
        """Establish connection to the container."""
        try:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            self.session = aiohttp.ClientSession(timeout=timeout)

            # Test connection with health check
            async with self.session.get(
                f"{self.config.audio_notebook_url}/health"
            ) as resp:
                if resp.status == 200:
                    self.connected = True
                    logger.info(f"Connected to container at {self.config.host}")
                    return True

            logger.warning("Health check failed")
            return False

        except aiohttp.ClientError as e:
            logger.error(f"Failed to connect: {e}")
            return False
        except asyncio.TimeoutError:
            logger.error("Connection timeout")
            return False

    async def disconnect(self) -> None:
        """Close connection."""
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None

        if self.ws:
            await self.ws.close()
            self.ws = None

        if self.session:
            await self.session.close()
            self.session = None

        self.connected = False
        logger.info("Disconnected from container")

    async def get_status(self) -> Dict[str, Any]:
        """Get server status."""
        if not self.session:
            return {"status": "disconnected"}

        try:
            async with self.session.get(
                f"{self.config.audio_notebook_url}/api/client/status"
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {"status": "error", "code": resp.status}
        except aiohttp.ClientError as e:
            logger.error(f"Status check failed: {e}")
            return {"status": "error", "message": str(e)}

    async def preload_model(self) -> bool:
        """Preload the transcription model on the server."""
        if not self.session:
            return False

        try:
            async with self.session.post(
                f"{self.config.audio_notebook_url}/api/client/preload-model"
            ) as resp:
                return resp.status == 200
        except aiohttp.ClientError as e:
            logger.error(f"Model preload failed: {e}")
            return False

    async def transcribe_file(
        self,
        file_path: Path,
        language: Optional[str] = None,
        enable_diarization: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Upload and transcribe an audio file."""
        if not self.session:
            raise RuntimeError("Not connected to server")

        if progress_callback:
            progress_callback("Uploading file...")

        # Prepare form data
        data = aiohttp.FormData()
        data.add_field(
            "file",
            open(file_path, "rb"),
            filename=file_path.name,
            content_type="application/octet-stream",
        )

        # Build URL with query params
        url = f"{self.config.audio_notebook_url}/api/client/transcribe"
        params = {}
        if language:
            params["language"] = language
        if enable_diarization:
            params["enable_diarization"] = "true"

        if progress_callback:
            progress_callback("Transcribing...")

        try:
            async with self.session.post(url, data=data, params=params) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise RuntimeError(f"Transcription failed: {error}")

                result = await resp.json()

                if progress_callback:
                    progress_callback("Complete")

                return result

        except aiohttp.ClientError as e:
            logger.error(f"Transcription request failed: {e}")
            raise RuntimeError(f"Network error: {e}")

    async def transcribe_audio_data(
        self,
        audio_data: bytes,
        language: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Transcribe raw audio data (WAV format)."""
        if not self.session:
            raise RuntimeError("Not connected to server")

        if progress_callback:
            progress_callback("Uploading audio...")

        # Prepare form data
        data = aiohttp.FormData()
        data.add_field(
            "file", audio_data, filename="recording.wav", content_type="audio/wav"
        )

        url = f"{self.config.audio_notebook_url}/api/client/transcribe"
        params = {}
        if language:
            params["language"] = language

        if progress_callback:
            progress_callback("Transcribing...")

        try:
            async with self.session.post(url, data=data, params=params) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise RuntimeError(f"Transcription failed: {error}")

                result = await resp.json()

                if progress_callback:
                    progress_callback("Complete")

                return result

        except aiohttp.ClientError as e:
            logger.error(f"Transcription request failed: {e}")
            raise RuntimeError(f"Network error: {e}")

    async def stream_transcription(
        self,
        audio_generator,
        on_realtime: Callable[[str], None],
        on_final: Callable[[Dict[str, Any]], None],
    ) -> None:
        """Stream audio for real-time transcription via WebSocket."""
        if not self.session:
            raise RuntimeError("Not connected to server")

        self.ws = await self.session.ws_connect(self.config.websocket_url)

        try:
            # Send audio chunks
            async for chunk in audio_generator:
                await self.ws.send_bytes(chunk)

                # Check for responses (non-blocking)
                try:
                    msg = await asyncio.wait_for(self.ws.receive(), timeout=0.01)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if data.get("type") == "realtime":
                            on_realtime(data.get("text", ""))
                        elif data.get("type") == "final":
                            on_final(data)
                except asyncio.TimeoutError:
                    pass

            # Signal end of audio
            await self.ws.send_json({"type": "end"})

            # Wait for final result
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data.get("type") == "final":
                        on_final(data)
                        break
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break

        finally:
            await self.ws.close()
            self.ws = None

    def is_connected(self) -> bool:
        """Check if connected to the server."""
        return self.connected and self.session is not None
