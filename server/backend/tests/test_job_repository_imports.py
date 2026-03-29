"""Regression tests for database repository imports."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys

from server.api.routes import transcription


def test_job_repository_imports_under_server_alias() -> None:
    """Import should succeed when backend root is aliased as `server`."""
    sys.modules.pop("server.database.job_repository", None)
    module = importlib.import_module("server.database.job_repository")
    assert hasattr(module, "get_connection")


def test_transcription_result_handler_resolves_deferred_job_import(monkeypatch) -> None:
    """Deferred import in result handler should resolve under `server` alias layout."""
    repository = importlib.import_module("server.database.job_repository")

    monkeypatch.setattr(
        repository,
        "get_job",
        lambda _job_id: {
            "status": "completed",
            "client_name": None,
            "result_json": '{"text": "ok"}',
        },
    )
    monkeypatch.setattr(repository, "mark_delivered", lambda _job_id: None)
    monkeypatch.setattr(transcription, "get_client_name", lambda _request: "Unknown Client")

    response = asyncio.run(transcription.get_transcription_result("job-123", object()))
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "completed"
