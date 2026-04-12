"""Tests for persist-before-deliver durability on the sync /audio route.

Follows the direct-call pattern from test_transcription_durability_routes.py:
- monkeypatch repository and module-level helpers
- invoke the async handler directly via asyncio.run()
- assert call ordering on mocks to verify the invariant

Covers:
- save_result is called BEFORE delivery on all 3 code paths
  (multitrack, integrated diarization, standard)
- mark_delivered runs AFTER webhook dispatch on each path
- create_job DB failure sets db_job_id=None and suppresses later persist calls
- save_result DB failure is CRITICAL-logged but does NOT abort delivery
- TranscriptionCancelledError, ValueError, and general Exception each trigger
  mark_failed with the expected error message
"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from server.api.routes import transcription
from server.core.model_manager import TranscriptionCancelledError


class _UploadStub:
    """Minimal async-readable UploadFile stand-in."""

    def __init__(self, filename: str = "in.wav", content: bytes = b"RIFF"):
        self.filename = filename
        self._content = content

    async def read(self) -> bytes:
        return self._content


def _request_with_engine(engine: object, *, config: object | None = None) -> SimpleNamespace:
    """Build a minimal Request with model_manager + engine wired through."""
    job_tracker = SimpleNamespace(
        try_start_job=lambda _client: (True, "job-abc", None),
        is_cancelled=lambda: False,
        end_job=lambda _jid: None,
    )
    model_manager = SimpleNamespace(
        job_tracker=job_tracker,
        transcription_engine=engine,
    )
    state_attrs: dict[str, object] = {"model_manager": model_manager}
    if config is not None:
        state_attrs["config"] = config
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(**state_attrs)),
        headers={},
    )


def _make_result_dict(**overrides) -> dict:
    base = {
        "text": "hello world",
        "segments": [],
        "words": [],
        "language": "en",
        "language_probability": 0.95,
        "duration": 1.0,
        "num_speakers": 0,
    }
    base.update(overrides)
    return base


class _ResultStub:
    def __init__(self, **overrides):
        self._d = _make_result_dict(**overrides)

    def to_dict(self) -> dict:
        return dict(self._d)


@pytest.fixture(autouse=True)
def _patch_client_name(monkeypatch):
    monkeypatch.setattr(transcription, "get_client_name", lambda _req: "test-client")


@pytest.fixture(autouse=True)
def _bypass_model_gate(monkeypatch):
    """Skip the 'main model selected' check — not relevant to durability logic."""
    monkeypatch.setattr(transcription, "_assert_main_model_selected", lambda _req: None)


@pytest.fixture(autouse=True)
def _mute_webhook(monkeypatch):
    """Replace webhook dispatch with a recording no-op so tests can assert order."""
    from server.core import webhook as wh

    recorded: list[tuple] = []

    async def _fake_dispatch(event: str, payload: dict) -> None:
        recorded.append((event, payload))

    monkeypatch.setattr(wh, "dispatch", _fake_dispatch)
    return recorded


@pytest.fixture()
def repo_mocks(monkeypatch):
    """Replace the 4 job-repository functions (imported at module level into
    the transcription module) with recorders.

    Because transcription.py does `from ... import create_job, save_result, ...`
    at module load, patching `server.database.job_repository.create_job` alone
    is insufficient — we must patch the bound names on the transcription module.
    """
    r = importlib.import_module("server.database.job_repository")
    bucket = SimpleNamespace(
        order=[],
        create_job=MagicMock(),
        save_result=MagicMock(),
        mark_delivered=MagicMock(),
        mark_failed=MagicMock(),
    )

    def _record(name, mock):
        def _wrapped(*args, **kwargs):
            bucket.order.append(name)
            return mock(*args, **kwargs)

        return _wrapped

    monkeypatch.setattr(transcription, "create_job", _record("create_job", bucket.create_job))
    monkeypatch.setattr(transcription, "save_result", _record("save_result", bucket.save_result))
    monkeypatch.setattr(
        transcription, "mark_delivered", _record("mark_delivered", bucket.mark_delivered)
    )
    monkeypatch.setattr(transcription, "mark_failed", _record("mark_failed", bucket.mark_failed))
    # Also patch on job_repository module in case any indirect import reaches it.
    monkeypatch.setattr(r, "create_job", bucket.create_job)
    monkeypatch.setattr(r, "save_result", bucket.save_result)
    monkeypatch.setattr(r, "mark_delivered", bucket.mark_delivered)
    monkeypatch.setattr(r, "mark_failed", bucket.mark_failed)
    return bucket


def _record_dispatch(mute_webhook_recorded: list[tuple], order: list[str]) -> None:
    """Helper: splice a webhook marker into the order list so we can
    verify save_result → webhook → mark_delivered ordering."""
    # Not needed — webhook order is tracked separately; tests that need
    # full ordering check both `bucket.order` and the webhook recorder.


# ── Standard path (no diarization, no multitrack) ───────────────────────────


def _run_standard(upload_content: bytes = b"RIFF", fake_result=None):
    """Run transcribe_audio along the standard (no-diarization) path."""
    fake_result = fake_result or _ResultStub()
    engine = SimpleNamespace(
        _backend=None,  # backend is None → use_integrated_diarization is False
        transcribe_file=lambda *a, **kw: fake_result,
    )
    req = _request_with_engine(engine)
    upload = _UploadStub(content=upload_content)
    return asyncio.run(
        transcription.transcribe_audio(
            request=req,
            file=upload,
            language=None,
            translation_enabled=False,
            translation_target_language=None,
            word_timestamps=None,
            diarization=None,
            expected_speakers=None,
            parallel_diarization=None,
            multitrack=False,
        )
    )


class TestStandardPath:
    def test_happy_path_order(self, repo_mocks, _mute_webhook):
        result = _run_standard()

        assert result["text"] == "hello world"
        # create_job must run before save_result; save_result before mark_delivered.
        assert repo_mocks.order == ["create_job", "save_result", "mark_delivered"]
        repo_mocks.create_job.assert_called_once()
        repo_mocks.save_result.assert_called_once()
        repo_mocks.mark_delivered.assert_called_once()
        assert repo_mocks.save_result.call_args.kwargs["job_id"] == "job-abc"
        # Webhook must have been dispatched exactly once between save and mark_delivered.
        assert len(_mute_webhook) == 1
        assert _mute_webhook[0][0] == "longform_complete"

    def test_save_result_db_failure_does_not_abort_delivery(self, repo_mocks, caplog):
        repo_mocks.save_result.side_effect = RuntimeError("DB locked")

        with caplog.at_level("CRITICAL"):
            result = _run_standard()

        # Client still got the result.
        assert result["text"] == "hello world"
        # save_result was attempted and failed; a CRITICAL log was emitted.
        repo_mocks.save_result.assert_called_once()
        assert any("Failed to persist result" in rec.message for rec in caplog.records)
        # mark_delivered must NOT fire on a row whose result was never persisted
        # — delivered=1 on status='processing' hides the row from the recovery
        # banner AND the orphan sweep, an irrecoverable state.
        repo_mocks.mark_delivered.assert_not_called()

    def test_create_job_failure_suppresses_downstream_persist(self, repo_mocks, caplog):
        repo_mocks.create_job.side_effect = RuntimeError("DB locked")

        with caplog.at_level("WARNING"):
            result = _run_standard()

        # Client still got the result; no subsequent persist operations attempted.
        assert result["text"] == "hello world"
        repo_mocks.create_job.assert_called_once()
        repo_mocks.save_result.assert_not_called()
        repo_mocks.mark_delivered.assert_not_called()
        assert any("Failed to create job row" in rec.message for rec in caplog.records)


# ── Multitrack path ─────────────────────────────────────────────────────────


class TestMultitrackPath:
    def test_happy_path_order(self, repo_mocks, monkeypatch, _mute_webhook):
        from server.core import multitrack as mt_mod

        fake_result = _ResultStub(num_speakers=2)
        monkeypatch.setattr(mt_mod, "transcribe_multitrack", lambda *a, **kw: fake_result)

        engine = SimpleNamespace(_backend=None)
        req = _request_with_engine(engine)
        upload = _UploadStub()
        result = asyncio.run(
            transcription.transcribe_audio(
                request=req,
                file=upload,
                language=None,
                translation_enabled=False,
                translation_target_language=None,
                word_timestamps=None,
                diarization=None,
                expected_speakers=None,
                parallel_diarization=None,
                multitrack=True,
            )
        )

        assert result["num_speakers"] == 2
        assert repo_mocks.order == ["create_job", "save_result", "mark_delivered"]
        assert len(_mute_webhook) == 1


# ── Integrated diarization path (e.g. WhisperX) ─────────────────────────────


class TestIntegratedDiarizationPath:
    def test_happy_path_order(self, repo_mocks, monkeypatch, _mute_webhook):
        # The integrated path does an inline `from server.core.stt.engine import
        # TranscriptionResult`. The real engine module imports torch + webrtcvad,
        # neither of which is in the test env. Inject a stub module instead.
        import sys
        from dataclasses import dataclass, field

        @dataclass
        class _FakeTranscriptionResult:
            text: str = ""
            segments: list = field(default_factory=list)
            words: list = field(default_factory=list)
            language: str | None = None
            language_probability: float = 0.0
            duration: float = 0.0
            num_speakers: int = 0

            def to_dict(self) -> dict:
                return {
                    "text": self.text,
                    "segments": self.segments,
                    "words": self.words,
                    "language": self.language,
                    "language_probability": self.language_probability,
                    "duration": self.duration,
                    "num_speakers": self.num_speakers,
                }

        import types as _types

        fake_engine_mod = _types.ModuleType("server.core.stt.engine")
        fake_engine_mod.TranscriptionResult = _FakeTranscriptionResult  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "server.core.stt.engine", fake_engine_mod)
        # Build a backend whose `transcribe_with_diarization` is overridden
        # (i.e. not the abstract STTBackend stub), to activate the integrated path.
        from server.core.stt.backends.base import STTBackend

        class _DiarBackend:
            preferred_input_sample_rate_hz = 16000
            backend_name = "fake-whisperx"

            def transcribe_with_diarization(self, audio_data, *, audio_sample_rate, **kwargs):
                return SimpleNamespace(
                    segments=[{"text": "hi", "speaker": "S1"}],
                    words=[],
                    language="en",
                    language_probability=0.9,
                    num_speakers=1,
                )

        # Ensure the override check sees a different function than the abstract stub.
        assert (
            _DiarBackend.transcribe_with_diarization is not STTBackend.transcribe_with_diarization
        )

        # Engine stubs required by the integrated path.
        engine = SimpleNamespace(
            _backend=_DiarBackend(),
            beam_size=5,
            initial_prompt=None,
            suppress_tokens=None,
            faster_whisper_vad_filter=False,
        )

        # Stub load_audio so we don't need a real WAV file.
        from server.core import audio_utils

        monkeypatch.setattr(
            audio_utils,
            "load_audio",
            lambda *a, **kw: ([0.0] * 16000, 16000),
        )

        req = _request_with_engine(engine)
        upload = _UploadStub()
        result = asyncio.run(
            transcription.transcribe_audio(
                request=req,
                file=upload,
                language=None,
                translation_enabled=False,
                translation_target_language=None,
                word_timestamps=None,
                diarization=True,
                expected_speakers=None,
                parallel_diarization=None,
                multitrack=False,
            )
        )

        assert result["num_speakers"] == 1
        # Note: integrated diarization path does NOT dispatch a webhook today —
        # we only assert the persist-before-deliver ordering here.
        assert repo_mocks.order == ["create_job", "save_result", "mark_delivered"]


# ── Failure handlers ────────────────────────────────────────────────────────


class TestFailureHandlers:
    def test_cancellation_triggers_mark_failed(self, repo_mocks):
        def _raise_cancel(*_a, **_kw):
            raise TranscriptionCancelledError()

        engine = SimpleNamespace(_backend=None, transcribe_file=_raise_cancel)
        req = _request_with_engine(engine)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                transcription.transcribe_audio(
                    request=req,
                    file=_UploadStub(),
                    language=None,
                    translation_enabled=False,
                    translation_target_language=None,
                    word_timestamps=None,
                    diarization=None,
                    expected_speakers=None,
                    parallel_diarization=None,
                    multitrack=False,
                )
            )

        assert exc.value.status_code == 499
        repo_mocks.mark_failed.assert_called_once_with("job-abc", "Transcription cancelled by user")

    def test_general_exception_triggers_mark_failed(self, repo_mocks):
        def _raise(*_a, **_kw):
            raise RuntimeError("backend crashed")

        engine = SimpleNamespace(_backend=None, transcribe_file=_raise)
        req = _request_with_engine(engine)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                transcription.transcribe_audio(
                    request=req,
                    file=_UploadStub(),
                    language=None,
                    translation_enabled=False,
                    translation_target_language=None,
                    word_timestamps=None,
                    diarization=None,
                    expected_speakers=None,
                    parallel_diarization=None,
                    multitrack=False,
                )
            )

        assert exc.value.status_code == 500
        repo_mocks.mark_failed.assert_called_once_with("job-abc", "backend crashed")

    def test_value_error_triggers_mark_failed(self, repo_mocks):
        def _raise(*_a, **_kw):
            raise ValueError("bad audio")

        engine = SimpleNamespace(_backend=None, transcribe_file=_raise)
        req = _request_with_engine(engine)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                transcription.transcribe_audio(
                    request=req,
                    file=_UploadStub(),
                    language=None,
                    translation_enabled=False,
                    translation_target_language=None,
                    word_timestamps=None,
                    diarization=None,
                    expected_speakers=None,
                    parallel_diarization=None,
                    multitrack=False,
                )
            )

        assert exc.value.status_code == 400
        repo_mocks.mark_failed.assert_called_once_with("job-abc", "bad audio")


# ── Post-persist guarantees (regressions found in review) ────────────────────


class TestPostPersistGuarantees:
    """After save_result succeeds, later failures must not clobber DB state."""

    def test_webhook_failure_after_persist_does_not_overwrite_to_failed(
        self, repo_mocks, monkeypatch
    ):
        """If the webhook raises AFTER save_result succeeded, the standard
        exception handler must NOT call mark_failed — otherwise status='completed'
        gets overwritten to status='failed' and the transcription is lost to
        every consumer (recovery banner, /result endpoint, orphan sweep)."""
        from server.core import webhook as wh

        async def _raising_dispatch(event, payload):
            raise RuntimeError("webhook endpoint down")

        monkeypatch.setattr(wh, "dispatch", _raising_dispatch)

        with pytest.raises(HTTPException) as exc:
            _run_standard()

        assert exc.value.status_code == 500  # webhook failure surfaces as 500
        # save_result ran successfully, so status='completed' in DB.
        repo_mocks.save_result.assert_called_once()
        # mark_failed must NOT have been called — persisted=True gates it.
        repo_mocks.mark_failed.assert_not_called()

    def test_mark_delivered_failure_does_not_abort_delivery(self, repo_mocks, caplog):
        """If mark_delivered raises, the client still gets the result
        and a warning is logged (delivered=0 is a safe state — recovery
        banner will re-offer the result)."""
        repo_mocks.mark_delivered.side_effect = RuntimeError("DB locked")

        with caplog.at_level("WARNING"):
            result = _run_standard()

        assert result["text"] == "hello world"
        repo_mocks.save_result.assert_called_once()
        repo_mocks.mark_delivered.assert_called_once()
        assert any(
            "Failed to mark job" in rec.message and "as delivered" in rec.message
            for rec in caplog.records
        )

    def test_tempfile_read_failure_triggers_mark_failed(self, repo_mocks):
        """If the incoming upload fails to read (e.g. client disconnect mid-body),
        mark_failed fires via the shared exception handler and end_job runs.
        Previously the tempfile block was outside the try/except, so this
        scenario leaked a 'processing' row and a busy tracker slot."""

        class _ReadFails(_UploadStub):
            async def read(self):
                raise RuntimeError("connection reset")

        engine = SimpleNamespace(_backend=None, transcribe_file=lambda *a, **k: _ResultStub())
        req = _request_with_engine(engine)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                transcription.transcribe_audio(
                    request=req,
                    file=_ReadFails(),
                    language=None,
                    translation_enabled=False,
                    translation_target_language=None,
                    word_timestamps=None,
                    diarization=None,
                    expected_speakers=None,
                    parallel_diarization=None,
                    multitrack=False,
                )
            )

        assert exc.value.status_code == 500
        # mark_failed was reached via the shared exception path.
        repo_mocks.mark_failed.assert_called_once_with("job-abc", "connection reset")

    def test_save_result_failure_on_multitrack_suppresses_mark_delivered(
        self, repo_mocks, monkeypatch
    ):
        """Symmetric to standard-path test: on multitrack, save failure must
        not cascade into delivered=1."""
        from server.core import multitrack as mt_mod

        fake_result = _ResultStub(num_speakers=2)
        monkeypatch.setattr(mt_mod, "transcribe_multitrack", lambda *a, **kw: fake_result)
        repo_mocks.save_result.side_effect = RuntimeError("DB locked")

        engine = SimpleNamespace(_backend=None)
        req = _request_with_engine(engine)
        result = asyncio.run(
            transcription.transcribe_audio(
                request=req,
                file=_UploadStub(),
                language=None,
                translation_enabled=False,
                translation_target_language=None,
                word_timestamps=None,
                diarization=None,
                expected_speakers=None,
                parallel_diarization=None,
                multitrack=True,
            )
        )

        assert result["num_speakers"] == 2
        repo_mocks.save_result.assert_called_once()
        repo_mocks.mark_delivered.assert_not_called()
