"""Tests for the /import route under session ephemeral retention.

Direct-call pattern (see test_transcription_durability_routes.py). The route
imports create_job / save_result / mark_failed into its own module namespace,
so patches target server.api.routes.transcription, not the repo module.
"""

from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from server.api.routes import transcription
from starlette.datastructures import UploadFile


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
    @pytest.fixture(autouse=True)
    def _quiet_route(self, monkeypatch):
        """Route-level stubs. Class-scoped on purpose: patching _run_file_import
        to a no-op here must NOT leak into TestRunFileImportDurability, which
        exercises the real worker."""
        monkeypatch.setattr(transcription, "get_client_name", lambda _req: "test-client")
        monkeypatch.setattr(transcription, "_assert_main_model_selected", lambda _req: None)
        monkeypatch.setattr(
            transcription, "resolve_parallel_diarization_default", lambda _cfg: False
        )
        # The route ends with loop.create_task(asyncio.to_thread(_run_file_import, ...));
        # neuter the worker so no real transcription starts.
        monkeypatch.setattr(transcription, "_run_file_import", lambda **kw: None)

    def test_returns_full_job_id_and_no_dedup_matches(self, monkeypatch):
        created: list[dict] = []
        monkeypatch.setattr(transcription, "create_job", lambda **kw: created.append(kw))

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


class TestRunFileImportDurability:
    """_run_file_import must persist BEFORE the in-memory job_tracker hand-off."""

    @staticmethod
    def _model_manager():
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

    @staticmethod
    def _ok_dispatch(**kw):
        result = SimpleNamespace(
            to_dict=lambda: {"text": "hello", "language": "en", "duration": 1.0}
        )
        outcome = SimpleNamespace(
            to_dict=lambda: {"requested": False, "performed": False, "reason": None}
        )
        return SimpleNamespace(result=result, outcome=outcome)

    def test_success_persists_before_end_job(self, monkeypatch, tmp_path):
        order: list[str] = []
        saved: list[dict] = []

        def _save(**kw):
            order.append("save_result")
            saved.append(kw)

        monkeypatch.setattr(transcription, "save_result", _save)
        calls = self._run(monkeypatch, tmp_path, dispatch=self._ok_dispatch)
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

        def _boom(**kw):
            raise RuntimeError("disk full")

        monkeypatch.setattr(transcription, "save_result", _boom)
        monkeypatch.setattr(
            transcription, "mark_failed", lambda jid, msg: failed.append((jid, msg))
        )
        self._run(monkeypatch, tmp_path, dispatch=self._ok_dispatch)

        assert failed and "persist" in failed[0][1].lower()
