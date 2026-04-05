"""P0 durability tests — transcription result persistence and failure recovery.

Covers P0-DURA-001 through P0-DURA-007 from the QA test-design document.
These protect the critical invariant: "AVOID DATA LOSS AT ALL COSTS."

Run:  ../../build/.venv/bin/pytest tests/test_p0_durability.py -v --tb=short
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from server.api import main as main_mod

# ── Module import ──────────────────────────────────────────────────────
# websocket.py has numpy/soundfile as top-level imports; the build venv
# provides both, so a straight import works.
from server.api.routes import websocket as ws_mod
from starlette.websockets import WebSocketState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(
    *,
    job_id: str = "test-job-001",
    audio_chunks: list[bytes] | None = None,
    sample_rate: int = 16000,
    client_name: str = "test-client",
) -> ws_mod.TranscriptionSession:
    """Build a TranscriptionSession with minimal stubs (bypass __init__)."""
    session = object.__new__(ws_mod.TranscriptionSession)
    session.websocket = MagicMock()
    session.websocket.client_state = WebSocketState.CONNECTED
    session.websocket.send_json = AsyncMock()
    session.client_name = client_name
    session.is_admin = False
    session.client_type = SimpleNamespace(value="web")
    session.session_id = "sess-001"
    session.is_recording = False
    session.language = None
    session.audio_chunks = audio_chunks or [b"\x00\x00" * 800]  # 100ms of silence at 16kHz
    session.sample_rate = sample_rate
    session._sample_rate_mismatch_reported = False
    session.temp_file = None
    session._realtime_engine = None
    session._use_realtime_engine = False
    session._current_job_id = job_id
    session._client_disconnected = False
    session.capabilities = SimpleNamespace(
        supports_binary_audio=True,
        preferred_sample_rate=sample_rate,
    )
    return session


def _fake_transcription_result(text: str = "Hello world", duration: float = 1.5):
    """Minimal transcription result matching engine.transcribe_file() output."""
    return SimpleNamespace(
        text=text,
        words=[],
        language="en",
        duration=duration,
    )


# ═══════════════════════════════════════════════════════════════════════
# P0-DURA-001: save_result() failure triggers mark_failed()
# 3 scenarios: DB error, serialization error, timeout
# ═══════════════════════════════════════════════════════════════════════


class _BaseProcessTranscription:
    """Shared setup for process_transcription tests."""

    @pytest.fixture(autouse=True)
    def _patch_heavy_deps(self, monkeypatch, tmp_path):
        """Mock model_manager, soundfile.write, config, and webhook dispatch."""
        # Model manager with a fake transcription engine
        self._transcribe_result = _fake_transcription_result()
        engine = MagicMock()
        engine.transcribe_file = MagicMock(return_value=self._transcribe_result)
        mm = MagicMock()
        mm.transcription_engine = engine
        mm.job_tracker = SimpleNamespace(
            update_progress=lambda *a: None,
        )
        monkeypatch.setattr(
            ws_mod,
            "_save_result",
            MagicMock(),
        )
        monkeypatch.setattr(ws_mod, "_mark_failed", MagicMock())
        monkeypatch.setattr(ws_mod, "_mark_delivered", MagicMock())
        monkeypatch.setattr(ws_mod, "_set_audio_path", MagicMock())
        self._save_result_mock = ws_mod._save_result
        self._mark_failed_mock = ws_mod._mark_failed
        self._mark_delivered_mock = ws_mod._mark_delivered

        # Config that returns a recordings_dir pointing to tmp_path
        cfg = MagicMock()
        cfg.get.return_value = str(tmp_path / "recordings")
        monkeypatch.setattr(
            "server.config.get_config",
            lambda: cfg,
        )
        # Patch get_model_manager inside websocket.process_transcription (lazy import)
        monkeypatch.setattr(
            "server.core.model_manager.get_model_manager",
            lambda: mm,
        )
        # Prevent webhook dispatch
        monkeypatch.setattr(
            "server.core.webhook.dispatch",
            AsyncMock(),
        )
        self._mm = mm
        self._engine = engine
        self._tmp_path = tmp_path


@pytest.mark.p0
@pytest.mark.durability
class TestDura001SaveResultFailure(_BaseProcessTranscription):
    """P0-DURA-001: save_result() failure triggers mark_failed()."""

    def _assert_mark_failed_with_persistence_message(self) -> None:
        """Shared assertion: mark_failed called once with job ID and persistence message."""
        ws_mod._mark_failed.assert_called_once()
        args = ws_mod._mark_failed.call_args[0]
        assert args[0] == "test-job-001"
        assert "Persistence failed" in args[1]

    def test_db_error_triggers_mark_failed(self, monkeypatch):
        """When save_result raises a DB error, mark_failed is called."""
        ws_mod._save_result.side_effect = RuntimeError("DB connection lost")
        session = _make_session()

        asyncio.run(session.process_transcription())

        self._assert_mark_failed_with_persistence_message()

    def test_serialization_error_triggers_mark_failed(self, monkeypatch):
        """When save_result raises due to JSON serialization, mark_failed is called."""
        ws_mod._save_result.side_effect = TypeError("Object not JSON serializable")
        session = _make_session()

        asyncio.run(session.process_transcription())

        self._assert_mark_failed_with_persistence_message()

    def test_timeout_error_triggers_mark_failed(self, monkeypatch):
        """When save_result raises a timeout, mark_failed is called."""
        ws_mod._save_result.side_effect = TimeoutError("DB write timed out")
        session = _make_session()

        asyncio.run(session.process_transcription())

        self._assert_mark_failed_with_persistence_message()

    def test_result_still_delivered_despite_save_failure(self, monkeypatch):
        """Even when persistence fails, the result is delivered to the client."""
        ws_mod._save_result.side_effect = RuntimeError("DB error")
        session = _make_session()

        asyncio.run(session.process_transcription())

        # send_json should have been called with the final result
        calls = session.websocket.send_json.call_args_list
        sent_types = [c[0][0]["type"] for c in calls]
        assert "final" in sent_types

    def test_mark_delivered_skipped_when_save_failed(self, monkeypatch):
        """mark_delivered must NOT be called when save_result failed."""
        ws_mod._save_result.side_effect = RuntimeError("DB error")
        session = _make_session()

        asyncio.run(session.process_transcription())

        ws_mod._mark_delivered.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# P0-DURA-002: WS disconnect during transcription — result already saved
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.durability
class TestDura002DisconnectMidProcess(_BaseProcessTranscription):
    """P0-DURA-002: WS disconnect during transcription — result persisted."""

    def test_disconnect_after_save_result_preserves_data(self, monkeypatch):
        """If client disconnects after save_result, data is safe despite failed delivery."""
        save_calls = []
        ws_mod._save_result.side_effect = lambda **kw: save_calls.append(kw)
        session = _make_session()
        # Simulate disconnect — send_message("final") becomes a no-op
        session.websocket.client_state = WebSocketState.DISCONNECTED

        asyncio.run(session.process_transcription())

        # save_result was called BEFORE delivery attempt (result is in DB)
        assert len(save_calls) == 1
        assert save_calls[0]["job_id"] == "test-job-001"
        # send_json was never called (WS disconnected), proving save-before-deliver
        session.websocket.send_json.assert_not_called()

    def test_disconnect_cancellation_marks_failed(self, monkeypatch):
        """If transcription is cancelled due to disconnect, job is marked failed."""
        from server.core.model_manager import TranscriptionCancelledError

        self._engine.transcribe_file.side_effect = TranscriptionCancelledError("cancelled")
        session = _make_session()
        session._client_disconnected = True

        asyncio.run(session.process_transcription())

        ws_mod._mark_failed.assert_called_once()
        args = ws_mod._mark_failed.call_args[0]
        assert "Cancelled" in args[1] or "disconnect" in args[1].lower()


# ═══════════════════════════════════════════════════════════════════════
# P0-DURA-003: WS disconnect after save_result failure — job marked failed
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.durability
class TestDura003CompoundFailure(_BaseProcessTranscription):
    """P0-DURA-003: Compound failure — save fails, then client disconnects."""

    def test_save_failure_then_disconnect_still_marks_failed(self, monkeypatch):
        """When both save_result fails AND client disconnects, mark_failed is called."""
        ws_mod._save_result.side_effect = RuntimeError("DB error")
        session = _make_session()
        # Client disconnects so send_message becomes a no-op
        session.websocket.client_state = WebSocketState.DISCONNECTED

        asyncio.run(session.process_transcription())

        # mark_failed should still be called even though WS is gone
        ws_mod._mark_failed.assert_called_once()

    def test_save_and_mark_failed_both_raise_no_crash(self, monkeypatch):
        """Double failure: save_result AND mark_failed both raise — no crash."""
        ws_mod._save_result.side_effect = RuntimeError("DB error")
        ws_mod._mark_failed.side_effect = RuntimeError("mark_failed also broken")
        session = _make_session()

        # Must not raise — the outer try/except in process_transcription handles this
        asyncio.run(session.process_transcription())


# ═══════════════════════════════════════════════════════════════════════
# P0-DURA-004: Large result (>1MB) — reference delivery
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.durability
class TestDura004LargeResult(_BaseProcessTranscription):
    """P0-DURA-004: Large result triggers reference delivery."""

    def test_large_result_sends_reference_not_final(self, monkeypatch):
        """Results >1MB are sent as result_ready reference, not inline final."""
        # Create a transcription result that will produce >1MB JSON
        large_text = "x" * 1_100_000
        self._transcribe_result.text = large_text
        self._engine.transcribe_file.return_value = self._transcribe_result
        session = _make_session()

        asyncio.run(session.process_transcription())

        calls = session.websocket.send_json.call_args_list
        sent_types = [c[0][0]["type"] for c in calls]
        assert "result_ready" in sent_types
        assert "final" not in sent_types

    def test_large_result_does_not_call_mark_delivered(self, monkeypatch):
        """mark_delivered is NOT called for reference delivery — HTTP fetch does it."""
        large_text = "x" * 1_100_000
        self._transcribe_result.text = large_text
        self._engine.transcribe_file.return_value = self._transcribe_result
        session = _make_session()

        asyncio.run(session.process_transcription())

        ws_mod._mark_delivered.assert_not_called()

    def test_normal_result_calls_mark_delivered(self, monkeypatch):
        """Normal-sized results DO call mark_delivered after inline delivery."""
        session = _make_session()

        asyncio.run(session.process_transcription())

        ws_mod._mark_delivered.assert_called_once_with("test-job-001")


# ═══════════════════════════════════════════════════════════════════════
# P0-DURA-005: Audio file written BEFORE transcription begins
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.durability
class TestDura005AudioPersistenceOrder(_BaseProcessTranscription):
    """P0-DURA-005: Audio persisted before STT backend is called."""

    def test_audio_written_before_transcription(self, monkeypatch):
        """Audio file must exist on disk before transcribe_file() is called."""
        audio_exists_at_transcribe_time = []

        def _check_audio_then_transcribe(**kwargs):
            file_path = kwargs.get("file_path")
            assert file_path is not None, "transcribe_file must receive file_path"
            audio_exists_at_transcribe_time.append(Path(file_path).exists())
            return _fake_transcription_result()

        self._engine.transcribe_file = _check_audio_then_transcribe
        session = _make_session()

        asyncio.run(session.process_transcription())

        assert len(audio_exists_at_transcribe_time) == 1, "transcribe_file should be called once"
        assert audio_exists_at_transcribe_time[0] is True, (
            "audio file must exist BEFORE transcription"
        )

    def test_set_audio_path_called_for_persistent_write(self, monkeypatch):
        """set_audio_path is called to record the persistent audio location in DB."""
        session = _make_session()

        asyncio.run(session.process_transcription())

        ws_mod._set_audio_path.assert_called_once()
        args = ws_mod._set_audio_path.call_args[0]
        assert args[0] == "test-job-001"
        assert "recordings" in args[1]  # path should be in the recordings dir


# ═══════════════════════════════════════════════════════════════════════
# P0-DURA-006: recover_orphaned_jobs() marks stale jobs as failed
# 3 scenarios: normal orphan, with audio, without audio
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.durability
class TestDura006OrphanRecovery:
    """P0-DURA-006: recover_orphaned_jobs marks stale processing jobs as failed."""

    def test_orphan_with_audio_gets_retry_message(self, monkeypatch, tmp_path):
        """Orphaned job WITH audio_path gets 'use retry to re-transcribe' message."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"\x00" * 100)

        orphaned = [{"id": "orphan-001", "audio_path": str(audio_file)}]
        mark_calls = []

        monkeypatch.setattr(
            "server.database.job_repository.get_orphaned_jobs",
            lambda timeout: orphaned,
        )
        monkeypatch.setattr(
            "server.database.job_repository.mark_failed",
            lambda job_id, reason: mark_calls.append((job_id, reason)),
        )

        asyncio.run(main_mod.recover_orphaned_jobs(timeout_minutes=10))

        assert len(mark_calls) == 1
        assert mark_calls[0][0] == "orphan-001"
        assert "retry" in mark_calls[0][1].lower()

    def test_orphan_without_audio_gets_not_preserved_message(self, monkeypatch, tmp_path):
        """Orphaned job WITHOUT audio gets 'audio not preserved' message."""
        orphaned = [{"id": "orphan-002", "audio_path": None}]
        mark_calls = []

        monkeypatch.setattr(
            "server.database.job_repository.get_orphaned_jobs",
            lambda timeout: orphaned,
        )
        monkeypatch.setattr(
            "server.database.job_repository.mark_failed",
            lambda job_id, reason: mark_calls.append((job_id, reason)),
        )

        asyncio.run(main_mod.recover_orphaned_jobs(timeout_minutes=10))

        assert len(mark_calls) == 1
        assert mark_calls[0][0] == "orphan-002"
        assert "not preserved" in mark_calls[0][1].lower()

    def test_orphan_with_missing_audio_file_gets_not_preserved(self, monkeypatch, tmp_path):
        """Orphaned job with audio_path pointing to deleted file → 'not preserved'."""
        orphaned = [{"id": "orphan-003", "audio_path": str(tmp_path / "deleted.wav")}]
        mark_calls = []

        monkeypatch.setattr(
            "server.database.job_repository.get_orphaned_jobs",
            lambda timeout: orphaned,
        )
        monkeypatch.setattr(
            "server.database.job_repository.mark_failed",
            lambda job_id, reason: mark_calls.append((job_id, reason)),
        )

        asyncio.run(main_mod.recover_orphaned_jobs(timeout_minutes=10))

        assert len(mark_calls) == 1
        assert "not preserved" in mark_calls[0][1].lower()

    def test_multiple_orphans_all_marked(self, monkeypatch, tmp_path):
        """All orphaned jobs are marked failed, not just the first."""
        audio = tmp_path / "test.wav"
        audio.write_bytes(b"\x00" * 100)
        orphaned = [
            {"id": "orphan-a", "audio_path": str(audio)},
            {"id": "orphan-b", "audio_path": None},
            {"id": "orphan-c", "audio_path": str(tmp_path / "gone.wav")},
        ]
        mark_calls = []

        monkeypatch.setattr(
            "server.database.job_repository.get_orphaned_jobs",
            lambda timeout: orphaned,
        )
        monkeypatch.setattr(
            "server.database.job_repository.mark_failed",
            lambda job_id, reason: mark_calls.append((job_id, reason)),
        )

        asyncio.run(main_mod.recover_orphaned_jobs(timeout_minutes=10))

        assert len(mark_calls) == 3
        marked_ids = {c[0] for c in mark_calls}
        assert marked_ids == {"orphan-a", "orphan-b", "orphan-c"}

    def test_zero_timeout_skips_recovery(self, monkeypatch):
        """timeout_minutes <= 0 means recovery is disabled."""
        get_orphaned = MagicMock()
        monkeypatch.setattr(
            "server.database.job_repository.get_orphaned_jobs",
            get_orphaned,
        )

        asyncio.run(main_mod.recover_orphaned_jobs(timeout_minutes=0))

        get_orphaned.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# P0-DURA-007: Orphan sweep respects is_busy() on periodic runs
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.durability
class TestDura007PeriodicSweepBusy:
    """P0-DURA-007: Periodic sweep skips when job tracker reports busy."""

    def test_sweep_skips_when_busy(self, monkeypatch):
        """When job_tracker.is_busy() returns True, orphan sweep is skipped."""
        get_orphaned = MagicMock()
        monkeypatch.setattr(
            "server.database.job_repository.get_orphaned_jobs",
            get_orphaned,
        )
        monkeypatch.setattr(
            "server.database.job_repository.mark_failed",
            MagicMock(),
        )

        tracker = SimpleNamespace(is_busy=lambda: (True, "test-user"))
        iteration_count = 0

        async def _mock_sleep(seconds):
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count > 1:
                # periodic_orphan_sweep catches CancelledError and returns cleanly
                raise asyncio.CancelledError()

        monkeypatch.setattr(asyncio, "sleep", _mock_sleep)

        # Function catches CancelledError internally and returns — no exception raised
        asyncio.run(
            main_mod.periodic_orphan_sweep(
                timeout_minutes=10,
                interval_minutes=1,
                job_tracker=tracker,
            )
        )

        get_orphaned.assert_not_called()

    def test_sweep_runs_when_not_busy(self, monkeypatch):
        """When job_tracker.is_busy() returns False, orphan sweep proceeds."""
        mark_calls = []
        monkeypatch.setattr(
            "server.database.job_repository.get_orphaned_jobs",
            lambda timeout: [{"id": "stale-001", "audio_path": None}],
        )
        monkeypatch.setattr(
            "server.database.job_repository.mark_failed",
            lambda job_id, reason: mark_calls.append((job_id, reason)),
        )

        tracker = SimpleNamespace(is_busy=lambda: (False, None))
        iteration_count = 0

        async def _mock_sleep(seconds):
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count > 1:
                raise asyncio.CancelledError()

        monkeypatch.setattr(asyncio, "sleep", _mock_sleep)

        # Function catches CancelledError internally and returns cleanly
        asyncio.run(
            main_mod.periodic_orphan_sweep(
                timeout_minutes=10,
                interval_minutes=1,
                job_tracker=tracker,
            )
        )

        assert len(mark_calls) == 1
        assert mark_calls[0][0] == "stale-001"

    def test_startup_recovery_does_not_check_busy(self, monkeypatch):
        """recover_orphaned_jobs (startup) has NO is_busy guard — it always runs."""
        mark_calls = []
        monkeypatch.setattr(
            "server.database.job_repository.get_orphaned_jobs",
            lambda timeout: [{"id": "startup-orphan", "audio_path": None}],
        )
        monkeypatch.setattr(
            "server.database.job_repository.mark_failed",
            lambda job_id, reason: mark_calls.append((job_id, reason)),
        )

        # No job_tracker passed — startup path doesn't accept one
        asyncio.run(main_mod.recover_orphaned_jobs(timeout_minutes=10))

        assert len(mark_calls) == 1
        assert mark_calls[0][0] == "startup-orphan"
