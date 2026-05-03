"""Profile CRUD endpoints (Issue #104, Story 1.2).

Mounted at ``/api/profiles`` from ``server/api/main.py``. Authentication is
enforced by ``AuthenticationMiddleware`` at the app layer (TLS mode); these
handlers do not re-check auth themselves, matching the project convention.

Schema-version validation: writes that ship an unsupported ``schema_version``
return HTTP 400 with body ``{"error": "unsupported_schema_version", ...}``
(FR16 / NFR13 / R-EL30).

Persist-Before-Deliver (NFR16): every handler relies on
``profile_repository``'s commit-before-return guarantee.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from server.database import profile_repository
from server.database.profile_repository import (
    SUPPORTED_SCHEMA_VERSIONS,
    UnsupportedSchemaVersionError,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ──────────────────────────────────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────────────────────────────────


class ProfilePublicFields(BaseModel):
    """Non-sensitive profile settings — safe to return to any client."""

    filename_template: str = Field(default="{date} {title}.txt")
    destination_folder: str = ""
    auto_summary_enabled: bool = False
    auto_export_enabled: bool = False
    summary_model_id: str | None = None
    summary_prompt_template: str | None = None
    export_format: str = "plaintext"

    model_config = {"extra": "allow"}  # forward-compat: unknown keys preserved


class ProfileCreate(BaseModel):
    name: str
    description: str | None = None
    schema_version: str = "1.0"
    public_fields: ProfilePublicFields = Field(default_factory=ProfilePublicFields)
    # private_fields are write-only: client may send plaintext here, but the
    # server must persist them via the keychain (Story 1.7) and store only
    # the references on the row. Until Story 1.7 lands, this map is stored
    # as the reference dict directly — the value is treated as the keychain
    # ID, not a secret. Tests verify FR11 (plaintext never returned).
    private_fields: dict[str, str] | None = None


class ProfileUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    schema_version: str | None = None
    public_fields: ProfilePublicFields | None = None
    private_fields: dict[str, str] | None = None


class ProfileResponse(BaseModel):
    id: int
    name: str
    description: str | None
    schema_version: str
    public_fields: ProfilePublicFields
    created_at: str
    updated_at: str
    # NOTE: private_field_refs intentionally absent — FR11 enforced at the
    # response-model boundary, not via remember-to-strip logic.


def _to_response(record: dict[str, Any]) -> ProfileResponse:
    public = profile_repository.to_public_dict(record)
    return ProfileResponse(
        id=public["id"],
        name=public["name"],
        description=public["description"],
        schema_version=public["schema_version"],
        public_fields=ProfilePublicFields.model_validate(public["public_fields"]),
        created_at=public["created_at"],
        updated_at=public["updated_at"],
    )


def _schema_version_error_detail(received: str) -> dict[str, Any]:
    return {
        "error": "unsupported_schema_version",
        "supported": sorted(SUPPORTED_SCHEMA_VERSIONS),
        "received": received,
    }


# ──────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ProfileResponse])
async def list_profiles_endpoint() -> list[ProfileResponse]:
    return [_to_response(p) for p in profile_repository.list_profiles()]


@router.get("/{profile_id}", response_model=ProfileResponse)
async def get_profile_endpoint(profile_id: int) -> ProfileResponse:
    profile = profile_repository.get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail={"error": "profile_not_found"})
    return _to_response(profile)


@router.post("", response_model=ProfileResponse, status_code=201)
async def create_profile_endpoint(body: ProfileCreate) -> ProfileResponse:
    if body.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=_schema_version_error_detail(body.schema_version),
        )
    try:
        profile_id = profile_repository.create_profile(
            name=body.name,
            description=body.description,
            schema_version=body.schema_version,
            public_fields=body.public_fields.model_dump(),
            private_field_refs=body.private_fields,
        )
    except UnsupportedSchemaVersionError as exc:
        raise HTTPException(
            status_code=400,
            detail=_schema_version_error_detail(exc.received),
        ) from exc
    profile = profile_repository.get_profile(profile_id)
    if profile is None:
        # Should never happen — create_profile commits before returning the
        # id and the row was just written. Treat as 500 rather than asserting
        # so we don't lean on Python's `-O` flag for correctness.
        raise HTTPException(
            status_code=500,
            detail={"error": "profile_vanished_post_commit", "id": profile_id},
        )
    return _to_response(profile)


@router.put("/{profile_id}", response_model=ProfileResponse)
async def update_profile_endpoint(profile_id: int, body: ProfileUpdate) -> ProfileResponse:
    if body.schema_version is not None and body.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=_schema_version_error_detail(body.schema_version),
        )

    # Only forward fields the caller actually set in the JSON payload —
    # the repository distinguishes "omitted" (sentinel) from "None"
    # (clear-to-NULL), so we MUST use exclude_unset semantics here.
    sent = body.model_fields_set
    update_kwargs: dict[str, Any] = {}
    if "name" in sent:
        update_kwargs["name"] = body.name
    if "description" in sent:
        update_kwargs["description"] = body.description
    if "schema_version" in sent:
        update_kwargs["schema_version"] = body.schema_version
    if "public_fields" in sent:
        update_kwargs["public_fields"] = (
            body.public_fields.model_dump() if body.public_fields is not None else None
        )
    if "private_fields" in sent:
        update_kwargs["private_field_refs"] = body.private_fields

    try:
        updated = profile_repository.update_profile(profile_id, **update_kwargs)
    except UnsupportedSchemaVersionError as exc:
        raise HTTPException(
            status_code=400,
            detail=_schema_version_error_detail(exc.received),
        ) from exc

    if not updated:
        raise HTTPException(status_code=404, detail={"error": "profile_not_found"})
    profile = profile_repository.get_profile(profile_id)
    if profile is None:
        # Race-condition guard — another client deleted the profile between
        # our UPDATE and our re-SELECT. Surface as 404 since the resource is
        # genuinely gone from the caller's perspective.
        raise HTTPException(status_code=404, detail={"error": "profile_not_found"})
    return _to_response(profile)


@router.delete("/{profile_id}", status_code=204)
async def delete_profile_endpoint(profile_id: int) -> None:
    deleted = profile_repository.delete_profile(profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail={"error": "profile_not_found"})
