"""
Health and status endpoints for TranscriptionSuite server.
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from server.api.routes.live import is_live_mode_active

from server import __version__

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Basic health check endpoint (no auth required)."""
    return {"status": "healthy", "service": "transcriptionsuite"}


@router.get("/ready")
async def readiness_check(request: Request) -> JSONResponse:
    """
    Readiness check - returns 200 only when server is fully ready.
    Used by clients to wait for model loading to complete.

    Returns:
        200: Server is ready (models loaded)
        503: Server is starting up (models still loading)
    """
    try:
        model_manager = request.app.state.model_manager
        status = model_manager.get_status()

        # Check if transcription model is loaded
        is_ready = status.get("transcription", {}).get("loaded", False)

        # Server is also considered ready when Live Mode is active (main
        # model is intentionally unloaded to free VRAM for the live engine).
        if is_ready or is_live_mode_active():
            return JSONResponse(
                content={
                    "status": "ready_live_mode" if not is_ready else "ready",
                    "models": status,
                },
                status_code=200,
            )
        else:
            return JSONResponse(
                content={"status": "loading", "models": status},
                status_code=503,
            )
    except AttributeError:
        return JSONResponse(
            content={"status": "initializing"},
            status_code=503,
        )


@router.get("/api/status")
async def get_status(request: Request) -> dict[str, Any]:
    """
    Get detailed server status including GPU and model information.

    The ``ready`` field consolidates the logic from ``/ready`` so that
    dashboard clients can poll a single endpoint instead of three.
    """
    try:
        model_manager = request.app.state.model_manager
        status = model_manager.get_status()
        is_ready = status.get("transcription", {}).get("loaded", False)
    except AttributeError:
        status = {"error": "Model manager not initialized"}
        is_ready = False

    return {
        "status": "running",
        "version": __version__,
        "models": status,
        "features": status.get("features", {}),
        "ready": is_ready or is_live_mode_active(),
    }
