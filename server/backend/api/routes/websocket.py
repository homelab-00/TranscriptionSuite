"""
WebSocket endpoint for real-time audio transcription.

Handles:
- Token-based authentication
- Audio streaming (PCM Int16 with server-selected sample rate)
- Long-form transcription with VAD
- Client type detection (standalone vs web)
- Preview transcription for standalone clients
- Session management (single active session)
"""

import asyncio
import json
import shutil
import struct
import tempfile
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

# NOTE: model_manager is imported lazily inside functions to avoid
# loading heavy ML libraries (torch, faster_whisper) at module import time.
# This reduces server startup time by ~10 seconds.
from server.api.routes.utils import authenticate_websocket_from_message
from server.core.client_detector import (
    ClientDetector,
    ClientType,
    get_client_capabilities,
)
from server.core.json_utils import sanitize_for_json
from server.database.job_repository import (
    create_job as _create_job,
)
from server.database.job_repository import (
    mark_delivered as _mark_delivered,
)
from server.database.job_repository import (
    mark_failed as _mark_failed,
)
from server.database.job_repository import (
    save_result as _save_result,
)
from server.database.job_repository import (
    set_audio_path as _set_audio_path,
)
from server.logging import get_logger, sanitize_log_value
from starlette.websockets import WebSocketState

logger = get_logger(__name__)

router = APIRouter()

# Global session state - tracks all connected sessions for cleanup
# (Multiple connections allowed, but only one can be recording at a time)
_connected_sessions: dict[str, "TranscriptionSession"] = {}
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
        self.language: str | None = None
        self.audio_chunks: list[bytes] = []
        self.sample_rate = 16000
        self._sample_rate_mismatch_reported = False
        self.temp_file: Path | None = None

        # Real-time engine (for standalone clients with VAD)
        self._realtime_engine: Any | None = None
        self._use_realtime_engine = False

        # Job tracking for transcription
        self._current_job_id: str | None = None

        # Set to True when the client disconnects mid-transcription so the
        # worker thread can abort via cancellation_check.
        self._client_disconnected = False

        # Get client capabilities
        self.capabilities = get_client_capabilities({"x-client-type": client_type.value}, {})

    async def send_message(self, msg_type: str, data: dict[str, Any] | None = None) -> None:
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

            # Save audio to persistent storage before transcription starts.
            # This ensures raw audio survives a server crash — job can be retried.
            # Falls back to /tmp if persistent write fails so transcription still runs.
            _audio_written_persistently = False
            if self._current_job_id:
                try:
                    from server.config import get_config as _get_config

                    _cfg = _get_config()
                    _recordings_dir = Path(
                        _cfg.get("durability", "recordings_dir", default="/data/recordings")
                        or "/data/recordings"
                    )
                    _recordings_dir.mkdir(parents=True, exist_ok=True)
                    _free_bytes = shutil.disk_usage(str(_recordings_dir)).free
                    if _free_bytes < 500_000_000:
                        logger.warning(
                            "Low disk space: %.0f MB free in %s — audio may not survive a crash",
                            _free_bytes / 1_000_000,
                            _recordings_dir,
                        )
                    _audio_path = _recordings_dir / f"{self._current_job_id}.wav"
                    sf.write(str(_audio_path), audio_float, self.sample_rate)
                    self.temp_file = _audio_path
                    _audio_written_persistently = True
                    try:
                        _set_audio_path(self._current_job_id, str(_audio_path))
                    except Exception as _sap_err:
                        logger.warning(
                            "Failed to set audio_path in DB for job %s: %s",
                            self._current_job_id,
                            _sap_err,
                        )
                except Exception as _write_err:
                    logger.error(
                        "Failed to write audio to persistent storage: %s — falling back to /tmp",
                        _write_err,
                    )

            if not _audio_written_persistently:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    self.temp_file = Path(tmp.name)
                    sf.write(tmp.name, audio_float, self.sample_rate)
                # Record /tmp path so retries know where to look (best-effort)
                if self._current_job_id:
                    try:
                        _set_audio_path(self._current_job_id, str(self.temp_file))
                    except Exception as _exc:
                        logger.debug(
                            "Failed to record audio path for job %s: %s",
                            sanitize_log_value(self._current_job_id),
                            repr(_exc),
                        )

            logger.info(
                f"Processing {len(audio_float) / self.sample_rate:.2f}s of audio "
                f"for {self.client_name} (sample_rate={self.sample_rate}Hz, "
                f"samples={len(audio_float)})"
            )

            # Get transcription engine (lazy import to avoid startup delay).
            # ensure_transcription_loaded() lazily reloads the model if a
            # prior Live-Mode restore left it detached (Issue #76).
            from server.core.model_manager import get_model_manager

            model_manager = get_model_manager()
            engine = await asyncio.to_thread(model_manager.ensure_transcription_loaded)

            # Transcribe — run in a thread so the event loop stays responsive.
            # Without this, the synchronous transcribe_file() blocks the entire
            # asyncio event loop (and the server) for the duration of processing.
            task = "translate" if getattr(self, "translation_enabled", False) else "transcribe"
            translation_target = (
                getattr(self, "translation_target_language", "en") if task == "translate" else None
            )

            # Shared progress state written by the worker thread, read by the loop.
            # Simple dict access is safe here — GIL guarantees atomic reads of ints.
            _progress: dict[str, int] = {"current": 0, "total": 0}

            def _on_progress(current: int, total: int) -> None:
                _progress["current"] = current
                _progress["total"] = total
                model_manager.job_tracker.update_progress(current, total)

            loop = asyncio.get_event_loop()
            transcribe_future = loop.run_in_executor(
                None,
                lambda: engine.transcribe_file(
                    file_path=str(self.temp_file),
                    language=self.language,
                    word_timestamps=True,
                    task=task,
                    translation_target_language=translation_target,
                    progress_callback=_on_progress,
                    cancellation_check=lambda: self._client_disconnected,
                ),
            )

            # While transcription runs, send progress keepalives every 5 seconds.
            # This serves two purposes:
            #   1. Keeps the WebSocket connection alive (prevents idle timeout).
            #   2. Gives the client visible feedback so the user doesn't navigate away.
            _KEEPALIVE_INTERVAL = 5.0
            while True:
                done, _ = await asyncio.wait({transcribe_future}, timeout=_KEEPALIVE_INTERVAL)
                if done:
                    break
                await self.send_message(
                    "processing_progress",
                    {
                        "current": _progress["current"],
                        "total": _progress["total"],
                    },
                )

            result = transcribe_future.result()

            # Build and sanitize result payload
            result_payload = sanitize_for_json(
                {
                    "text": result.text,
                    "words": result.words or [],
                    "language": result.language,
                    "duration": result.duration,
                }
            )

            # PERSIST BEFORE DELIVER — result must survive even if delivery fails
            _result_persisted = False
            if self._current_job_id:
                try:
                    _save_result(
                        job_id=self._current_job_id,
                        result_text=result.text or "",
                        result_json=json.dumps(result_payload, ensure_ascii=False),
                        result_language=result.language,
                        duration_seconds=result.duration,
                    )
                    _result_persisted = True
                except Exception as _e:
                    # DB write failed — log CRITICAL but do NOT abort delivery.
                    # The user's transcription must not be lost because of a DB error.
                    logger.critical(
                        "CRITICAL: Failed to persist transcription result for job %s — "
                        "result will be delivered to client but is NOT in the database: %s",
                        self._current_job_id,
                        _e,
                    )
                    # Do NOT re-raise. Do NOT call mark_failed. Attempt delivery anyway.

            # Size check: very large results (>1 MB) cannot safely be sent over a
            # single WebSocket frame. Send a reference instead and let the client
            # fetch the result via HTTP. Wave 1 already persisted it to DB.
            _result_size = len(json.dumps(result_payload))
            _sent_as_reference = False
            if _result_size > 1_000_000 and self._current_job_id:
                # Send a lightweight reference so the client fetches via HTTP.
                # Do NOT call mark_delivered here — the client hasn't fetched yet.
                # mark_delivered is called by GET /result/{job_id} on actual fetch.
                await self.send_message("result_ready", {"job_id": self._current_job_id})
                _sent_as_reference = True
            else:
                # Send final result (best-effort — result is in DB regardless, or logged as lost above)
                await self.send_message("final", result_payload)

            # Only mark delivered when result was actually sent inline (not as reference).
            # For result_ready, the GET /result/{job_id} endpoint marks delivered on fetch.
            # Skip mark_delivered entirely if save_result failed — the row is stuck in
            # 'processing' state and will be cleaned up by orphan recovery on restart.
            if self._current_job_id and _result_persisted and not _sent_as_reference:
                try:
                    _mark_delivered(self._current_job_id)
                except Exception as _e:
                    logger.warning(
                        "Failed to mark job %s as delivered: %s", self._current_job_id, _e
                    )

            # R-001 zombie-job guard: if persistence failed, explicitly mark the
            # job as failed so it doesn't sit in 'processing' forever.  The result
            # was delivered to the client (best-effort) but is NOT in the database;
            # orphan recovery needs a terminal state, not a timeout guess.
            if self._current_job_id and not _result_persisted:
                try:
                    _mark_failed(
                        self._current_job_id,
                        "Persistence failed — result delivered to client but not saved to database",
                    )
                except Exception as _mf_err:
                    logger.warning(
                        "Failed to mark job %s as failed after persistence failure: %s",
                        self._current_job_id,
                        _mf_err,
                    )

            logger.info(f"Transcription complete for {self.client_name}")

            # Fire outgoing webhook (separate guard so failures don't
            # trigger a "transcription failed" error message to the client)
            try:
                from server.core.webhook import dispatch as dispatch_webhook

                await dispatch_webhook(
                    "longform_complete",
                    {
                        "source": "longform",
                        "text": result.text,
                        "filename": "",
                        "duration": result.duration,
                        "language": result.language,
                        "num_speakers": 0,
                    },
                )
            except Exception as wh_err:
                logger.warning("Webhook dispatch failed after transcription: %s", wh_err)

        except Exception as e:
            # Import lazily to avoid circular imports at module load time.
            from server.core.model_manager import TranscriptionCancelledError
            from server.core.stt.backends.base import BackendDependencyError

            if isinstance(e, TranscriptionCancelledError):
                logger.info(f"Transcription cancelled (client disconnected) for {self.client_name}")
                if self._current_job_id:
                    try:
                        _mark_failed(self._current_job_id, "Cancelled: client disconnected")
                    except Exception as _mf_err:
                        logger.warning(
                            "Failed to mark job %s as failed: %s", self._current_job_id, _mf_err
                        )
            else:
                # Surface BackendDependencyError remedy so the dashboard
                # can render an actionable hint (Issue #76).
                dep_error: BackendDependencyError | None = None
                if isinstance(e, BackendDependencyError):
                    dep_error = e
                elif isinstance(e.__cause__, BackendDependencyError):
                    dep_error = e.__cause__  # type: ignore[assignment]
                logger.error(f"Transcription error: {e}", exc_info=True)
                error_message = (
                    f"Transcription failed: {e}. {dep_error.remedy}"
                    if dep_error is not None
                    else f"Transcription failed: {e}"
                )
                if self._current_job_id:
                    try:
                        _mark_failed(self._current_job_id, error_message)
                    except Exception as _mf_err:
                        logger.warning(
                            "Failed to mark job %s as failed: %s", self._current_job_id, _mf_err
                        )
                await self.send_message("error", {"message": error_message})

        finally:
            # Only delete files in /tmp — persistent audio in recordings_dir must survive
            # so failed jobs can be retried (Wave 2) and orphan recovery can find them (Wave 3).
            if (
                self.temp_file
                and self.temp_file.exists()
                and str(self.temp_file).startswith("/tmp")
            ):
                try:
                    self.temp_file.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete temp file: {e}")
            self.temp_file = None
            self.audio_chunks = []

    async def start_recording(
        self,
        language: str | None = None,
        use_vad: bool = False,
        translation_enabled: bool = False,
        translation_target_language: str = "en",
    ) -> None:
        """
        Start a recording session.

        Args:
            language: Target language code
            use_vad: Use VAD for automatic start/stop detection
            translation_enabled: Enable source→target translation
            translation_target_language: Translation target (v1: "en" only)
        """
        self.is_recording = True
        self.language = language
        self.translation_enabled = translation_enabled
        self.translation_target_language = translation_target_language
        self.audio_chunks = []
        self._sample_rate_mismatch_reported = False
        self._use_realtime_engine = use_vad and self.capabilities.supports_vad_events
        self.sample_rate = self._determine_capture_sample_rate_hz()
        backend_name = "realtime_vad"
        if not self._use_realtime_engine:
            try:
                from server.core.model_manager import get_model_manager

                engine = get_model_manager().transcription_engine
                backend_name = getattr(getattr(engine, "_backend", None), "backend_name", "unknown")
            except Exception:
                backend_name = "unknown"
        logger.info(
            "Session capture configured for %s: backend=%s sample_rate=%sHz vad=%s",
            self.client_name,
            backend_name,
            self.sample_rate,
            self._use_realtime_engine,
        )

        if self._use_realtime_engine:
            # Initialize realtime engine for VAD-based recording
            from server.core.model_manager import get_model_manager

            model_manager = get_model_manager()

            # Capture the event loop for thread-safe callback scheduling
            # VAD callbacks are invoked from worker threads, so we need to use
            # run_coroutine_threadsafe instead of create_task
            loop = asyncio.get_running_loop()

            def schedule_coro(coro):
                """Schedule a coroutine from a worker thread."""
                asyncio.run_coroutine_threadsafe(coro, loop)

            self._realtime_engine = model_manager.get_realtime_engine(
                session_id=self.session_id,
                client_type=self.client_type,
                language=language,
                on_recording_start=lambda: schedule_coro(self._on_vad_recording_start()),
                on_recording_stop=lambda: schedule_coro(self._on_vad_recording_stop()),
                on_vad_start=lambda: schedule_coro(self._on_vad_start()),
                on_vad_stop=lambda: schedule_coro(self._on_vad_stop()),
            )
            self._realtime_engine.start_recording(language)
            logger.info(f"Recording started with VAD for {self.client_name}")

        else:
            logger.info(f"Recording started for {self.client_name}")

        await self.send_message(
            "session_started",
            {
                "vad_enabled": self._use_realtime_engine,
                "preview_enabled": False,
                "capture_sample_rate_hz": self.sample_rate,
                "job_id": self._current_job_id,
            },
        )

    def _determine_capture_sample_rate_hz(self) -> int:
        """Select the capture sample rate for this /ws session."""
        if self._use_realtime_engine:
            # RealtimeSTT live-style path is fixed to 16 kHz.
            return 16000

        try:
            from server.core.model_manager import get_model_manager

            engine = get_model_manager().transcription_engine
            backend = getattr(engine, "_backend", None)
            preferred = int(getattr(backend, "preferred_input_sample_rate_hz", 16000) or 16000)
            if preferred <= 0:
                return 16000
            return preferred
        except Exception as e:
            logger.warning("Falling back to 16kHz capture rate (could not inspect backend): %s", e)
            return 16000

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
            get_model_manager()
            # No special per-client model handling required


async def handle_client_message(session: TranscriptionSession, message: dict[str, Any]) -> None:
    """Handle a JSON message from the client."""
    from server.core.model_manager import get_model_manager

    msg_type = message.get("type")

    if msg_type == "start":
        # Check job tracker before starting recording
        model_manager = get_model_manager()
        success, job_id, active_user = model_manager.job_tracker.try_start_job(session.client_name)

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

        # Extract job metadata from message before attributes are set by start_recording()
        _msg_data = message.get("data", {})
        _language = _msg_data.get("language")
        _translation_enabled = _msg_data.get("translation_enabled", False)
        _translation_target = _msg_data.get("translation_target_language")
        try:
            _create_job(
                job_id=session._current_job_id,
                source="websocket",
                client_name=session.client_name,
                language=_language,
                task="translate" if _translation_enabled else "transcribe",
                translation_target=_translation_target,
            )
        except Exception as _e:
            logger.warning(
                "Failed to create job record for %s: %s",
                sanitize_log_value(session._current_job_id),
                repr(_e),
            )
            session._current_job_id = None  # Prevent downstream DB noise

        language = _msg_data.get("language")
        use_vad = _msg_data.get("use_vad", False)
        translation_enabled = _msg_data.get("translation_enabled", False)
        translation_target_language = _msg_data.get("translation_target_language", "en")
        await session.start_recording(
            language, use_vad, translation_enabled, translation_target_language
        )

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
            sample_rate = int(
                metadata.get("sample_rate", session.sample_rate) or session.sample_rate
            )
            if sample_rate != session.sample_rate:
                message = (
                    f"Audio sample rate mismatch: expected {session.sample_rate}, "
                    f"got {sample_rate}. Dropping chunk."
                )
                logger.warning(message)
                if not session._sample_rate_mismatch_reported:
                    session._sample_rate_mismatch_reported = True
                    await session.send_message("error", {"message": message})
                return
        except Exception as e:
            logger.warning(f"Failed to parse metadata: {e}")

        # Extract PCM data
        pcm_data = data[4 + metadata_len :]
        session.add_audio_chunk(pcm_data)

    except Exception as e:
        logger.error(f"Error processing binary message: {e}")


def _get_websocket_headers(websocket: WebSocket) -> dict[str, str]:
    """Extract headers from WebSocket connection."""
    headers = {}
    for key, value in websocket.headers.items():
        headers[key.lower()] = value
    return headers


def _get_websocket_query_params(websocket: WebSocket) -> dict[str, str]:
    """Extract query parameters from WebSocket connection."""
    return dict(websocket.query_params)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time transcription."""
    await websocket.accept()
    session: TranscriptionSession | None = None

    # Detect client type from headers/query params
    headers = _get_websocket_headers(websocket)
    query_params = _get_websocket_query_params(websocket)
    client_type = ClientDetector.detect(headers, query_params)

    # Check source host for logging
    client_host = websocket.client.host if websocket.client else None

    logger.debug(f"WebSocket connection from client type: {client_type.value}, host: {client_host}")

    try:
        auth = await authenticate_websocket_from_message(
            websocket,
            allow_localhost_bypass=True,
            failure_type="auth_fail",
        )
        if auth is None:
            return
        if auth.is_localhost_bypass:
            logger.info("WebSocket connection from trusted local host - bypassing authentication")

        # Generate unique session ID
        session_id = str(uuid.uuid4())

        # Create new session (multiple connections allowed - job tracker
        # controls who can actually start recording)
        session = TranscriptionSession(
            websocket=websocket,
            client_name=auth.client_name,
            is_admin=auth.is_admin,
            client_type=client_type,
            session_id=session_id,
        )

        # Track session for cleanup
        async with _sessions_lock:
            _connected_sessions[session_id] = session

        # Notify model manager about standalone client
        if client_type == ClientType.STANDALONE:
            from server.core.model_manager import get_model_manager

            get_model_manager()
            # No special per-client model handling required

        # Send auth success with capabilities
        await session.send_message(
            "auth_ok",
            {
                "client_name": auth.client_name,
                "client_type": client_type.value,
                "capabilities": session.capabilities.to_dict(),
            },
        )
        logger.info(
            f"WebSocket session started for {auth.client_name} "
            f"(type: {client_type.value}, id: {session_id})"
        )

        # Message loop
        while True:
            # Receive message (JSON or binary)
            message = await websocket.receive()

            # Check for disconnect message
            if message.get("type") == "websocket.disconnect":
                logger.info("WebSocket disconnect message received")
                if session:
                    session._client_disconnected = True
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
        if session:
            session._client_disconnected = True

    except TimeoutError:
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
