"""Route-level recovery tests for Issue #76.

Verifies that ``notebook._run_transcription`` and
``transcription._run_file_import`` call
``model_manager.ensure_transcription_loaded()`` instead of grabbing the
``transcription_engine`` property directly, and that
``BackendDependencyError`` produces an actionable ``remedy`` field in the
job-tracker result so the dashboard can render an actionable hint.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _make_engine() -> SimpleNamespace:
    """Fake AudioToTextRecorder with a non-None backend."""
    backend = MagicMock()
    backend.backend_name = "whisper"
    backend.transcribe_with_diarization = None  # falsy attr (not the base method)
    return SimpleNamespace(
        _backend=backend,
        model_name="tiny",
        beam_size=5,
        is_loaded=lambda: True,
        transcribe_file=MagicMock(
            return_value=SimpleNamespace(
                text="hello",
                segments=[],
                words=[],
                language="en",
                language_probability=0.99,
                duration=1.5,
                num_speakers=0,
                to_dict=lambda: {
                    "text": "hello",
                    "segments": [],
                    "words": [],
                    "language": "en",
                    "language_probability": 0.99,
                    "duration": 1.5,
                    "num_speakers": 0,
                },
            )
        ),
    )


class _JobTracker:
    def __init__(self):
        self.results: dict[str, dict] = {}
        self.cancelled = False

    def end_job(self, job_id, result=None):
        self.results[job_id] = result or {}

    def update_progress(self, *_a, **_kw):
        pass

    def is_cancelled(self):
        return self.cancelled


class _ModelManager:
    """Stub model manager that records ensure_transcription_loaded calls."""

    def __init__(self, engine, *, dep_error=None):
        self._engine = engine
        self._dep_error = dep_error
        self.ensure_calls = 0
        self.job_tracker = _JobTracker()

    def ensure_transcription_loaded(self):
        self.ensure_calls += 1
        if self._dep_error is not None:
            raise self._dep_error
        return self._engine

    def get_diarization_feature_status(self):
        return {"available": False, "reason": "not_requested"}


# ─────────────────────────────────────────────────────────────────────────────
# Notebook upload (_run_transcription)
# ─────────────────────────────────────────────────────────────────────────────


class TestNotebookRunTranscription:
    def test_calls_ensure_transcription_loaded_not_property(self, tmp_path: Path, monkeypatch):
        """Healthy path: ensure_transcription_loaded() is the entry point."""
        from server.api.routes import notebook as nb_route

        # Redirect the audio output dir into tmp so mkdir() doesn't try /data.
        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        # Stub the heavy bits that _run_transcription tries to do AFTER
        # the engine is acquired (audio decoding, MP3 encode, DB save).
        monkeypatch.setattr(
            nb_route,
            "save_longform_to_database",
            lambda **_kw: 42,
        )
        monkeypatch.setattr(
            nb_route,
            "check_time_slot_overlap",
            lambda *_a, **_kw: None,
        )
        # Stub convert_to_mp3 in the lazy-import location used by the route.
        import server.core.audio_utils as au

        monkeypatch.setattr(au, "convert_to_mp3", lambda *_a, **_kw: None)

        engine = _make_engine()
        mgr = _ModelManager(engine)

        # Real tmp file path (won't be unlinked because tmp_path fixture cleans up)
        tmp_file = tmp_path / "input.wav"
        tmp_file.write_bytes(b"\x00" * 1024)

        nb_route._run_transcription(
            model_manager=mgr,
            tmp_path=tmp_file,
            filename="input.wav",
            language=None,
            translation_enabled=False,
            translation_target_language=None,
            enable_diarization=False,
            enable_word_timestamps=True,
            file_created_at=None,
            expected_speakers=None,
            parallel_diarization=None,
            use_parallel_default=False,
            title=None,
            job_id="job-recovery-1",
            event_loop=None,
        )

        assert mgr.ensure_calls == 1
        # job_id is truncated to 8 chars in the result (job-recovery-1 → job-reco).
        result = mgr.job_tracker.results["job-recovery-1"]
        assert "error" not in result, f"expected success, got error: {result}"
        assert result["recording_id"] == 42

    def test_dependency_error_attaches_remedy_to_result(self, tmp_path: Path):
        """BackendDependencyError -> result includes ``remedy`` and ``backend_type``."""
        from server.api.routes import notebook as nb_route
        from server.core.stt.backends.base import BackendDependencyError

        dep_err = BackendDependencyError(
            "NeMo toolkit is required for NVIDIA Parakeet models but is not installed",
            backend_type="nemo",
            remedy="Set INSTALL_NEMO=true in your Docker environment and restart.",
        )
        mgr = _ModelManager(engine=None, dep_error=dep_err)

        tmp_file = tmp_path / "input.wav"
        tmp_file.write_bytes(b"\x00" * 1024)

        nb_route._run_transcription(
            model_manager=mgr,
            tmp_path=tmp_file,
            filename="input.wav",
            language=None,
            translation_enabled=False,
            translation_target_language=None,
            enable_diarization=False,
            enable_word_timestamps=True,
            file_created_at=None,
            expected_speakers=None,
            parallel_diarization=None,
            use_parallel_default=False,
            title=None,
            job_id="job-dep-err",
            event_loop=None,
        )

        result = mgr.job_tracker.results["job-dep-err"]
        # The bare error string is the BackendDependencyError message; the
        # remedy is the actionable hint surfaced separately.
        assert "NeMo toolkit" in result["error"]
        assert "INSTALL_NEMO" in result["remedy"]
        assert result["backend_type"] == "nemo"

    def test_mp3_conversion_failure_preserves_transcript(self, tmp_path: Path, monkeypatch):
        """FINDING #2: if MP3 conversion fails (e.g. ffmpeg is absent on a stock
        macOS install), the COMPLETED transcript must still be saved by falling
        back to storing the original audio — never discarded (persist-before-deliver).
        """
        import server.core.audio_utils as au
        from server.api.routes import notebook as nb_route

        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        saved: dict = {}

        def _save(**kw):
            saved.update(kw)
            return 99

        monkeypatch.setattr(nb_route, "save_longform_to_database", _save)
        monkeypatch.setattr(nb_route, "check_time_slot_overlap", lambda *_a, **_kw: None)

        # MP3 conversion fails exactly as it does when ffmpeg is not installed.
        def _boom(*_a, **_kw):
            raise RuntimeError("ffmpeg is not installed or not in PATH")

        monkeypatch.setattr(au, "convert_to_mp3", _boom)

        engine = _make_engine()
        mgr = _ModelManager(engine)

        tmp_file = tmp_path / "input.wav"
        tmp_file.write_bytes(b"\x00" * 2048)

        nb_route._run_transcription(
            model_manager=mgr,
            tmp_path=tmp_file,
            filename="input.wav",
            language=None,
            translation_enabled=False,
            translation_target_language=None,
            enable_diarization=False,
            enable_word_timestamps=True,
            file_created_at=None,
            expected_speakers=None,
            parallel_diarization=None,
            use_parallel_default=False,
            title=None,
            job_id="job-mp3-fallback",
            event_loop=None,
        )

        result = mgr.job_tracker.results["job-mp3-fallback"]
        assert "error" not in result, f"transcript lost on MP3 failure: {result}"
        assert result["recording_id"] == 99
        # The fallback stored the ORIGINAL audio so the transcript could be saved.
        stored = Path(saved["audio_path"])
        assert stored.exists()
        assert stored.suffix == ".wav"
        # Original audio bytes were copied verbatim (durability goal, not a no-op
        # touch). tmp_file is cleaned up by _run_transcription, so compare to the
        # known content rather than re-reading the (now-deleted) source.
        assert stored.read_bytes() == b"\x00" * 2048

    def test_mp3_fallback_dedups_colliding_filename(self, tmp_path: Path, monkeypatch):
        """The fallback's de-collision loop must not overwrite an existing stored
        original-audio file (data-loss-adjacent)."""
        import server.core.audio_utils as au
        from server.api.routes import notebook as nb_route

        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        # Pre-create a colliding original so the fallback must pick input-2.wav.
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / "input.wav").write_bytes(b"pre-existing")

        saved: dict = {}

        def _save(**kw):
            saved.update(kw)
            return 7

        monkeypatch.setattr(nb_route, "save_longform_to_database", _save)
        monkeypatch.setattr(nb_route, "check_time_slot_overlap", lambda *_a, **_kw: None)

        def _boom(*_a, **_kw):
            raise RuntimeError("ffmpeg is not installed or not in PATH")

        monkeypatch.setattr(au, "convert_to_mp3", _boom)

        mgr = _ModelManager(_make_engine())
        tmp_file = tmp_path / "input.wav"
        tmp_file.write_bytes(b"\x01" * 1024)

        nb_route._run_transcription(
            model_manager=mgr,
            tmp_path=tmp_file,
            filename="input.wav",
            language=None,
            translation_enabled=False,
            translation_target_language=None,
            enable_diarization=False,
            enable_word_timestamps=True,
            file_created_at=None,
            expected_speakers=None,
            parallel_diarization=None,
            use_parallel_default=False,
            title=None,
            job_id="job-mp3-collide",
            event_loop=None,
        )

        stored = Path(saved["audio_path"])
        assert stored.name == "input-2.wav"
        # The pre-existing file was NOT clobbered.
        assert (audio_dir / "input.wav").read_bytes() == b"pre-existing"
        assert stored.read_bytes() == b"\x01" * 1024


# ─────────────────────────────────────────────────────────────────────────────
# File import (_run_file_import)
# ─────────────────────────────────────────────────────────────────────────────


class TestFileImportRunFileImport:
    def test_calls_ensure_transcription_loaded_not_property(self, tmp_path: Path):
        """Healthy path: ensure_transcription_loaded() is the entry point."""
        from server.api.routes import transcription as tx_route

        engine = _make_engine()
        mgr = _ModelManager(engine)

        tmp_file = tmp_path / "input.wav"
        tmp_file.write_bytes(b"\x00" * 1024)

        tx_route._run_file_import(
            model_manager=mgr,
            tmp_path=tmp_file,
            filename="input.wav",
            language=None,
            translation_enabled=False,
            translation_target_language=None,
            enable_diarization=False,
            enable_word_timestamps=True,
            expected_speakers=None,
            parallel_diarization=None,
            use_parallel_default=False,
            multitrack=False,
            job_id="job-import-recovery",
            event_loop=None,
        )

        assert mgr.ensure_calls == 1
        result = mgr.job_tracker.results["job-import-recovery"]
        assert "error" not in result
        assert "transcription" in result

    def test_dependency_error_attaches_remedy_to_result(self, tmp_path: Path):
        """BackendDependencyError on import -> result includes remedy/backend_type."""
        from server.api.routes import transcription as tx_route
        from server.core.stt.backends.base import BackendDependencyError

        dep_err = BackendDependencyError(
            "VibeVoice-ASR backend selected but compatible VibeVoice-ASR modules could not be imported",
            backend_type="vibevoice_asr",
            remedy="Install VibeVoice-ASR optional dependency (see Settings → About).",
        )
        mgr = _ModelManager(engine=None, dep_error=dep_err)

        tmp_file = tmp_path / "input.wav"
        tmp_file.write_bytes(b"\x00" * 1024)

        tx_route._run_file_import(
            model_manager=mgr,
            tmp_path=tmp_file,
            filename="input.wav",
            language=None,
            translation_enabled=False,
            translation_target_language=None,
            enable_diarization=False,
            enable_word_timestamps=True,
            expected_speakers=None,
            parallel_diarization=None,
            use_parallel_default=False,
            multitrack=False,
            job_id="job-import-dep-err",
            event_loop=None,
        )

        result = mgr.job_tracker.results["job-import-dep-err"]
        assert "VibeVoice-ASR" in result["error"]
        assert result["remedy"] == dep_err.remedy
        assert result["backend_type"] == "vibevoice_asr"


# ─────────────────────────────────────────────────────────────────────────────
# Live-mode reload visibility (Issue #76 secondary fix)
# ─────────────────────────────────────────────────────────────────────────────


class TestReloadMainModelVisibility:
    @pytest.mark.asyncio
    async def test_dependency_error_emits_warn_event_and_does_not_raise(self, monkeypatch):
        """BackendDependencyError on reload -> warning logged, event emitted, no raise."""
        from server.api.routes import live as live_route
        from server.core.stt.backends.base import BackendDependencyError

        dep_err = BackendDependencyError(
            "NeMo toolkit is required for NVIDIA Parakeet models but is not installed",
            backend_type="nemo",
            remedy="Set INSTALL_NEMO=true and restart.",
        )

        events: list[tuple] = []

        def fake_emit(*args, **kwargs):
            events.append((args, kwargs))

        # Patch in the lazy-import location used inside _reload_main_model.
        import server.core.startup_events as se

        monkeypatch.setattr(se, "emit_event", fake_emit)

        fake_mm = SimpleNamespace(
            load_transcription_model=MagicMock(side_effect=dep_err),
        )
        monkeypatch.setattr(live_route, "get_model_manager", lambda: fake_mm)

        # Construct a minimal session and call the private method directly.
        session = live_route.LiveModeSession.__new__(live_route.LiveModeSession)
        session.client_name = "test-client"

        # Should NOT raise — dependency errors are graceful.
        await session._reload_main_model()

        assert any("warn-stt-main" in str(args) for args, _ in events), (
            "Expected emit_event('warn-stt-main', ...) to be called"
        )

    @pytest.mark.asyncio
    async def test_generic_error_emits_event_and_reraises(self, monkeypatch):
        """Non-dependency reload failure -> event emitted AND exception re-raised."""
        from server.api.routes import live as live_route

        events: list[tuple] = []

        def fake_emit(*args, **kwargs):
            events.append((args, kwargs))

        import server.core.startup_events as se

        monkeypatch.setattr(se, "emit_event", fake_emit)

        fake_mm = SimpleNamespace(
            load_transcription_model=MagicMock(side_effect=RuntimeError("CUDA out of memory")),
        )
        monkeypatch.setattr(live_route, "get_model_manager", lambda: fake_mm)

        session = live_route.LiveModeSession.__new__(live_route.LiveModeSession)
        session.client_name = "test-client"

        with pytest.raises(RuntimeError, match="CUDA out of memory"):
            await session._reload_main_model()

        assert any("warn-stt-main" in str(args) for args, _ in events), (
            "Expected emit_event('warn-stt-main', ...) to be called for non-dep errors too"
        )
