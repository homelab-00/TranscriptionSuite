"""
Health and status endpoints for TranscriptionSuite server.
"""

from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from server import __version__

router = APIRouter()


@router.get("/health")
async def health_check() -> Dict[str, str]:
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

        if is_ready:
            return JSONResponse(
                content={"status": "ready", "models": status},
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
async def get_status(request: Request) -> Dict[str, Any]:
    """
    Get detailed server status including GPU and model information.
    """
    try:
        model_manager = request.app.state.model_manager
        status = model_manager.get_status()
    except AttributeError:
        status = {"error": "Model manager not initialized"}

    return {
        "status": "running",
        "version": __version__,
        "models": status,
        "features": status.get("features", {}),
    }
