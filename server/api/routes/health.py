"""
Health and status endpoints for TranscriptionSuite server.
"""

from typing import Any, Dict

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health_check() -> Dict[str, str]:
    """Basic health check endpoint (no auth required)."""
    return {"status": "healthy", "service": "transcription-suite"}


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
        "version": "2.0.0",
        "models": status,
    }
