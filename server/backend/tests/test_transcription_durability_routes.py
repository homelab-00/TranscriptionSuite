"""Tests for transcription durability routes: result, retry, recent, dismiss.

Follows the direct-call pattern from test_job_repository_imports.py:
- monkeypatch repository functions in server.database.job_repository
- monkeypatch get_client_name in server.api.routes.transcription
- invoke async handlers directly with asyncio.run()

This keeps tests fast and dependency-free (no HTTP server, no database).
"""

from __future__ import annotations

import asyncio
import importlib
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from server.api.routes import transcription

# ── Helpers ───────────────────────────────────────────────────────────────────


def _request() -> object:
    """Minimal stand-in for Request when get_client_name is patched."""
    return object()


def _request_with_state(**state_attrs) -> SimpleNamespace:
    """Request stub with app.state — required by the retry success path."""
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**state_attrs)))


class _BgTasksMock:
    """Captures BackgroundTasks.add_task() calls without executing them."""

    def __init__(self):
        self.tasks: list = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append((func, args, kwargs))


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _patch_client_name(monkeypatch):
    """All tests in this module assume the caller is 'test-client'."""
    monkeypatch.setattr(transcription, "get_client_name", lambda _req: "test-client")


@pytest.fixture()
def repo(monkeypatch):
    """Job repository with write-side functions pre-patched to no-ops.

    Individual tests override specific functions as needed.
    """
    r = importlib.import_module("server.database.job_repository")
    monkeypatch.setattr(r, "mark_delivered", lambda _: None)
    monkeypatch.setattr(r, "mark_failed", lambda _id, _msg: None)
    monkeypatch.setattr(r, "reset_for_retry", lambda _: None)
    return r


# ── GET /api/transcribe/result/{job_id} ──────────────────────────────────────


class TestGetTranscriptionResult:
    """Status-code matrix for the result-fetch endpoint."""

    def test_404_when_job_not_found(self, repo, monkeypatch):
        monkeypatch.setattr(repo, "get_job", lambda _: None)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.get_transcription_result("missing", _request()))
        assert exc.value.status_code == 404

    def test_202_while_processing(self, repo, monkeypatch):
        monkeypatch.setattr(
            repo, "get_job", lambda _: {"status": "processing", "client_name": None}
        )

        resp = asyncio.run(transcription.get_transcription_result("job-proc", _request()))

        assert resp.status_code == 202
        body = json.loads(resp.body)
        assert body["status"] == "processing"
        assert body["job_id"] == "job-proc"

    def test_410_for_failed_job_includes_error_message(self, repo, monkeypatch):
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {"status": "failed", "client_name": None, "error_message": "GPU OOM"},
        )

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.get_transcription_result("job-fail", _request()))
        assert exc.value.status_code == 410
        assert "GPU OOM" in exc.value.detail

    def test_200_for_completed_job_returns_result(self, repo, monkeypatch):
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "completed",
                "client_name": None,
                "result_json": '{"text": "hello world"}',
            },
        )

        resp = asyncio.run(transcription.get_transcription_result("job-ok", _request()))

        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["status"] == "completed"
        assert body["result"]["text"] == "hello world"
        assert body["job_id"] == "job-ok"

    def test_200_calls_mark_delivered(self, repo, monkeypatch):
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "completed",
                "client_name": None,
                "result_json": "{}",
            },
        )
        delivered = []
        monkeypatch.setattr(repo, "mark_delivered", lambda job_id: delivered.append(job_id))

        asyncio.run(transcription.get_transcription_result("job-ok", _request()))

        assert delivered == ["job-ok"]

    def test_403_for_different_client(self, repo, monkeypatch):
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "completed",
                "client_name": "other-client",
                "result_json": "{}",
            },
        )

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.get_transcription_result("job-other", _request()))
        assert exc.value.status_code == 403

    def test_200_for_own_client_job(self, repo, monkeypatch):
        """Job with client_name matching the caller is accessible."""
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "completed",
                "client_name": "test-client",
                "result_json": '{"text": "mine"}',
            },
        )

        resp = asyncio.run(transcription.get_transcription_result("job-mine", _request()))

        assert resp.status_code == 200

    def test_200_for_null_result_json_returns_empty_dict(self, repo, monkeypatch):
        """Null result_json should return an empty result dict, not crash."""
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "completed",
                "client_name": None,
                "result_json": None,
            },
        )

        resp = asyncio.run(transcription.get_transcription_result("job-empty", _request()))

        assert resp.status_code == 200
        assert json.loads(resp.body)["result"] == {}

    def test_500_for_corrupt_result_json(self, repo, monkeypatch):
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "completed",
                "client_name": None,
                "result_json": "NOT{JSON",
            },
        )

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.get_transcription_result("job-corrupt", _request()))
        assert exc.value.status_code == 500


# ── POST /api/transcribe/retry/{job_id} ──────────────────────────────────────


class TestRetryTranscription:
    """State machine transitions and precondition checks for the retry endpoint."""

    def test_404_when_job_not_found(self, repo, monkeypatch):
        monkeypatch.setattr(repo, "get_job", lambda _: None)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.retry_transcription("missing", _request(), _BgTasksMock()))
        assert exc.value.status_code == 404

    def test_403_for_different_client(self, repo, monkeypatch):
        monkeypatch.setattr(repo, "get_job", lambda _: {"status": "failed", "client_name": "other"})

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.retry_transcription("job-x", _request(), _BgTasksMock()))
        assert exc.value.status_code == 403

    def test_409_when_already_processing(self, repo, monkeypatch):
        monkeypatch.setattr(
            repo, "get_job", lambda _: {"status": "processing", "client_name": None}
        )

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.retry_transcription("job-proc", _request(), _BgTasksMock()))
        assert exc.value.status_code == 409

    def test_409_when_not_in_failed_state(self, repo, monkeypatch):
        """Retry is only valid for failed jobs; completed jobs must not be retried."""
        monkeypatch.setattr(repo, "get_job", lambda _: {"status": "completed", "client_name": None})

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.retry_transcription("job-done", _request(), _BgTasksMock()))
        assert exc.value.status_code == 409
        assert "failed" in exc.value.detail

    def test_410_when_audio_path_is_none(self, repo, monkeypatch):
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "failed",
                "client_name": None,
                "audio_path": None,
            },
        )

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.retry_transcription("job-na", _request(), _BgTasksMock()))
        assert exc.value.status_code == 410

    def test_410_when_audio_file_missing_from_disk(self, repo, monkeypatch, tmp_path):
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "failed",
                "client_name": None,
                "audio_path": str(tmp_path / "gone.wav"),  # never created
            },
        )

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.retry_transcription("job-nofile", _request(), _BgTasksMock()))
        assert exc.value.status_code == 410

    def test_202_accepted_when_audio_exists(self, repo, monkeypatch, tmp_path):
        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"RIFF")
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "failed",
                "client_name": None,
                "audio_path": str(audio),
            },
        )

        resp = asyncio.run(
            transcription.retry_transcription("job-retry", _request_with_state(), _BgTasksMock())
        )

        assert resp.status_code == 202
        body = json.loads(resp.body)
        assert body["job_id"] == "job-retry"
        assert body["status"] == "processing"

    def test_202_schedules_exactly_one_background_task(self, repo, monkeypatch, tmp_path):
        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"RIFF")
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "failed",
                "client_name": None,
                "audio_path": str(audio),
            },
        )

        bg = _BgTasksMock()
        asyncio.run(transcription.retry_transcription("job-retry", _request_with_state(), bg))

        assert len(bg.tasks) == 1

    def test_reset_for_retry_called_before_background_task(self, repo, monkeypatch, tmp_path):
        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"RIFF")
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "failed",
                "client_name": None,
                "audio_path": str(audio),
            },
        )
        resets = []
        monkeypatch.setattr(repo, "reset_for_retry", lambda job_id: resets.append(job_id))

        asyncio.run(
            transcription.retry_transcription("job-reset", _request_with_state(), _BgTasksMock())
        )

        assert resets == ["job-reset"]


# ── GET /api/transcribe/recent ────────────────────────────────────────────────


class TestGetRecentUndelivered:
    def test_200_empty_list_when_no_undelivered_jobs(self, repo, monkeypatch):
        monkeypatch.setattr(repo, "get_recent_undelivered", lambda _client, limit=5: [])

        resp = asyncio.run(transcription.get_recent_undelivered_results(_request()))

        assert resp.status_code == 200
        assert json.loads(resp.body) == []

    def test_200_returns_job_summary_fields(self, repo, monkeypatch):
        monkeypatch.setattr(
            repo,
            "get_recent_undelivered",
            lambda _client, limit=5: [
                {
                    "id": "job-1",
                    "completed_at": "2026-03-30T12:00:00",
                    "result_json": json.dumps({"text": "Test transcription."}),
                }
            ],
        )

        resp = asyncio.run(transcription.get_recent_undelivered_results(_request()))

        assert resp.status_code == 200
        items = json.loads(resp.body)
        assert len(items) == 1
        assert items[0]["job_id"] == "job-1"
        assert items[0]["completed_at"] == "2026-03-30T12:00:00"
        assert items[0]["text_preview"] == "Test transcription."

    def test_text_preview_capped_at_100_chars(self, repo, monkeypatch):
        long_text = "A" * 200
        monkeypatch.setattr(
            repo,
            "get_recent_undelivered",
            lambda _client, limit=5: [
                {"id": "j", "completed_at": None, "result_json": json.dumps({"text": long_text})}
            ],
        )

        resp = asyncio.run(transcription.get_recent_undelivered_results(_request()))

        items = json.loads(resp.body)
        assert len(items[0]["text_preview"]) == 100

    def test_malformed_result_json_yields_empty_preview(self, repo, monkeypatch):
        """Malformed result_json must not crash the endpoint — return empty preview."""
        monkeypatch.setattr(
            repo,
            "get_recent_undelivered",
            lambda _client, limit=5: [
                {"id": "job-bad", "completed_at": None, "result_json": "NOT_JSON{"}
            ],
        )

        resp = asyncio.run(transcription.get_recent_undelivered_results(_request()))

        assert resp.status_code == 200
        assert json.loads(resp.body)[0]["text_preview"] == ""

    def test_passes_caller_client_name_to_repository(self, repo, monkeypatch):
        """Repository must be queried with the caller's client name, not a hardcoded value."""
        received = []
        monkeypatch.setattr(
            repo,
            "get_recent_undelivered",
            lambda client, limit=5: received.append(client) or [],
        )

        asyncio.run(transcription.get_recent_undelivered_results(_request()))

        assert received == ["test-client"]


# ── POST /api/transcribe/result/{job_id}/dismiss ──────────────────────────────


class TestDismissTranscriptionResult:
    def test_404_when_job_not_found(self, repo, monkeypatch):
        monkeypatch.setattr(repo, "get_job", lambda _: None)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.dismiss_transcription_result("missing", _request()))
        assert exc.value.status_code == 404

    def test_403_for_different_client(self, repo, monkeypatch):
        monkeypatch.setattr(repo, "get_job", lambda _: {"client_name": "other-client"})

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.dismiss_transcription_result("job-other", _request()))
        assert exc.value.status_code == 403

    def test_200_and_marks_delivered_for_own_job(self, repo, monkeypatch):
        monkeypatch.setattr(repo, "get_job", lambda _: {"client_name": "test-client"})
        delivered = []
        monkeypatch.setattr(repo, "mark_delivered", lambda job_id: delivered.append(job_id))

        resp = asyncio.run(transcription.dismiss_transcription_result("job-mine", _request()))

        assert resp.status_code == 200
        assert json.loads(resp.body)["job_id"] == "job-mine"
        assert delivered == ["job-mine"]

    def test_200_when_job_has_null_client_name(self, repo, monkeypatch):
        """Jobs with null client_name are accessible to any authenticated caller."""
        monkeypatch.setattr(repo, "get_job", lambda _: {"client_name": None})

        resp = asyncio.run(transcription.dismiss_transcription_result("job-null", _request()))

        assert resp.status_code == 200
