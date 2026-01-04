"""
WebSocket endpoint for real-time audio transcription.

Handles:
- Token-based authentication
- Audio streaming (16kHz PCM Int16)
- Long-form transcription with VAD
- Client type detection (standalone vs web)
- Preview transcription for standalone clients
- Session management (single active session)
"""

import asyncio
import json
import struct
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import soundfile as sf
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

# NOTE: model_manager is imported lazily inside functions to avoid
# loading heavy ML libraries (torch, faster_whisper) at module import time.
# This reduces server startup time by ~10 seconds.
from server.core.token_store import get_token_store
from server.core.client_detector import (
    ClientType,
    ClientDetector,
    get_client_capabilities,
)
from server.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Global session state - tracks all connected sessions for cleanup
# (Multiple connections allowed, but only one can be recording at a time)
_connected_sessions: Dict[str, "TranscriptionSession"] = {}
_sessions_lock = asyncio.Lock()


class TranscriptionSession:
    """
    Manages a single transcription session.

    Supports both file-based transcription (web clients) and
    real-time VAD-based transcription (standalone clients).
    """

    def __init__(
        self,
        websocket: WebSocket,
        client_name: str,
        is_admin: bool,
        client_type: ClientType,
        session_id: str,
    ):
        self.websocket = websocket
        self.client_name = client_name
        self.is_admin = is_admin
        self.client_type = client_type
        self.session_id = session_id

        self.is_recording = False
        self.language: Optional[str] = None
        self.audio_chunks: list[bytes] = []
        self.sample_rate = 16000
        self.temp_file: Optional[Path] = None

        # Real-time engine (for standalone clients with VAD)
        self._realtime_engine: Optional[Any] = None
        self._use_realtime_engine = False

        # Job tracking for transcription
        self._current_job_id: Optional[str] = None

        # Get client capabilities
        self.capabilities = get_client_capabilities(
            {"x-client-type": client_type.value}, {}
        )

    async def send_message(
        self, msg_type: str, data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send a JSON message to the client."""
        if self.websocket.client_state != WebSocketState.CONNECTED:
            return

        message = {
            "type": msg_type,
            "data": data or {},
            "timestamp": asyncio.get_event_loop().time(),
        }
        try:
            await self.websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    def add_audio_chunk(self, pcm_data: bytes) -> None:
        """Add a chunk of PCM audio data."""
        self.audio_chunks.append(pcm_data)

        # Also feed to realtime engine if using VAD
        if self._use_realtime_engine and self._realtime_engine:
            self._realtime_engine.feed_audio(pcm_data, self.sample_rate)

    async def process_transcription(self) -> None:
        """Process accumulated audio and return transcription."""
        if not self.audio_chunks:
            await self.send_message("error", {"message": "No audio data received"})
            return

        try:
            # Combine all audio chunks
            combined_audio = b"".join(self.audio_chunks)

            # Convert bytes to numpy array (Int16 PCM)
            audio_array = np.frombuffer(combined_audio, dtype=np.int16)

            # Convert to float32 [-1.0, 1.0]
            audio_float = audio_array.astype(np.float32) / 32768.0

            # Save to temporary WAV file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                self.temp_file = Path(tmp.name)
                sf.write(tmp.name, audio_float, self.sample_rate)

            logger.info(
                f"Processing {len(audio_float) / self.sample_rate:.2f}s of audio "
                f"for {self.client_name}"
            )

            # Get transcription engine (lazy import to avoid startup delay)
            from server.core.model_manager import get_model_manager

            model_manager = get_model_manager()
            engine = model_manager.transcription_engine

            # Transcribe
            result = engine.transcribe_file(
                file_path=str(self.temp_file),
                language=self.language,
                word_timestamps=True,
            )

            # Send final result
            # result.words is already a flat list of word dicts
            await self.send_message(
                "final",
                {
                    "text": result.text,
                    "words": result.words,
                    "language": result.language,
                    "duration": result.duration,
                },
            )

            logger.info(f"Transcription complete for {self.client_name}")

        except Exception as e:
            logger.error(f"Transcription error: {e}", exc_info=True)
            await self.send_message("error", {"message": f"Transcription failed: {e}"})

        finally:
            # Cleanup
            if self.temp_file and self.temp_file.exists():
                try:
                    self.temp_file.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete temp file: {e}")
            self.temp_file = None
            self.audio_chunks = []

    async def start_recording(
        self,
        language: Optional[str] = None,
        use_vad: bool = False,
    ) -> None:
        """
        Start a recording session.

        Args:
            language: Target language code
            use_vad: Use VAD for automatic start/stop detection
        """
        self.is_recording = True
        self.language = language
        self.audio_chunks = []
        self._use_realtime_engine = use_vad and self.capabilities.supports_vad_events

        if self._use_realtime_engine:
            # Initialize realtime engine for VAD-based recording
            from server.core.model_manager import get_model_manager

            model_manager = get_model_manager()
            self._realtime_engine = model_manager.get_realtime_engine(
                session_id=self.session_id,
                client_type=self.client_type,
                language=language,
                on_recording_start=lambda: asyncio.create_task(
                    self._on_vad_recording_start()
                ),
                on_recording_stop=lambda: asyncio.create_task(
                    self._on_vad_recording_stop()
                ),
                on_vad_start=lambda: asyncio.create_task(self._on_vad_start()),
                on_vad_stop=lambda: asyncio.create_task(self._on_vad_stop()),
            )
            self._realtime_engine.start_recording(language)
            logger.info(f"Recording started with VAD for {self.client_name}")
        else:
            logger.info(f"Recording started for {self.client_name}")

        await self.send_message(
            "session_started",
            {
                "vad_enabled": self._use_realtime_engine,
                "preview_enabled": self.capabilities.supports_preview
                and self._use_realtime_engine,
            },
        )

    async def _on_vad_recording_start(self) -> None:
        """Called when VAD detects speech start."""
        await self.send_message("vad_recording_start")

    async def _on_vad_recording_stop(self) -> None:
        """Called when VAD detects speech stop."""
        await self.send_message("vad_recording_stop")

    async def _on_vad_start(self) -> None:
        """Called when VAD detects voice activity."""
        await self.send_message("vad_start")

    async def _on_vad_stop(self) -> None:
        """Called when VAD detects voice inactivity."""
        await self.send_message("vad_stop")

    async def stop_recording(self) -> None:
        """Stop recording and process transcription."""
        if not self.is_recording:
            return

        self.is_recording = False
        await self.send_message("session_stopped")
        logger.info(f"Recording stopped for {self.client_name}")

        # Stop realtime engine if using VAD
        if self._realtime_engine:
            self._realtime_engine.stop_recording()

        try:
            # Process the transcription
            await self.process_transcription()
        finally:
            # Release the job slot when transcription is done
            self._release_job()

    def _release_job(self) -> None:
        """Release the job slot in the job tracker."""
        if self._current_job_id:
            from server.core.model_manager import get_model_manager

            model_manager = get_model_manager()
            model_manager.job_tracker.end_job(self._current_job_id)
            self._current_job_id = None

    async def cleanup(self) -> None:
        """Clean up session resources."""
        from server.core.model_manager import get_model_manager

        # Release any active job
        self._release_job()

        if self._realtime_engine:
            model_manager = get_model_manager()
            model_manager.release_realtime_engine(self.session_id)
            self._realtime_engine = None

        # Notify model manager about client disconnect
        if self.client_type == ClientType.STANDALONE:
            model_manager = get_model_manager()
            model_manager.on_standalone_client_disconnected()


async def handle_client_message(
    session: TranscriptionSession, message: Dict[str, Any]
) -> None:
    """Handle a JSON message from the client."""
    from server.core.model_manager import get_model_manager

    msg_type = message.get("type")

    if msg_type == "start":
        # Check job tracker before starting recording
        model_manager = get_model_manager()
        success, job_id, active_user = model_manager.job_tracker.try_start_job(
            session.client_name
        )

        if not success:
            # Another transcription is running - send session_busy but keep connection open
            await session.send_message("session_busy", {"active_user": active_user})
            logger.info(
                f"Recording rejected for {session.client_name} - "
                f"job already running for {active_user}"
            )
            return

        # Store job_id in session for cleanup
        session._current_job_id = job_id

        language = message.get("data", {}).get("language")
        use_vad = message.get("data", {}).get("use_vad", False)
        await session.start_recording(language, use_vad)

    elif msg_type == "stop":
        await session.stop_recording()

    elif msg_type == "ping":
        await session.send_message("pong")

    elif msg_type == "get_capabilities":
        await session.send_message("capabilities", session.capabilities.to_dict())

    else:
        logger.warning(f"Unknown message type: {msg_type}")


async def handle_binary_message(session: TranscriptionSession, data: bytes) -> None:
    """Handle binary audio data from the client."""
    if not session.is_recording:
        logger.warning("Received audio data but not recording")
        return

    try:
        # Parse binary message: [4 bytes metadata length][metadata JSON][PCM data]
        if len(data) < 4:
            logger.warning("Binary message too short")
            return

        # Read metadata length
        metadata_len = struct.unpack("<I", data[:4])[0]

        if len(data) < 4 + metadata_len:
            logger.warning("Invalid binary message format")
            return

        # Extract metadata (we don't strictly need it, but validate format)
        metadata_bytes = data[4 : 4 + metadata_len]
        try:
            metadata = json.loads(metadata_bytes.decode("utf-8"))
            sample_rate = metadata.get("sample_rate", 16000)
            if sample_rate != session.sample_rate:
                logger.warning(
                    f"Sample rate mismatch: expected {session.sample_rate}, got {sample_rate}"
                )
        except Exception as e:
            logger.warning(f"Failed to parse metadata: {e}")

        # Extract PCM data
        pcm_data = data[4 + metadata_len :]
        session.add_audio_chunk(pcm_data)

    except Exception as e:
        logger.error(f"Error processing binary message: {e}")


def _get_websocket_headers(websocket: WebSocket) -> Dict[str, str]:
    """Extract headers from WebSocket connection."""
    headers = {}
    for key, value in websocket.headers.items():
        headers[key.lower()] = value
    return headers


def _get_websocket_query_params(websocket: WebSocket) -> Dict[str, str]:
    """Extract query parameters from WebSocket connection."""
    return dict(websocket.query_params)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time transcription."""
    await websocket.accept()
    session: Optional[TranscriptionSession] = None

    # Detect client type from headers/query params
    headers = _get_websocket_headers(websocket)
    query_params = _get_websocket_query_params(websocket)
    client_type = ClientDetector.detect(headers, query_params)

    # Check if connection is from localhost
    client_host = websocket.client.host if websocket.client else None
    is_localhost = client_host in ("127.0.0.1", "::1", "localhost")

    logger.debug(
        f"WebSocket connection from client type: {client_type.value}, host: {client_host}"
    )

    try:
        # Wait for authentication message
        auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)

        if auth_msg.get("type") != "auth":
            await websocket.send_json(
                {
                    "type": "auth_fail",
                    "data": {"message": "Expected auth message"},
                    "timestamp": asyncio.get_event_loop().time(),
                }
            )
            await websocket.close()
            return

        # Validate token (skip validation for localhost connections)
        token = auth_msg.get("data", {}).get("token")

        if is_localhost:
            # For localhost, allow connection without token validation
            # Use a default token for tracking purposes
            from datetime import datetime, timezone
            from server.core.token_store import StoredToken

            stored_token = StoredToken(
                token="localhost",  # Note: 'token' not 'token_hash' (stores the hash)
                client_name="localhost-user",
                is_admin=True,
                is_revoked=False,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            logger.info(
                "WebSocket connection from localhost - bypassing authentication"
            )
        else:
            # For remote connections, require valid token
            if not token:
                await websocket.send_json(
                    {
                        "type": "auth_fail",
                        "data": {"message": "No token provided"},
                        "timestamp": asyncio.get_event_loop().time(),
                    }
                )
                await websocket.close()
                return

            token_store = get_token_store()
            stored_token = token_store.validate_token(token)

            if not stored_token:
                await websocket.send_json(
                    {
                        "type": "auth_fail",
                        "data": {"message": "Invalid or expired token"},
                        "timestamp": asyncio.get_event_loop().time(),
                    }
                )
                await websocket.close()
                return

        # Generate unique session ID
        session_id = str(uuid.uuid4())

        # Create new session (multiple connections allowed - job tracker
        # controls who can actually start recording)
        session = TranscriptionSession(
            websocket=websocket,
            client_name=stored_token.client_name,
            is_admin=stored_token.is_admin,
            client_type=client_type,
            session_id=session_id,
        )

        # Track session for cleanup
        async with _sessions_lock:
            _connected_sessions[session_id] = session

        # Notify model manager about standalone client
        if client_type == ClientType.STANDALONE:
            from server.core.model_manager import get_model_manager

            model_manager = get_model_manager()
            model_manager.on_standalone_client_connected()

        # Send auth success with capabilities
        await session.send_message(
            "auth_ok",
            {
                "client_name": stored_token.client_name,
                "client_type": client_type.value,
                "capabilities": session.capabilities.to_dict(),
            },
        )
        logger.info(
            f"WebSocket session started for {stored_token.client_name} "
            f"(type: {client_type.value}, id: {session_id})"
        )

        # Message loop
        while True:
            # Receive message (JSON or binary)
            message = await websocket.receive()

            # Check for disconnect message
            if message.get("type") == "websocket.disconnect":
                logger.info("WebSocket disconnect message received")
                break

            if "text" in message:
                # JSON message
                try:
                    msg_data = json.loads(message["text"])
                    await handle_client_message(session, msg_data)
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON message: {e}")

            elif "bytes" in message:
                # Binary audio data
                await handle_binary_message(session, message["bytes"])

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")

    except asyncio.TimeoutError:
        logger.warning("WebSocket authentication timeout")
        await websocket.close()

    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.close()
        except Exception as close_error:
            logger.debug(f"Failed to close WebSocket (already closed?): {close_error}")

    finally:
        # Clean up session
        if session:
            await session.cleanup()
            async with _sessions_lock:
                if session.session_id in _connected_sessions:
                    del _connected_sessions[session.session_id]
            logger.info(f"WebSocket session ended for {session.client_name}")
