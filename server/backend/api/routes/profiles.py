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
from server.core.filename_template import find_unknown_placeholders
from server.database import profile_repository
from server.database.profile_repository import (
    SUPPORTED_SCHEMA_VERSIONS,
    UnsupportedSchemaVersionError,
)


def _validate_template(public_fields: Any) -> None:
    """Reject templates with unknown placeholders (Issue #104, Story 3.2 AC1).

    Raises HTTPException 400 with the R-EL24 error shape.
    """
    if public_fields is None:
        return
    template = (
        public_fields.filename_template if hasattr(public_fields, "filename_template") else None
    )
    if not template:
        return
    unknown = find_unknown_placeholders(template)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_template",
                "unknown_placeholders": unknown,
            },
        )


def _validate_webhook_url_field(public_fields: Any) -> None:
    """Reject webhook URLs that fail the SSRF / scheme allowlist (Story 7.2).

    Raises HTTPException 400 with the per-AC error shape:
      - scheme_not_allowed: ``{"error": "scheme_not_allowed", "allowed": [...], "received": ...}``
      - private_ip_blocked: ``{"error": "private_ip_blocked", "ip": ..., ...}``
      - invalid_url:        ``{"error": "invalid_url", "reason": ...}``
      - dns_failure:        ``{"error": "dns_failure", "reason": ...}``
    """
    if public_fields is None:
        return
    url = public_fields.webhook_url if hasattr(public_fields, "webhook_url") else ""
    if not url:
        # Empty string is the "webhook disabled" signal — no validation.
        return

    from server.core.webhook_url_validation import (
        WebhookUrlValidationError,
        validate_webhook_url,
    )

    try:
        validate_webhook_url(url)
    except WebhookUrlValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": exc.code, **exc.detail},
        ) from exc


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
    # Sprint 5 — Story 7.2 / FR43-46 — per-profile webhook configuration.
    # The URL itself is public-fields (Lurkers can see if a profile fires
    # webhooks at all); the auth header value is private and stored via
    # private_field_refs (NFR8 / FR49) — Story 1.7 keychain.
    webhook_url: str = ""
    webhook_include_transcript_text: bool = False

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


# Sensitive keys that may be persisted inside ``public_fields_json`` until
# Story 1.7 (keychain) lands, but MUST be stripped from API responses to
# prevent credential leakage via GET /api/profiles. Keep this list explicit
# (not regex/pattern) so adding a new sensitive field requires a deliberate
# code change. The coordinator reads these from the persisted
# ``public_fields_json`` directly, so stripping at the response boundary
# does not affect the delivery pipeline.
_RESPONSE_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "webhook_auth_header",  # Sprint 5 Story 7.2 — bearer token / API key
    }
)


def _scrub_sensitive_public_fields(public: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``public_fields`` with sensitive keys removed."""
    return {k: v for k, v in public.items() if k not in _RESPONSE_SENSITIVE_KEYS}


def _to_response(record: dict[str, Any]) -> ProfileResponse:
    public = profile_repository.to_public_dict(record)
    safe_public = _scrub_sensitive_public_fields(public["public_fields"])
    return ProfileResponse(
        id=public["id"],
        name=public["name"],
        description=public["description"],
        schema_version=public["schema_version"],
        public_fields=ProfilePublicFields.model_validate(safe_public),
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
    # Story 3.2 AC1: reject templates with unknown placeholders. Applied at
    # CREATE as well as UPDATE so a malformed template can never be saved.
    _validate_template(body.public_fields)
    # Story 7.2 — reject webhook URLs that fail the SSRF / scheme allowlist.
    _validate_webhook_url_field(body.public_fields)
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
    # Story 3.2 AC1: reject templates with unknown placeholders.
    _validate_template(body.public_fields)
    # Story 7.2 — reject webhook URLs that fail the SSRF / scheme allowlist.
    _validate_webhook_url_field(body.public_fields)

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
