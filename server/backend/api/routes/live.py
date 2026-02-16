"""
WebSocket endpoint for Live Mode real-time transcription.

Provides a dedicated endpoint for continuous sentence-by-sentence
transcription using RealtimeSTT. Unlike the main /ws endpoint which
handles file-based transcription, Live Mode runs continuously and
streams completed sentences as they are detected.

Model Swapping: When Live Mode starts, the main transcription model
is unloaded to free VRAM for the Live Mode model. When Live Mode
stops, the main model is reloaded for normal transcription.
"""

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from server.api.routes.utils import authenticate_websocket_from_message
from server.core.live_engine import (
    LiveModeConfig,
    LiveModeEngine,
    LiveModeState,
)
from server.core.model_manager import get_model_manager
from server.config import get_config, resolve_live_transcriber_model
from server.logging import get_logger
from starlette.websockets import WebSocketState

logger = get_logger(__name__)

router = APIRouter()

# Track active Live Mode session (only one at a time)
_live_mode_state: dict[str, Optional["LiveModeSession"]] = {"active_session": None}
_session_lock = asyncio.Lock()


class LiveModeSession:
    """
    Manages a Live Mode WebSocket session.

    Handles authentication, engine control, and message streaming
    for a single Live Mode client.
    """

    def __init__(
        self,
        websocket: WebSocket,
        client_name: str,
    ):
        self.websocket = websocket
        self.client_name = client_name
        self._engine: Optional[LiveModeEngine] = None
        self._message_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._running = False

    async def send_message(self, msg_type: str, data: Optional[dict] = None) -> None:
        """Send a JSON message to the client."""
        if (
            self.websocket.client_state != WebSocketState.CONNECTED
            or self.websocket.application_state != WebSocketState.CONNECTED
        ):
            return

        message = {
            "type": msg_type,
            "data": data or {},
            "timestamp": asyncio.get_event_loop().time(),
        }
        try:
            await self.websocket.send_json(message)
        except Exception as e:
            # Socket can close between state check and send.
            logger.debug(f"Failed to send message (socket closed): {e}")

    def _queue_message(self, msg_type: str, data: Optional[dict] = None) -> None:
        """Queue a message from the engine thread to be sent async."""
        try:
            self._message_queue.put_nowait(
                {
                    "type": msg_type,
                    "data": data or {},
                }
            )
        except asyncio.QueueFull:
            logger.warning("Message queue full, dropping message")

    def _on_sentence(self, text: str) -> None:
        """Callback when a sentence is completed."""
        self._queue_message("sentence", {"text": text})

    def _on_realtime_update(self, text: str) -> None:
        """Callback for real-time partial updates."""
        self._queue_message("partial", {"text": text})

    def _on_state_change(self, state: LiveModeState) -> None:
        """Callback when engine state changes."""
        self._queue_message("state", {"state": state.name})

    async def start_engine(self, config_data: Optional[dict] = None) -> bool:
        """
        Start the Live Mode engine.

        This unloads the main transcription model to free VRAM, then
        starts the Live Mode engine with its own (typically smaller) model.

        If the Live Mode model is the same as the main model, the model
        files are already cached and only need to be reloaded with
        different configurations.
        """
        if self._engine and self._engine.is_running:
            await self.send_message("error", {"message": "Engine already running"})
            return False

        try:
            # Build config from client data
            server_cfg = get_config()
            config = LiveModeConfig()
            config.model = resolve_live_transcriber_model(server_cfg)
            if config_data:
                if "model" in config_data:
                    candidate_model = str(config_data["model"] or "").strip()
                    if candidate_model:
                        config.model = candidate_model
                if "language" in config_data:
                    config.language = config_data["language"]
                if "translation_enabled" in config_data:
                    raw_enabled = config_data["translation_enabled"]
                    if isinstance(raw_enabled, str):
                        config.translation_enabled = raw_enabled.strip().lower() in (
                            "1",
                            "true",
                            "yes",
                            "on",
                        )
                    else:
                        config.translation_enabled = bool(raw_enabled)
                if "translation_target_language" in config_data:
                    config.translation_target_language = (
                        str(config_data["translation_target_language"] or "en")
                        .strip()
                        .lower()
                    )
                if "silero_sensitivity" in config_data:
                    config.silero_sensitivity = float(config_data["silero_sensitivity"])
                if "post_speech_silence_duration" in config_data:
                    config.post_speech_silence_duration = float(
                        config_data["post_speech_silence_duration"]
                    )

            if config.translation_enabled:
                from server.core.stt.capabilities import supports_english_translation

                if config.translation_target_language != "en":
                    await self.send_message(
                        "error",
                        {
                            "message": "Live Mode translation target must be English ('en') in v1."
                        },
                    )
                    return False
                if not supports_english_translation(config.model):
                    await self.send_message(
                        "error",
                        {
                            "message": (
                                "Selected Live Mode model does not support translation. "
                                "Use a multilingual non-turbo Whisper model."
                            )
                        },
                    )
                    return False

            # Check if Live Mode model is the same as main model
            model_manager = get_model_manager()
            is_same_model = model_manager.is_same_model(
                model_manager.main_model_name,
                config.model,
            )

            if is_same_model:
                logger.info(
                    f"Live Mode using same model as main ({config.model}) - "
                    "model files already cached"
                )
                await self.send_message(
                    "status",
                    {
                        "message": f"Using cached model ({config.model})...",
                        "same_model": True,
                    },
                )
            else:
                await self.send_message(
                    "status",
                    {
                        "message": f"Switching to Live Mode model ({config.model})...",
                        "same_model": False,
                    },
                )

            # Unload the main transcription model to free VRAM for Live Mode
            await self.send_message("status", {"message": "Unloading main model..."})
            try:
                model_manager.unload_transcription_model()
                logger.info("Unloaded main transcription model for Live Mode")
            except Exception as e:
                logger.warning(f"Failed to unload main model (may not be loaded): {e}")

            # Create engine with callbacks
            await self.send_message("status", {"message": "Loading Live Mode model..."})
            self._engine = LiveModeEngine(
                config=config,
                on_sentence=self._on_sentence,
                on_realtime_update=self._on_realtime_update,
                on_state_change=self._on_state_change,
            )

            # Start the engine
            if self._engine.start():
                self._running = True
                logger.info(f"Live Mode started for {self.client_name}")
                return True
            else:
                # If start failed, try to reload main model
                await self._reload_main_model()
                await self.send_message("error", {"message": "Failed to start engine"})
                return False

        except Exception as e:
            logger.error(f"Failed to start Live Mode: {e}")
            # Try to reload main model on failure
            await self._reload_main_model()
            await self.send_message("error", {"message": str(e)})
            return False

    async def _reload_main_model(self) -> None:
        """Reload the main transcription model after Live Mode ends."""
        try:
            model_manager = get_model_manager()
            # Load in background thread to not block
            await asyncio.to_thread(model_manager.load_transcription_model)
            logger.info("Reloaded main transcription model after Live Mode")
        except Exception as e:
            logger.error(f"Failed to reload main transcription model: {e}")

    async def stop_engine(self) -> None:
        """
        Stop the Live Mode engine.

        This stops the Live Mode engine and reloads the main transcription
        model so normal transcription can resume.
        """
        self._running = False
        if self._engine:
            self._engine.stop()
            self._engine = None
            logger.info(f"Live Mode stopped for {self.client_name}")

            # Reload main transcription model
            await self.send_message("status", {"message": "Reloading main model..."})
            await self._reload_main_model()

        await self.send_message("state", {"state": "STOPPED"})

    async def get_history(self) -> list[str]:
        """Get transcription history."""
        if self._engine:
            return self._engine.sentence_history
        return []

    async def clear_history(self) -> None:
        """Clear transcription history."""
        if self._engine:
            self._engine.clear_history()
        await self.send_message("history_cleared", {})

    async def cleanup(self) -> None:
        """Clean up session resources."""
        await self.stop_engine()

    async def process_messages(self) -> None:
        """Process queued messages from engine callbacks."""
        # Wait for engine to start before processing
        # The loop needs to keep running even when queue is empty,
        # as long as the engine might produce more messages
        while True:
            try:
                msg = await asyncio.wait_for(self._message_queue.get(), timeout=0.1)
                await self.send_message(msg["type"], msg["data"])
            except asyncio.TimeoutError:
                # Check if we should exit - only exit when:
                # 1. _running is False (engine stopped)
                # 2. Queue is empty (no pending messages)
                if not self._running and self._message_queue.empty():
                    break
                continue
            except Exception as e:
                logger.error(f"Error processing message: {e}")


async def handle_client_message(session: LiveModeSession, message: dict) -> None:
    """Handle a JSON message from the client."""
    msg_type = message.get("type", "")
    data = message.get("data", {})

    if msg_type == "start":
        # Start Live Mode with optional config
        await session.start_engine(data.get("config"))

    elif msg_type == "stop":
        # Stop Live Mode
        await session.stop_engine()

    elif msg_type == "get_history":
        # Get transcription history
        history = await session.get_history()
        await session.send_message("history", {"sentences": history})

    elif msg_type == "clear_history":
        # Clear history
        await session.clear_history()

    elif msg_type == "ping":
        # Keep-alive ping
        await session.send_message("pong", {})

    else:
        logger.warning(f"Unknown message type: {msg_type}")
        await session.send_message(
            "error", {"message": f"Unknown message type: {msg_type}"}
        )


@router.websocket("/ws/live")
async def live_mode_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for Live Mode transcription."""
    await websocket.accept()
    session: Optional[LiveModeSession] = None

    # Check source host for logging
    client_host = websocket.client.host if websocket.client else None

    logger.debug(f"Live Mode WebSocket connection from host: {client_host}")

    try:
        auth = await authenticate_websocket_from_message(
            websocket,
            allow_localhost_bypass=True,
            failure_type="auth_fail",
        )
        if auth is None:
            return

        if auth.is_localhost_bypass:
            logger.info(
                "Live Mode connection from localhost - bypassing authentication"
            )

        client_name = auth.client_name

        # Check if another session is active
        async with _session_lock:
            if _live_mode_state["active_session"] is not None:
                await websocket.send_json(
                    {
                        "type": "error",
                        "data": {
                            "message": "Another Live Mode session is already active"
                        },
                        "timestamp": asyncio.get_event_loop().time(),
                    }
                )
                await websocket.close()
                return

            # Create and register session
            session = LiveModeSession(
                websocket=websocket,
                client_name=client_name,
            )
            _live_mode_state["active_session"] = session

        # Send auth success
        await session.send_message("auth_ok", {"client_name": client_name})
        logger.info(f"Live Mode session started for {client_name}")

        # Start message processing task
        message_task = asyncio.create_task(session.process_messages())

        # Message loop
        try:
            while True:
                message = await websocket.receive()

                if message.get("type") == "websocket.disconnect":
                    logger.info("Live Mode WebSocket disconnect message received")
                    break

                # Handle binary audio data
                if "bytes" in message:
                    audio_data = message["bytes"]
                    if session and session._engine and session._engine.is_running:
                        # Parse audio format (same as /ws endpoint):
                        # [4 bytes metadata length][metadata JSON][PCM Int16 data]
                        if len(audio_data) > 4:
                            import struct

                            metadata_len = struct.unpack("<I", audio_data[:4])[0]
                            if len(audio_data) >= 4 + metadata_len:
                                pcm_data = audio_data[4 + metadata_len :]
                                session._engine.feed_audio(pcm_data)
                    continue

                if "text" in message:
                    try:
                        msg_data = json.loads(message["text"])
                        await handle_client_message(session, msg_data)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON message: {e}")
        finally:
            # Cancel message processing task
            message_task.cancel()
            try:
                await message_task
            except asyncio.CancelledError:
                logger.debug("Live Mode message task cancelled during cleanup")

    except WebSocketDisconnect:
        logger.info("Live Mode WebSocket disconnected")

    except asyncio.TimeoutError:
        logger.warning("Live Mode WebSocket authentication timeout")
        await websocket.close()

    except Exception as e:
        logger.error(f"Live Mode WebSocket error: {e}", exc_info=True)
        try:
            await websocket.close()
        except Exception as close_error:
            logger.debug(
                "Failed to close Live Mode websocket after error: %s", close_error
            )

    finally:
        # Clean up session
        if session:
            await session.cleanup()
            async with _session_lock:
                if _live_mode_state["active_session"] is session:
                    _live_mode_state["active_session"] = None
            logger.info(f"Live Mode session ended for {session.client_name}")
