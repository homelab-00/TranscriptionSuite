"""
Authentication API endpoints for TranscriptionSuite server.

Handles:
- Token-based login
- Token management (admin only)
- User information
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server.api.routes.utils import require_admin
from server.core.token_store import get_token_store

logger = logging.getLogger(__name__)

router = APIRouter()


class LoginRequest(BaseModel):
    """Request model for login."""

    token: str


class LoginResponse(BaseModel):
    """Response model for login."""

    success: bool
    user: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


class CreateTokenRequest(BaseModel):
    """Request model for creating a token."""

    client_name: str
    is_admin: bool = False
    expiry_days: Optional[int] = None


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> Dict[str, Any]:
    """
    Authenticate with a token.

    Returns user information if the token is valid.
    """
    try:
        token_store = get_token_store()
        stored_token = token_store.validate_token(request.token)

        if stored_token is None:
            return {
                "success": False,
                "message": "Invalid or expired token",
            }

        return {
            "success": True,
            "user": {
                "name": stored_token.client_name,
                "is_admin": stored_token.is_admin,
                "token_id": stored_token.token_id,
            },
        }

    except Exception as e:
        logger.error(f"Login failed: {e}")
        return {
            "success": False,
            "message": "Authentication failed",
        }


@router.get("/tokens")
async def list_tokens(request: Request) -> Dict[str, Any]:
    """
    List all tokens (admin only).
    """
    if not require_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        token_store = get_token_store()
        tokens = token_store.list_tokens()

        return {
            "tokens": [
                {
                    "token_id": t.token_id,
                    "client_name": t.client_name,
                    "is_admin": t.is_admin,
                    "created_at": t.created_at,
                    "expires_at": t.expires_at,
                    "is_revoked": t.is_revoked,
                    "is_expired": t.is_expired(),
                    "token": f"{t.token[:8]}..." if t.token else None,  # Show partial hash only
                }
                for t in tokens
            ]
        }

    except Exception as e:
        logger.error(f"Failed to list tokens: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tokens")
async def create_token(request: Request, body: CreateTokenRequest) -> Dict[str, Any]:
    """
    Create a new token (admin only).

    Returns the newly created token (only shown once).
    """
    if not require_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        token_store = get_token_store()
        stored_token, plaintext_token = token_store.generate_token(
            client_name=body.client_name,
            is_admin=body.is_admin,
            expiry_days=body.expiry_days,
        )

        return {
            "success": True,
            "message": "Token created successfully",
            "token": {
                "token": plaintext_token,  # Only time this is shown!
                "token_id": stored_token.token_id,
                "client_name": stored_token.client_name,
                "is_admin": stored_token.is_admin,
                "created_at": stored_token.created_at,
                "expires_at": stored_token.expires_at,
            },
        }

    except Exception as e:
        logger.error(f"Failed to create token: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tokens/{token_id}")
async def revoke_token(request: Request, token_id: str) -> Dict[str, Any]:
    """
    Revoke a token by its ID (admin only).
    """
    if not require_admin(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        token_store = get_token_store()
        success = token_store.revoke_token_by_id(token_id)

        if not success:
            raise HTTPException(status_code=404, detail="Token not found")

        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revoke token: {e}")
        raise HTTPException(status_code=500, detail=str(e))
