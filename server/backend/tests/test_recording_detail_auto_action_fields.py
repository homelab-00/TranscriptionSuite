"""Recording-detail response surfaces auto-action fields (Issue #104, Sprint 4 no. 3).

Migration 015 added five user-facing auto-action columns to ``recordings``;
without them on the response model, the dashboard's AutoActionStatusBadge
cannot render. This test pins the contract: the five columns appear in
``GET /api/notebook/recordings/{id}`` JSON.

Follows the direct-call pattern from test_transcription_durability_routes.py
— invoke the handler with asyncio.run, assert on the returned dict.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from server.api.routes import notebook


@pytest.fixture()
def patched_getters(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch the data-access functions on the notebook module so the route
    runs against an in-memory recording dict instead of hitting SQLite."""
    recording: dict[str, Any] = {
        "id": 42,
        "filename": "demo.wav",
        "filepath": "/data/recordings/demo.wav",
        "title": "Demo",
        "duration_seconds": 60.0,
        "recorded_at": "2025-01-15T12:00:00Z",
        "imported_at": None,
        "word_count": 5,
        "has_diarization": False,
        "summary": None,
        "summary_model": None,
        "transcription_backend": "whisper",
        # Sprint 4 lifecycle columns (migration 015) — these are what we're
        # pinning to the response.
        "auto_summary_status": "success",
        "auto_summary_error": None,
        "auto_export_status": "deferred",
        "auto_export_error": "destination unavailable",
        "auto_export_path": "/mnt/external/exports",
    }
    monkeypatch.setattr(notebook, "get_recording", lambda rid: recording if rid == 42 else None)
    monkeypatch.setattr(notebook, "get_segments", lambda _rid: [])
    monkeypatch.setattr(notebook, "get_words", lambda _rid: [])
    return recording


def test_recording_detail_includes_all_auto_action_fields(
    patched_getters: dict[str, Any],
) -> None:
    """All five Sprint 4 columns surface verbatim in the response dict."""
    result = asyncio.run(notebook.get_recording_detail(42))
    assert result["auto_summary_status"] == "success"
    assert result["auto_summary_error"] is None
    assert result["auto_export_status"] == "deferred"
    assert result["auto_export_error"] == "destination unavailable"
    assert result["auto_export_path"] == "/mnt/external/exports"


def test_recording_response_model_validates_serialization(
    patched_getters: dict[str, Any],
) -> None:
    """The Pydantic RecordingDetailResponse round-trips the new fields.

    Catches typos in the model field names — Pydantic silently drops unknown
    fields on validation, so without this check a misnamed column would just
    disappear from the response."""
    result = asyncio.run(notebook.get_recording_detail(42))
    validated = notebook.RecordingDetailResponse(**result)
    payload = validated.model_dump()
    for field in (
        "auto_summary_status",
        "auto_summary_error",
        "auto_export_status",
        "auto_export_error",
        "auto_export_path",
    ):
        assert field in payload, f"missing {field} on RecordingDetailResponse"


def test_recording_detail_handles_null_auto_action_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh recording with no auto-actions yet returns nulls cleanly —
    the dashboard's statusToBadgeProps treats null status as 'no badge'."""
    recording: dict[str, Any] = {
        "id": 1,
        "filename": "fresh.wav",
        "filepath": "/data/recordings/fresh.wav",
        "title": "Fresh",
        "duration_seconds": 10.0,
        "recorded_at": "2025-01-15T12:00:00Z",
        "imported_at": None,
        "word_count": 0,
        "has_diarization": False,
        "summary": None,
        "summary_model": None,
        "transcription_backend": None,
        "auto_summary_status": None,
        "auto_summary_error": None,
        "auto_export_status": None,
        "auto_export_error": None,
        "auto_export_path": None,
    }
    monkeypatch.setattr(notebook, "get_recording", lambda _rid: recording)
    monkeypatch.setattr(notebook, "get_segments", lambda _rid: [])
    monkeypatch.setattr(notebook, "get_words", lambda _rid: [])
    result = asyncio.run(notebook.get_recording_detail(1))
    assert result["auto_summary_status"] is None
    assert result["auto_export_status"] is None
