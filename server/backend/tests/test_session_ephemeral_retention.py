"""Tests for session ephemeral retention (2026-08-09 spec).

Covers the repository purge primitives (delete_job, backstop queries,
legacy-row query) and the extended cleanup task. Uses a real temporary
SQLite DB via the same get_connection monkeypatch pattern as
test_job_repository_imports.py.
"""

from __future__ import annotations

import importlib
import sqlite3
from contextlib import contextmanager

import pytest

repo = importlib.import_module("server.database.job_repository")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Real SQLite DB with the transcription_jobs columns this feature touches.

    Re-resolves the repo module on every use: test_job_repository_imports pops
    server.database.job_repository from sys.modules and re-imports it, so a
    handle captured at collection time can diverge from the object that
    audio_cleanup's function-local imports resolve. Patching the CURRENT
    module (and rebinding the test-module global) keeps both call paths on
    the same patched get_connection.
    """
    global repo
    repo = importlib.import_module("server.database.job_repository")
    db_path = tmp_path / "jobs.db"
    # check_same_thread=False: cleanup_old_recordings runs repo queries via
    # asyncio.to_thread; production get_connection opens per-call connections.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE transcription_jobs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'processing',
            source TEXT,
            client_name TEXT,
            language TEXT,
            task TEXT,
            translation_target TEXT,
            job_profile_snapshot TEXT,
            snapshot_schema_version TEXT,
            audio_hash TEXT,
            normalized_audio_hash TEXT,
            audio_path TEXT,
            result_text TEXT,
            result_json TEXT,
            result_language TEXT,
            duration_seconds REAL,
            error_message TEXT,
            delivered INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
        """
    )
    conn.commit()

    @contextmanager
    def _get_connection():
        yield conn

    monkeypatch.setattr(repo, "get_connection", _get_connection)
    yield conn
    conn.close()


def _insert(
    conn,
    job_id: str,
    *,
    source: str = "file_import",
    status: str = "processing",
    delivered: int = 0,
    audio_path: str | None = None,
    result_text: str | None = None,
    created_at: str = "2020-01-01 00:00:00",
    completed_at: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO transcription_jobs
            (id, status, source, delivered, audio_path, result_text,
             created_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (job_id, status, source, delivered, audio_path, result_text, created_at, completed_at),
    )
    conn.commit()


def _row(conn, job_id: str):
    return conn.execute("SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)).fetchone()


class TestDeleteJob:
    def test_deletes_row_and_audio_file(self, db, tmp_path):
        wav = tmp_path / "job1.wav"
        wav.write_bytes(b"RIFF")
        _insert(db, "job1", audio_path=str(wav))

        repo.delete_job("job1")

        assert _row(db, "job1") is None
        assert not wav.exists()

    def test_missing_audio_file_still_deletes_row(self, db, tmp_path):
        _insert(db, "job2", audio_path=str(tmp_path / "gone.wav"))

        repo.delete_job("job2")

        assert _row(db, "job2") is None

    def test_null_audio_path_deletes_row(self, db):
        _insert(db, "job3", audio_path=None)

        repo.delete_job("job3")

        assert _row(db, "job3") is None

    def test_nonexistent_job_is_noop(self, db):
        repo.delete_job("missing")  # must not raise

    def test_never_raises_on_db_error(self, monkeypatch):
        @contextmanager
        def _broken():
            raise RuntimeError("db locked")
            yield  # pragma: no cover

        monkeypatch.setattr(repo, "get_connection", _broken)
        repo.delete_job("whatever")  # must not raise


class TestSessionSources:
    def test_exactly_websocket_and_file_import(self):
        assert set(repo.SESSION_SOURCES) == {"websocket", "file_import"}


class TestGetPurgeableSessionJobs:
    def test_returns_old_delivered_session_rows_only(self, db):
        _insert(
            db,
            "ws-old",
            source="websocket",
            status="completed",
            delivered=1,
            completed_at="2020-01-01T00:00:00+00:00",
        )
        _insert(
            db,
            "imp-old",
            source="file_import",
            status="completed",
            delivered=1,
            completed_at="2020-01-02T00:00:00+00:00",
        )
        # Excluded: wrong source, undelivered, failed, too recent
        _insert(
            db,
            "upload-old",
            source="audio_upload",
            status="completed",
            delivered=1,
            completed_at="2020-01-01T00:00:00+00:00",
        )
        _insert(
            db,
            "ws-undelivered",
            source="websocket",
            status="completed",
            delivered=0,
            completed_at="2020-01-01T00:00:00+00:00",
        )
        _insert(db, "ws-failed", source="websocket", status="failed", delivered=0)
        _insert(
            db,
            "ws-recent",
            source="websocket",
            status="completed",
            delivered=1,
            completed_at="2099-01-01T00:00:00+00:00",
        )

        ids = {j["id"] for j in repo.get_purgeable_session_jobs(max_age_days=7)}

        assert ids == {"ws-old", "imp-old"}


class TestGetStaleFailedImports:
    def test_returns_only_aged_failed_imports_without_audio(self, db, tmp_path):
        _insert(
            db,
            "imp-fail-old",
            source="file_import",
            status="failed",
            created_at="2020-01-01 00:00:00",
        )
        # Excluded: has audio (hypothetical future), wrong source, recent, not failed
        _insert(
            db,
            "imp-fail-audio",
            source="file_import",
            status="failed",
            audio_path=str(tmp_path / "kept.wav"),
            created_at="2020-01-01 00:00:00",
        )
        _insert(
            db, "ws-fail-old", source="websocket", status="failed", created_at="2020-01-01 00:00:00"
        )
        _insert(
            db,
            "imp-fail-recent",
            source="file_import",
            status="failed",
            created_at="2099-01-01 00:00:00",
        )
        _insert(
            db,
            "imp-done",
            source="file_import",
            status="completed",
            created_at="2020-01-01 00:00:00",
        )

        ids = {j["id"] for j in repo.get_stale_failed_imports(max_age_days=7)}

        assert ids == {"imp-fail-old"}


class TestGetLegacySessionRows:
    def test_returns_bare_anchors_and_delivered_session_rows(self, db, tmp_path):
        # Bare /import dedup anchors — any status, no result, no audio
        _insert(db, "anchor-proc", source="file_import", status="processing")
        _insert(db, "anchor-failed", source="file_import", status="failed")
        # Delivered session rows
        _insert(
            db,
            "ws-done",
            source="websocket",
            status="completed",
            delivered=1,
            result_text="hello",
            audio_path=str(tmp_path / "a.wav"),
        )
        _insert(
            db,
            "imp-done",
            source="file_import",
            status="completed",
            delivered=1,
            result_text="hello",
        )
        # Kept: undelivered / failed-with-content / non-session
        _insert(
            db,
            "ws-undelivered",
            source="websocket",
            status="completed",
            delivered=0,
            result_text="precious",
        )
        _insert(
            db,
            "ws-failed-wav",
            source="websocket",
            status="failed",
            audio_path=str(tmp_path / "b.wav"),
        )
        _insert(
            db,
            "upload-done",
            source="audio_upload",
            status="completed",
            delivered=1,
            result_text="hello",
        )

        ids = {j["id"] for j in repo.get_legacy_session_rows()}

        assert ids == {"anchor-proc", "anchor-failed", "ws-done", "imp-done"}


class TestCleanupOldRecordingsPurgesRows:
    @staticmethod
    def _run(max_age_days: int = 7) -> None:
        import asyncio

        from server.database import audio_cleanup

        asyncio.run(audio_cleanup.cleanup_old_recordings("/data/recordings", max_age_days))

    def test_purges_aged_delivered_session_rows(self, db, tmp_path):
        wav = tmp_path / "ws.wav"
        wav.write_bytes(b"RIFF")
        _insert(
            db,
            "ws-old",
            source="websocket",
            status="completed",
            delivered=1,
            audio_path=str(wav),
            completed_at="2020-01-01T00:00:00+00:00",
        )

        self._run()

        assert _row(db, "ws-old") is None
        assert not wav.exists()

    def test_purges_aged_failed_imports(self, db):
        _insert(
            db,
            "imp-fail-old",
            source="file_import",
            status="failed",
            created_at="2020-01-01 00:00:00",
        )

        self._run()

        assert _row(db, "imp-fail-old") is None

    def test_keeps_non_session_rows_deletes_only_their_audio(self, db, tmp_path):
        wav = tmp_path / "up.wav"
        wav.write_bytes(b"RIFF")
        _insert(
            db,
            "upload-old",
            source="audio_upload",
            status="completed",
            delivered=1,
            audio_path=str(wav),
            completed_at="2020-01-01T00:00:00+00:00",
        )

        self._run()

        assert _row(db, "upload-old") is not None  # row kept (status quo)
        assert not wav.exists()  # WAV still garbage-collected

    def test_keeps_failed_websocket_rows(self, db, tmp_path):
        wav = tmp_path / "retryable.wav"
        wav.write_bytes(b"RIFF")
        _insert(
            db,
            "ws-failed",
            source="websocket",
            status="failed",
            audio_path=str(wav),
            created_at="2020-01-01 00:00:00",
        )

        self._run()

        assert _row(db, "ws-failed") is not None
        assert wav.exists()

    def test_retention_zero_skips_everything(self, db):
        _insert(
            db,
            "ws-old",
            source="websocket",
            status="completed",
            delivered=1,
            completed_at="2020-01-01T00:00:00+00:00",
        )

        self._run(max_age_days=0)

        assert _row(db, "ws-old") is not None


class TestPurgeLegacySessionRows:
    def test_purges_anchors_and_delivered_rows_keeps_the_rest(self, db, tmp_path):
        import asyncio

        from server.database import audio_cleanup

        wav = tmp_path / "done.wav"
        wav.write_bytes(b"RIFF")
        _insert(db, "anchor", source="file_import", status="failed")
        _insert(
            db,
            "ws-done",
            source="websocket",
            status="completed",
            delivered=1,
            result_text="x",
            audio_path=str(wav),
        )
        _insert(
            db,
            "ws-undelivered",
            source="websocket",
            status="completed",
            delivered=0,
            result_text="precious",
        )

        asyncio.run(audio_cleanup.purge_legacy_session_rows())

        assert _row(db, "anchor") is None
        assert _row(db, "ws-done") is None
        assert not wav.exists()
        assert _row(db, "ws-undelivered") is not None
