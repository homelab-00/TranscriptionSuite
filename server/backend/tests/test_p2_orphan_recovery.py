"""Tests for orphan job recovery: startup and periodic sweep.

[P2] Covers:
- P2-ORPH-001: Fast re-crash within timeout window (inside vs outside cutoff)
- P2-ORPH-002: Startup recovery ignores is_busy; periodic sweep respects it

Follows the direct-call pattern: monkeypatch job_repository functions, call
handlers directly via asyncio.run(), assert on side effects.
"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest

# ── Helpers ──────────────────────────────────────────────────────────────────


def _job(job_id: str = "job-1", audio_path: str | None = None) -> dict:
    """Minimal orphaned job dict."""
    return {"id": job_id, "audio_path": audio_path}


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def repo(monkeypatch):
    """Job repository with functions pre-patched to safe defaults."""
    r = importlib.import_module("server.database.job_repository")
    monkeypatch.setattr(r, "get_orphaned_jobs", lambda _timeout: [])
    monkeypatch.setattr(r, "mark_failed", lambda _id, _msg: None)
    return r


@pytest.fixture()
def main_mod():
    """Import the main module containing orphan recovery functions."""
    return importlib.import_module("server.api.main")


# ── P2-ORPH-001: Timeout window boundary ────────────────────────────────────


@pytest.mark.p2
class TestP2Orph001:
    """[P2] Fast re-crash within timeout window."""

    def test_job_inside_timeout_window_not_orphaned(self, repo, main_mod, monkeypatch):
        """A job with created_at INSIDE the timeout window should NOT be
        returned by get_orphaned_jobs, so recover_orphaned_jobs marks nothing."""
        # get_orphaned_jobs returns empty — the job is still within the window
        monkeypatch.setattr(repo, "get_orphaned_jobs", lambda _timeout: [])

        marked: list[str] = []
        monkeypatch.setattr(repo, "mark_failed", lambda jid, _msg: marked.append(jid))

        asyncio.run(main_mod.recover_orphaned_jobs(timeout_minutes=10))

        assert marked == [], "No jobs should be marked failed when none are outside the window"

    def test_job_outside_timeout_window_is_orphaned(self, repo, main_mod, monkeypatch):
        """A job with created_at OUTSIDE the timeout window IS returned by
        get_orphaned_jobs, so recover_orphaned_jobs marks it failed."""
        monkeypatch.setattr(repo, "get_orphaned_jobs", lambda _timeout: [_job("stale-1")])

        marked: list[tuple[str, str]] = []
        monkeypatch.setattr(repo, "mark_failed", lambda jid, msg: marked.append((jid, msg)))

        asyncio.run(main_mod.recover_orphaned_jobs(timeout_minutes=10))

        assert len(marked) == 1
        assert marked[0][0] == "stale-1"
        assert "Server restarted" in marked[0][1]
        assert "audio not preserved" in marked[0][1]

    def test_orphan_with_audio_path_gets_retry_message(self, repo, main_mod, monkeypatch, tmp_path):
        """When audio_path exists on disk, the message mentions retry."""
        audio_file = tmp_path / "recording.wav"
        audio_file.write_bytes(b"RIFF")
        monkeypatch.setattr(
            repo,
            "get_orphaned_jobs",
            lambda _timeout: [_job("audio-1", str(audio_file))],
        )

        marked: list[tuple[str, str]] = []
        monkeypatch.setattr(repo, "mark_failed", lambda jid, msg: marked.append((jid, msg)))

        asyncio.run(main_mod.recover_orphaned_jobs(timeout_minutes=10))

        assert len(marked) == 1
        assert "retry" in marked[0][1].lower()


# ── Deferred: Empty job ID edge case ────────────────────────────────────────


@pytest.mark.p2
class TestOrphanEmptyJobId:
    """Edge case: orphan row with id=None → mark_failed("") is called."""

    def test_orphan_with_none_id_calls_mark_failed_with_empty_string(
        self, repo, main_mod, monkeypatch
    ):
        """When DB returns an orphan row whose 'id' is None (or missing),
        recover_orphaned_jobs defaults to '' and calls mark_failed('')."""
        # Simulate a DB row missing the "id" key entirely
        monkeypatch.setattr(repo, "get_orphaned_jobs", lambda _timeout: [{"audio_path": None}])

        marked: list[tuple[str, str]] = []
        monkeypatch.setattr(repo, "mark_failed", lambda jid, msg: marked.append((jid, msg)))

        asyncio.run(main_mod.recover_orphaned_jobs(timeout_minutes=10))

        assert len(marked) == 1
        assert marked[0][0] == "", "job_id should be empty string from .get('id', '')"

    def test_orphan_with_explicit_none_id(self, repo, main_mod, monkeypatch):
        """When DB returns id=None explicitly, .get('id', '') returns None
        (not the default), so mark_failed(None, ...) is called."""
        # dict.get("id", "") returns None when key exists but value is None
        monkeypatch.setattr(
            repo, "get_orphaned_jobs", lambda _timeout: [{"id": None, "audio_path": None}]
        )

        marked: list[tuple] = []
        monkeypatch.setattr(repo, "mark_failed", lambda jid, msg: marked.append((jid, msg)))

        asyncio.run(main_mod.recover_orphaned_jobs(timeout_minutes=10))

        assert len(marked) == 1
        # dict.get returns None when key exists with value None — the default is NOT used
        assert marked[0][0] is None


# ── P2-ORPH-002: Startup vs periodic sweep is_busy behaviour ────────────────


@pytest.mark.p2
class TestP2Orph002:
    """[P2] Startup recovery ignores is_busy; periodic sweep respects it."""

    def test_startup_recovery_marks_failed_even_when_tracker_busy(
        self, repo, main_mod, monkeypatch
    ):
        """recover_orphaned_jobs (startup) does NOT check job_tracker.is_busy
        — it marks orphaned jobs as failed regardless."""
        monkeypatch.setattr(repo, "get_orphaned_jobs", lambda _timeout: [_job("orphan-startup")])

        marked: list[str] = []
        monkeypatch.setattr(repo, "mark_failed", lambda jid, _msg: marked.append(jid))

        # recover_orphaned_jobs has no job_tracker param — it always proceeds
        asyncio.run(main_mod.recover_orphaned_jobs(timeout_minutes=10))

        assert marked == ["orphan-startup"]

    def test_periodic_sweep_skips_when_tracker_busy(self, repo, main_mod, monkeypatch):
        """periodic_orphan_sweep skips marking when job_tracker.is_busy()
        returns True, protecting active long-running sessions."""
        # Return an orphan so that if the sweep does NOT skip, it would mark it
        monkeypatch.setattr(repo, "get_orphaned_jobs", lambda _timeout: [_job("should-skip")])

        marked: list[str] = []
        monkeypatch.setattr(repo, "mark_failed", lambda jid, _msg: marked.append(jid))

        busy_tracker = SimpleNamespace(is_busy=lambda: (True, "active-user"))

        # We need the sweep to execute one iteration then stop.
        # Patch asyncio.sleep to raise CancelledError after the first call,
        # simulating one sweep cycle.
        call_count = 0

        async def _fake_sleep(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError

        monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

        # periodic_orphan_sweep catches CancelledError and returns cleanly
        asyncio.run(
            main_mod.periodic_orphan_sweep(
                timeout_minutes=10,
                interval_minutes=1,
                job_tracker=busy_tracker,
            )
        )

        assert marked == [], "Sweep should skip marking when tracker is busy"
