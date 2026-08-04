"""Retroactive diarization of an already-transcribed recording (GH-279).

Every existing diarization consumer goes through
``core.diarization_dispatch.transcribe_with_optional_diarization``, which
always couples diarization to a FRESH transcription pass. This module covers
the other case: a notebook recording that was transcribed without diarization
(e.g. a Live-Mode session promotion, or an upload with the toggle off) and
already has word-level timestamps persisted in the ``words`` table.

Here we diarize the stored audio file alone — no STT engine runs — and align
the resulting speaker turns onto the stored words via the same DB-layer
alignment used at import time (``replace_recording_segments_with_diarization``).

Model lifecycle mirrors ``parallel_diarize.transcribe_then_diarize`` phase 2:
unload the STT model first (frees VRAM), load the diarizer, and in ``finally``
restore the pre-job state (unload diarizer, reload STT) with guarded calls so
a restore failure never masks the real outcome.

Failure contract (CLAUDE.md data-loss invariant): if diarization fails at any
stage — model load, inference, zero turns found, DB write — the recording's
existing transcript is left completely untouched and the error is surfaced
through ``job_tracker.end_job`` for client polling.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def run_retro_diarization(
    *,
    model_manager: Any,
    recording_id: int,
    job_id: str,
    expected_speakers: int | None = None,
) -> None:
    """Diarize an existing recording's stored audio and persist the merge.

    Synchronous worker intended for ``asyncio.to_thread()``. Stores the
    success or error result in ``model_manager.job_tracker`` so clients can
    poll GET /api/admin/status for completion — the same contract as
    ``notebook._run_transcription``.
    """
    from server.database.database import (
        get_recording,
        get_words,
        replace_recording_segments_with_diarization,
    )

    try:
        recording = get_recording(recording_id)
        if not recording:
            raise ValueError(f"Recording {recording_id} not found")

        audio_path = Path(recording.get("filepath") or "")
        if not audio_path.exists():
            raise FileNotFoundError(f"Original audio file not found on disk: {audio_path}")

        words = get_words(recording_id)
        if not words:
            raise ValueError(
                "Recording has no word-level timestamps; retroactive diarization "
                "needs them for speaker alignment"
            )

        # The diarizing phase includes the model swap — the swap is part of
        # the wait the user experiences (GH-211).
        model_manager.job_tracker.set_phase("diarizing")
        logger.info(
            "Starting retroactive diarization for recording %d (%s)",
            recording_id,
            audio_path.name,
        )

        model_manager.unload_transcription_model()  # Frees VRAM for the diarizer
        try:
            model_manager.load_diarization_model()
            diar_engine = model_manager.diarization_engine
            diar_result = diar_engine.diarize_file(str(audio_path), num_speakers=expected_speakers)
        finally:
            # Restore the pre-job model state. Guarded: a restore failure must
            # not replace the real diarization outcome propagating out.
            try:
                model_manager.unload_diarization_model()
            except Exception:
                logger.warning(
                    "Failed to unload the diarization model after retro-diarize",
                    exc_info=True,
                )
            try:
                model_manager.load_transcription_model()
            except Exception:
                logger.warning(
                    "Failed to reload STT model after retro-diarize",
                    exc_info=True,
                )

        diar_dicts = [seg.to_dict() for seg in diar_result.segments]
        if not diar_dicts:
            raise RuntimeError(
                "Diarization found no speaker turns; the recording was left unchanged"
            )

        if not replace_recording_segments_with_diarization(
            recording_id,
            diar_dicts,
            alignment_words=words,
        ):
            raise RuntimeError(
                "Failed to persist diarized segments; the recording was left unchanged"
            )

        model_manager.job_tracker.end_job(
            job_id,
            result={
                "job_id": job_id[:8],
                "recording_id": recording_id,
                "num_speakers": diar_result.num_speakers,
                "message": (
                    f"Diarization complete: {diar_result.num_speakers} speaker(s) identified"
                ),
            },
        )
        logger.info(
            "Retro-diarize job %s completed: recording_id=%d, %d speakers",
            job_id[:8],
            recording_id,
            diar_result.num_speakers,
        )

        _run_review_lifecycle_hook(recording_id)

    except Exception as e:
        logger.error(
            "Retro-diarize job %s failed for recording %d: %s",
            job_id[:8],
            recording_id,
            e,
            exc_info=True,
        )
        model_manager.job_tracker.end_job(
            job_id,
            result={
                "job_id": job_id[:8],
                "recording_id": recording_id,
                "error": str(e),
            },
        )

    finally:
        # Must stay LAST in this finally - nothing may sit behind it.
        from server.core.audio_utils import post_job_gpu_cleanup

        post_job_gpu_cleanup("notebook retro-diarize", model_manager.gpu_device_index)


def _run_review_lifecycle_hook(recording_id: int) -> None:
    """Open the ADR-009 review lifecycle for the freshly diarized recording.

    Mirrors the post-save block of ``notebook._run_transcription``: compute
    per-turn confidence and insert a ``pending`` review row when low-confidence
    turns exist. A recording that was never diarized has no review row, so the
    None → pending transition is valid. Bookkeeping must never crash the job —
    the diarized segments are already durably committed.
    """
    from server.core.diarization_confidence import (
        LOW_CONFIDENCE_THRESHOLD,
        per_turn_confidence,
    )
    from server.core.diarization_review_lifecycle import on_transcription_complete
    from server.database.database import get_segments, get_words

    try:
        segments_for_conf = get_segments(recording_id)
        words_for_conf = get_words(recording_id)
        turns = per_turn_confidence(segments_for_conf, words_for_conf)
        has_low_conf = any(t["confidence"] < LOW_CONFIDENCE_THRESHOLD for t in turns)
        on_transcription_complete(recording_id, has_low_conf)
    except Exception:
        logger.exception(
            "diarization-review lifecycle hook failed for recording %d",
            recording_id,
        )
