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
        transcription_status = status.get("transcription", {}) if isinstance(status, dict) else {}
        is_loaded = bool(transcription_status.get("loaded", False))
        main_model_disabled = bool(transcription_status.get("disabled", False))
        is_ready = is_loaded or main_model_disabled

        # Server is also considered ready when Live Mode is active (main
        # model is intentionally unloaded to free VRAM for the live engine).
        if is_ready or is_live_mode_active():
            return JSONResponse(
                content={
                    "status": "ready_live_mode"
                    if (not is_ready and is_live_mode_active())
                    else "ready",
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
        transcription_status = status.get("transcription", {}) if isinstance(status, dict) else {}
        is_loaded = bool(transcription_status.get("loaded", False))
        main_model_disabled = bool(transcription_status.get("disabled", False))
        is_ready = is_loaded or main_model_disabled
    except AttributeError:
        status = {"error": "Model manager not initialized"}
        is_ready = False

    response: dict[str, Any] = {
        "status": "running",
        "version": __version__,
        "models": status,
        "features": status.get("features", {}),
        "ready": is_ready or is_live_mode_active(),
    }

    gpu_error = getattr(request.app.state, "gpu_error", None)
    if gpu_error is not None:
        response["gpu_error"] = gpu_error.get("error", "Unknown GPU error")
        response["gpu_error_action"] = "Please restart your computer to reset the GPU driver."
        # Surface the diagnostic recovery_hint (added by Task 4) so the
        # dashboard's GpuHealthCard can display it verbatim in the red state.
        # Optional — only present for the error-999 unrecoverable fingerprint;
        # absent for other failure modes. Backward compatible (additive only).
        recovery_hint = gpu_error.get("recovery_hint")
        if recovery_hint:
            response["gpu_error_recovery_hint"] = recovery_hint

    return response
