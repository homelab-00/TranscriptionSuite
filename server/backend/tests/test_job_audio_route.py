"""Tests for GET /api/transcribe/audio/{job_id} - downloading a job's source WAV.

The route exists so a user can keep the recording itself when transcription
dies (e.g. a GPU OOM), instead of being left with nothing. That makes two
properties load-bearing:

- it is a PURE READ - it must never mark the job delivered and never purge it,
  or the Save Audio button would destroy the very thing it saves;
- its Content-Disposition must survive Uvicorn's Latin-1 header encoding, so
  non-ASCII (Greek) names still download (Issue #106).

Follows the direct-call pattern from test_transcription_durability_routes.py:
- monkeypatch repository functions in server.database.job_repository
- monkeypatch get_client_name in server.api.routes.transcription
- invoke async handlers directly with asyncio.run()
"""

from __future__ import annotations

import asyncio
import importlib
import inspect

import pytest
from fastapi import HTTPException
from server.api.routes import _http_utils, notebook, transcription

# ── Helpers ───────────────────────────────────────────────────────────────────


def _request() -> object:
    """Minimal stand-in for Request when get_client_name is patched."""
    return object()


def _wav(tmp_path, name: str = "saved.wav"):
    """Write a real (tiny) file so Path.exists() and FileResponse are honest."""
    audio = tmp_path / name
    audio.write_bytes(b"RIFF____WAVEfmt ")
    return audio


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _patch_client_name(monkeypatch):
    """All tests in this module assume the caller is 'test-client'."""
    monkeypatch.setattr(transcription, "get_client_name", lambda _req: "test-client")


@pytest.fixture()
def repo(monkeypatch):
    """Job repository whose destructive functions blow up if the route calls them.

    The route is a pure read; any write reaching the repository is a bug, so the
    default stubs fail loudly rather than silently succeeding.
    """
    r = importlib.import_module("server.database.job_repository")

    def _forbidden(name):
        def _boom(*_args, **_kwargs):
            raise AssertionError(f"{name} must never be called by the audio download route")

        return _boom

    monkeypatch.setattr(r, "mark_delivered", _forbidden("mark_delivered"))
    monkeypatch.setattr(r, "delete_job", _forbidden("delete_job"))
    return r


# ── Status-code matrix ────────────────────────────────────────────────────────


class TestRouteRegistration:
    def test_mounted_at_api_transcribe_audio_job_id(self):
        """The dashboard is written against this exact URL - pin it here.

        The router is mounted with prefix="/api/transcribe" in api/main.py, so
        the full path is GET /api/transcribe/audio/{job_id}.
        """
        matches = [
            r
            for r in transcription.router.routes
            if getattr(r, "endpoint", None) is transcription.get_job_audio
        ]
        assert len(matches) == 1
        assert matches[0].path == "/audio/{job_id}"
        assert matches[0].methods == {"GET"}


class TestGetJobAudio:
    def test_404_when_job_not_found(self, repo, monkeypatch):
        monkeypatch.setattr(repo, "get_job", lambda _: None)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.get_job_audio("missing", _request()))
        assert exc.value.status_code == 404
        assert exc.value.detail == "Job not found"

    def test_403_for_different_client(self, repo, monkeypatch, tmp_path):
        audio = _wav(tmp_path)
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "failed",
                "client_name": "other-client",
                "audio_path": str(audio),
            },
        )

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.get_job_audio("job-other", _request()))
        assert exc.value.status_code == 403
        assert exc.value.detail == "Access denied"

    def test_200_for_job_with_null_client_name(self, repo, monkeypatch, tmp_path):
        """A null client_name means the job is not owned - any caller may fetch it."""
        audio = _wav(tmp_path)
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {"status": "failed", "client_name": None, "audio_path": str(audio)},
        )

        resp = asyncio.run(transcription.get_job_audio("job-null", _request()))

        assert resp.status_code == 200

    def test_410_when_audio_was_never_preserved(self, repo, monkeypatch):
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {"status": "failed", "client_name": None, "audio_path": None},
        )

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.get_job_audio("job-na", _request()))
        assert exc.value.status_code == 410
        assert exc.value.detail == "Audio was not preserved for this job - cannot download"

    def test_410_when_tmp_path_lost_on_restart(self, repo, monkeypatch):
        """A /tmp path that no longer exists gets its own diagnosable message."""
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "failed",
                "client_name": None,
                "audio_path": "/tmp/does-not-exist-4c1f/session.wav",
            },
        )

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.get_job_audio("job-tmp", _request()))
        assert exc.value.status_code == 410
        assert "temporary storage (/tmp)" in exc.value.detail
        assert "lost on server restart" in exc.value.detail
        assert exc.value.detail.endswith("cannot download")

    def test_410_when_audio_file_deleted(self, repo, monkeypatch):
        # Deliberately NOT tmp_path: pytest puts tmp_path under /tmp on Linux,
        # which would land in the "lost on server restart" branch instead. This
        # path is only ever read via Path.exists() - nothing is written.
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "failed",
                "client_name": None,
                "audio_path": "/var/lib/transcriptionsuite-does-not-exist/gone.wav",
            },
        )

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.get_job_audio("job-gone", _request()))
        assert exc.value.status_code == 410
        assert exc.value.detail == "Audio file has been deleted - cannot download"

    def test_200_returns_the_wav_as_a_file_response(self, repo, monkeypatch, tmp_path):
        audio = _wav(tmp_path)
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "failed",
                "client_name": "test-client",
                "audio_path": str(audio),
                "created_at": "2026-09-04 13:45:07",
            },
        )

        resp = asyncio.run(transcription.get_job_audio("job-ok", _request()))

        assert resp.status_code == 200
        assert str(resp.path) == str(audio)
        assert resp.media_type == "audio/wav"
        assert (
            resp.headers["content-disposition"]
            == 'attachment; filename="transcription-20260904-134507-job-ok.wav"; '
            "filename*=UTF-8''transcription-20260904-134507-job-ok.wav"
        )

    def test_200_filename_falls_back_when_created_at_is_unusable(self, repo, monkeypatch, tmp_path):
        """An absent or unparsable created_at must degrade, never raise."""
        audio = _wav(tmp_path)
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "failed",
                "client_name": None,
                "audio_path": str(audio),
                "created_at": "not a timestamp",
            },
        )

        resp = asyncio.run(transcription.get_job_audio("job-nots", _request()))

        assert 'filename="transcription-job-nots.wav"' in resp.headers["content-disposition"]

    def test_served_as_an_attachment_not_an_inline_player_source(self, repo, monkeypatch, tmp_path):
        """This is a download, not a seekable player.

        The notebook recordings route serves `inline` because a browser audio
        element streams from it. This one exists so the user can keep the file,
        so it must arrive as an attachment with a filename, and the route adds
        no Range handling of its own. (Starlette's FileResponse still advertises
        accept-ranges itself; that comes from the framework, not from here.)
        """
        audio = _wav(tmp_path)
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {"status": "failed", "client_name": None, "audio_path": str(audio)},
        )

        resp = asyncio.run(transcription.get_job_audio("job-nr", _request()))

        assert resp.status_code == 200
        disposition = resp.headers["content-disposition"]
        assert disposition.startswith("attachment;")
        assert "inline" not in disposition
        # The route's own source carries no Range/206 branch at all.
        source = inspect.getsource(transcription.get_job_audio)
        assert "206" not in source
        assert "Range" not in source


# ── Issue #106 regression guard: Greek names survive Latin-1 headers ──────────


class TestContentDispositionEncoding:
    def test_greek_name_survives_latin1_header_encoding(self, repo, monkeypatch, tmp_path):
        """Uvicorn encodes header values as Latin-1; a raw Greek name would explode."""
        audio = _wav(tmp_path)
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {"status": "failed", "client_name": None, "audio_path": str(audio)},
        )

        resp = asyncio.run(transcription.get_job_audio("συνεδρία-α1", _request()))

        header = resp.headers["content-disposition"]
        header.encode("latin-1")  # exactly what Uvicorn does - must not raise
        assert "filename*=UTF-8''" in header
        assert header.startswith("attachment; ")
        # The percent-encoded form carries the real Greek name.
        assert "%CF%83%CF%85%CE%BD%CE%B5%CE%B4%CF%81%CE%AF%CE%B1" in header

    def test_helper_is_shared_not_copied(self):
        """notebook must import the helper, not keep a second definition of it."""
        assert notebook._content_disposition is _http_utils._content_disposition
        assert notebook._ASCII_FALLBACK_REPLACE is _http_utils._ASCII_FALLBACK_REPLACE


# ── The download must never consume the thing it downloads ───────────────────


class TestDownloadIsAPureRead:
    """The most important test in this file.

    delete_job unlinks the WAV as well as deleting the row, and mark_delivered
    makes the job sweepable by the retention task. If the download route ever
    calls either, saving the audio would be what destroys it.
    """

    def test_does_not_mark_delivered_or_purge_and_leaves_the_wav_on_disk(
        self, repo, monkeypatch, tmp_path
    ):
        audio = _wav(tmp_path)
        calls: list[str] = []
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "failed",
                "client_name": "test-client",
                "source": "websocket",
                "audio_path": str(audio),
                "created_at": "2026-09-04 13:45:07",
            },
        )
        # Record instead of raise, so a regression reports *which* call happened.
        monkeypatch.setattr(repo, "mark_delivered", lambda jid: calls.append(f"delivered:{jid}"))
        monkeypatch.setattr(repo, "delete_job", lambda jid: calls.append(f"deleted:{jid}"))

        resp = asyncio.run(transcription.get_job_audio("job-keep", _request()))

        assert resp.status_code == 200
        assert calls == []
        assert audio.exists(), "the source WAV must still be on disk after a download"
        assert audio.read_bytes() == b"RIFF____WAVEfmt "

    def test_repeated_downloads_stay_available(self, repo, monkeypatch, tmp_path):
        """A second download must work - the first one consumed nothing."""
        audio = _wav(tmp_path)
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {"status": "failed", "client_name": None, "audio_path": str(audio)},
        )

        first = asyncio.run(transcription.get_job_audio("job-twice", _request()))
        second = asyncio.run(transcription.get_job_audio("job-twice", _request()))

        assert first.status_code == 200
        assert second.status_code == 200
        assert audio.exists()


# ── Filename builder unit tests ───────────────────────────────────────────────


class TestJobAudioFilename:
    @pytest.mark.parametrize(
        "created_at",
        [None, "", "not a timestamp", "2026-13-45 99:99:99", 0, object()],
    )
    def test_parse_is_total(self, created_at):
        """No created_at value may ever raise - a bad timestamp must not block a save."""
        assert transcription._job_audio_filename("abc", created_at) == "transcription-abc.wav"

    def test_sqlite_current_timestamp_form(self):
        """created_at is written by SQLite CURRENT_TIMESTAMP (space separator)."""
        assert (
            transcription._job_audio_filename("abc", "2026-09-04 13:45:07")
            == "transcription-20260904-134507-abc.wav"
        )

    def test_isoformat_form(self):
        """Legacy/hand-written rows may hold an isoformat string instead."""
        assert (
            transcription._job_audio_filename("abc", "2026-09-04T13:45:07+00:00")
            == "transcription-20260904-134507-abc.wav"
        )
