"""
WebSocket endpoint for Live Mode real-time transcription.

Provides a dedicated endpoint for continuous sentence-by-sentence
transcription using the RealtimeSTT-compatible whisper path. Unlike the main /ws endpoint which
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
from server.config import get_config, resolve_live_transcriber_model
from server.core.live_engine import (
    LiveModeConfig,
    LiveModeEngine,
    LiveModeState,
)
from server.core.model_manager import get_model_manager
from server.core.stt.backends.factory import detect_backend_type
from server.logging import get_logger
from starlette.websockets import WebSocketState

logger = get_logger(__name__)

router = APIRouter()

# Track active Live Mode session (only one at a time)
_live_mode_state: dict[str, Optional["LiveModeSession"]] = {"active_session": None}
_session_lock = asyncio.Lock()


def is_live_mode_active() -> bool:
    """Check if a Live Mode session is currently active."""
    return _live_mode_state["active_session"] is not None


def is_live_mode_model_supported(model_name: str) -> bool:
    """Live Mode only supports faster-whisper (whisper backend) in v1."""
    name = (model_name or "").strip()
    if not name or name == "__none__":
        return False
    return detect_backend_type(name) == "whisper"


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
        self._engine: LiveModeEngine | None = None
        self._message_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._running = False
        # Backend borrowed from the main engine (non-None when sharing).
        self._shared_backend: object | None = None
        # Capture the event loop so engine callbacks (from background threads)
        # can safely enqueue messages via call_soon_threadsafe.
        self._loop = asyncio.get_running_loop()

    async def send_message(self, msg_type: str, data: dict | None = None) -> None:
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

    def _queue_message(self, msg_type: str, data: dict | None = None) -> None:
        """Queue a message from the engine thread to be sent async.

        asyncio.Queue is NOT thread-safe, so we use call_soon_threadsafe
        to schedule the put_nowait on the event loop from the engine's
        background thread.
        """
        msg = {"type": msg_type, "data": data or {}}
        try:
            self._loop.call_soon_threadsafe(self._message_queue.put_nowait, msg)
        except RuntimeError:
            # Event loop closed — session is shutting down
            logger.debug("Event loop closed, dropping queued message")

    def _on_sentence(self, text: str) -> None:
        """Callback when a sentence is completed."""
        self._queue_message("sentence", {"text": text})
        # Fire outgoing webhook (thread-safe — this runs in engine's background thread)
        from server.core.webhook import dispatch_fire_and_forget

        dispatch_fire_and_forget(
            self._loop,
            "live_sentence",
            {
                "source": "live",
                "text": text,
            },
        )

    def _on_realtime_update(self, text: str) -> None:
        """Callback for real-time partial updates."""
        self._queue_message("partial", {"text": text})

    def _on_state_change(self, state: LiveModeState) -> None:
        """Callback when engine state changes."""
        self._queue_message("state", {"state": state.name})

    async def start_engine(self, config_data: dict | None = None) -> bool:
        """
        Start the Live Mode engine.

        When the live model is the same as the main model **and** the
        model-level load parameters match, the GPU-loaded backend is
        shared instead of unloaded and reloaded — saving significant
        startup time.

        When models differ (or load params are incompatible), the main
        model is fully unloaded to free VRAM before loading the live
        model.
        """
        if self._engine and self._engine.is_running:
            await self.send_message("error", {"message": "Engine already running"})
            return False

        # R-003: Track whether the main model has been displaced (detached or
        # unloaded).  The finally block uses this to guarantee restoration on
        # ANY exit — including asyncio.CancelledError which bypasses
        # ``except Exception``.
        _model_displaced = False

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
                        str(config_data["translation_target_language"] or "en").strip().lower()
                    )
                if "silero_sensitivity" in config_data:
                    config.silero_sensitivity = float(config_data["silero_sensitivity"])
                if "post_speech_silence_duration" in config_data:
                    config.post_speech_silence_duration = float(
                        config_data["post_speech_silence_duration"]
                    )

            if not config.model.strip():
                await self.send_message(
                    "error",
                    {
                        "status_code": 409,
                        "message": (
                            "Live model not selected. Choose a Live Mode model in Server settings "
                            "before starting Live Mode."
                        ),
                    },
                )
                return False

            if not is_live_mode_model_supported(config.model):
                backend_type = detect_backend_type(config.model)
                await self.send_message(
                    "error",
                    {
                        "message": (
                            "Live Mode only supports faster-whisper models "
                            "(RealtimeSTT path) in v1. "
                            f"Selected backend '{backend_type}' is not supported."
                        )
                    },
                )
                return False

            if config.translation_enabled:
                from server.core.stt.capabilities import supports_english_translation

                if config.translation_target_language != "en":
                    await self.send_message(
                        "error",
                        {"message": "Live Mode translation target must be English ('en') in v1."},
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

            # Determine whether we can share the backend (same model +
            # compatible model-level load params).
            can_share = False
            if is_same_model:
                main_params = model_manager.get_transcription_load_params()
                if main_params:
                    can_share = (
                        main_params.get("device") == config.device
                        and main_params.get("compute_type") == config.compute_type
                        and main_params.get("gpu_device_index") == config.gpu_device_index
                        and main_params.get("batch_size") == config.batch_size
                    )
                    if not can_share:
                        logger.info(
                            "Same model but load params differ — falling back to "
                            f"full reload (main={main_params}, live={{"
                            f"device={config.device!r}, "
                            f"compute_type={config.compute_type!r}, "
                            f"gpu_device_index={config.gpu_device_index!r}, "
                            f"batch_size={config.batch_size!r}}})"
                        )

            shared_backend = None

            if can_share:
                logger.info(
                    f"Live Mode reusing main backend ({config.model}) — skipping unload/reload"
                )
                await self.send_message(
                    "status",
                    {
                        "message": f"Reusing loaded model ({config.model})...",
                        "same_model": True,
                    },
                )
                shared_backend = model_manager.detach_transcription_backend()
                if shared_backend is None:
                    # Main model wasn't loaded — fall back to normal path
                    logger.warning(
                        "Backend detach returned None (main model not loaded), "
                        "falling back to full load"
                    )
                    can_share = False
                else:
                    _model_displaced = True
                    # Assign immediately so _restore_or_reload_main_model()
                    # can reattach (not reload) if a CancelledError fires
                    # before we reach the engine-creation block below.
                    self._shared_backend = shared_backend

            if not can_share:
                if is_same_model:
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

                # Unload the main transcription model to free VRAM for Live Mode.
                # unload_transcription_model() handles "nothing loaded" gracefully
                # (silent return), so an exception here means a genuine failure —
                # proceeding would risk CUDA OOM when loading the live model.
                await self.send_message("status", {"message": "Unloading main model..."})
                try:
                    model_manager.unload_transcription_model()
                    _model_displaced = True
                    logger.info("Unloaded main transcription model for Live Mode")
                except Exception as e:
                    logger.error(f"Failed to unload main model — aborting Live Mode start: {e}")
                    await self.send_message(
                        "error",
                        {"message": f"Failed to free GPU memory for Live Mode: {e}"},
                    )
                    return False

            # Create engine with callbacks (and shared backend when available)
            if shared_backend is not None:
                await self.send_message("status", {"message": "Starting Live Mode..."})
            else:
                await self.send_message("status", {"message": "Loading Live Mode model..."})

            self._shared_backend = shared_backend
            self._engine = LiveModeEngine(
                config=config,
                on_sentence=self._on_sentence,
                on_realtime_update=self._on_realtime_update,
                on_state_change=self._on_state_change,
                shared_backend=shared_backend,
            )

            # Start the engine
            if self._engine.start():
                self._running = True
                _model_displaced = False  # Engine owns the model now
                logger.info(f"Live Mode started for {self.client_name}")
                return True
            else:
                await self.send_message("error", {"message": "Failed to start engine"})
                return False  # finally will restore

        except Exception as e:
            logger.error(f"Failed to start Live Mode: {e}")
            await self.send_message("error", {"message": str(e)})
            return False  # finally will restore

        finally:
            # R-003: Guarantee main-model restoration on ANY exit path —
            # including asyncio.CancelledError (BaseException) from a WS
            # disconnect during the model-swap window.  On the success path
            # _model_displaced is already False, so this is a no-op.
            if _model_displaced:
                # Stop and discard any partially-constructed engine to
                # prevent daemon-thread leaks from a failed start().
                if self._engine is not None:
                    try:
                        self._engine.stop()
                    except Exception:
                        pass  # Best-effort cleanup — engine may already be torn down
                    self._engine = None
                # asyncio.shield() keeps the restore coroutine running
                # even if CancelledError fires during the await — the
                # model reload completes in the background.
                try:
                    await asyncio.shield(self._restore_or_reload_main_model())
                except (Exception, asyncio.CancelledError) as _restore_err:
                    logger.error(
                        "Failed to restore main model after live-mode failure: %s",
                        _restore_err,
                    )

    async def _reload_main_model(self) -> None:
        """Reload the main transcription model after Live Mode ends.

        BackendDependencyError is treated as a recoverable warning (the user
        can install the missing dep and restart). Any OTHER reload failure is
        logged with full traceback, surfaced to the dashboard via emit_event,
        and re-raised so the caller's try/except sees the original error
        instead of the engine silently staying detached (Issue #76).
        """
        from server.core.startup_events import emit_event
        from server.core.stt.backends.base import BackendDependencyError

        try:
            model_manager = get_model_manager()
            # Load in background thread to not block
            await asyncio.to_thread(model_manager.load_transcription_model)
            logger.info("Reloaded main transcription model after Live Mode")
        except Exception as e:
            if isinstance(e, BackendDependencyError) or (
                e.__cause__ and isinstance(e.__cause__, BackendDependencyError)
            ):
                dep = e if isinstance(e, BackendDependencyError) else e.__cause__
                logger.warning(
                    "Skipped main model reload after Live Mode — missing dependency: %s. %s",
                    dep,
                    getattr(dep, "remedy", ""),
                )
                # Surface to the dashboard so the user knows the main model
                # is unavailable and what to do about it.
                try:
                    emit_event(
                        "warn-stt-main",
                        "warning",
                        f"Main transcription model unavailable: {dep}. "
                        f"{getattr(dep, 'remedy', '')}".strip(),
                        persistent=True,
                    )
                except Exception:
                    logger.warning("emit_event failed for warn-stt-main", exc_info=True)
                # Recoverable: do not raise — file routes auto-reload on demand
                # via ensure_transcription_loaded() and produce the same warning.
                return

            logger.error("Failed to reload main transcription model after Live Mode: %s", e)
            try:
                emit_event(
                    "warn-stt-main",
                    "warning",
                    f"Main transcription model failed to reload: {e}. "
                    "Open Settings → Models and click 'Reload Model'.",
                    persistent=True,
                )
            except Exception:
                logger.debug("emit_event failed for warn-stt-main", exc_info=True)
            # Non-dependency failures are unexpected — re-raise so the caller's
            # try/except (start_engine finally / stop_engine) records the full
            # traceback and the engine is not silently left detached forever.
            raise

    async def _restore_or_reload_main_model(self) -> None:
        """Return the shared backend to the main engine, or reload from scratch."""
        if self._shared_backend is not None:
            model_manager = get_model_manager()
            model_manager.attach_transcription_backend(self._shared_backend)
            self._shared_backend = None
            logger.info("Returned shared backend to main engine")
        else:
            await self._reload_main_model()

    async def stop_engine(self) -> None:
        """
        Stop the Live Mode engine.

        When the backend was shared, it is returned to the main engine
        without a reload.  Otherwise the main model is fully reloaded.
        """
        self._running = False
        if self._engine:
            self._engine.stop()
            self._engine = None
            logger.info(f"Live Mode stopped for {self.client_name}")

            # Restore or reload main transcription model
            if self._shared_backend is not None:
                await self.send_message("status", {"message": "Restoring main model (shared)..."})
            else:
                await self.send_message("status", {"message": "Reloading main model..."})
            # Reload failures are surfaced via emit_event in _reload_main_model
            # and recovered on demand by ensure_transcription_loaded() (Issue
            # #76). Catch here so the STOPPED state still reaches the client
            # and session cleanup proceeds. Also catch CancelledError so a
            # WS cancel mid-reload doesn't skip the STOPPED state notification.
            try:
                await self._restore_or_reload_main_model()
            except (Exception, asyncio.CancelledError) as restore_err:
                logger.error(
                    "Failed to restore main model after Live Mode stop (client=%s): %s",
                    self.client_name,
                    restore_err,
                )

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
            except TimeoutError:
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
        await session.send_message("error", {"message": f"Unknown message type: {msg_type}"})


@router.websocket("/ws/live")
async def live_mode_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for Live Mode transcription."""
    await websocket.accept()
    session: LiveModeSession | None = None

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
            logger.info("Live Mode connection from trusted local host - bypassing authentication")

        client_name = auth.client_name

        # Check if another session is active
        async with _session_lock:
            if _live_mode_state["active_session"] is not None:
                await websocket.send_json(
                    {
                        "type": "error",
                        "data": {"message": "Another Live Mode session is already active"},
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

    except TimeoutError:
        logger.warning("Live Mode WebSocket authentication timeout")
        await websocket.close()

    except Exception as e:
        logger.error(f"Live Mode WebSocket error: {e}", exc_info=True)
        try:
            await websocket.close()
        except Exception as close_error:
            logger.debug("Failed to close Live Mode websocket after error: %s", close_error)

    finally:
        # Clean up session
        if session:
            await session.cleanup()
            async with _session_lock:
                if _live_mode_state["active_session"] is session:
                    _live_mode_state["active_session"] = None
            logger.info(f"Live Mode session ended for {session.client_name}")
