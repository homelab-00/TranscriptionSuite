"""Shared transcribe-with-optional-diarization dispatch (GH-258).

One place that turns "an audio file plus a diarization request" into a
:class:`TranscriptionResult` whose segments carry speaker labels. Extracted so
the WebSocket recording path does not become a fourth copy of logic already
duplicated across ``transcription.py``, ``notebook.py`` and ``openai_audio.py``.
Those three routes are deliberately NOT migrated in this change; each has its
own HTTP status codes, response headers and database writes, and moving them is
a separate PR.

Error contract, which is about which operation raised rather than which type:
  * anything from the DIARIZATION attempt is swallowed - the transcript is
    still returned, with the reason recorded on the outcome;
  * anything from the PLAIN TRANSCRIPTION call propagates - that is a genuine
    transcription failure and the caller owns it;
  * ``TranscriptionCancelledError`` and ``AudioDecodeError`` propagate from
    either, because a user cancel must reach the caller's cancel handling and a
    corrupt file would defeat plain transcription too.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from server.core.model_manager import TranscriptionCancelledError

if TYPE_CHECKING:
    from server.core.model_manager import ModelManager
    from server.core.stt.engine import AudioToTextRecorder, TranscriptionResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiarizationOutcome:
    """Why diarization did or did not happen, for client-facing reporting."""

    requested: bool
    performed: bool
    reason: str | None = None
    remedy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "performed": self.performed,
            "reason": self.reason,
            "remedy": self.remedy,
        }


@dataclass(frozen=True)
class DiarizedTranscription:
    """A transcription plus whatever the diarization attempt produced."""

    result: TranscriptionResult
    #: Speaker turns in the shape ``save_longform_to_database`` expects for
    #: word alignment. ``None`` when diarization did not run or did not succeed.
    speaker_segments: list[dict[str, Any]] | None
    outcome: DiarizationOutcome


def transcribe_with_optional_diarization(
    *,
    engine: AudioToTextRecorder,
    model_manager: ModelManager,
    file_path: str,
    enable_diarization: bool,
    language: str | None = None,
    task: str | None = None,
    translation_target_language: str | None = None,
    word_timestamps: bool = True,
    expected_speakers: int | None = None,
    parallel_diarization: bool | None = None,
    diarization_engine: str | None = None,
    sensevoice_engine_default: str = "funasr",
    progress_callback: Callable[[int, int], None] | None = None,
    cancellation_check: Callable[[], bool] | None = None,
) -> DiarizedTranscription:
    """Transcribe *file_path*, attaching speaker labels when asked to."""
    if not enable_diarization:
        result = _transcribe_plain(
            engine=engine,
            file_path=file_path,
            language=language,
            task=task,
            translation_target_language=translation_target_language,
            word_timestamps=word_timestamps,
            progress_callback=progress_callback,
            cancellation_check=cancellation_check,
        )
        return DiarizedTranscription(
            result=result,
            speaker_segments=None,
            outcome=DiarizationOutcome(requested=False, performed=False),
        )

    backend = getattr(engine, "_backend", None)

    from server.config import resolve_sensevoice_diarization_engine
    from server.core.stt.backends import base as backend_base

    resolved_engine = resolve_sensevoice_diarization_engine(
        getattr(engine, "model_name", None),
        diarization_engine,
        sensevoice_engine_default,
        funasr_diar_available=getattr(backend, "_diarization_loaded", False),
    )

    if backend_base.use_integrated_diarization_for(backend, resolved_engine):
        integrated = _run_integrated(
            engine=engine,
            backend=backend,
            file_path=file_path,
            language=language,
            task=task,
            expected_speakers=expected_speakers,
            progress_callback=progress_callback,
        )
        if integrated is not None:
            return integrated
        # The backend's own pass failed. Fall back to PLAIN transcription
        # rather than the two-pass PyAnnote path: the dominant failure is a
        # missing HF token, which the second path cannot fix either, and a
        # user is waiting on a live recording.
        result = _transcribe_plain(
            engine=engine,
            file_path=file_path,
            language=language,
            task=task,
            translation_target_language=translation_target_language,
            word_timestamps=word_timestamps,
            progress_callback=progress_callback,
            cancellation_check=cancellation_check,
        )
        return DiarizedTranscription(
            result=result,
            speaker_segments=None,
            outcome=_failure_outcome(model_manager, None),
        )

    return _run_standard(
        engine=engine,
        model_manager=model_manager,
        file_path=file_path,
        language=language,
        task=task,
        translation_target_language=translation_target_language,
        expected_speakers=expected_speakers,
        parallel_diarization=parallel_diarization,
        progress_callback=progress_callback,
        cancellation_check=cancellation_check,
    )


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _transcribe_plain(
    *,
    engine: AudioToTextRecorder,
    file_path: str,
    language: str | None,
    task: str | None,
    translation_target_language: str | None,
    word_timestamps: bool,
    progress_callback: Callable[[int, int], None] | None,
    cancellation_check: Callable[[], bool] | None,
) -> TranscriptionResult:
    """Run transcription with no diarization. Failures propagate."""
    return engine.transcribe_file(
        file_path,
        language=language,
        task=task,
        translation_target_language=translation_target_language,
        word_timestamps=word_timestamps,
        progress_callback=progress_callback,
        cancellation_check=cancellation_check,
    )


def _run_integrated(
    *,
    engine: AudioToTextRecorder,
    backend: Any,
    file_path: str,
    language: str | None,
    task: str | None,
    expected_speakers: int | None,
    progress_callback: Callable[[int, int], None] | None,
) -> DiarizedTranscription | None:
    """Single-pass diarization on backends that implement it themselves.

    Returns ``None`` when the backend path failed, so the caller can fall back.
    """
    from server.core.audio_utils import AudioDecodeError, load_audio
    from server.core.stt.engine import TranscriptionResult

    backend_label = getattr(backend, "backend_name", "integrated")
    try:
        preferred_rate = int(getattr(backend, "preferred_input_sample_rate_hz", 16000) or 16000)
        audio_data, audio_sample_rate = load_audio(file_path, target_sample_rate=preferred_rate)
        logger.info("Using %s single-pass diarization", backend_label)
        diar_result = backend.transcribe_with_diarization(
            audio_data,
            audio_sample_rate=audio_sample_rate,
            language=language,
            task=task,
            beam_size=getattr(engine, "beam_size", 5),
            # Forward the engine's configured decoding options exactly as the
            # import route does. Omitting them would silently decode a recording
            # differently from the same audio imported as a file.
            initial_prompt=getattr(engine, "initial_prompt", None),
            suppress_tokens=getattr(engine, "suppress_tokens", None),
            vad_filter=getattr(engine, "faster_whisper_vad_filter", True),
            num_speakers=expected_speakers,
            progress_callback=progress_callback,
        )
    except (TranscriptionCancelledError, AudioDecodeError):
        raise
    except Exception:
        logger.warning(
            "%s single-pass diarization failed; falling back to plain transcription",
            backend_label,
            exc_info=True,
        )
        return None

    result = TranscriptionResult(
        text=" ".join(seg.get("text", "") for seg in diar_result.segments).strip(),
        segments=diar_result.segments,
        words=diar_result.words,
        language=diar_result.language,
        language_probability=diar_result.language_probability,
        duration=len(audio_data) / audio_sample_rate,
        num_speakers=diar_result.num_speakers,
    )
    logger.info(
        "%s diarization complete: %s speakers found", backend_label, diar_result.num_speakers
    )
    return DiarizedTranscription(
        result=result,
        speaker_segments=list(diar_result.segments),
        outcome=DiarizationOutcome(requested=True, performed=True, reason="ready"),
    )


def _run_standard(
    *,
    engine: AudioToTextRecorder,
    model_manager: ModelManager,
    file_path: str,
    language: str | None,
    task: str | None,
    translation_target_language: str | None,
    expected_speakers: int | None,
    parallel_diarization: bool | None,
    progress_callback: Callable[[int, int], None] | None,
    cancellation_check: Callable[[], bool] | None,
) -> DiarizedTranscription:
    """Two-pass path: STT plus a separate diarizer, then a speaker merge."""
    from server.core import parallel_diarize

    if parallel_diarization is None:
        from server.config import get_config, resolve_parallel_diarization_default

        use_parallel = resolve_parallel_diarization_default(get_config())
    else:
        use_parallel = parallel_diarization

    diarize_fn = (
        parallel_diarize.transcribe_and_diarize
        if use_parallel
        else parallel_diarize.transcribe_then_diarize
    )

    # parallel_diarize swallows diarization failures by design; this collector
    # is the only way to learn WHY, which is what makes OOM reportable.
    observed: list[BaseException] = []

    result, diar_result = diarize_fn(
        engine=engine,
        model_manager=model_manager,
        file_path=file_path,
        language=language,
        task=task,
        translation_target_language=translation_target_language,
        # Speaker alignment needs word timings regardless of what was asked for.
        word_timestamps=True,
        expected_speakers=expected_speakers,
        cancellation_check=cancellation_check,
        progress_callback=progress_callback,
        on_diarization_error=observed.append,
    )

    if diar_result is None:
        return DiarizedTranscription(
            result=result,
            speaker_segments=None,
            outcome=_failure_outcome(model_manager, observed[0] if observed else None),
        )

    diar_dicts = [seg.to_dict() for seg in diar_result.segments]
    merged = _merge_speakers(result, diar_dicts)
    if not merged:
        return DiarizedTranscription(
            result=result,
            speaker_segments=None,
            outcome=_failure_outcome(model_manager, observed[0] if observed else None),
        )

    logger.info("Diarization complete: %s speakers found", result.num_speakers)
    return DiarizedTranscription(
        result=result,
        speaker_segments=diar_dicts,
        outcome=DiarizationOutcome(requested=True, performed=True, reason="ready"),
    )


def _merge_speakers(result: TranscriptionResult, diar_dicts: list[dict[str, Any]]) -> bool:
    """Attach speakers to *result* in place. Returns False when nothing merged.

    Mutating the result matches what every existing route does
    (``transcription.py:502-504``); a copy here would silently diverge from
    them the moment ``TranscriptionResult`` gains a field.
    """
    from server.core import speaker_merge

    try:
        merged_segments, merged_words, num_speakers = speaker_merge.build_speaker_segments(
            result.words, diar_dicts
        )
        if merged_segments:
            result.segments = merged_segments
            result.words = merged_words
            result.num_speakers = num_speakers
            return True

        # No word timestamps (e.g. the MLX Canary backend) - fall back to
        # segment-level attribution so the segments still carry speakers.
        if not result.words and result.segments:
            fallback = speaker_merge.build_speaker_segments_nowords(result.segments, diar_dicts)
            if fallback:
                speakers = {seg["speaker"] for seg in fallback} - {"UNKNOWN"}
                result.segments = fallback
                result.num_speakers = len(speakers)
                return True
        return False
    except Exception:
        logger.warning(
            "Speaker merge failed; returning the transcript without speakers", exc_info=True
        )
        return False


def _failure_outcome(model_manager: ModelManager, exc: BaseException | None) -> DiarizationOutcome:
    """Build the outcome for a diarization attempt that did not produce speakers."""
    from server.core.stt.backends.base import as_gpu_oom

    if exc is not None:
        oom = as_gpu_oom(exc)
        if oom is not None:
            return DiarizationOutcome(
                requested=True, performed=False, reason="out_of_memory", remedy=oom.remedy
            )

    try:
        reason = model_manager.get_diarization_feature_status().get("reason", "unavailable")
    except Exception:
        reason = "unavailable"
    return DiarizationOutcome(requested=True, performed=False, reason=reason or "unavailable")
