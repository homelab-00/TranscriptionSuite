"""Tests for GH-211 phase transitions at the orchestration seams.

Covers:
- ``_run_file_import`` reports ``loading_model`` then ``transcribing`` on the
  plain (non-diarized) path, using the direct-call pattern from
  ``test_transcription_durability_routes.py`` with a real
  ``TranscriptionJobTracker`` wrapped by a phase spy.
- ``transcribe_then_diarize`` reports ``transcribing`` then ``diarizing``.
- ``transcribe_and_diarize`` reports ``transcribing_diarizing`` for the
  parallel path.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from server.api.routes.transcription import _run_file_import
from server.core.model_manager import TranscriptionJobTracker
from server.core.parallel_diarize import transcribe_and_diarize, transcribe_then_diarize

# ── Helpers ───────────────────────────────────────────────────────────────────


class _PhaseSpyTracker(TranscriptionJobTracker):
    """Real tracker that also records every phase passed to set_phase."""

    def __init__(self):
        super().__init__()
        self.phases: list[str] = []

    def set_phase(self, phase: str) -> None:
        self.phases.append(phase)
        super().set_phase(phase)


def _spy_model_manager() -> tuple[MagicMock, _PhaseSpyTracker]:
    tracker = _PhaseSpyTracker()
    mm = MagicMock()
    mm.job_tracker = tracker
    return mm, tracker


# ── _run_file_import ──────────────────────────────────────────────────────────


def test_run_file_import_reports_loading_model_then_transcribing(tmp_path):
    audio_file = tmp_path / "memo.wav"
    audio_file.write_bytes(b"fake audio")

    mm, tracker = _spy_model_manager()
    ok, job_id, _ = tracker.try_start_job("test-client")
    assert ok

    engine = MagicMock()
    engine.transcribe_file.return_value.to_dict.return_value = {"text": "hi"}
    mm.ensure_transcription_loaded.return_value = engine

    _run_file_import(
        model_manager=mm,
        tmp_path=audio_file,
        filename="memo.wav",
        language=None,
        translation_enabled=False,
        translation_target_language=None,
        enable_diarization=False,
        enable_word_timestamps=True,
        expected_speakers=None,
        parallel_diarization=None,
        use_parallel_default=False,
        multitrack=False,
        job_id=job_id,
        event_loop=None,
    )

    assert tracker.phases == ["loading_model", "transcribing"]
    # end_job clears the tracker state after success
    assert tracker.get_status()["is_busy"] is False


# ── transcribe_then_diarize ───────────────────────────────────────────────────


@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_sequential_orchestrator_reports_transcribing_then_diarizing(mock_load_audio):
    mm, tracker = _spy_model_manager()
    engine = MagicMock()
    engine.transcribe_file.return_value = MagicMock(words=[], segments=[])
    diar_result = MagicMock()
    diar_result.num_speakers = 2
    mm.diarization_engine.diarize_audio.return_value = diar_result

    result, diar = transcribe_then_diarize(
        engine=engine,
        model_manager=mm,
        file_path="/tmp/fake.wav",
    )

    assert diar is diar_result
    assert tracker.phases == ["transcribing", "diarizing"]


# ── transcribe_and_diarize ────────────────────────────────────────────────────


@patch("server.core.audio_utils.load_audio", return_value=(MagicMock(), 16000))
def test_parallel_orchestrator_reports_transcribing_diarizing(mock_load_audio):
    mm, tracker = _spy_model_manager()
    engine = MagicMock()
    engine.transcribe_file.return_value = MagicMock(words=[], segments=[])
    diar_result = MagicMock()
    diar_result.num_speakers = 2
    mm.diarization_engine.diarize_audio.return_value = diar_result

    result, diar = transcribe_and_diarize(
        engine=engine,
        model_manager=mm,
        file_path="/tmp/fake.wav",
    )

    assert diar is diar_result
    assert tracker.phases == ["transcribing_diarizing"]
