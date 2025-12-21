"""
WebSocket endpoint for real-time audio transcription.

Handles:
- Token-based authentication
- Audio streaming (16kHz PCM Int16)
- Long-form transcription
- Session management (single active session)
"""

import asyncio
import io
import json
import struct
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import soundfile as sf
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from server.core.model_manager import get_model_manager
from server.core.token_store import get_token_store
from server.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Global session state (single active session)
_active_session: Optional[Dict[str, Any]] = None
_session_lock = asyncio.Lock()


class TranscriptionSession:
    """Manages a single transcription session."""

    def __init__(self, websocket: WebSocket, client_name: str, is_admin: bool):
        self.websocket = websocket
        self.client_name = client_name
        self.is_admin = is_admin
        self.is_recording = False
        self.language: Optional[str] = None
        self.audio_chunks: list[bytes] = []
        self.sample_rate = 16000
        self.temp_file: Optional[Path] = None

    async def send_message(self, msg_type: str, data: Optional[Dict[str, Any]] = None):
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

    def add_audio_chunk(self, pcm_data: bytes):
        """Add a chunk of PCM audio data."""
        self.audio_chunks.append(pcm_data)

    async def process_transcription(self):
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

            # Get transcription engine
            model_manager = get_model_manager()
            engine = model_manager.transcription_engine

            # Transcribe
            result = engine.transcribe_file(
                file_path=str(self.temp_file),
                language=self.language,
                word_timestamps=True,
            )

            # Collect all words from all segments
            all_words = []
            for segment in result.segments:
                for w in segment.words:
                    all_words.append({
                        "word": w.word,
                        "start": w.start,
                        "end": w.end,
                        "probability": w.probability,
                    })

            # Send final result
            await self.send_message(
                "final",
                {
                    "text": result.text,
                    "words": all_words,
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

    async def start_recording(self, language: Optional[str] = None):
        """Start a recording session."""
        self.is_recording = True
        self.language = language
        self.audio_chunks = []
        await self.send_message("session_started")
        logger.info(f"Recording started for {self.client_name}")

    async def stop_recording(self):
        """Stop recording and process transcription."""
        if not self.is_recording:
            return

        self.is_recording = False
        await self.send_message("session_stopped")
        logger.info(f"Recording stopped for {self.client_name}")

        # Process the transcription
        await self.process_transcription()


async def handle_client_message(session: TranscriptionSession, message: Dict[str, Any]):
    """Handle a JSON message from the client."""
    msg_type = message.get("type")

    if msg_type == "start":
        language = message.get("data", {}).get("language")
        await session.start_recording(language)

    elif msg_type == "stop":
        await session.stop_recording()

    elif msg_type == "ping":
        await session.send_message("pong")

    else:
        logger.warning(f"Unknown message type: {msg_type}")


async def handle_binary_message(session: TranscriptionSession, data: bytes):
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


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time transcription."""
    global _active_session

    await websocket.accept()
    session: Optional[TranscriptionSession] = None

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

        # Validate token
        token = auth_msg.get("data", {}).get("token")
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

        # Check for active session
        async with _session_lock:
            if _active_session is not None:
                active_user = _active_session.get("client_name", "unknown")
                await websocket.send_json(
                    {
                        "type": "session_busy",
                        "data": {"active_user": active_user},
                        "timestamp": asyncio.get_event_loop().time(),
                    }
                )
                await websocket.close()
                return

            # Create new session
            session = TranscriptionSession(
                websocket, stored_token.client_name, stored_token.is_admin
            )
            _active_session = {
                "client_name": stored_token.client_name,
                "session": session,
            }

        # Send auth success
        await session.send_message("auth_ok", {"client_name": stored_token.client_name})
        logger.info(f"WebSocket session started for {stored_token.client_name}")

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
        except Exception:
            pass

    finally:
        # Clean up session
        async with _session_lock:
            if _active_session and session:
                if _active_session.get("session") == session:
                    _active_session = None
                    logger.info(f"WebSocket session ended for {session.client_name}")
