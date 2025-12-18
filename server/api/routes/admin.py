"""
Admin API endpoints for TranscriptionSuite server.

Handles:
- Token management
- Server configuration
- Log access
- Model management
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class TokenCreateRequest(BaseModel):
    """Request to create a new token."""

    name: str
    is_admin: bool = False


class TokenResponse(BaseModel):
    """Response for token operations."""

    token_id: str
    name: str
    is_admin: bool
    created_at: str
    token: Optional[str] = None  # Only set on creation


@router.get("/status")
async def get_admin_status(request: Request) -> Dict[str, Any]:
    """Get detailed admin status information."""
    try:
        model_manager = request.app.state.model_manager
        config = request.app.state.config

        return {
            "status": "running",
            "models": model_manager.get_status(),
            "config": {
                "server": config.server,
                "transcription": {
                    "model": config.transcription.get("model"),
                    "device": config.transcription.get("device"),
                },
            },
        }
    except Exception as e:
        logger.error(f"Failed to get admin status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/load")
async def load_models(request: Request) -> Dict[str, str]:
    """Explicitly load transcription models."""
    try:
        model_manager = request.app.state.model_manager
        model_manager.load_transcription_model()
        return {"status": "loaded"}
    except Exception as e:
        logger.error(f"Failed to load models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/unload")
async def unload_models(request: Request) -> Dict[str, str]:
    """Unload transcription models to free memory."""
    try:
        model_manager = request.app.state.model_manager
        model_manager.unload_all()
        return {"status": "unloaded"}
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

        # Read last N lines
        lines = []
        with open(log_path, "r") as f:
            all_lines = f.readlines()
            lines = all_lines[-limit:]

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


# Token management endpoints (placeholder - implement with proper auth)
@router.get("/tokens")
async def list_tokens() -> Dict[str, Any]:
    """List all tokens (admin only)."""
    # TODO: Implement proper token store integration
    return {
        "tokens": [],
        "message": "Token management not yet implemented in unified server",
    }


@router.post("/tokens")
async def create_token(request: TokenCreateRequest) -> Dict[str, Any]:
    """Create a new token (admin only)."""
    # TODO: Implement proper token creation
    raise HTTPException(
        status_code=501,
        detail="Token management not yet implemented in unified server",
    )


@router.delete("/tokens/{token_id}")
async def revoke_token(token_id: str) -> Dict[str, str]:
    """Revoke a token (admin only)."""
    # TODO: Implement proper token revocation
    raise HTTPException(
        status_code=501,
        detail="Token management not yet implemented in unified server",
    )
