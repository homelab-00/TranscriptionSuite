"""Tests for disabled main/live model slot behavior."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from server.api.routes import health, transcription
from server.config import DISABLED_MODEL_SENTINEL


class _FakeModelManager:
    def __init__(self, status: dict):
        self._status = status

    def get_status(self) -> dict:
        return self._status


class _FakeRequest:
    def __init__(self, *, config: dict | None = None, status: dict | None = None):
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                config=config or {},
                model_manager=_FakeModelManager(status or {}),
            )
        )


def test_ready_endpoint_treats_disabled_main_model_as_ready() -> None:
    request = _FakeRequest(
        status={
            "transcription": {
                "loaded": False,
                "disabled": True,
            }
        }
    )

    response = asyncio.run(health.readiness_check(request))
    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["status"] == "ready"


def test_api_status_marks_ready_when_main_model_disabled() -> None:
    request = _FakeRequest(
        status={
            "transcription": {
                "loaded": False,
                "disabled": True,
            },
            "features": {},
        }
    )

    payload = asyncio.run(health.get_status(request))
    assert payload["ready"] is True


def test_transcription_routes_reject_when_main_model_is_disabled() -> None:
    request = _FakeRequest(
        config={
            "main_transcriber": {"model": DISABLED_MODEL_SENTINEL},
        }
    )

    with pytest.raises(HTTPException) as exc:
        transcription._assert_main_model_selected(request)

    assert exc.value.status_code == 409
    assert "Main model not selected" in str(exc.value.detail)
