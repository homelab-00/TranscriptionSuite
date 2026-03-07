"""Tests for TranscriptionJobTracker — pure state machine, no ML dependencies.

Covers:
- ``try_start_job`` success and mutual exclusion
- ``end_job`` matching and mismatching IDs
- ``cancel_job`` / ``is_cancelled`` round-trip
- ``is_busy`` state tracking
- ``update_progress`` / ``clear_progress``
- ``get_status`` dict structure
- Result storage and clearing across jobs
- Thread safety under concurrent access
"""

from __future__ import annotations

import threading

from server.core.model_manager import TranscriptionJobTracker

# ── try_start_job ─────────────────────────────────────────────────────────


class TestTryStartJob:
    def test_first_job_succeeds(self):
        tracker = TranscriptionJobTracker()

        success, job_id, busy_user = tracker.try_start_job("alice")

        assert success is True
        assert job_id is not None
        assert busy_user is None

    def test_second_job_rejected_while_first_active(self):
        tracker = TranscriptionJobTracker()
        tracker.try_start_job("alice")

        success, job_id, busy_user = tracker.try_start_job("bob")

        assert success is False
        assert job_id is None
        assert busy_user == "alice"

    def test_job_id_is_uuid_format(self):
        tracker = TranscriptionJobTracker()

        _, job_id, _ = tracker.try_start_job("alice")

        # UUID4 format: 8-4-4-4-12 hex chars
        parts = job_id.split("-")
        assert len(parts) == 5
        assert [len(p) for p in parts] == [8, 4, 4, 4, 12]

    def test_same_user_cannot_start_two_jobs(self):
        tracker = TranscriptionJobTracker()
        tracker.try_start_job("alice")

        success, _, busy_user = tracker.try_start_job("alice")

        assert success is False
        assert busy_user == "alice"


# ── end_job ───────────────────────────────────────────────────────────────


class TestEndJob:
    def test_end_matching_job_returns_true(self):
        tracker = TranscriptionJobTracker()
        _, job_id, _ = tracker.try_start_job("alice")

        result = tracker.end_job(job_id)

        assert result is True

    def test_end_mismatching_job_returns_false(self):
        tracker = TranscriptionJobTracker()
        tracker.try_start_job("alice")

        result = tracker.end_job("wrong-id")

        assert result is False

    def test_end_allows_new_job(self):
        tracker = TranscriptionJobTracker()
        _, job_id, _ = tracker.try_start_job("alice")
        tracker.end_job(job_id)

        success, new_id, _ = tracker.try_start_job("bob")

        assert success is True
        assert new_id is not None
        assert new_id != job_id

    def test_end_stores_result(self):
        tracker = TranscriptionJobTracker()
        _, job_id, _ = tracker.try_start_job("alice")
        result_data = {"recording_id": 42, "job_id": job_id}

        tracker.end_job(job_id, result=result_data)

        status = tracker.get_status()
        assert status["result"] == result_data

    def test_end_clears_cancelled_flag(self):
        tracker = TranscriptionJobTracker()
        _, job_id, _ = tracker.try_start_job("alice")
        tracker.cancel_job()

        tracker.end_job(job_id)

        assert tracker.is_cancelled() is False

    def test_end_clears_progress(self):
        tracker = TranscriptionJobTracker()
        _, job_id, _ = tracker.try_start_job("alice")
        tracker.update_progress(5, 10, "halfway")

        tracker.end_job(job_id)

        status = tracker.get_status()
        assert status["progress"] is None


# ── cancel_job ────────────────────────────────────────────────────────────


class TestCancelJob:
    def test_cancel_active_job_succeeds(self):
        tracker = TranscriptionJobTracker()
        tracker.try_start_job("alice")

        success, user = tracker.cancel_job()

        assert success is True
        assert user == "alice"

    def test_cancel_no_job_fails(self):
        tracker = TranscriptionJobTracker()

        success, user = tracker.cancel_job()

        assert success is False
        assert user is None

    def test_is_cancelled_after_cancel(self):
        tracker = TranscriptionJobTracker()
        tracker.try_start_job("alice")

        tracker.cancel_job()

        assert tracker.is_cancelled() is True

    def test_is_cancelled_false_initially(self):
        tracker = TranscriptionJobTracker()
        tracker.try_start_job("alice")

        assert tracker.is_cancelled() is False

    def test_new_job_resets_cancelled_flag(self):
        """Starting a new job after ending a cancelled one resets the flag."""
        tracker = TranscriptionJobTracker()
        _, job_id, _ = tracker.try_start_job("alice")
        tracker.cancel_job()
        tracker.end_job(job_id)

        tracker.try_start_job("bob")

        assert tracker.is_cancelled() is False


# ── is_busy ───────────────────────────────────────────────────────────────


class TestIsBusy:
    def test_not_busy_initially(self):
        tracker = TranscriptionJobTracker()

        busy, user = tracker.is_busy()

        assert busy is False
        assert user is None

    def test_busy_while_job_active(self):
        tracker = TranscriptionJobTracker()
        tracker.try_start_job("alice")

        busy, user = tracker.is_busy()

        assert busy is True
        assert user == "alice"

    def test_not_busy_after_job_ends(self):
        tracker = TranscriptionJobTracker()
        _, job_id, _ = tracker.try_start_job("alice")
        tracker.end_job(job_id)

        busy, user = tracker.is_busy()

        assert busy is False
        assert user is None


# ── update_progress / clear_progress ──────────────────────────────────────


class TestProgress:
    def test_update_progress_visible_in_status(self):
        tracker = TranscriptionJobTracker()
        tracker.try_start_job("alice")

        tracker.update_progress(3, 10, "processing chunk 3")

        status = tracker.get_status()
        assert status["progress"] == {
            "current": 3,
            "total": 10,
            "message": "processing chunk 3",
        }

    def test_clear_progress(self):
        tracker = TranscriptionJobTracker()
        tracker.try_start_job("alice")
        tracker.update_progress(5, 10)

        tracker.clear_progress()

        status = tracker.get_status()
        assert status["progress"] is None

    def test_progress_default_message_empty(self):
        tracker = TranscriptionJobTracker()
        tracker.try_start_job("alice")

        tracker.update_progress(1, 5)

        status = tracker.get_status()
        assert status["progress"]["message"] == ""


# ── get_status ────────────────────────────────────────────────────────────


class TestGetStatus:
    def test_idle_status_structure(self):
        tracker = TranscriptionJobTracker()

        status = tracker.get_status()

        assert status == {
            "is_busy": False,
            "active_user": None,
            "active_job_id": None,
            "cancellation_requested": False,
            "progress": None,
            "result": None,
        }

    def test_active_status_truncates_job_id(self):
        tracker = TranscriptionJobTracker()
        _, job_id, _ = tracker.try_start_job("alice")

        status = tracker.get_status()

        assert status["is_busy"] is True
        assert status["active_user"] == "alice"
        assert status["active_job_id"] == job_id[:8]
        assert status["cancellation_requested"] is False

    def test_status_reflects_cancellation(self):
        tracker = TranscriptionJobTracker()
        tracker.try_start_job("alice")
        tracker.cancel_job()

        status = tracker.get_status()

        assert status["cancellation_requested"] is True

    def test_result_cleared_on_new_job(self):
        """Starting a new job clears the previous job's result."""
        tracker = TranscriptionJobTracker()
        _, job_id, _ = tracker.try_start_job("alice")
        tracker.end_job(job_id, result={"recording_id": 1})

        tracker.try_start_job("bob")

        status = tracker.get_status()
        assert status["result"] is None


# ── Thread safety ─────────────────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_start_only_one_wins(self):
        """Only one of N concurrent try_start_job calls should succeed."""
        tracker = TranscriptionJobTracker()
        results: list[tuple[bool, str | None, str | None]] = []
        lock = threading.Lock()

        def attempt(user: str):
            r = tracker.try_start_job(user)
            with lock:
                results.append(r)

        threads = [threading.Thread(target=attempt, args=(f"user-{i}",)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        winners = [r for r in results if r[0] is True]
        losers = [r for r in results if r[0] is False]

        assert len(winners) == 1
        assert len(losers) == 19

    def test_concurrent_cancel_is_safe(self):
        """Multiple threads cancelling simultaneously should not raise."""
        tracker = TranscriptionJobTracker()
        tracker.try_start_job("alice")
        errors: list[Exception] = []

        def cancel():
            try:
                tracker.cancel_job()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=cancel) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []

    def test_concurrent_status_reads_are_safe(self):
        """Reading status while jobs start/end should not raise."""
        tracker = TranscriptionJobTracker()
        errors: list[Exception] = []
        stop = threading.Event()

        def read_status():
            while not stop.is_set():
                try:
                    tracker.get_status()
                except Exception as e:
                    errors.append(e)

        def start_end_jobs():
            for i in range(50):
                ok, jid, _ = tracker.try_start_job(f"user-{i}")
                if ok:
                    tracker.end_job(jid)

        readers = [threading.Thread(target=read_status) for _ in range(5)]
        writer = threading.Thread(target=start_end_jobs)

        for r in readers:
            r.start()
        writer.start()

        writer.join()
        stop.set()
        for r in readers:
            r.join()

        assert errors == []
