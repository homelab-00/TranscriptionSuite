# Session Ephemeral Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Session-tab transcriptions (mic + file imports) leave no server-side trace once confirmed delivered; the duplicate dialog never appears in any Session flow; the `/import` durability bug is fixed.

**Architecture:** Extend the existing durability pipeline (`transcription_jobs` table) with a post-delivery purge step scoped to session sources (`'websocket'`, `'file_import'`). The `/import` worker joins the persist-before-deliver pipeline (`save_result`/`mark_failed`); the dashboard polls `GET /api/transcribe/result/{job_id}` instead of scraping the in-memory job tracker. Dedup hashing is removed from `/import` entirely. A backstop sweep and a one-time startup cleanup catch stragglers and legacy rows.

**Tech Stack:** FastAPI + SQLite (server/backend), Zustand + vitest (dashboard), pytest via the build venv.

**Spec:** `docs/superpowers/specs/2026-08-09-session-ephemeral-retention-design.md`

**Branch:** `feat/session-ephemeral-retention` (already created; the spec is committed there).

---

## Ground rules for the executor

- Backend tests: `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` — always finish with the FULL suite, not just the new files.
- Dashboard tests need Node 22: `cd dashboard && nvm use && npx vitest run src/stores/importQueueStore.test.ts`.
- Per CLAUDE.md: run GitNexus `impact` before editing each symbol, `detect_changes` before each commit. No AI attribution anywhere. Commit style: `type(area): summary` + bullet body, long lines NOT broken.
- The three WS session test-factories break on new session **attributes** — this plan deliberately adds none (purge state is method-local).
- `server/backend/api/routes/transcription.py` already imports at module top: `create_job`, `save_result`, `mark_failed`, `find_duplicates_anywhere`, `sanitize_for_json`, `_json`, `sanitize_log_value`. Verify with grep before adding duplicate imports.

---

### Task 1: `delete_job` + `SESSION_SOURCES` in the job repository

**Files:**
- Modify: `server/backend/database/job_repository.py`
- Test: `server/backend/tests/test_session_ephemeral_retention.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `server/backend/tests/test_session_ephemeral_retention.py`:

```python
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
from pathlib import Path

import pytest

repo = importlib.import_module("server.database.job_repository")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Real SQLite DB with the transcription_jobs columns this feature touches."""
    db_path = tmp_path / "jobs.db"
    conn = sqlite3.connect(db_path)
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
    return conn.execute(
        "SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)
    ).fetchone()


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_session_ephemeral_retention.py -v --tb=short`
Expected: FAIL — `AttributeError: module ... has no attribute 'delete_job'` / `'SESSION_SOURCES'`.

- [ ] **Step 3: Implement in `job_repository.py`**

Add `from pathlib import Path` to the module imports. After `get_jobs_for_cleanup`, add:

```python
# ─── Session ephemeral retention (2026-08-09 spec) ───────────────────────────

# Sources whose rows are purged after confirmed delivery. Rows from any other
# source (e.g. 'audio_upload', notebook uploads) are NEVER purged — only these
# two values may ever reach delete_job via the session lifecycle.
SESSION_SOURCES = ("websocket", "file_import")


def delete_job(job_id: str) -> None:
    """Delete a job row and its audio file (session ephemeral retention).

    Best-effort by contract: every failure is logged as a warning and
    swallowed — a purge must never break delivery or session teardown.
    The backstop sweep in audio_cleanup catches stragglers.
    """
    try:
        row = get_job(job_id)
        if row is None:
            return
        audio_path = row.get("audio_path")
        if audio_path:
            try:
                Path(audio_path).unlink(missing_ok=True)
            except Exception:
                logger.warning(
                    "delete_job: failed to unlink audio for %s",
                    sanitize_log_value(job_id),
                    exc_info=True,
                )
        with get_connection() as conn:
            conn.execute("DELETE FROM transcription_jobs WHERE id = ?", (job_id,))
            conn.commit()
    except Exception:
        logger.warning(
            "delete_job: failed to purge job %s", sanitize_log_value(job_id), exc_info=True
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_session_ephemeral_retention.py -v --tb=short`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add server/backend/database/job_repository.py server/backend/tests/test_session_ephemeral_retention.py
git commit -m "feat(server): add delete_job purge primitive and SESSION_SOURCES for session ephemeral retention"
```

---

### Task 2: Backstop + legacy queries in the job repository

**Files:**
- Modify: `server/backend/database/job_repository.py`
- Test: `server/backend/tests/test_session_ephemeral_retention.py`

- [ ] **Step 1: Write the failing tests** (append to the new test file)

```python
class TestGetPurgeableSessionJobs:
    def test_returns_old_delivered_session_rows_only(self, db):
        _insert(db, "ws-old", source="websocket", status="completed", delivered=1,
                completed_at="2020-01-01T00:00:00+00:00")
        _insert(db, "imp-old", source="file_import", status="completed", delivered=1,
                completed_at="2020-01-02T00:00:00+00:00")
        # Excluded: wrong source, undelivered, failed, too recent
        _insert(db, "upload-old", source="audio_upload", status="completed", delivered=1,
                completed_at="2020-01-01T00:00:00+00:00")
        _insert(db, "ws-undelivered", source="websocket", status="completed", delivered=0,
                completed_at="2020-01-01T00:00:00+00:00")
        _insert(db, "ws-failed", source="websocket", status="failed", delivered=0)
        _insert(db, "ws-recent", source="websocket", status="completed", delivered=1,
                completed_at="2099-01-01T00:00:00+00:00")

        ids = {j["id"] for j in repo.get_purgeable_session_jobs(max_age_days=7)}

        assert ids == {"ws-old", "imp-old"}


class TestGetStaleFailedImports:
    def test_returns_only_aged_failed_imports_without_audio(self, db, tmp_path):
        _insert(db, "imp-fail-old", source="file_import", status="failed",
                created_at="2020-01-01 00:00:00")
        # Excluded: has audio (hypothetical future), wrong source, recent, not failed
        _insert(db, "imp-fail-audio", source="file_import", status="failed",
                audio_path=str(tmp_path / "kept.wav"), created_at="2020-01-01 00:00:00")
        _insert(db, "ws-fail-old", source="websocket", status="failed",
                created_at="2020-01-01 00:00:00")
        _insert(db, "imp-fail-recent", source="file_import", status="failed",
                created_at="2099-01-01 00:00:00")
        _insert(db, "imp-done", source="file_import", status="completed",
                created_at="2020-01-01 00:00:00")

        ids = {j["id"] for j in repo.get_stale_failed_imports(max_age_days=7)}

        assert ids == {"imp-fail-old"}


class TestGetLegacySessionRows:
    def test_returns_bare_anchors_and_delivered_session_rows(self, db, tmp_path):
        # Bare /import dedup anchors — any status, no result, no audio
        _insert(db, "anchor-proc", source="file_import", status="processing")
        _insert(db, "anchor-failed", source="file_import", status="failed")
        # Delivered session rows
        _insert(db, "ws-done", source="websocket", status="completed", delivered=1,
                result_text="hello", audio_path=str(tmp_path / "a.wav"))
        _insert(db, "imp-done", source="file_import", status="completed", delivered=1,
                result_text="hello")
        # Kept: undelivered / failed-with-content / non-session
        _insert(db, "ws-undelivered", source="websocket", status="completed", delivered=0,
                result_text="precious")
        _insert(db, "ws-failed-wav", source="websocket", status="failed",
                audio_path=str(tmp_path / "b.wav"))
        _insert(db, "upload-done", source="audio_upload", status="completed", delivered=1,
                result_text="hello")

        ids = {j["id"] for j in repo.get_legacy_session_rows()}

        assert ids == {"anchor-proc", "anchor-failed", "ws-done", "imp-done"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_session_ephemeral_retention.py -v --tb=short`
Expected: new classes FAIL with `AttributeError` (functions missing); Task 1 classes still PASS.

- [ ] **Step 3: Implement the three queries** (append to `job_repository.py`, after `delete_job`)

```python
def get_purgeable_session_jobs(max_age_days: int, limit: int = 100) -> list[dict]:
    """Return completed+delivered session-source jobs older than max_age_days.

    Backstop for rows that missed their immediate post-delivery purge (e.g. a
    crash between mark_delivered and delete_job). completed_at is isoformat —
    see get_jobs_for_cleanup for the cutoff-format note.
    """
    from datetime import timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).isoformat()
    placeholders = ",".join("?" for _ in SESSION_SOURCES)
    with get_connection() as conn:
        cursor = conn.execute(
            f"""
            SELECT * FROM transcription_jobs
            WHERE status = 'completed'
              AND delivered = 1
              AND source IN ({placeholders})
              AND completed_at < ?
            ORDER BY completed_at ASC
            LIMIT ?
            """,
            (*SESSION_SOURCES, cutoff, limit),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_stale_failed_imports(max_age_days: int, limit: int = 100) -> list[dict]:
    """Return aged failed file_import rows with no preserved audio.

    A failed import keeps no audio (the /import temp file is always deleted),
    so nothing is retryable — the row exists only to deliver its error message
    via GET /result/{job_id} (410). When the client never polls (e.g. the
    dashboard crashed), this query lets the backstop sweep purge the row.

    created_at is written by SQLite CURRENT_TIMESTAMP (space separator), so
    the cutoff must use strftime — see get_orphaned_jobs for the format note.
    """
    from datetime import timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM transcription_jobs
            WHERE status = 'failed'
              AND source = 'file_import'
              AND audio_path IS NULL
              AND created_at < ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (cutoff, limit),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_legacy_session_rows(limit: int = 1000) -> list[dict]:
    """One-time startup cleanup query (session-ephemeral-retention migration).

    Returns rows that predate the ephemeral lifecycle:
    - bare /import dedup anchors — source='file_import' with neither result
      text nor audio, ANY status. These rows were written purely so the old
      dedup check could find re-imports; they are what triggers the duplicate
      dialog and hold nothing recoverable.
    - already-delivered session rows — completed + delivered=1 for any session
      source. The result reached the client; under the new lifecycle these
      would have been purged at delivery time.

    Failed or undelivered rows WITH content are never returned. Runs at
    startup before any request is served, so no live 'processing' row can be
    caught by the anchor arm.
    """
    placeholders = ",".join("?" for _ in SESSION_SOURCES)
    with get_connection() as conn:
        cursor = conn.execute(
            f"""
            SELECT * FROM transcription_jobs
            WHERE (source = 'file_import'
                   AND result_text IS NULL
                   AND audio_path IS NULL)
               OR (source IN ({placeholders})
                   AND status = 'completed'
                   AND delivered = 1)
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (*SESSION_SOURCES, limit),
        )
        return [dict(row) for row in cursor.fetchall()]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_session_ephemeral_retention.py -v --tb=short`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add server/backend/database/job_repository.py server/backend/tests/test_session_ephemeral_retention.py
git commit -m "feat(server): add backstop and legacy-row queries for session ephemeral retention"
```

---

### Task 3: Extend the cleanup task + one-time legacy purge

**Files:**
- Modify: `server/backend/database/audio_cleanup.py`
- Modify: `server/backend/api/main.py` (lifespan, right after `recover_orphaned_jobs`)
- Test: `server/backend/tests/test_session_ephemeral_retention.py`

- [ ] **Step 1: Write the failing tests** (append to the test file)

```python
class TestCleanupOldRecordingsPurgesRows:
    def _run(self, monkeypatch, db):
        """Run cleanup_old_recordings against the patched repo module."""
        import asyncio

        from server.database import audio_cleanup

        asyncio.run(audio_cleanup.cleanup_old_recordings("/data/recordings", max_age_days=7))

    def test_purges_aged_delivered_session_rows(self, db, monkeypatch, tmp_path):
        wav = tmp_path / "ws.wav"
        wav.write_bytes(b"RIFF")
        _insert(db, "ws-old", source="websocket", status="completed", delivered=1,
                audio_path=str(wav), completed_at="2020-01-01T00:00:00+00:00")

        self._run(monkeypatch, db)

        assert _row(db, "ws-old") is None
        assert not wav.exists()

    def test_purges_aged_failed_imports(self, db, monkeypatch):
        _insert(db, "imp-fail-old", source="file_import", status="failed",
                created_at="2020-01-01 00:00:00")

        self._run(monkeypatch, db)

        assert _row(db, "imp-fail-old") is None

    def test_keeps_non_session_rows_deletes_only_their_audio(self, db, monkeypatch, tmp_path):
        wav = tmp_path / "up.wav"
        wav.write_bytes(b"RIFF")
        _insert(db, "upload-old", source="audio_upload", status="completed", delivered=1,
                audio_path=str(wav), completed_at="2020-01-01T00:00:00+00:00")

        self._run(monkeypatch, db)

        assert _row(db, "upload-old") is not None  # row kept (status quo)
        assert not wav.exists()  # WAV still garbage-collected

    def test_keeps_failed_websocket_rows(self, db, monkeypatch, tmp_path):
        wav = tmp_path / "retryable.wav"
        wav.write_bytes(b"RIFF")
        _insert(db, "ws-failed", source="websocket", status="failed",
                audio_path=str(wav), created_at="2020-01-01 00:00:00")

        self._run(monkeypatch, db)

        assert _row(db, "ws-failed") is not None
        assert wav.exists()

    def test_retention_zero_skips_everything(self, db, monkeypatch):
        import asyncio

        from server.database import audio_cleanup

        _insert(db, "ws-old", source="websocket", status="completed", delivered=1,
                completed_at="2020-01-01T00:00:00+00:00")

        asyncio.run(audio_cleanup.cleanup_old_recordings("/data/recordings", max_age_days=0))

        assert _row(db, "ws-old") is not None


class TestPurgeLegacySessionRows:
    def test_purges_anchors_and_delivered_rows_keeps_the_rest(self, db, monkeypatch, tmp_path):
        import asyncio

        from server.database import audio_cleanup

        wav = tmp_path / "done.wav"
        wav.write_bytes(b"RIFF")
        _insert(db, "anchor", source="file_import", status="failed")
        _insert(db, "ws-done", source="websocket", status="completed", delivered=1,
                result_text="x", audio_path=str(wav))
        _insert(db, "ws-undelivered", source="websocket", status="completed", delivered=0,
                result_text="precious")

        asyncio.run(audio_cleanup.purge_legacy_session_rows())

        assert _row(db, "anchor") is None
        assert _row(db, "ws-done") is None
        assert not wav.exists()
        assert _row(db, "ws-undelivered") is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_session_ephemeral_retention.py -v --tb=short`
Expected: new classes FAIL (`purge_legacy_session_rows` missing; row-purge assertions fail against the current WAV-only cleanup).

- [ ] **Step 3: Implement in `audio_cleanup.py`**

Update the module docstring (it currently says "The job DB row is always kept") to:

```python
"""
Audio cleanup module for transcription durability (Wave 2) and session
ephemeral retention (2026-08-09 spec).

For non-session jobs (e.g. source='audio_upload'): deletes only the raw audio
file of completed+delivered jobs older than the retention window — the DB row
is kept as a record that a transcription happened.

For session-source jobs ('websocket', 'file_import'): the backstop passes also
delete the DB ROW — the Session tab is ephemeral, and rows here only survive
their immediate post-delivery purge after a crash. Aged failed file_import
rows (which never have audio, so nothing is retryable) are purged too.

Never deletes audio for failed or undelivered jobs, and never touches failed
mic ('websocket') rows — their WAV is what makes /retry possible.
"""
```

Extend `cleanup_old_recordings` — after the existing per-job WAV deletion loop and before the final summary `logger.info`, add:

```python
    # Session ephemeral retention backstops. Immediate purge normally removes
    # session rows at delivery time; these passes only catch crash-window
    # stragglers and failed imports whose client never polled the error.
    from .job_repository import (
        delete_job,
        get_purgeable_session_jobs,
        get_stale_failed_imports,
    )

    purged_rows = 0
    try:
        stragglers = await asyncio.to_thread(get_purgeable_session_jobs, max_age_days)
        stale_imports = await asyncio.to_thread(get_stale_failed_imports, max_age_days)
        for job in [*stragglers, *stale_imports]:
            await asyncio.to_thread(delete_job, job["id"])
            purged_rows += 1
    except Exception:
        logger.exception("Audio cleanup: session-row backstop purge failed")
```

and extend the summary log line to include `purged_rows`:

```python
    logger.info(
        "Audio cleanup complete: %d file(s) deleted, %d skipped, %d session row(s) purged "
        "(retention=%d days, dir=%s)",
        deleted,
        skipped,
        purged_rows,
        max_age_days,
        recordings_dir,
    )
```

Note: the early `if not jobs: return` guard in the current implementation must NOT short-circuit the new passes — restructure so the WAV pass and the row-purge passes both always run (keep the `max_age_days <= 0` early return as the only skip). Concretely: replace `if not jobs: ... return` with `if not jobs: logger.debug(...)` and initialize `deleted = skipped = 0` before the loop.

Then add the one-time startup purge at the end of the module:

```python
async def purge_legacy_session_rows() -> None:
    """One-time startup migration for session ephemeral retention.

    Purges rows accumulated under the old lifecycle: bare /import dedup
    anchors (the rows behind the duplicate dialog) and already-delivered
    session rows. Anything failed or undelivered with content is untouched.
    Safe to run every startup — once drained it finds nothing.
    """
    from .job_repository import delete_job, get_legacy_session_rows

    total = 0
    while True:
        try:
            rows = await asyncio.to_thread(get_legacy_session_rows)
        except Exception:
            logger.exception("Legacy session-row purge: query failed")
            return
        if not rows:
            break
        for row in rows:
            await asyncio.to_thread(delete_job, row["id"])
        total += len(rows)
        if len(rows) < 1000:  # last page
            break
    if total:
        logger.info("Legacy session-row purge: %d row(s) removed", total)
```

- [ ] **Step 4: Wire the startup call in `api/main.py`**

Immediately after `await recover_orphaned_jobs(_orphan_timeout)` / `_log_time("orphan job recovery complete")` (around line 436), add:

```python
    # One-time legacy purge for session ephemeral retention (2026-08-09 spec).
    # Runs before any request is served, so no live job can be caught.
    from server.database.audio_cleanup import purge_legacy_session_rows

    await purge_legacy_session_rows()
    _log_time("legacy session-row purge complete")
```

- [ ] **Step 5: Run the tests to verify they pass, plus neighbors**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_session_ephemeral_retention.py tests/test_main_lifespan_sweeper.py -v --tb=short`
Expected: PASS. If `test_main_lifespan_sweeper.py` mocks lifespan internals and breaks on the new call, patch `purge_legacy_session_rows` the same way it patches `recover_orphaned_jobs`.

- [ ] **Step 6: Commit**

```bash
git add server/backend/database/audio_cleanup.py server/backend/api/main.py server/backend/tests/test_session_ephemeral_retention.py
git commit -m "feat(server): extend cleanup sweep with session-row purges and one-time legacy cleanup at startup"
```

---

### Task 4: Purge on `/result` fetch and dismiss

**Files:**
- Modify: `server/backend/api/routes/transcription.py` (`get_transcription_result`, `dismiss_transcription_result`)
- Test: `server/backend/tests/test_transcription_durability_routes.py`

- [ ] **Step 1: Write the failing tests** (append inside the existing classes; follow the direct-call pattern already in the file)

In `TestGetTranscriptionResult`:

```python
    def test_200_purges_session_source_job(self, repo, monkeypatch):
        purged: list[str] = []
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "completed",
                "client_name": None,
                "source": "file_import",
                "result_json": '{"text": "hi"}',
            },
        )
        monkeypatch.setattr(repo, "delete_job", lambda jid: purged.append(jid))

        resp = asyncio.run(transcription.get_transcription_result("job-imp", _request()))

        assert resp.status_code == 200
        assert purged == ["job-imp"]

    def test_200_keeps_non_session_job(self, repo, monkeypatch):
        purged: list[str] = []
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "completed",
                "client_name": None,
                "source": "audio_upload",
                "result_json": '{"text": "hi"}',
            },
        )
        monkeypatch.setattr(repo, "delete_job", lambda jid: purged.append(jid))

        resp = asyncio.run(transcription.get_transcription_result("job-up", _request()))

        assert resp.status_code == 200
        assert purged == []

    def test_410_purges_failed_import_without_audio(self, repo, monkeypatch):
        purged: list[str] = []
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "failed",
                "client_name": None,
                "source": "file_import",
                "audio_path": None,
                "error_message": "boom",
            },
        )
        monkeypatch.setattr(repo, "delete_job", lambda jid: purged.append(jid))

        with pytest.raises(HTTPException) as exc:
            asyncio.run(transcription.get_transcription_result("job-if", _request()))

        assert exc.value.status_code == 410
        assert purged == ["job-if"]

    def test_410_keeps_failed_websocket_job(self, repo, monkeypatch):
        purged: list[str] = []
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {
                "status": "failed",
                "client_name": None,
                "source": "websocket",
                "audio_path": "/data/recordings/x.wav",
                "error_message": "boom",
            },
        )
        monkeypatch.setattr(repo, "delete_job", lambda jid: purged.append(jid))

        with pytest.raises(HTTPException):
            asyncio.run(transcription.get_transcription_result("job-ws", _request()))

        assert purged == []
```

In the dismiss test class (`TestDismissTranscriptionResult` or equivalent — match the existing class name):

```python
    def test_dismiss_purges_completed_session_job(self, repo, monkeypatch):
        purged: list[str] = []
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {"status": "completed", "client_name": None, "source": "websocket"},
        )
        monkeypatch.setattr(repo, "delete_job", lambda jid: purged.append(jid))

        resp = asyncio.run(transcription.dismiss_transcription_result("job-d", _request()))

        assert resp.status_code == 200
        assert purged == ["job-d"]

    def test_dismiss_keeps_non_session_job(self, repo, monkeypatch):
        purged: list[str] = []
        monkeypatch.setattr(
            repo,
            "get_job",
            lambda _: {"status": "completed", "client_name": None, "source": "audio_upload"},
        )
        monkeypatch.setattr(repo, "delete_job", lambda jid: purged.append(jid))

        resp = asyncio.run(transcription.dismiss_transcription_result("job-d2", _request()))

        assert resp.status_code == 200
        assert purged == []
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_transcription_durability_routes.py -v --tb=short`
Expected: new tests FAIL (`delete_job` never called); all pre-existing tests PASS.

- [ ] **Step 3: Implement the route changes**

In `get_transcription_result`, change the function-local import to:

```python
    from ...database.job_repository import SESSION_SOURCES, delete_job, get_job, mark_delivered
```

Replace the failed branch:

```python
    if job["status"] == "failed":
        detail = job.get("error_message") or "Transcription failed"
        # Session ephemeral retention: a failed import keeps no audio, so
        # nothing is retryable — the row's only purpose was delivering this
        # error message, which just happened. Failed 'websocket' jobs keep
        # their row + WAV so /retry stays possible.
        if job.get("source") == "file_import" and not job.get("audio_path"):
            delete_job(job_id)
        raise HTTPException(status_code=410, detail=detail)
```

After the `mark_delivered` try/except in the completed branch (result data is already in memory at that point), add before the `return JSONResponse(...)`:

```python
    # Session ephemeral retention: a delivered session job leaves no
    # server-side trace. delete_job never raises (warning-only contract).
    if job.get("source") in SESSION_SOURCES:
        delete_job(job_id)
```

In `dismiss_transcription_result`, change the import to include `SESSION_SOURCES, delete_job` and after `mark_delivered(job_id)` add:

```python
    # Dismiss means "I don't want it" — purge session jobs like a delivery.
    if job.get("status") == "completed" and job.get("source") in SESSION_SOURCES:
        delete_job(job_id)
```

- [ ] **Step 4: Run to verify everything passes**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_transcription_durability_routes.py -v --tb=short`
Expected: PASS (all — old tests use rows without `source`, `dict.get("source")` returns None, no purge, unchanged behavior).

- [ ] **Step 5: Commit**

```bash
git add server/backend/api/routes/transcription.py server/backend/tests/test_transcription_durability_routes.py
git commit -m "feat(server): purge session-source jobs on result fetch, failed-import 410, and dismiss"
```

---

### Task 5: `/import` route — remove dedup, mandatory durability row, full job_id

**Files:**
- Modify: `server/backend/api/routes/transcription.py` (`ImportAcceptedResponse`, `import_and_transcribe`)
- Test: `server/backend/tests/test_import_ephemeral_route.py` (new)

- [ ] **Step 1: Grep for existing contract tests**

Run: `grep -rln "dedup_matches" server/backend/tests/`
Any test asserting `/import` returns `dedup_matches` or writes hashes must be updated in this task (delete the assertion or repurpose per the new contract). `test_dedup_check_endpoint.py` and `test_create_job_audio_hash.py` target surfaces that KEEP working (the standalone dedup-check endpoint and the repo function) — leave them alone unless they call the `/import` route itself.

- [ ] **Step 2: Write the failing tests**

Create `server/backend/tests/test_import_ephemeral_route.py`:

```python
"""Tests for the /import route under session ephemeral retention.

Direct-call pattern (see test_transcription_durability_routes.py):
- monkeypatch repo functions on server.database.job_repository is NOT enough
  here — /import imports create_job at module top, so patch it on the
  transcription route module itself.
"""

from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from server.api.routes import transcription


class _Tracker:
    def __init__(self):
        self.ended: list[str] = []

    def try_start_job(self, user):
        return (True, "full-job-id-1234", None)

    def end_job(self, job_id, result=None):
        self.ended.append(job_id)
        return True


def _request(tracker):
    config = SimpleNamespace(get=lambda *a, **k: k.get("default"))
    state = SimpleNamespace(
        model_manager=SimpleNamespace(job_tracker=tracker),
        config=config,
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _upload() -> UploadFile:
    return UploadFile(filename="test.wav", file=io.BytesIO(b"RIFF0000WAVE"))


@pytest.fixture(autouse=True)
def _quiet_route(monkeypatch):
    monkeypatch.setattr(transcription, "get_client_name", lambda _req: "test-client")
    monkeypatch.setattr(transcription, "_assert_main_model_selected", lambda _req: None)
    monkeypatch.setattr(
        transcription, "resolve_parallel_diarization_default", lambda _cfg: False
    )
    # The route ends with loop.create_task(asyncio.to_thread(_run_file_import, ...));
    # neuter the worker so no real transcription starts.
    monkeypatch.setattr(transcription, "_run_file_import", lambda **kw: None)


def _call(tracker):
    return asyncio.run(
        transcription.import_and_transcribe(
            _request(tracker),
            file=_upload(),
            language=None,
            translation_enabled=False,
            translation_target_language=None,
            enable_diarization=False,
            enable_word_timestamps=True,
            expected_speakers=None,
            parallel_diarization=None,
            diarization_engine=None,
            multitrack=False,
        )
    )


class TestImportRoute:
    def test_returns_full_job_id_and_no_dedup_matches(self, monkeypatch):
        created: list[dict] = []
        monkeypatch.setattr(
            transcription, "create_job", lambda **kw: created.append(kw)
        )

        resp = _call(_Tracker())

        assert resp["job_id"] == "full-job-id-1234"
        assert "dedup_matches" not in resp
        assert created[0]["source"] == "file_import"
        # No hashes computed or stored any more
        assert "audio_hash" not in created[0]
        assert "normalized_audio_hash" not in created[0]

    def test_create_job_failure_aborts_with_500_and_releases_slot(self, monkeypatch):
        def _boom(**kw):
            raise RuntimeError("db locked")

        monkeypatch.setattr(transcription, "create_job", _boom)
        tracker = _Tracker()

        with pytest.raises(HTTPException) as exc:
            _call(tracker)

        assert exc.value.status_code == 500
        assert tracker.ended == ["full-job-id-1234"]
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_import_ephemeral_route.py -v --tb=short`
Expected: FAIL — response carries `job_id` == short id + `dedup_matches`; create_job failure currently swallowed.

- [ ] **Step 4: Implement**

Replace `ImportAcceptedResponse` (keep `DedupMatch` — the standalone dedup-check endpoint still uses it):

```python
class ImportAcceptedResponse(BaseModel):
    """Response model for accepted file import job (202).

    ``job_id`` is the FULL job id: the client polls
    GET /api/transcribe/result/{job_id} with it (202 processing / 410 failed /
    200 completed). Session ephemeral retention (2026-08-09 spec) removed the
    dedup_matches field — session imports no longer hash or dedup-check.
    """

    job_id: str
```

In `import_and_transcribe`:
1. Delete the whole hashing block (the `audio_hash`/`normalized_audio_hash` computation and its try/except) and the `dedup_matches` list comprehension.
2. Make the durability row mandatory — replace the `try: create_job(...) except: warn` block with:

```python
    # Session ephemeral retention: the durability row is the delivery channel
    # for the import result (the client polls GET /result/{job_id}). Without
    # the row the outcome would be unreachable, so a failed insert aborts the
    # request instead of running a transcription nobody can fetch.
    try:
        create_job(
            job_id=job_id,
            source="file_import",
            client_name=client_name,
            language=language,
            task="translate" if translation_enabled else "transcribe",
            translation_target=(translation_target_language if translation_enabled else None),
        )
    except Exception as _e:
        logger.error(
            "Failed to create durability row for import job %s: %s", job_id[:8], _e
        )
        model_manager.job_tracker.end_job(job_id)
        try:
            tmp_path.unlink()
        except Exception:
            logger.warning("Failed to remove temp upload %s after aborted import", tmp_path)
        raise HTTPException(
            status_code=500, detail="Could not create job record — import aborted"
        ) from _e
```

3. Change the return to `return {"job_id": job_id}` and update the route docstring: clients poll `GET /api/transcribe/result/{job_id}` (202/410/200), the result is persisted server-side before it is fetchable, and the row is purged after confirmed delivery.

- [ ] **Step 5: Run to verify they pass**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_import_ephemeral_route.py tests/test_dedup_check_endpoint.py -v --tb=short`
Expected: PASS. The dedup-check endpoint suite must stay green (endpoint untouched).

- [ ] **Step 6: Commit**

```bash
git add server/backend/api/routes/transcription.py server/backend/tests/test_import_ephemeral_route.py
git commit -m "feat(server): drop dedup hashing from /import, make durability row mandatory, return full job_id"
```

---

### Task 6: `_run_file_import` joins the durability pipeline

**Files:**
- Modify: `server/backend/api/routes/transcription.py` (`_run_file_import` + new `_persist_import_result` helper)
- Test: `server/backend/tests/test_import_ephemeral_route.py`

- [ ] **Step 1: Write the failing tests** (append to `test_import_ephemeral_route.py`)

```python
class TestRunFileImportDurability:
    """_run_file_import must persist BEFORE the in-memory job_tracker hand-off."""

    def _model_manager(self):
        calls: list[tuple] = []

        class _JT:
            def set_phase(self, *_a):
                pass

            def update_progress(self, *_a):
                pass

            def is_cancelled(self):
                return False

            def end_job(self, job_id, result=None):
                calls.append(("end_job", job_id, result))
                return True

        mm = SimpleNamespace(
            job_tracker=_JT(),
            gpu_device_index=0,
            ensure_transcription_loaded=lambda: SimpleNamespace(model_name="m"),
        )
        mm.job_tracker.set_phase = mm.job_tracker.set_phase  # keep mypy quiet
        return mm, calls

    @pytest.fixture(autouse=True)
    def _no_gpu_cleanup(self, monkeypatch):
        import server.core.audio_utils as audio_utils

        monkeypatch.setattr(audio_utils, "post_job_gpu_cleanup", lambda *_a, **_k: None)

    def _run(self, monkeypatch, tmp_path, *, dispatch):
        import server.core.diarization_dispatch as dd

        monkeypatch.setattr(dd, "transcribe_with_optional_diarization", dispatch)
        mm, calls = self._model_manager()
        wav = tmp_path / "in.wav"
        wav.write_bytes(b"RIFF")
        transcription._run_file_import(
            model_manager=mm,
            tmp_path=wav,
            filename="in.wav",
            language=None,
            translation_enabled=False,
            translation_target_language=None,
            enable_diarization=False,
            enable_word_timestamps=True,
            expected_speakers=None,
            parallel_diarization=None,
            use_parallel_default=False,
            multitrack=False,
            job_id="job-import-1",
            event_loop=None,
        )
        return calls

    def test_success_persists_before_end_job(self, monkeypatch, tmp_path):
        order: list[str] = []
        saved: list[dict] = []

        def _dispatch(**kw):
            result = SimpleNamespace(
                to_dict=lambda: {"text": "hello", "language": "en", "duration": 1.0}
            )
            outcome = SimpleNamespace(
                to_dict=lambda: {"requested": False, "performed": False, "reason": None}
            )
            return SimpleNamespace(result=result, outcome=outcome)

        def _save(**kw):
            order.append("save_result")
            saved.append(kw)

        monkeypatch.setattr(transcription, "save_result", _save)
        calls = self._run(monkeypatch, tmp_path, dispatch=_dispatch)
        order.extend(name for name, *_ in calls)

        assert order == ["save_result", "end_job"]
        assert saved[0]["job_id"] == "job-import-1"
        assert saved[0]["result_text"] == "hello"
        import json as _j

        payload = _j.loads(saved[0]["result_json"])
        assert payload["transcription"]["text"] == "hello"
        assert payload["text"] == "hello"  # top-level mirror for /recent previews

    def test_failure_calls_mark_failed(self, monkeypatch, tmp_path):
        failed: list[tuple] = []

        def _dispatch(**kw):
            raise RuntimeError("decode error")

        monkeypatch.setattr(
            transcription, "mark_failed", lambda jid, msg: failed.append((jid, msg))
        )
        self._run(monkeypatch, tmp_path, dispatch=_dispatch)

        assert failed and failed[0][0] == "job-import-1"
        assert "decode error" in failed[0][1]

    def test_cancel_calls_mark_failed_with_cancel_message(self, monkeypatch, tmp_path):
        from server.core.model_manager import TranscriptionCancelledError

        failed: list[tuple] = []

        def _dispatch(**kw):
            raise TranscriptionCancelledError("cancelled")

        monkeypatch.setattr(
            transcription, "mark_failed", lambda jid, msg: failed.append((jid, msg))
        )
        self._run(monkeypatch, tmp_path, dispatch=_dispatch)

        assert failed and "cancelled" in failed[0][1].lower()

    def test_save_result_failure_marks_failed(self, monkeypatch, tmp_path):
        failed: list[tuple] = []

        def _dispatch(**kw):
            result = SimpleNamespace(
                to_dict=lambda: {"text": "hello", "language": "en", "duration": 1.0}
            )
            outcome = SimpleNamespace(
                to_dict=lambda: {"requested": False, "performed": False, "reason": None}
            )
            return SimpleNamespace(result=result, outcome=outcome)

        def _boom(**kw):
            raise RuntimeError("disk full")

        monkeypatch.setattr(transcription, "save_result", _boom)
        monkeypatch.setattr(
            transcription, "mark_failed", lambda jid, msg: failed.append((jid, msg))
        )
        self._run(monkeypatch, tmp_path, dispatch=_dispatch)

        assert failed and "persist" in failed[0][1].lower()
```

Note for the executor: `_run_file_import` resolves `TranscriptionCancelledError` and `save_result`/`mark_failed` — check how the module imports them (module top vs function-local) and patch at the binding the function actually uses. If `save_result` is imported inside `_run_file_import` from `...database.job_repository`, patch `server.database.job_repository.save_result` instead of `transcription.save_result`. Adjust the monkeypatch targets accordingly — the assertions stay the same.

- [ ] **Step 2: Run to verify they fail**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_import_ephemeral_route.py -v --tb=short`
Expected: new class FAILS (no persistence calls happen today).

- [ ] **Step 3: Implement**

Add a module-level helper above `_run_file_import`:

```python
def _persist_import_result(
    job_id: str, payload: dict[str, Any], result_dict: dict[str, Any]
) -> None:
    """Persist an import result to its durability row BEFORE the in-memory
    job_tracker hand-off (persist-before-deliver, CLAUDE.md invariant).

    The row is the import path's ONLY delivery channel — the dashboard polls
    GET /result/{job_id} — so a failed write escalates to mark_failed: the
    client then receives an actionable 410 instead of polling 202 forever
    until the orphan sweep mislabels the job.
    """
    from server.core.json_utils import sanitize_for_json

    try:
        sanitized = sanitize_for_json(payload)
        save_result(
            job_id=job_id,
            result_text=result_dict.get("text", "") or "",
            result_json=_json.dumps(sanitized, ensure_ascii=False),
            result_language=result_dict.get("language"),
            duration_seconds=result_dict.get("duration"),
        )
    except Exception:
        logger.critical(
            "Failed to persist import result for job %s — the transcription exists "
            "only in the in-memory job tracker and is lost on restart",
            sanitize_log_value(job_id),
            exc_info=True,
        )
        try:
            mark_failed(
                job_id,
                "Persistence failed — the transcription completed but could not be "
                "saved. Check the server logs.",
            )
        except Exception:
            logger.warning(
                "Failed to mark import job %s as failed after persistence failure",
                sanitize_log_value(job_id),
                exc_info=True,
            )
```

(If `save_result`/`mark_failed` are not already module-top imports in `transcription.py`, add them to the existing `job_repository` import.)

In `_run_file_import`:

1. **Multitrack success path** — replace the inline `end_job(... result={...})` with:

```python
            result_dict = result.to_dict()
            payload = {
                "job_id": job_id[:8],
                "transcription": result_dict,
                "diarization": {
                    "requested": False,
                    "performed": False,
                    "reason": "multitrack",
                },
                # Top-level text mirror so /recent previews and the recovery
                # banner render this row without knowing the import shape.
                "text": result_dict.get("text", ""),
            }
            _persist_import_result(job_id, payload, result_dict)
            model_manager.job_tracker.end_job(job_id, result=payload)
```

(The webhook dispatch after it keeps using `result_dict` — unchanged.)

2. **Normal success path** — same pattern:

```python
        result_dict = result.to_dict()
        payload = {
            "job_id": job_id[:8],
            "transcription": result_dict,
            "diarization": diarization_outcome,
            "text": result_dict.get("text", ""),
        }
        _persist_import_result(job_id, payload, result_dict)
        model_manager.job_tracker.end_job(job_id, result=payload)
```

3. **Cancel branch** — before the existing `end_job`, add:

```python
        try:
            mark_failed(job_id, "Transcription cancelled by user")
        except Exception:
            logger.warning(
                "Failed to mark cancelled import job %s", sanitize_log_value(job_id), exc_info=True
            )
```

4. **Error branch** — after composing `error_payload`, add (remedy included when present):

```python
        _row_error = str(e) if dep_error is None else f"{e}. {dep_error.remedy}"
        try:
            mark_failed(job_id, _row_error)
        except Exception:
            logger.warning(
                "Failed to mark import job %s as failed", sanitize_log_value(job_id), exc_info=True
            )
```

5. Update the `_run_file_import` docstring: it now persists results to the durability row (persist-before-deliver) and keeps `job_tracker` for progress reporting; also update the Issue #104 comment block in `import_and_transcribe` if any stale text remains about NULL result columns.

- [ ] **Step 4: Run to verify they pass**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_import_ephemeral_route.py -v --tb=short`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add server/backend/api/routes/transcription.py server/backend/tests/test_import_ephemeral_route.py
git commit -m "fix(server): persist file-import results to the durability row before job_tracker hand-off"
```

---

### Task 7: WebSocket post-delivery purge

**Files:**
- Modify: `server/backend/api/routes/websocket.py` (import block lines ~39-48; auto-add block lines ~641-665)
- Test: `server/backend/tests/test_websocket_session_purge.py` (new)

- [ ] **Step 1: Read the existing WS test factories first**

Read `server/backend/tests/test_persist_before_deliver_matrix.py` and `test_websocket_notebook_autoadd.py` to reuse their session factory + monkeypatch pattern verbatim (they already fake `_save_result`, `_mark_delivered`, `send_message`, engine, and dispatch). Copy the factory into the new test file (or import it if it is shared via a fixtures module) — do NOT add attributes to the session class.

- [ ] **Step 2: Write the failing tests**

Create `server/backend/tests/test_websocket_session_purge.py` with four cases, using the borrowed factory. The assertions that matter:

```python
# 1. Happy path: persisted + delivered inline + no auto-add → purged
assert purged == [job_id]

# 2. result_ready reference path (>1MB payload) → NOT purged here
assert purged == []

# 3. auto-add ON and _save_session_to_notebook returns a recording id → purged
assert purged == [job_id]

# 4. auto-add ON and _save_session_to_notebook returns None (or raises) → NOT purged
assert purged == []
```

Each case monkeypatches `websocket._delete_job` with `lambda jid: purged.append(jid)` (plus `websocket._save_result`, `websocket._mark_delivered`, `websocket._save_session_to_notebook` per the factory pattern). For case 2 make the payload >1MB via a long `result.text` (or monkeypatch `json.dumps` length behavior — prefer the long text, it is what production sees).

- [ ] **Step 3: Run to verify they fail**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_websocket_session_purge.py -v --tb=short`
Expected: FAIL — `websocket` has no `_delete_job` attribute.

- [ ] **Step 4: Implement**

Add to the existing `job_repository` import block in `websocket.py`:

```python
    delete_job as _delete_job,
```

Replace the auto-add block (currently `if self.auto_add_to_notebook:` ... through the `except Exception as nb_err:` handler) with:

```python
            # Auto-add to the Audio Notebook (GH #199). Runs AFTER the result is
            # persisted and delivered: the notebook entry is a derived artifact,
            # so a failure here must never cost the user their transcript. Runs
            # in a thread, since the MP3 encode would otherwise block the event
            # loop. _autoadd_ok gates the ephemeral purge below — a failed
            # notebook save keeps row + WAV so nothing is lost.
            _autoadd_ok = True
            if self.auto_add_to_notebook:
                _autoadd_ok = False
                try:
                    recording_id = await asyncio.to_thread(
                        _save_session_to_notebook,
                        audio_path=self.temp_file,
                        duration_seconds=result.duration,
                        result=result,
                        model_name=getattr(engine, "model_name", None),
                        diarization_segments=dispatched.speaker_segments,
                    )
                    if recording_id:
                        _autoadd_ok = True
                        logger.info("Saved session recording to notebook: id=%s", recording_id)
                    else:
                        _warn_notebook_autoadd_failed(
                            "Could not save the recording to the Audio Notebook."
                        )
                except Exception as nb_err:
                    logger.error("Failed to add recording to notebook: %s", nb_err, exc_info=True)
                    _warn_notebook_autoadd_failed(
                        f"Could not save the recording to the Audio Notebook: {nb_err}"
                    )

            # Session ephemeral retention (2026-08-09 spec): a session job whose
            # result reached the client keeps no server-side trace — purge the
            # row and its WAV. Fires only on confirmed inline delivery; the
            # result_ready reference path purges inside GET /result/{job_id}
            # instead, and a failed notebook auto-add cancels the purge (row +
            # WAV stay as the recovery copy). Guarded so a purge error can
            # never surface as a post-delivery "transcription failed" banner.
            if (
                self._current_job_id
                and _result_persisted
                and not _sent_as_reference
                and _final_delivered
                and _autoadd_ok
            ):
                try:
                    _delete_job(self._current_job_id)
                except Exception as _purge_err:
                    logger.warning(
                        "Post-delivery purge failed for job %s: %s",
                        self._current_job_id,
                        _purge_err,
                    )
```

- [ ] **Step 5: Run the new file + the WS neighbors**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_websocket_session_purge.py tests/test_persist_before_deliver_matrix.py tests/test_websocket_notebook_autoadd.py tests/test_websocket_disconnect_salvage.py tests/test_websocket_longform_payload.py -v --tb=short`
Expected: PASS. If a matrix/salvage test drives the success path without patching `_delete_job`, it now hits the real one, which no-ops on a missing row and never raises — but patch `websocket._delete_job` to a no-op in those files' shared fixtures anyway so no test touches the real DB.

- [ ] **Step 6: Commit**

```bash
git add server/backend/api/routes/websocket.py server/backend/tests/test_websocket_session_purge.py
git commit -m "feat(server): purge mic-session jobs after confirmed delivery with notebook auto-add gating"
```

---

### Task 8: Full backend suite

- [ ] **Step 1: Run everything**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short`
Expected: PASS. Likely stragglers to fix here: any `/import` contract test still expecting `dedup_matches` or the short job id; lifespan tests needing a `purge_legacy_session_rows` patch; websocket fixtures needing `_delete_job` no-ops. Fix implementation only if the test reveals a real bug; otherwise update the test to the new contract.

- [ ] **Step 2: Commit any test fixes**

```bash
git add -A server/backend/tests
git commit -m "test(server): align existing suites with the session ephemeral retention contract"
```

---

### Task 9: Dashboard — poll `/result` instead of the job tracker; remove session dedup

**Files:**
- Modify: `dashboard/src/api/types.ts` (remove `dedup_matches` from `TranscriptionAccepted`)
- Modify: `dashboard/src/stores/importQueueStore.ts`
- Test: `dashboard/src/stores/importQueueStore.test.ts`

- [ ] **Step 1: Update the test harness and write failing tests**

In `importQueueStore.test.ts`:

1. Extend the apiClient mock (top of file):

```typescript
vi.mock('../api/client', () => ({
  apiClient: {
    importAndTranscribe: vi.fn(),
    uploadAndTranscribe: vi.fn(),
    getAdminStatus: vi.fn(),
    fetchTranscriptionResult: vi.fn(),
    cancelTranscription: vi.fn().mockResolvedValue(undefined),
  },
}));
```

2. Add a Response helper next to the other helpers:

```typescript
function httpResult(status: number, body?: unknown): Response {
  return { status, json: async () => body } as unknown as Response;
}
```

3. For every session-job test that currently mocks `apiClient.getAdminStatus` to deliver the session result, replace the mock with:

```typescript
vi.mocked(apiClient.fetchTranscriptionResult).mockResolvedValue(
  httpResult(200, {
    job_id: 'server-job-1',
    status: 'completed',
    result: {
      job_id: 'server-j',
      transcription: sessionTranscription,
      diarization: { requested: false, performed: false, reason: null },
    },
  }),
);
```

(Notebook-job tests keep `getAdminStatus` — that path is unchanged.)

4. Delete the `resolveDuplicateChoice` import and the whole GH-120 dedup describe block. Replace with:

```typescript
  // Session ephemeral retention: the server no longer sends dedup_matches and
  // the client must never prompt. A LEGACY server that still includes the
  // field gets silently ignored — the import proceeds as a normal new entry.
  describe('session imports never prompt for duplicates', () => {
    it('ignores a legacy dedup_matches field and completes the job', async () => {
      const requestChoiceSpy = vi.fn();
      useDedupChoiceStore.setState({ requestChoice: requestChoiceSpy as never });
      vi.mocked(apiClient.importAndTranscribe).mockResolvedValue({
        job_id: 'server-job-1',
        dedup_matches: [
          { recording_id: 'old', name: 'old.wav', created_at: '2026-01-01' },
        ],
      } as never);
      vi.mocked(apiClient.fetchTranscriptionResult).mockResolvedValue(
        httpResult(200, {
          job_id: 'server-job-1',
          status: 'completed',
          result: {
            job_id: 'server-j',
            transcription: sessionTranscription,
            diarization: { requested: false, performed: false, reason: null },
          },
        }),
      );

      getState().addFiles([new File(['x'], 'dup.wav')], 'session-normal');
      await vi.advanceTimersByTimeAsync(10_000);

      expect(requestChoiceSpy).not.toHaveBeenCalled();
      expect(getState().jobs[0].status).toBe('success');
    });
  });
```

(Reuse the file's existing fake-timer + electronAPI conventions from the GH-212 describe; `sessionTranscription` may need to be hoisted or duplicated into this describe.)

5. Add polling-outcome tests in a new describe:

```typescript
  describe('pollForSessionResult HTTP outcomes', () => {
    it('surfaces the 410 error detail as the job error', async () => {
      vi.mocked(apiClient.importAndTranscribe).mockResolvedValue({
        job_id: 'server-job-1',
      } as never);
      vi.mocked(apiClient.fetchTranscriptionResult).mockResolvedValue(
        httpResult(410, { detail: 'CUDA out of memory' }),
      );

      getState().addFiles([new File(['x'], 'oom.wav')], 'session-normal');
      await vi.advanceTimersByTimeAsync(10_000);

      expect(getState().jobs[0].status).toBe('error');
      expect(getState().jobs[0].error).toContain('CUDA out of memory');
    });

    it('treats 404 as a lost job', async () => {
      vi.mocked(apiClient.importAndTranscribe).mockResolvedValue({
        job_id: 'server-job-1',
      } as never);
      vi.mocked(apiClient.fetchTranscriptionResult).mockResolvedValue(httpResult(404));

      getState().addFiles([new File(['x'], 'lost.wav')], 'session-normal');
      await vi.advanceTimersByTimeAsync(10_000);

      expect(getState().jobs[0].status).toBe('error');
      expect(getState().jobs[0].error).toContain('lost');
    });

    it('keeps polling on 202 then resolves on 200', async () => {
      vi.mocked(apiClient.importAndTranscribe).mockResolvedValue({
        job_id: 'server-job-1',
      } as never);
      vi.mocked(apiClient.fetchTranscriptionResult)
        .mockResolvedValueOnce(httpResult(202, { status: 'processing' }))
        .mockResolvedValue(
          httpResult(200, {
            job_id: 'server-job-1',
            status: 'completed',
            result: {
              job_id: 'server-j',
              transcription: sessionTranscription,
              diarization: { requested: false, performed: false, reason: null },
            },
          }),
        );

      getState().addFiles([new File(['x'], 'slow.wav')], 'session-normal');
      await vi.advanceTimersByTimeAsync(15_000);

      expect(getState().jobs[0].status).toBe('success');
    });
  });
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd dashboard && nvm use && npx vitest run src/stores/importQueueStore.test.ts`
Expected: FAIL — `fetchTranscriptionResult` never called by the store; dedup describe compile errors surface any missed import cleanup.

- [ ] **Step 3: Implement in `importQueueStore.ts`**

1. Remove imports: `DedupMatch` (types), `useDedupChoiceStore`, `DedupChoice`, `useAriaAnnouncerStore` (verify with grep it has no other use in this file before removing).
2. Delete the whole "Duplicate resolution (GH-120)" section: `DuplicatePolicy`, `DEFAULT_DUPLICATE_POLICY`, `resolveDuplicateChoice`.
3. Replace `pollForSessionResult` (keep `POLL_INTERVAL_MS`/`MAX_POLLS`):

```typescript
// Session imports poll the durability row directly (GET /api/transcribe/result/
// {job_id}): 202 processing, 200 completed (the server purges the row after
// this response), 410 failed with the error detail, 404 job lost. Must go
// through apiClient's absolute base URL — a relative fetch resolves against
// the packaged file:// origin and never reaches the backend (GH #202).
async function pollForSessionResult(serverJobId: string): Promise<FileImportJobResult> {
  for (let i = 0; i < MAX_POLLS; i++) {
    if (_abort) throw new Error('Import queue aborted');
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));

    let resp: Response;
    try {
      resp = await apiClient.fetchTranscriptionResult(serverJobId);
    } catch (err) {
      console.warn('Poll error (will retry):', err);
      continue;
    }

    if (resp.status === 202) continue;
    if (resp.status === 200) {
      const body = (await resp.json()) as { result?: FileImportJobResult };
      return body.result ?? {};
    }
    if (resp.status === 410) {
      let detail = 'Transcription failed';
      try {
        detail = ((await resp.json()) as { detail?: string }).detail ?? detail;
      } catch {
        // keep the generic message when the body is not JSON
      }
      throw new Error(detail);
    }
    if (resp.status === 404) {
      throw new Error('Transcription job lost — server may have restarted');
    }
    if (resp.status === 403) throw new Error('Access denied for this transcription job');
    console.warn(`Poll got HTTP ${resp.status} (will retry)`);
  }
  throw new Error('Transcription timed out after 24 hours');
}
```

`FileImportJobResult` fields are all optional except `job_id` — check the interface; if `job_id` is required, type the return as `FileImportJobResult` via `body.result ?? ({ job_id: serverJobId } as FileImportJobResult)`.

4. In `processSessionJob`, delete the entire `if (importResponse.dedup_matches?.length) { ... }` block (keep the `const { job_id: serverJobId } = importResponse;` line and the `pollForSessionResult(serverJobId)` call; the `result.error` / `!result.transcription` guards stay).
5. In `types.ts`, remove the `dedup_matches` field and its doc comment from `TranscriptionAccepted` (keep `DedupMatch` and `DedupCheckResponse` — the dedup-check endpoint and `DedupPromptModal` remain).

- [ ] **Step 4: Run to verify green**

Run: `cd dashboard && nvm use && npx vitest run src/stores/importQueueStore.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/stores/importQueueStore.ts dashboard/src/stores/importQueueStore.test.ts dashboard/src/api/types.ts
git commit -m "feat(dashboard): poll /result for session imports and remove the session dedup prompt flow"
```

---

### Task 10: Remove the Folder Watch duplicate-policy setting

**Files:**
- Modify: `dashboard/components/views/SettingsModal.tsx`
- Modify: `dashboard/electron/main.ts`
- Contract: `dashboard/ui-contract/` (extract → build → bump → baseline → check)

- [ ] **Step 1: SettingsModal removals** (all reference the current line numbers; re-locate by content)

1. Line ~59: delete `import type { DuplicatePolicy } from '../../src/stores/importQueueStore';` (the type no longer exists — TS will force this).
2. Lines ~73-87: delete the `DUPLICATE_POLICY_ORDER`, `DUPLICATE_POLICY_LABELS`, `normalizeDuplicatePolicy` constants + their GH-120 comment block.
3. Line ~215: delete the `duplicatePolicy: 'create_new' as DuplicatePolicy,` field from the `appSettings` initial state.
4. Line ~458: delete the `duplicatePolicy: normalizeDuplicatePolicy(cfg['folderWatch.duplicatePolicy']),` load mapping.
5. Line ~579: delete the `['folderWatch.duplicatePolicy', appSettings.duplicatePolicy],` save entry.
6. Lines ~960-979: delete the whole `<Section title="Folder Watch">...</Section>` block (label, `CustomSelect`, helper `<p>`).

- [ ] **Step 2: electron/main.ts** — delete the default and its comment (lines ~558-561):

```typescript
    // GH-120 — how Folder Watch resolves a detected duplicate without blocking
    // the import queue on the interactive modal. 'create_new' | 'ask'.
    // Default 'create_new': unattended batch never stalls and never drops a file.
    'folderWatch.duplicatePolicy': 'create_new',
```

A stale stored value in the user's config file is simply never read again — electron-store ignores unknown keys (no migration needed).

- [ ] **Step 3: Typecheck + tests**

Run: `cd dashboard && nvm use && npx tsc --noEmit -p . && npx vitest run`
Expected: clean compile; full vitest suite PASS (fix any test still importing `DuplicatePolicy`).

- [ ] **Step 4: UI contract** (SettingsModal CSS classes changed — full flow, in this order)

```bash
cd dashboard
npm run ui:contract:extract
npm run ui:contract:build
# 1. hand-normalize repo_path in the extracted YAML if it stamped the worktree path
# 2. bump meta.spec_version (minor) in the contract YAML — BEFORE the baseline update
node ../scripts/ui-contract/validate-contract.mjs --update-baseline
npm run ui:contract:check
```

(Verify the validate script location first: `ls scripts/ui-contract/` from repo root — memory says it lives under the top-level `scripts/`, adjust the relative path accordingly.)
Expected: `ui:contract:check` green.

- [ ] **Step 5: Commit**

```bash
git add dashboard/components/views/SettingsModal.tsx dashboard/electron/main.ts dashboard/ui-contract
git commit -m "chore(ui): remove the Folder Watch duplicate-policy setting made obsolete by session ephemeral retention"
```

---

### Task 11: Docs alignment

**Files:**
- Modify: `docs/api-contracts-server.md` (grep `dedup_matches`, `/import`, `admin/status` polling guidance)
- Modify: `docs/data-models-server.md` (durability/retention section)

- [ ] **Step 1: Update `docs/api-contracts-server.md`**

- `/import` response: `{"job_id": "<full id>"}` — no `dedup_matches`; note "poll `GET /api/transcribe/result/{job_id}`" replacing any "poll /api/admin/status" instruction.
- Add to the `/result/{job_id}` entry: "For session-source jobs (`websocket`, `file_import`) a 200 also purges the row and its audio — repeat fetches return 404. A 410 on a failed `file_import` job purges the row as well."
- `/import/dedup-check` stays documented as-is.

- [ ] **Step 2: Update `docs/data-models-server.md`** — in the `transcription_jobs` section, replace any "rows are never deleted" claim with a short "Session ephemeral retention" paragraph:

> Session-source rows (`source` = `websocket` or `file_import`) are deleted — together with their audio file — immediately after the result is confirmed delivered (inline WS final, `GET /result` fetch, or dismiss). Failed mic jobs keep row + WAV indefinitely for `/retry`; failed imports (which never retain audio) are purged once the client has received the 410 error, or by the cleanup sweep. Rows from other sources (e.g. `audio_upload`) keep the pre-existing behavior: row kept forever, audio garbage-collected after `audio_retention_days`.

- [ ] **Step 3: Commit**

```bash
git add docs/api-contracts-server.md docs/data-models-server.md
git commit -m "docs(server): document session ephemeral retention lifecycle and the new /import contract"
```

---

### Task 12: Final verification + PR

- [ ] **Step 1: Full backend suite**: `cd server/backend && ../../build/.venv/bin/pytest tests/ --tb=short` → PASS
- [ ] **Step 2: Full dashboard suite**: `cd dashboard && nvm use && npx vitest run && npx tsc --noEmit -p . && npm run ui:contract:check` → PASS
- [ ] **Step 3: GitNexus** `detect_changes` — verify only the expected symbols/flows changed; report blast radius.
- [ ] **Step 4: Push + PR** targeting `main`, body summarizing: ephemeral session lifecycle, dedup removal (dialog gone), /import durability fix, legacy cleanup, smoke checklist:
  - [ ] Session mic recording → transcript delivered → `transcription_jobs` row gone, WAV gone
  - [ ] Session mic recording with auto-add ON → notebook entry exists, row + WAV gone
  - [ ] Session file import of a previously-imported file → NO duplicate dialog
  - [ ] Import completes with dashboard closed → reopen → recovery banner offers it → fetch → row gone
  - [ ] Failed import → queue row shows the real error, no false "job lost"
  - [ ] Failed mic job → retry works (WAV preserved)
  - [ ] Packaged build: >1 MB import result fetch works (GH #202 regression check)
  - [ ] Server restart after upgrade: log shows legacy purge count once, second restart shows nothing

---

## Self-review notes (spec coverage)

- Spec §1 lifecycle → Tasks 1, 4, 7. Purge scoped to `SESSION_SOURCES` only (spec's "session-source" definition; `audio_upload` proven untouched by tests in Tasks 2/3/4).
- Spec §2 import durability → Tasks 5, 6, 9 (poll switch). GH #202 risk covered: `fetchTranscriptionResult` already builds absolute URLs.
- Spec §3 dedup removal → Tasks 5 (server), 9 (store), 10 (settings). `DedupPromptModal`/`dedupChoiceStore`/`DedupChoiceContainer` deliberately kept per spec.
- Spec §4 safety net → Tasks 2, 4 (failed-mic keeps row+WAV; failed-import purge-on-410; `/recent` untouched).
- Spec §5 backstop sweep → Task 3.
- Spec §6 legacy cleanup → Tasks 2, 3.
- Error-handling table → delete_job never-raise contract (Task 1), `_autoadd_ok` gate (Task 7), `_persist_import_result` escalation (Task 6).
- Testing section → Tasks 1-9 test files; WS factories get no new session attributes (Task 7 uses locals only); ui-contract flow in Task 10; electron-store default removal is migration-free (Task 10).
