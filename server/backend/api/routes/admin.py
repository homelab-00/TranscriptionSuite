"""
Admin API endpoints for TranscriptionSuite server.

Handles:
- Server configuration
- Log access
- Model management
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)

from server.api.routes.utils import (
    authenticate_websocket_from_headers,
    require_admin,
)
from server.config import resolve_live_transcriber_model, resolve_main_transcriber_model

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/status")
async def get_admin_status(request: Request) -> Dict[str, Any]:
    """Get detailed admin status information."""
    if not require_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        model_manager = request.app.state.model_manager
        config = request.app.state.config
        main_cfg = config.get("main_transcriber", default={}) or {}
        live_cfg = config.get("live_transcriber", default={}) or {}
        legacy_cfg = config.transcription or {}

        if not isinstance(main_cfg, dict):
            main_cfg = {}
        if not isinstance(live_cfg, dict):
            live_cfg = {}
        if not isinstance(legacy_cfg, dict):
            legacy_cfg = {}

        main_model = resolve_main_transcriber_model(config)
        live_model = resolve_live_transcriber_model(config)
        main_device = main_cfg.get("device") or legacy_cfg.get("device")
        live_device = live_cfg.get("device") or main_device

        return {
            "status": "running",
            "models": model_manager.get_status(),
            "config": {
                "server": config.server,
                "main_transcriber": {
                    "model": main_model,
                    "device": main_device,
                },
                "live_transcriber": {
                    "model": live_model,
                    "device": live_device,
                },
                # Backward-compat aliases consumed by older clients.
                "transcription": {
                    "model": main_model,
                    "device": main_device,
                },
                "live_transcription": {
                    "model": live_model,
                    "device": live_device,
                },
            },
        }
    except Exception as e:
        logger.error(f"Failed to get admin status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/load")
async def load_models(request: Request) -> Dict[str, str]:
    """Explicitly load transcription models."""
    if not require_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        model_manager = request.app.state.model_manager
        model_manager.load_transcription_model()
        return {"status": "loaded"}
    except Exception as e:
        logger.error(f"Failed to load models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/models/load/stream")
async def load_models_stream(websocket: WebSocket) -> None:
    """
    Load transcription models with streaming progress updates.

    This WebSocket endpoint loads models in a background thread while
    streaming progress messages to the client. This prevents the UI
    from freezing during large model downloads.

    Protocol:
    - Connect to WebSocket
    - Receive: {"type": "progress", "message": "..."} - Progress updates
    - Receive: {"type": "complete", "status": "loaded"} - Success
    - Receive: {"type": "error", "message": "..."} - Error
    - Connection closes after complete/error
    """
    await websocket.accept()

    auth = await authenticate_websocket_from_headers(
        websocket,
        require_admin=True,
        allow_localhost_bypass=True,
        failure_type="error",
    )
    if auth is None:
        return

    logger.info(
        "WebSocket connected for model loading with progress "
        f"(client={auth.client_name})"
    )

    try:
        # Get model manager from app state
        model_manager = websocket.app.state.model_manager

        # Track messages to send
        message_queue: asyncio.Queue[Dict[str, str]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        async def send_progress(msg: str) -> None:
            """Queue a progress message for sending."""
            await message_queue.put({"type": "progress", "message": msg})

        def progress_callback(msg: str) -> None:
            """Called from model loading thread - queue message for async send."""
            asyncio.run_coroutine_threadsafe(send_progress(msg), loop)

        # Start message sender task
        async def message_sender() -> None:
            """Send queued messages to WebSocket."""
            while True:
                msg = await message_queue.get()
                if msg.get("type") == "_done":
                    break
                try:
                    await websocket.send_json(msg)
                except Exception as e:
                    logger.warning(f"Failed to send WebSocket message: {e}")
                    break

        sender_task = asyncio.create_task(message_sender())

        # Initial progress message
        await websocket.send_json(
            {"type": "progress", "message": "Initializing model loader..."}
        )

        # Run model loading in thread pool
        try:
            await loop.run_in_executor(
                None,
                lambda: model_manager.load_transcription_model(
                    progress_callback=progress_callback
                ),
            )

            # Send completion message
            await websocket.send_json({"type": "complete", "status": "loaded"})
            logger.info("Model loading completed successfully via WebSocket")

        except Exception as e:
            logger.error(f"Model loading failed: {e}")
            await websocket.send_json({"type": "error", "message": str(e)})

        # Stop the sender task
        await message_queue.put({"type": "_done"})
        await sender_task

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during model loading")
    except Exception as e:
        logger.error(f"WebSocket error during model loading: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception as send_error:
            logger.debug(
                "Failed to send model loading error to websocket: %s", send_error
            )
    finally:
        try:
            await websocket.close()
        except Exception as close_error:
            logger.debug("Failed to close model loading websocket: %s", close_error)


@router.post("/models/unload")
async def unload_models(request: Request) -> Dict[str, str]:
    """Unload transcription models to free memory."""
    if not require_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        model_manager = request.app.state.model_manager

        # Check if server is busy with a transcription
        is_busy, active_user = model_manager.job_tracker.is_busy()
        if is_busy:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot unload models - transcription in progress for {active_user}",
            )

        model_manager.unload_all()
        return {"status": "unloaded"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to unload models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs")
async def get_logs(
    service: Optional[str] = Query(None, description="Filter by service"),
    level: Optional[str] = Query(None, description="Filter by level"),
    limit: int = Query(100, ge=1, le=1000, description="Number of lines"),
) -> Dict[str, Any]:
    """
    Get recent log entries.

    Note: This is a simplified implementation. For production,
    consider using a proper log aggregation system.
    """
    try:
        import json
        from pathlib import Path

        # Try to find log file
        log_paths = [
            Path("/data/logs/server.log"),
            Path(__file__).parent.parent.parent.parent / "data" / "logs" / "server.log",
        ]

        log_path = None
        for path in log_paths:
            if path.exists():
                log_path = path
                break

        if not log_path:
            return {"logs": [], "message": "Log file not found"}

        # Read last N lines efficiently using file seeking
        # This avoids loading the entire file into memory
        lines = []
        try:
            with open(log_path, "rb") as f:
                # Seek to end of file
                f.seek(0, 2)
                file_size = f.tell()

                # Read backwards in chunks to find last N lines
                buffer_size = 8192
                lines_found = []
                position = file_size

                while position > 0 and len(lines_found) < limit:
                    # Calculate chunk size
                    chunk_size = min(buffer_size, position)
                    position -= chunk_size

                    # Read chunk
                    f.seek(position)
                    chunk = f.read(chunk_size).decode("utf-8", errors="replace")

                    # Split into lines and prepend to our list
                    chunk_lines = chunk.split("\n")
                    lines_found = chunk_lines + lines_found

                # Get the last N lines (may have extra from chunk reading)
                lines = (
                    lines_found[-limit:] if len(lines_found) > limit else lines_found
                )
                # Remove empty lines
                lines = [line for line in lines if line.strip()]
        except Exception as e:
            logger.error(f"Failed to read log file: {e}")
            return {"logs": [], "message": "Error reading log file"}

        # Parse JSON logs
        logs = []
        for line in lines:
            try:
                entry = json.loads(line.strip())

                # Apply filters
                if service and entry.get("service") != service:
                    continue
                if level and entry.get("level") != level.upper():
                    continue

                logs.append(entry)
            except json.JSONDecodeError:
                # Handle non-JSON log lines
                logs.append({"message": line.strip(), "raw": True})

        return {
            "logs": logs,
            "count": len(logs),
            "filters": {
                "service": service,
                "level": level,
            },
        }

    except Exception as e:
        logger.error(f"Failed to get logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))
