"""Tests for the shared transcribe-with-optional-diarization dispatch (GH-258)."""

from __future__ import annotations

import sys
import types as _types
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from server.core.diarization_dispatch import (
    DiarizationOutcome,
    transcribe_with_optional_diarization,
)
from server.core.model_manager import TranscriptionCancelledError


@dataclass
class _FakeTranscriptionResult:
    """Stand-in for TranscriptionResult (the real module imports torch)."""

    text: str = ""
    segments: list[dict[str, Any]] = field(default_factory=list)
    words: list[dict[str, Any]] = field(default_factory=list)
    language: str | None = None
    language_probability: float = 0.0
    duration: float = 0.0
    num_speakers: int = 0


@pytest.fixture
def fake_engine_module(monkeypatch):
    """Stub ``server.core.stt.engine`` for the integrated path.

    ``_run_integrated`` does an inline ``from server.core.stt.engine import
    TranscriptionResult``; the real module imports torch and webrtcvad, neither
    of which is in the test environment.
    """
    module = _types.ModuleType("server.core.stt.engine")
    module.TranscriptionResult = _FakeTranscriptionResult  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "server.core.stt.engine", module)
    return module


def _plain_result(text="hello world"):
    return _FakeTranscriptionResult(
        text=text,
        segments=[{"text": text, "start": 0.0, "end": 1.0}],
        words=[{"word": "hello", "start": 0.0, "end": 0.5}],
        duration=1.0,
    )


def _make_engine(result=None, side_effect=None, backend=None):
    engine = MagicMock()
    engine.model_name = "large-v3"
    engine.beam_size = 5
    # Default to None, NOT a MagicMock: the real use_integrated_diarization_for
    # reads `type(backend).transcribe_with_diarization`, and the MagicMock CLASS
    # has no such attribute, so a mock backend raises AttributeError. None short-
    # circuits the check to False, which is what the standard-path tests want.
    engine._backend = backend
    if side_effect is not None:
        engine.transcribe_file.side_effect = side_effect
    else:
        engine.transcribe_file.return_value = result or _plain_result()
    return engine


def _make_model_manager(reason="unavailable"):
    mm = MagicMock()
    mm.get_diarization_feature_status.return_value = {"available": False, "reason": reason}
    return mm


def test_diarization_off_runs_plain_transcription_and_reports_not_requested():
    expected = _plain_result()
    engine = _make_engine(result=expected)

    dispatched = transcribe_with_optional_diarization(
        engine=engine,
        model_manager=_make_model_manager(),
        file_path="/tmp/a.wav",
        enable_diarization=False,
    )

    assert dispatched.result is expected
    assert dispatched.speaker_segments is None
    assert dispatched.outcome == DiarizationOutcome(requested=False, performed=False)
    engine.transcribe_file.assert_called_once()


def test_diarization_forces_word_timestamps_even_when_the_caller_said_no():
    engine = _make_engine()
    mm = _make_model_manager()
    diar_result = MagicMock(segments=[], num_speakers=0)

    with patch(
        "server.core.parallel_diarize.transcribe_and_diarize",
        return_value=(_plain_result(), diar_result),
    ) as diarize_fn:
        transcribe_with_optional_diarization(
            engine=engine,
            model_manager=mm,
            file_path="/tmp/a.wav",
            enable_diarization=True,
            word_timestamps=False,
            parallel_diarization=True,
        )

    assert diarize_fn.call_args.kwargs["word_timestamps"] is True


def test_standard_path_merges_speakers_onto_the_result():
    base = _plain_result()
    diar_seg = MagicMock()
    diar_seg.to_dict.return_value = {"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0}
    diar_result = MagicMock(segments=[diar_seg], num_speakers=1)

    merged_segments = [{"text": "hello world", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]
    merged_words = [{"word": "hello", "start": 0.0, "end": 0.5, "speaker": "SPEAKER_00"}]

    with (
        patch(
            "server.core.parallel_diarize.transcribe_and_diarize",
            return_value=(base, diar_result),
        ),
        patch(
            "server.core.speaker_merge.build_speaker_segments",
            return_value=(merged_segments, merged_words, 1),
        ),
    ):
        dispatched = transcribe_with_optional_diarization(
            engine=_make_engine(),
            model_manager=_make_model_manager(),
            file_path="/tmp/a.wav",
            enable_diarization=True,
            parallel_diarization=True,
        )

    assert dispatched.result.segments == merged_segments
    assert dispatched.result.num_speakers == 1
    assert dispatched.speaker_segments == [{"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0}]
    assert dispatched.outcome.performed is True
    assert dispatched.outcome.reason == "ready"


def test_sequential_path_is_chosen_when_parallel_is_false():
    diar_result = MagicMock(segments=[], num_speakers=0)

    with (
        patch(
            "server.core.parallel_diarize.transcribe_then_diarize",
            return_value=(_plain_result(), diar_result),
        ) as sequential,
        patch("server.core.parallel_diarize.transcribe_and_diarize") as parallel,
    ):
        transcribe_with_optional_diarization(
            engine=_make_engine(),
            model_manager=_make_model_manager(),
            file_path="/tmp/a.wav",
            enable_diarization=True,
            parallel_diarization=False,
        )

    sequential.assert_called_once()
    parallel.assert_not_called()


def test_diarization_returning_none_degrades_with_the_feature_status_reason():
    base = _plain_result()

    with patch(
        "server.core.parallel_diarize.transcribe_and_diarize",
        return_value=(base, None),
    ):
        dispatched = transcribe_with_optional_diarization(
            engine=_make_engine(),
            model_manager=_make_model_manager(reason="token_missing"),
            file_path="/tmp/a.wav",
            enable_diarization=True,
            parallel_diarization=True,
        )

    assert dispatched.result is base
    assert dispatched.speaker_segments is None
    assert dispatched.outcome.performed is False
    assert dispatched.outcome.reason == "token_missing"


def test_observed_out_of_memory_is_classified_with_a_remedy():
    base = _plain_result()

    def _fake_diarize(*_args, on_diarization_error=None, **_kwargs):
        on_diarization_error(RuntimeError("CUDA failed with error out of memory"))
        return base, None

    with patch("server.core.parallel_diarize.transcribe_and_diarize", _fake_diarize):
        dispatched = transcribe_with_optional_diarization(
            engine=_make_engine(),
            model_manager=_make_model_manager(),
            file_path="/tmp/a.wav",
            enable_diarization=True,
            parallel_diarization=True,
        )

    assert dispatched.outcome.reason == "out_of_memory"
    assert dispatched.outcome.remedy
    assert "VRAM" in dispatched.outcome.remedy


def test_broken_diarization_segment_conversion_degrades_instead_of_losing_the_transcript():
    """GH-274 review finding: `seg.to_dict()` sits before the merge guard — a
    broken diarization payload must degrade, never discard a completed
    transcript (persist-before-deliver invariant)."""
    base = _plain_result()
    bad_seg = MagicMock()
    bad_seg.to_dict.side_effect = TypeError("start is None")

    with patch(
        "server.core.parallel_diarize.transcribe_and_diarize",
        return_value=(base, MagicMock(segments=[bad_seg], num_speakers=1)),
    ):
        dispatched = transcribe_with_optional_diarization(
            engine=_make_engine(),
            model_manager=_make_model_manager(),
            file_path="/tmp/a.wav",
            enable_diarization=True,
            parallel_diarization=True,
        )

    assert dispatched.result is base
    assert dispatched.speaker_segments is None
    assert dispatched.outcome.performed is False


def test_speaker_merge_failure_degrades_instead_of_raising():
    base = _plain_result()
    diar_seg = MagicMock()
    diar_seg.to_dict.return_value = {"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0}

    with (
        patch(
            "server.core.parallel_diarize.transcribe_and_diarize",
            return_value=(base, MagicMock(segments=[diar_seg], num_speakers=1)),
        ),
        patch(
            "server.core.speaker_merge.build_speaker_segments",
            side_effect=RuntimeError("merge exploded"),
        ),
    ):
        dispatched = transcribe_with_optional_diarization(
            engine=_make_engine(),
            model_manager=_make_model_manager(),
            file_path="/tmp/a.wav",
            enable_diarization=True,
            parallel_diarization=True,
        )

    assert dispatched.result is base
    assert dispatched.outcome.performed is False


def test_cancellation_propagates_rather_than_degrading():
    with patch(
        "server.core.parallel_diarize.transcribe_and_diarize",
        side_effect=TranscriptionCancelledError("cancelled"),
    ):
        with pytest.raises(TranscriptionCancelledError):
            transcribe_with_optional_diarization(
                engine=_make_engine(),
                model_manager=_make_model_manager(),
                file_path="/tmp/a.wav",
                enable_diarization=True,
                parallel_diarization=True,
            )


def test_plain_transcription_failure_propagates():
    engine = _make_engine(side_effect=RuntimeError("model exploded"))

    with pytest.raises(RuntimeError, match="model exploded"):
        transcribe_with_optional_diarization(
            engine=engine,
            model_manager=_make_model_manager(),
            file_path="/tmp/a.wav",
            enable_diarization=False,
        )


def test_integrated_backend_single_pass_path(fake_engine_module):
    backend = MagicMock()
    backend.backend_name = "whisperx"
    backend.preferred_input_sample_rate_hz = 16000
    diar_segments = [{"text": "hi", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]
    backend.transcribe_with_diarization.return_value = MagicMock(
        segments=diar_segments,
        words=[],
        language="en",
        language_probability=0.99,
        num_speakers=1,
    )
    engine = _make_engine(backend=backend)

    with (
        patch("server.core.audio_utils.load_audio", return_value=([0.0] * 16000, 16000)),
        patch("server.core.stt.backends.base.use_integrated_diarization_for", return_value=True),
    ):
        dispatched = transcribe_with_optional_diarization(
            engine=engine,
            model_manager=_make_model_manager(),
            file_path="/tmp/a.wav",
            enable_diarization=True,
        )

    assert dispatched.outcome.performed is True
    assert dispatched.result.num_speakers == 1
    assert dispatched.speaker_segments == diar_segments
    engine.transcribe_file.assert_not_called()


def test_integrated_path_forwards_the_engine_decoding_options(fake_engine_module):
    """Parity with the import route: a recording must decode identically."""
    backend = MagicMock()
    backend.backend_name = "whisperx"
    backend.preferred_input_sample_rate_hz = 16000
    backend.transcribe_with_diarization.return_value = MagicMock(
        segments=[], words=[], language="en", language_probability=0.99, num_speakers=0
    )
    engine = _make_engine(backend=backend)
    engine.initial_prompt = "medical terminology"
    engine.suppress_tokens = [-1]
    engine.faster_whisper_vad_filter = False

    with (
        patch("server.core.audio_utils.load_audio", return_value=([0.0] * 16000, 16000)),
        patch("server.core.stt.backends.base.use_integrated_diarization_for", return_value=True),
    ):
        transcribe_with_optional_diarization(
            engine=engine,
            model_manager=_make_model_manager(),
            file_path="/tmp/a.wav",
            enable_diarization=True,
        )

    kwargs = backend.transcribe_with_diarization.call_args.kwargs
    assert kwargs["initial_prompt"] == "medical terminology"
    assert kwargs["suppress_tokens"] == [-1]
    assert kwargs["vad_filter"] is False


def test_initial_prompt_flows_to_plain_transcription():
    """The OpenAI endpoints forward the client's ``prompt``; it must reach
    ``transcribe_file`` when the plain path runs (GH-274)."""
    engine = _make_engine()

    transcribe_with_optional_diarization(
        engine=engine,
        model_manager=_make_model_manager(),
        file_path="/tmp/a.wav",
        enable_diarization=False,
        initial_prompt="glossary: CUDA, VRAM",
    )

    assert engine.transcribe_file.call_args.kwargs["initial_prompt"] == "glossary: CUDA, VRAM"


def test_initial_prompt_overrides_the_engine_prompt_on_the_integrated_path(fake_engine_module):
    """A caller-supplied prompt wins over the engine's configured one,
    matching the OpenAI route's ``initial_prompt or engine.initial_prompt``."""
    backend = MagicMock()
    backend.backend_name = "whisperx"
    backend.preferred_input_sample_rate_hz = 16000
    backend.transcribe_with_diarization.return_value = MagicMock(
        segments=[], words=[], language="en", language_probability=0.99, num_speakers=0
    )
    engine = _make_engine(backend=backend)
    engine.initial_prompt = "engine default"

    with (
        patch("server.core.audio_utils.load_audio", return_value=([0.0] * 16000, 16000)),
        patch("server.core.stt.backends.base.use_integrated_diarization_for", return_value=True),
    ):
        transcribe_with_optional_diarization(
            engine=engine,
            model_manager=_make_model_manager(),
            file_path="/tmp/a.wav",
            enable_diarization=True,
            initial_prompt="caller prompt",
        )

    kwargs = backend.transcribe_with_diarization.call_args.kwargs
    assert kwargs["initial_prompt"] == "caller prompt"


def test_integrated_backend_failure_falls_back_to_plain_transcription(fake_engine_module):
    backend = MagicMock()
    backend.backend_name = "whisperx"
    backend.preferred_input_sample_rate_hz = 16000
    backend.transcribe_with_diarization.side_effect = ValueError("needs a HuggingFace token")
    expected = _plain_result()
    engine = _make_engine(result=expected, backend=backend)

    with (
        patch("server.core.audio_utils.load_audio", return_value=([0.0] * 16000, 16000)),
        patch("server.core.stt.backends.base.use_integrated_diarization_for", return_value=True),
    ):
        dispatched = transcribe_with_optional_diarization(
            engine=engine,
            model_manager=_make_model_manager(reason="token_missing"),
            file_path="/tmp/a.wav",
            enable_diarization=True,
            word_timestamps=False,
        )

    assert dispatched.result is expected
    assert dispatched.outcome.performed is False
    assert dispatched.outcome.reason == "token_missing"
    engine.transcribe_file.assert_called_once()
    # The degraded fallback honors the caller's word_timestamps choice rather
    # than forcing it on (GH-274 delta).
    assert engine.transcribe_file.call_args.kwargs["word_timestamps"] is False


def test_audio_decode_error_propagates_from_the_integrated_path(fake_engine_module):
    from server.core.audio_utils import AudioDecodeError

    backend = MagicMock()
    backend.backend_name = "whisperx"
    backend.preferred_input_sample_rate_hz = 16000
    engine = _make_engine(backend=backend)

    with (
        patch("server.core.audio_utils.load_audio", side_effect=AudioDecodeError("corrupt")),
        patch("server.core.stt.backends.base.use_integrated_diarization_for", return_value=True),
    ):
        with pytest.raises(AudioDecodeError):
            transcribe_with_optional_diarization(
                engine=engine,
                model_manager=_make_model_manager(),
                file_path="/tmp/a.wav",
                enable_diarization=True,
            )
