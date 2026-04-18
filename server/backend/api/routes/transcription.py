"""
Transcription API endpoints for TranscriptionSuite server.

Handles:
- Audio file transcription
- Real-time audio streaming (WebSocket)
- Transcription status and results
- File import (background transcription without notebook storage)
"""

import asyncio
import functools
import json as _json
import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from server.api.routes.utils import get_client_name
from server.config import resolve_main_transcriber_model
from server.core.json_utils import sanitize_for_json
from server.core.model_manager import TranscriptionCancelledError
from server.core.stt.backends.base import BackendDependencyError, STTBackend
from server.database.job_repository import (
    create_job,
    mark_delivered,
    mark_failed,
    save_result,
)
from server.logging import sanitize_log_value

logger = logging.getLogger(__name__)

router = APIRouter()


def _assert_main_model_selected(request: Request) -> None:
    config = request.app.state.config
    model_name = resolve_main_transcriber_model(config)
    if model_name.strip():
        return
    raise HTTPException(
        status_code=409,
        detail="Main model not selected. Choose a main model in Server settings before transcription.",
    )


class TranscriptionRequest(BaseModel):
    """Request model for transcription."""

    language: str | None = None
    translation_enabled: bool = False
    translation_target_language: str | None = None
    word_timestamps: bool = True
    diarization: bool = False


class TranscriptionResponse(BaseModel):
    """Response model for transcription results."""

    text: str
    segments: list[dict[str, Any]]
    words: list[dict[str, Any]]
    language: str | None = None
    language_probability: float = 0.0
    duration: float = 0.0
    num_speakers: int = 0


@router.post("/audio", response_model=TranscriptionResponse)
@router.post("/file", response_model=TranscriptionResponse, include_in_schema=False)
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    language: str | None = Form(None),
    translation_enabled: bool = Form(False),
    translation_target_language: str | None = Form(None),
    word_timestamps: bool | None = Form(None),
    diarization: bool | None = Form(None),
    expected_speakers: int | None = Form(None),
    parallel_diarization: bool | None = Form(None),
    multitrack: bool = Form(False),
) -> dict[str, Any]:
    """
    Transcribe an uploaded audio file.

    Accepts audio/video files and returns transcription with:
    - Full text
    - Segments with timing
    - Word-level timestamps (optional)
    - Speaker labels (optional, if diarization enabled)

    Client detection:
    - Standalone client (X-Client-Type: standalone): Uses static_transcription config
    - Web UI clients: Uses API defaults (word_timestamps=True, diarization=False)

    Parameters:
    - expected_speakers: Exact number of speakers (2-10). Forces diarization to
      identify exactly this many speakers. Useful for podcasts with known hosts
      where occasional clips should be attributed to the main speakers.

    Returns 409 Conflict if another transcription job is already running.
    """
    _assert_main_model_selected(request)

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Validate expected_speakers parameter
    if expected_speakers is not None:
        if expected_speakers < 1 or expected_speakers > 10:
            raise HTTPException(
                status_code=400,
                detail="expected_speakers must be between 1 and 10",
            )

    # Get model manager and check if busy
    model_manager = request.app.state.model_manager
    client_name = get_client_name(request)

    # Ensure the transcription model is loaded BEFORE acquiring a job slot
    # (Issue #76) — a failed reload must not hold the single-slot tracker or
    # leave an orphan DB row. BackendDependencyError surfaces HTTP 503 with
    # the remedy; any other reload failure propagates to the generic handler.
    try:
        await asyncio.to_thread(model_manager.ensure_transcription_loaded)
    except BackendDependencyError as dep_err:
        remedy_suffix = f". {dep_err.remedy}" if dep_err.remedy else ""
        detail_message = f"Backend dependency missing: {dep_err}{remedy_suffix}"
        logger.warning("Transcription pre-check failed — %s", detail_message)
        raise HTTPException(status_code=503, detail=detail_message) from dep_err

    # Try to acquire a job slot
    success, job_id, active_user = model_manager.job_tracker.try_start_job(client_name)
    if not success:
        raise HTTPException(
            status_code=409,
            detail=f"A transcription is already running for {active_user}",
        )

    # Persist-before-deliver: create the job row so results can be saved and
    # clients can recover via GET /result/{job_id} on delivery failure.
    db_job_id: str | None = job_id
    try:
        create_job(
            job_id=job_id,
            source="audio_upload",
            client_name=client_name,
            language=language,
            task="translate" if translation_enabled else "transcribe",
            translation_target=(translation_target_language if translation_enabled else None),
        )
    except Exception as _e:
        logger.warning(
            "Failed to create job row for %s: %s",
            sanitize_log_value(job_id),
            _e,
        )
        db_job_id = None

    # Tracks whether save_result succeeded. Gates mark_delivered (so we never
    # mark an unpersisted row as delivered) and mark_failed (so a post-persist
    # exception — e.g. webhook failure — cannot clobber status='completed').
    _persisted = False

    def _persist_result(result_dict: dict[str, Any]) -> None:
        """Persist result to DB before delivery.

        DB failure logs CRITICAL but never raises — delivery must not be
        sacrificed for DB consistency. See project invariant in CLAUDE.md.
        """
        nonlocal _persisted
        if db_job_id is None:
            return
        try:
            sanitized = sanitize_for_json(result_dict)
            save_result(
                job_id=db_job_id,
                result_text=sanitized.get("text", "") or "",
                result_json=_json.dumps(sanitized, ensure_ascii=False),
                result_language=sanitized.get("language"),
                duration_seconds=sanitized.get("duration"),
            )
            _persisted = True
        except Exception:
            logger.critical(
                "Failed to persist result for job %s — delivery will proceed",
                sanitize_log_value(db_job_id),
                exc_info=True,
            )

    # Detect standalone client via header
    client_type = request.headers.get("X-Client-Type", "")

    # Apply defaults based on client type
    if client_type == "standalone":
        # Standalone client defaults (Audio Notebook handles diarization/timestamps)
        if word_timestamps is None:
            word_timestamps = False
        if diarization is None:
            diarization = False
        logger.debug("Standalone client defaults applied")
    else:
        # Recorder web UI: always disable word_timestamps and diarization
        if word_timestamps is None:
            word_timestamps = False
        if diarization is None:
            diarization = False

    # Moved inside the main try/except/finally so that tempfile I/O failures
    # (client disconnect during read, disk full, etc.) trigger mark_failed and
    # end_job via the shared handlers below, instead of leaking a 'processing'
    # row and a busy tracker slot.
    tmp_path: str | None = None

    try:
        # Save uploaded file to temp location
        suffix = Path(file.filename).suffix or ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        # ensure_transcription_loaded() ran at route entry (before
        # try_start_job) — the engine is guaranteed attached here (Issue #76).
        engine = model_manager.transcription_engine

        # --- Multitrack path: split channels, transcribe each, merge ---
        if multitrack:
            from server.core.multitrack import transcribe_multitrack

            result = await asyncio.to_thread(
                functools.partial(
                    transcribe_multitrack,
                    engine,
                    tmp_path,
                    language=language,
                    task="translate" if translation_enabled else "transcribe",
                    translation_target_language=(
                        translation_target_language if translation_enabled else None
                    ),
                    cancellation_check=model_manager.job_tracker.is_cancelled,
                )
            )

            result_dict = result.to_dict()

            # Persist to DB BEFORE delivery so a client disconnect can recover
            # via GET /result/{job_id}.
            _persist_result(result_dict)

            from server.core.webhook import dispatch as dispatch_webhook

            await dispatch_webhook(
                "longform_complete",
                {
                    "source": "longform",
                    "text": result_dict.get("text", ""),
                    "filename": file.filename or "",
                    "duration": result_dict.get("duration", 0),
                    "language": result_dict.get("language"),
                    "num_speakers": result_dict.get("num_speakers", 0),
                },
            )

            if _persisted and db_job_id is not None:
                try:
                    mark_delivered(db_job_id)
                except Exception as _e:
                    logger.warning(
                        "Failed to mark job %s as delivered: %s",
                        sanitize_log_value(db_job_id),
                        _e,
                    )

            return result_dict

        # Check if the backend supports single-pass diarization (WhisperX)
        backend = engine._backend
        use_integrated_diarization = (
            diarization
            and backend is not None
            and type(backend).transcribe_with_diarization
            is not STTBackend.transcribe_with_diarization
        )

        if use_integrated_diarization:
            # --- Integrated backend single-pass path (e.g. WhisperX, VibeVoice) ---
            try:
                from server.core.audio_utils import load_audio

                backend_label = getattr(backend, "backend_name", "integrated")
                logger.info("Using %s single-pass diarization", backend_label)
                preferred_rate = int(
                    getattr(backend, "preferred_input_sample_rate_hz", 16000) or 16000
                )
                audio_data, audio_sample_rate = load_audio(
                    tmp_path, target_sample_rate=preferred_rate
                )

                diar_result = await asyncio.to_thread(
                    functools.partial(
                        backend.transcribe_with_diarization,
                        audio_data,
                        audio_sample_rate=audio_sample_rate,
                        language=language,
                        task="translate" if translation_enabled else "transcribe",
                        beam_size=engine.beam_size,
                        initial_prompt=engine.initial_prompt,
                        suppress_tokens=engine.suppress_tokens,
                        vad_filter=engine.faster_whisper_vad_filter,
                        num_speakers=expected_speakers,
                    )
                )

                from server.core.stt.engine import TranscriptionResult

                result = TranscriptionResult(
                    text=" ".join(seg.get("text", "") for seg in diar_result.segments).strip(),
                    segments=diar_result.segments,
                    words=diar_result.words,
                    language=diar_result.language,
                    language_probability=diar_result.language_probability,
                    duration=len(audio_data) / audio_sample_rate,
                    num_speakers=diar_result.num_speakers,
                )

                result_dict = result.to_dict()

                # Persist to DB BEFORE delivery so a client disconnect can recover
                # via GET /result/{job_id}.
                _persist_result(result_dict)

                if _persisted and db_job_id is not None:
                    try:
                        mark_delivered(db_job_id)
                    except Exception as _e:
                        logger.warning(
                            "Failed to mark job %s as delivered: %s",
                            sanitize_log_value(db_job_id),
                            _e,
                        )

                return result_dict

            except TranscriptionCancelledError:
                # User cancellation must not be silently converted to "fallback to
                # standard transcription" — propagate to the outer handler so the
                # 499 response + mark_failed fire as the durability spec intends.
                raise
            except ValueError:
                # Input-validation failures from the integrated path should surface
                # as HTTP 400 via the outer handler — not silently retried via the
                # non-diarized standard path.
                raise
            except Exception:
                logger.warning(
                    "Integrated backend diarization failed (returning transcript without speakers)",
                    exc_info=True,
                )
                # Fall through to standard transcription without diarization
                diarization = False

        # Force word timestamps when diarization is requested
        # (needed for proper text-to-speaker alignment)
        need_word_timestamps = word_timestamps or diarization

        if diarization:
            # Resolve parallel vs sequential diarization
            config = request.app.state.config
            use_parallel = (
                parallel_diarization
                if parallel_diarization is not None
                else config.get("diarization", "parallel", default=True)
            )

            if use_parallel:
                from server.core.parallel_diarize import transcribe_and_diarize

                diarize_fn = transcribe_and_diarize
            else:
                from server.core.parallel_diarize import transcribe_then_diarize

                diarize_fn = transcribe_then_diarize

            result, diar_result = await asyncio.to_thread(
                functools.partial(
                    diarize_fn,
                    engine=engine,
                    model_manager=model_manager,
                    file_path=tmp_path,
                    language=language,
                    task="translate" if translation_enabled else "transcribe",
                    translation_target_language=(
                        translation_target_language if translation_enabled else None
                    ),
                    word_timestamps=need_word_timestamps,
                    expected_speakers=expected_speakers,
                    cancellation_check=model_manager.job_tracker.is_cancelled,
                )
            )

            if diar_result is not None:
                try:
                    from server.core.speaker_merge import build_speaker_segments

                    diar_dicts = [seg.to_dict() for seg in diar_result.segments]
                    merged_segments, merged_words, num_speakers = build_speaker_segments(
                        result.words, diar_dicts
                    )

                    if merged_segments:
                        result.segments = merged_segments
                        result.words = merged_words
                        result.num_speakers = num_speakers
                        logger.info(
                            "Speaker merge complete: %s speakers, %s segments",
                            num_speakers,
                            len(merged_segments),
                        )
                    elif not result.words and result.segments:
                        # No word timestamps (e.g. MLX Canary) — fall back
                        # to segment-level speaker attribution.
                        from server.core.speaker_merge import build_speaker_segments_nowords

                        fallback = build_speaker_segments_nowords(result.segments, diar_dicts)
                        if fallback:
                            speakers = {s["speaker"] for s in fallback} - {"UNKNOWN"}
                            result.segments = fallback
                            result.num_speakers = len(speakers)
                            logger.info(
                                "Segment-level speaker merge: %s speakers, %s segments",
                                len(speakers),
                                len(fallback),
                            )
                except Exception:
                    logger.warning(
                        "Speaker merge failed (returning transcript without speakers)",
                        exc_info=True,
                    )
        else:
            # Transcribe without diarization
            logger.info("Transcribing uploaded file")
            result = await asyncio.to_thread(
                functools.partial(
                    engine.transcribe_file,
                    tmp_path,
                    language=language,
                    task="translate" if translation_enabled else "transcribe",
                    translation_target_language=(
                        translation_target_language if translation_enabled else None
                    ),
                    word_timestamps=need_word_timestamps,
                    cancellation_check=model_manager.job_tracker.is_cancelled,
                )
            )

        result_dict = result.to_dict()

        # Persist to DB BEFORE delivery so a client disconnect can recover
        # via GET /result/{job_id}.
        _persist_result(result_dict)

        # Fire outgoing webhook for completed transcription
        from server.core.webhook import dispatch as dispatch_webhook

        await dispatch_webhook(
            "longform_complete",
            {
                "source": "longform",
                "text": result_dict.get("text", ""),
                "filename": file.filename or "",
                "duration": result_dict.get("duration", 0),
                "language": result_dict.get("language"),
                "num_speakers": result_dict.get("num_speakers", 0),
            },
        )

        if _persisted and db_job_id is not None:
            try:
                mark_delivered(db_job_id)
            except Exception as _e:
                logger.warning(
                    "Failed to mark job %s as delivered: %s",
                    sanitize_log_value(db_job_id),
                    _e,
                )

        return result_dict

    except ValueError as e:
        # Skip mark_failed if we already persisted a completed result — a later
        # raise (e.g. webhook failure) must not clobber status='completed'.
        if not _persisted and db_job_id is not None:
            try:
                mark_failed(db_job_id, str(e))
            except Exception as _mf_err:
                logger.warning(
                    "Failed to mark job %s as failed: %s",
                    sanitize_log_value(db_job_id),
                    _mf_err,
                )
        raise HTTPException(status_code=400, detail=str(e)) from e

    except TranscriptionCancelledError:
        logger.info("Transcription cancelled by user")
        if not _persisted and db_job_id is not None:
            try:
                mark_failed(db_job_id, "Transcription cancelled by user")
            except Exception as _mf_err:
                logger.warning(
                    "Failed to mark job %s as failed: %s",
                    sanitize_log_value(db_job_id),
                    _mf_err,
                )
        raise HTTPException(status_code=499, detail="Transcription cancelled by user") from None

    except BackendDependencyError as dep_err:
        # Surface the actionable remedy (e.g. "Set INSTALL_NEMO=true") so the
        # dashboard can show a recovery hint instead of a generic 500 (Issue #76).
        # Matches the 503 contract at admin.py:233-236.
        remedy_suffix = f". {dep_err.remedy}" if dep_err.remedy else ""
        detail_message = f"Backend dependency missing: {dep_err}{remedy_suffix}"
        logger.warning("Transcription failed — %s", detail_message)
        if not _persisted and db_job_id is not None:
            try:
                mark_failed(db_job_id, detail_message)
            except Exception as _mf_err:
                logger.warning(
                    "Failed to mark job %s as failed: %s",
                    sanitize_log_value(db_job_id),
                    _mf_err,
                )
        raise HTTPException(status_code=503, detail=detail_message) from dep_err

    except Exception as e:
        logger.error("Transcription failed", exc_info=True)
        if not _persisted and db_job_id is not None:
            try:
                mark_failed(db_job_id, str(e))
            except Exception as _mf_err:
                logger.warning(
                    "Failed to mark job %s as failed: %s",
                    sanitize_log_value(db_job_id),
                    _mf_err,
                )
        raise HTTPException(status_code=500, detail=str(e)) from e

    finally:
        # Release the job slot
        model_manager.job_tracker.end_job(job_id)

        # Cleanup temp file (may be None if the tempfile write itself failed)
        if tmp_path:
            try:
                Path(tmp_path).unlink()
            except OSError:
                logger.warning("Failed to cleanup temp file %s", tmp_path, exc_info=True)


@router.post("/quick", response_model=TranscriptionResponse)
async def transcribe_quick(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    language: str | None = Form(None),
    translation_enabled: bool = Form(False),
    translation_target_language: str | None = Form(None),
) -> dict[str, Any]:
    """
    Quick transcription for Record view - text only, no word timestamps or diarization.

    Optimized for speed - returns just the transcription text and basic metadata.

    Returns 409 Conflict if another transcription job is already running.
    """
    _assert_main_model_selected(request)

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Get model manager and check if busy
    model_manager = request.app.state.model_manager
    client_name = get_client_name(request)

    # Ensure the transcription model is loaded BEFORE acquiring a job slot
    # (Issue #76) — see transcribe_audio for rationale.
    try:
        await asyncio.to_thread(model_manager.ensure_transcription_loaded)
    except BackendDependencyError as dep_err:
        remedy_suffix = f". {dep_err.remedy}" if dep_err.remedy else ""
        detail_message = f"Backend dependency missing: {dep_err}{remedy_suffix}"
        logger.warning("Quick transcription pre-check failed — %s", detail_message)
        raise HTTPException(status_code=503, detail=detail_message) from dep_err

    # Try to acquire a job slot
    success, job_id, active_user = model_manager.job_tracker.try_start_job(client_name)
    if not success:
        raise HTTPException(
            status_code=409,
            detail=f"A transcription is already running for {active_user}",
        )

    # Save uploaded file to temp location
    suffix = Path(file.filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # ensure_transcription_loaded() ran at route entry — the engine is
        # guaranteed attached here (Issue #76).
        engine = model_manager.transcription_engine

        # Transcribe without word timestamps for speed, with cancellation support
        logger.info("Quick transcription started")
        result = await asyncio.to_thread(
            functools.partial(
                engine.transcribe_file,
                tmp_path,
                language=language,
                task="translate" if translation_enabled else "transcribe",
                translation_target_language=(
                    translation_target_language if translation_enabled else None
                ),
                word_timestamps=False,  # No word timestamps for speed
                cancellation_check=model_manager.job_tracker.is_cancelled,
            )
        )

        result_dict = result.to_dict()

        # Fire outgoing webhook for completed transcription
        from server.core.webhook import dispatch as dispatch_webhook

        await dispatch_webhook(
            "longform_complete",
            {
                "source": "longform",
                "text": result_dict.get("text", ""),
                "filename": file.filename or "",
                "duration": result_dict.get("duration", 0),
                "language": result_dict.get("language"),
                "num_speakers": result_dict.get("num_speakers", 0),
            },
        )

        return result_dict

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    except TranscriptionCancelledError:
        logger.info("Quick transcription cancelled by user")
        raise HTTPException(status_code=499, detail="Transcription cancelled by user") from None

    except BackendDependencyError as dep_err:
        # Surface the actionable remedy so the dashboard can show a recovery
        # hint instead of a generic 500 (Issue #76). Matches 503 contract at
        # admin.py:233-236.
        remedy_suffix = f". {dep_err.remedy}" if dep_err.remedy else ""
        detail_message = f"Backend dependency missing: {dep_err}{remedy_suffix}"
        logger.warning("Quick transcription failed — %s", detail_message)
        raise HTTPException(status_code=503, detail=detail_message) from dep_err

    except Exception as e:
        logger.error("Quick transcription failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e

    finally:
        # Release the job slot
        model_manager.job_tracker.end_job(job_id)

        # Cleanup temp file
        try:
            Path(tmp_path).unlink()
        except OSError:
            logger.warning("Failed to cleanup temp file %s", tmp_path, exc_info=True)


@router.post("/cancel")
async def cancel_transcription(request: Request) -> dict[str, Any]:
    """
    Cancel the currently running transcription job.

    This requests cancellation of any active transcription. The actual cancellation
    happens between segments during processing, so there may be a brief delay.

    Returns:
        - success: Whether a job was cancelled
        - cancelled_user: The user whose job was cancelled (if any)
        - message: Human-readable status message
    """
    model_manager = request.app.state.model_manager
    success, cancelled_user = model_manager.job_tracker.cancel_job()

    if success:
        return {
            "success": True,
            "cancelled_user": cancelled_user,
            "message": f"Cancellation requested for {cancelled_user}'s transcription",
        }
    else:
        return {
            "success": False,
            "cancelled_user": None,
            "message": "No transcription job is currently running",
        }


# ─── File Import (background transcription, no notebook/DB storage) ─────────


class ImportAcceptedResponse(BaseModel):
    """Response model for accepted file import job (202)."""

    job_id: str


def _run_file_import(
    *,
    model_manager: Any,
    tmp_path: Path,
    filename: str,
    language: str | None,
    translation_enabled: bool,
    translation_target_language: str | None,
    enable_diarization: bool,
    enable_word_timestamps: bool,
    expected_speakers: int | None,
    parallel_diarization: bool | None,
    use_parallel_default: bool,
    multitrack: bool,
    job_id: str,
    event_loop: Any = None,
) -> None:
    """
    Run transcription in a background thread for file import.

    Unlike _run_transcription in notebook.py, this does NOT:
    - Check time-slot conflicts
    - Convert to MP3
    - Save to database

    It stores the full transcription result in job_tracker so the client
    can format and save the output file locally.
    """
    try:
        # Progress callback to update job tracker with chunk progress
        def on_progress(current: int, total: int) -> None:
            model_manager.job_tracker.update_progress(current, total)

        # Get transcription engine, lazily reloading the model if a prior
        # Live-Mode restore left it detached (Issue #76).
        engine = model_manager.ensure_transcription_loaded()

        # --- Multitrack path: split channels, transcribe each, merge ---
        if multitrack:
            from server.core.multitrack import transcribe_multitrack

            result = transcribe_multitrack(
                engine,
                str(tmp_path),
                language=language,
                task="translate" if translation_enabled else "transcribe",
                translation_target_language=(
                    translation_target_language if translation_enabled else None
                ),
                cancellation_check=model_manager.job_tracker.is_cancelled,
                progress_callback=on_progress,
            )

            result_dict = result.to_dict()
            model_manager.job_tracker.end_job(
                job_id,
                result={
                    "job_id": job_id[:8],
                    "transcription": result_dict,
                    "diarization": {
                        "requested": False,
                        "performed": False,
                        "reason": "multitrack",
                    },
                },
            )
            logger.info("File import job %s completed (multitrack): %s", job_id[:8], filename)

            if event_loop is not None:
                from server.core.webhook import dispatch_fire_and_forget

                dispatch_fire_and_forget(
                    event_loop,
                    "longform_complete",
                    {
                        "source": "longform",
                        "text": result_dict.get("text", ""),
                        "filename": filename,
                        "duration": result_dict.get("duration", 0),
                        "language": result_dict.get("language"),
                        "num_speakers": result_dict.get("num_speakers", 0),
                    },
                )
            return

        # Check if the backend supports single-pass diarization (WhisperX)
        backend = engine._backend
        use_integrated_diarization = (
            enable_diarization
            and backend is not None
            and type(backend).transcribe_with_diarization
            is not STTBackend.transcribe_with_diarization
        )

        diarization_outcome: dict[str, Any] = {
            "requested": bool(enable_diarization),
            "performed": False,
            "reason": None,
        }

        if use_integrated_diarization:
            # --- Integrated backend single-pass path (e.g. WhisperX, VibeVoice) ---
            try:
                from server.core.audio_utils import load_audio

                backend_label = getattr(backend, "backend_name", "integrated")
                logger.info(
                    "File import: using %s single-pass diarization for: %s",
                    backend_label,
                    filename,
                )
                preferred_rate = int(
                    getattr(backend, "preferred_input_sample_rate_hz", 16000) or 16000
                )
                audio_data, audio_sample_rate = load_audio(
                    str(tmp_path), target_sample_rate=preferred_rate
                )

                diar_result = backend.transcribe_with_diarization(
                    audio_data,
                    audio_sample_rate=audio_sample_rate,
                    language=language,
                    task="translate" if translation_enabled else "transcribe",
                    beam_size=engine.beam_size,
                    initial_prompt=engine.initial_prompt,
                    suppress_tokens=engine.suppress_tokens,
                    vad_filter=engine.faster_whisper_vad_filter,
                    num_speakers=expected_speakers,
                    progress_callback=on_progress,
                )

                from server.core.stt.engine import TranscriptionResult

                result = TranscriptionResult(
                    text=" ".join(seg.get("text", "") for seg in diar_result.segments).strip(),
                    segments=diar_result.segments,
                    words=diar_result.words,
                    language=diar_result.language,
                    language_probability=diar_result.language_probability,
                    duration=len(audio_data) / audio_sample_rate,
                    num_speakers=diar_result.num_speakers,
                )

                diarization_outcome["performed"] = True
                diarization_outcome["reason"] = "ready"
                logger.info(
                    "File import: %s diarization complete: %s speakers found",
                    backend_label,
                    diar_result.num_speakers,
                )

            except TranscriptionCancelledError:
                # User cancellation must propagate — otherwise we'd silently fall
                # through to the standard path and waste GPU time re-transcribing
                # a file the user already cancelled.
                raise
            except ValueError as e:
                logger.error("File import: diarization requires HuggingFace token: %s", e)
                diarization_outcome["reason"] = model_manager.get_diarization_feature_status().get(
                    "reason", "token_missing"
                )
                use_integrated_diarization = False
            except Exception as e:
                logger.error(
                    "File import: integrated backend diarization failed (continuing without): %s",
                    e,
                )
                diarization_outcome["reason"] = "unavailable"
                use_integrated_diarization = False

        if not use_integrated_diarization:
            # --- Standard path (NeMo backends or WhisperX fallback) ---
            need_word_timestamps = enable_word_timestamps or enable_diarization

            if enable_diarization and not diarization_outcome["performed"]:
                use_parallel = (
                    parallel_diarization
                    if parallel_diarization is not None
                    else use_parallel_default
                )

                if use_parallel:
                    from server.core.parallel_diarize import transcribe_and_diarize

                    diarize_fn = transcribe_and_diarize
                else:
                    from server.core.parallel_diarize import transcribe_then_diarize

                    diarize_fn = transcribe_then_diarize

                result, diar_result = diarize_fn(
                    engine=engine,
                    model_manager=model_manager,
                    file_path=str(tmp_path),
                    language=language,
                    task="translate" if translation_enabled else "transcribe",
                    translation_target_language=(
                        translation_target_language if translation_enabled else None
                    ),
                    word_timestamps=need_word_timestamps,
                    expected_speakers=expected_speakers,
                    progress_callback=on_progress,
                )

                if diar_result is not None:
                    try:
                        from server.core.speaker_merge import build_speaker_segments

                        diar_dicts = [seg.to_dict() for seg in diar_result.segments]
                        merged_segments, merged_words, num_speakers = build_speaker_segments(
                            result.words, diar_dicts
                        )

                        if merged_segments:
                            result.segments = merged_segments
                            result.words = merged_words
                            result.num_speakers = num_speakers
                        elif not result.words and result.segments:
                            # No word timestamps (e.g. MLX Canary) — fall back
                            # to segment-level speaker attribution.
                            from server.core.speaker_merge import (
                                build_speaker_segments_nowords,
                            )

                            fallback = build_speaker_segments_nowords(result.segments, diar_dicts)
                            if fallback:
                                speakers = {s["speaker"] for s in fallback} - {"UNKNOWN"}
                                result.segments = fallback
                                result.num_speakers = len(speakers)
                    except Exception:
                        logger.warning(
                            "File import: speaker merge failed (returning without speakers)",
                            exc_info=True,
                        )

                    diarization_outcome["performed"] = True
                    diarization_outcome["reason"] = "ready"
                    logger.info(
                        "File import: diarization complete: %s speakers found",
                        diar_result.num_speakers if diar_result else 0,
                    )
                else:
                    diarization_outcome["reason"] = (
                        model_manager.get_diarization_feature_status().get("reason", "unavailable")
                    )
            else:
                # Transcribe without diarization
                logger.info("File import: transcribing uploaded file: %s", filename)
                result = engine.transcribe_file(
                    str(tmp_path),
                    language=language,
                    task="translate" if translation_enabled else "transcribe",
                    translation_target_language=(
                        translation_target_language if translation_enabled else None
                    ),
                    word_timestamps=need_word_timestamps,
                    progress_callback=on_progress,
                )

        # Store successful result for client polling
        result_dict = result.to_dict()
        model_manager.job_tracker.end_job(
            job_id,
            result={
                "job_id": job_id[:8],
                "transcription": result_dict,
                "diarization": diarization_outcome,
            },
        )
        logger.info("File import job %s completed: %s", job_id[:8], filename)

        # Fire outgoing webhook (background thread — use fire-and-forget)
        if event_loop is not None:
            from server.core.webhook import dispatch_fire_and_forget

            dispatch_fire_and_forget(
                event_loop,
                "longform_complete",
                {
                    "source": "longform",
                    "text": result_dict.get("text", ""),
                    "filename": filename,
                    "duration": result_dict.get("duration", 0),
                    "language": result_dict.get("language"),
                    "num_speakers": result_dict.get("num_speakers", 0),
                },
            )

    except TranscriptionCancelledError:
        logger.info("File import job %s cancelled by user", job_id[:8])
        model_manager.job_tracker.end_job(
            job_id,
            result={
                "job_id": job_id[:8],
                "error": "Transcription cancelled by user",
            },
        )

    except Exception as e:
        logger.error("File import job %s failed: %s", job_id[:8], e, exc_info=True)
        # Surface BackendDependencyError remedy so the dashboard can render an
        # actionable hint instead of just the bare error string (Issue #76).
        # BackendDependencyError is imported at module top.
        dep_error: BackendDependencyError | None = None
        if isinstance(e, BackendDependencyError):
            dep_error = e
        elif isinstance(e.__cause__, BackendDependencyError):
            dep_error = e.__cause__
        error_payload: dict[str, Any] = {
            "job_id": job_id[:8],
            "error": str(e),
        }
        if dep_error is not None:
            error_payload["remedy"] = dep_error.remedy
            error_payload["backend_type"] = dep_error.backend_type
        model_manager.job_tracker.end_job(
            job_id,
            result=error_payload,
        )

    finally:
        # Cleanup temp file
        try:
            tmp_path.unlink()
        except Exception as e:
            logger.warning("File import: failed to cleanup temp file %s: %s", tmp_path, e)


@router.post("/import", response_model=ImportAcceptedResponse, status_code=202)
async def import_and_transcribe(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    language: str | None = Form(None),
    translation_enabled: bool = Form(False),
    translation_target_language: str | None = Form(None),
    enable_diarization: bool = Form(False),
    enable_word_timestamps: bool = Form(True),
    expected_speakers: int | None = Form(None),
    parallel_diarization: bool | None = Form(None),
    multitrack: bool = Form(False),
) -> dict[str, Any]:
    """
    Import an audio file and transcribe it in the background.

    Unlike the notebook upload, this does NOT save to the database or convert
    to MP3. The full transcription result is stored in job_tracker for the
    client to retrieve, format (SRT/TXT), and save to disk.

    Returns 202 Accepted immediately with a job_id. Clients should poll
    GET /api/admin/status to check job_tracker.result for completion.

    Returns 409 Conflict if another transcription job is already running.
    """
    _assert_main_model_selected(request)

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Validate expected_speakers parameter
    if expected_speakers is not None:
        if expected_speakers < 1 or expected_speakers > 10:
            raise HTTPException(
                status_code=400,
                detail="expected_speakers must be between 1 and 10",
            )

    # Get model manager and check if busy
    model_manager = request.app.state.model_manager
    client_name = get_client_name(request)

    # Try to acquire a job slot
    success, job_id, active_user = model_manager.job_tracker.try_start_job(client_name)
    if not success:
        raise HTTPException(
            status_code=409,
            detail=f"A transcription is already running for {active_user}",
        )

    # Save uploaded file to temp location (fast — just I/O)
    suffix = Path(file.filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    # Resolve parallel diarization default from config before entering background thread
    config = request.app.state.config
    use_parallel_default = config.get("diarization", "parallel", default=True)

    # Capture event loop for webhook dispatch from background thread
    loop = asyncio.get_running_loop()

    # Launch background transcription task
    loop.create_task(
        asyncio.to_thread(
            _run_file_import,
            model_manager=model_manager,
            tmp_path=tmp_path,
            filename=file.filename,
            language=language,
            translation_enabled=translation_enabled,
            translation_target_language=translation_target_language,
            enable_diarization=enable_diarization,
            enable_word_timestamps=enable_word_timestamps,
            expected_speakers=expected_speakers,
            parallel_diarization=parallel_diarization,
            use_parallel_default=use_parallel_default,
            multitrack=multitrack,
            job_id=job_id,
            event_loop=loop,
        )
    )

    # Return immediately — client polls /api/admin/status for result
    return {"job_id": job_id[:8]}


@router.get("/result/{job_id}", response_model=None)
async def get_transcription_result(job_id: str, request: Request) -> JSONResponse:
    """Retrieve a saved transcription result by job ID.

    Returns:
        200: Result JSON (completed job). Also marks job as delivered.
        202: Job still processing — client should poll again.
        404: Job not found.
        410: Job failed (includes error_message).
    """
    import json as _json

    from ...database.job_repository import get_job, mark_delivered

    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    client_name = get_client_name(request)
    if job.get("client_name") is not None and job["client_name"] != client_name:
        raise HTTPException(status_code=403, detail="Access denied")
    if job["status"] == "processing":
        return JSONResponse(status_code=202, content={"status": "processing", "job_id": job_id})
    if job["status"] == "failed":
        raise HTTPException(
            status_code=410, detail=job.get("error_message") or "Transcription failed"
        )
    # completed
    if job.get("result_json"):
        try:
            result_data = _json.loads(job["result_json"])
        except _json.JSONDecodeError as _e:
            logger.error("Malformed result_json for job %s: %s", sanitize_log_value(job_id), _e)
            raise HTTPException(status_code=500, detail="Result data is corrupted") from _e
    else:
        result_data = {}
    try:
        mark_delivered(job_id)
    except Exception as e:
        logger.warning("Failed to mark job %s as delivered: %s", sanitize_log_value(job_id), e)
    return JSONResponse(
        status_code=200,
        content={"job_id": job_id, "status": "completed", "result": result_data},
    )


@router.post("/retry/{job_id}", response_model=None)
async def retry_transcription(
    job_id: str, request: Request, background_tasks: BackgroundTasks
) -> JSONResponse:
    """Re-transcribe a job from its saved audio file.

    Resets the job status to 'processing' and runs transcription in the
    background. The client should poll GET /result/{job_id} for the result.

    Returns:
        202: Retry started. Poll /result/{job_id} for completion.
        403: Job belongs to a different client.
        404: Job not found.
        409: Job is already processing.
        410: Audio file not available (never saved or already deleted).
    """
    from ...database.job_repository import get_job, reset_for_retry

    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    client_name = get_client_name(request)
    if job.get("client_name") is not None and job["client_name"] != client_name:
        raise HTTPException(status_code=403, detail="Access denied")

    if job["status"] == "processing":
        raise HTTPException(status_code=409, detail="Job is already processing")

    if job["status"] != "failed":
        raise HTTPException(
            status_code=409,
            detail=f"Only failed jobs can be retried (current status: {job['status']})",
        )

    # Pre-check model availability so we don't reset the job to 'processing'
    # only to immediately fail. A TOCTOU race is still possible (model becomes
    # busy between this check and try_start_job in _run_retry), but the
    # background task handles that gracefully.
    model_manager = request.app.state.model_manager
    is_busy, active_user = model_manager.job_tracker.is_busy()
    if is_busy:
        raise HTTPException(
            status_code=409,
            detail="Model is currently busy. Try again when the active session ends.",
        )

    audio_path = job.get("audio_path")
    if not audio_path:
        raise HTTPException(
            status_code=410, detail="Audio was not preserved for this job — cannot retry"
        )
    if not Path(audio_path).exists():
        if audio_path.startswith("/tmp/"):
            raise HTTPException(
                status_code=410,
                detail="Audio was in temporary storage (/tmp) and lost on server restart — cannot retry",
            )
        raise HTTPException(status_code=410, detail="Audio file has been deleted — cannot retry")

    reset_for_retry(job_id)
    background_tasks.add_task(_run_retry, job_id, audio_path, job, request.app.state)

    return JSONResponse(status_code=202, content={"job_id": job_id, "status": "processing"})


async def _run_retry(job_id: str, audio_path: str, job: dict[str, Any], app_state: Any) -> None:
    """Background task: re-transcribe from saved audio and persist the result."""
    import json as _json

    from ...core.json_utils import sanitize_for_json
    from ...database.job_repository import mark_failed, save_result

    model_manager = app_state.model_manager

    # Acquire the job tracker slot so the retry cannot run concurrently with
    # an active WebSocket session. If the model is busy, mark the retry failed
    # so the job stays in 'failed' state and can be retried again later.
    client_name = job.get("client_name") or "retry"
    success, tracker_job_id, active_user = model_manager.job_tracker.try_start_job(client_name)
    if not success:
        logger.warning(
            "Retry for job %s deferred — model busy (active user: %s). "
            "Job remains failed; retry again when the session ends.",
            sanitize_log_value(job_id),
            sanitize_log_value(active_user or "unknown"),
        )
        try:
            mark_failed(
                job_id,
                f"Retry deferred — model was busy (active user: {active_user}). Try again.",
            )
        except Exception as _mf_err:
            logger.warning(
                "Failed to mark retry job %s as failed: %s", sanitize_log_value(job_id), _mf_err
            )
        return

    try:
        # Lazily reload the model if a prior Live-Mode restore left it
        # detached (Issue #76).
        engine = await asyncio.to_thread(model_manager.ensure_transcription_loaded)

        result = await asyncio.to_thread(
            engine.transcribe_file,
            audio_path,
            language=job.get("language"),
            task=job.get("task", "transcribe"),
            translation_target_language=job.get("translation_target"),
            word_timestamps=True,
        )

        result_payload = sanitize_for_json(
            {
                "text": result.text,
                "words": result.words or [],
                "language": result.language,
                "duration": result.duration,
            }
        )

        save_result(
            job_id=job_id,
            result_text=result.text or "",
            result_json=_json.dumps(result_payload, ensure_ascii=False),
            result_language=result.language,
            duration_seconds=result.duration,
        )
        # Leave delivered=0 so the result surfaces in the recovery banner.
        # The client calls GET /result/{job_id} to retrieve it, which marks delivered.
        logger.info("Retry transcription complete for job %s", sanitize_log_value(job_id))

    except BackendDependencyError as dep_err:
        # Surface the actionable remedy so the dashboard shows a recovery hint
        # instead of a bare error string (Issue #76).
        logger.warning(
            "Retry failed for job %s — backend dependency missing: %s. %s",
            sanitize_log_value(job_id),
            dep_err,
            dep_err.remedy,
        )
        try:
            mark_failed(job_id, f"{dep_err}. {dep_err.remedy}")
        except Exception as _mf_err:
            logger.warning(
                "Failed to mark retry job %s as failed: %s",
                sanitize_log_value(job_id),
                _mf_err,
            )
        return

    except FileNotFoundError:
        logger.warning(
            "Audio file removed before retry could complete for job %s: %s",
            sanitize_log_value(job_id),
            sanitize_log_value(audio_path),
        )
        try:
            mark_failed(job_id, "Audio file was removed before retry could complete")
        except Exception as _mf_err:
            logger.warning(
                "Failed to mark retry job %s as failed: %s", sanitize_log_value(job_id), _mf_err
            )
        return

    except Exception as exc:
        logger.error(
            "Retry transcription failed for job %s: %s",
            sanitize_log_value(job_id),
            exc,
            exc_info=True,
        )
        try:
            mark_failed(job_id, str(exc))
        except Exception as _mf_err:
            logger.warning(
                "Failed to mark retry job %s as failed: %s", sanitize_log_value(job_id), _mf_err
            )
    finally:
        if tracker_job_id:
            model_manager.job_tracker.end_job(tracker_job_id)


def _sorted_languages(langs: dict[str, str]) -> dict[str, str]:
    """Return *langs* sorted: English first, then alphabetical by name."""
    items = sorted(langs.items(), key=lambda kv: (kv[1] != "English", kv[1]))
    return dict(items)


# 25 European languages supported by NeMo models (Parakeet & Canary).
_NEMO_LANGUAGES: dict[str, str] = _sorted_languages(
    {
        "bg": "Bulgarian",
        "hr": "Croatian",
        "cs": "Czech",
        "da": "Danish",
        "nl": "Dutch",
        "en": "English",
        "et": "Estonian",
        "fi": "Finnish",
        "fr": "French",
        "de": "German",
        "el": "Greek",
        "hu": "Hungarian",
        "it": "Italian",
        "lv": "Latvian",
        "lt": "Lithuanian",
        "mt": "Maltese",
        "pl": "Polish",
        "pt": "Portuguese",
        "ro": "Romanian",
        "ru": "Russian",
        "sk": "Slovak",
        "sl": "Slovenian",
        "es": "Spanish",
        "sv": "Swedish",
        "uk": "Ukrainian",
    }
)

# Full Whisper language set (90 languages).
_WHISPER_LANGUAGES: dict[str, str] = _sorted_languages(
    {
        "en": "English",
        "zh": "Chinese",
        "de": "German",
        "es": "Spanish",
        "ru": "Russian",
        "ko": "Korean",
        "fr": "French",
        "ja": "Japanese",
        "pt": "Portuguese",
        "tr": "Turkish",
        "pl": "Polish",
        "ca": "Catalan",
        "nl": "Dutch",
        "ar": "Arabic",
        "sv": "Swedish",
        "it": "Italian",
        "id": "Indonesian",
        "hi": "Hindi",
        "fi": "Finnish",
        "vi": "Vietnamese",
        "he": "Hebrew",
        "uk": "Ukrainian",
        "el": "Greek",
        "ms": "Malay",
        "cs": "Czech",
        "ro": "Romanian",
        "da": "Danish",
        "hu": "Hungarian",
        "ta": "Tamil",
        "no": "Norwegian",
        "th": "Thai",
        "ur": "Urdu",
        "hr": "Croatian",
        "bg": "Bulgarian",
        "lt": "Lithuanian",
        "la": "Latin",
        "mi": "Maori",
        "ml": "Malayalam",
        "cy": "Welsh",
        "sk": "Slovak",
        "te": "Telugu",  # codespell:ignore te
        "fa": "Persian",
        "lv": "Latvian",
        "bn": "Bengali",
        "sr": "Serbian",
        "az": "Azerbaijani",
        "sl": "Slovenian",
        "kn": "Kannada",
        "et": "Estonian",
        "mk": "Macedonian",
        "br": "Breton",
        "eu": "Basque",
        "is": "Icelandic",
        "hy": "Armenian",
        "ne": "Nepali",
        "mn": "Mongolian",
        "bs": "Bosnian",
        "kk": "Kazakh",
        "sq": "Albanian",
        "sw": "Swahili",
        "gl": "Galician",
        "mr": "Marathi",
        "pa": "Punjabi",
        "si": "Sinhala",
        "km": "Khmer",
        "sn": "Shona",
        "yo": "Yoruba",
        "so": "Somali",
        "af": "Afrikaans",
        "oc": "Occitan",
        "ka": "Georgian",
        "be": "Belarusian",
        "tg": "Tajik",
        "sd": "Sindhi",
        "gu": "Gujarati",
        "am": "Amharic",
        "yi": "Yiddish",
        "lo": "Lao",
        "uz": "Uzbek",
        "fo": "Faroese",  # codespell:ignore fo
        "ht": "Haitian Creole",
        "ps": "Pashto",
        "tk": "Turkmen",
        "nn": "Nynorsk",
        "mt": "Maltese",
        "sa": "Sanskrit",
        "lb": "Luxembourgish",
        "my": "Myanmar",
        "bo": "Tibetan",
        "tl": "Tagalog",
        "mg": "Malagasy",
        "as": "Assamese",
        "tt": "Tatar",
        "haw": "Hawaiian",
        "ln": "Lingala",
        "ha": "Hausa",
        "ba": "Bashkir",
        "jw": "Javanese",
        "su": "Sundanese",
    }
)

_VIBEVOICE_ASR_LANGUAGES: dict[str, str] = {}


@router.get("/recent")
async def get_recent_undelivered_results(request: Request) -> JSONResponse:
    """Return recently completed but undelivered transcription results for the caller.

    Used by the dashboard to surface recovered results after a server restart.

    Returns:
        200: List of up to 5 undelivered completed jobs with a text preview.
    """
    import json as _json

    from ...database.job_repository import get_recent_undelivered

    client_name = get_client_name(request)
    rows = get_recent_undelivered(client_name, limit=5)
    result_list = []
    for row in rows:
        raw_json = row.get("result_json") or "{}"
        try:
            result_data = _json.loads(raw_json)
        except _json.JSONDecodeError:
            result_data = {}
        result_list.append(
            {
                "job_id": row.get("id"),
                "completed_at": row.get("completed_at"),
                "text_preview": result_data.get("text", "")[:100],
            }
        )
    return JSONResponse(status_code=200, content=result_list)


@router.post("/result/{job_id}/dismiss")
async def dismiss_transcription_result(job_id: str, request: Request) -> JSONResponse:
    """Mark a completed transcription result as delivered (dismiss the notification).

    Equivalent to delivery without transferring the full payload.

    Returns:
        200: Job marked as delivered.
        403: Job belongs to a different client.
        404: Job not found.
    """
    from ...database.job_repository import get_job, mark_delivered

    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    client_name = get_client_name(request)
    if job.get("client_name") is not None and job["client_name"] != client_name:
        raise HTTPException(status_code=403, detail="Access denied")
    mark_delivered(job_id)
    return JSONResponse(status_code=200, content={"job_id": job_id})


@router.get("/languages")
async def get_supported_languages(request: Request) -> dict[str, Any]:
    """Get list of supported languages for the active transcription model.

    Returns different language sets depending on the backend:
    - **whisper**: All 90 Whisper languages, translation to English.
    - **parakeet**: 25 European languages, no translation.
    - **canary**: 25 European languages, bidirectional English ↔ EU translation.
    - **vibevoice_asr**: Auto-detect only (no explicit language selection in v1 UI).
    """
    from server.config import resolve_main_transcriber_model
    from server.core.stt.backends.factory import detect_backend_type
    from server.core.stt.capabilities import supports_auto_detect

    model_name: str | None = None
    backend_type = "whisper"
    try:
        config = request.app.state.config
        model_name = resolve_main_transcriber_model(config)
        backend_type = detect_backend_type(model_name)
    except Exception:
        # On config-read failure, keep the conservative defaults above so we
        # don't lie about capabilities — model_name stays None, backend_type
        # stays "whisper". supports_auto_detect(None) is True, which matches
        # the fallback Whisper story.
        pass

    if backend_type in ("parakeet", "canary", "mlx_canary"):
        languages = _NEMO_LANGUAGES
    elif backend_type in ("vibevoice_asr", "mlx_vibevoice", "mlx_parakeet"):
        # mlx_parakeet: parakeet-mlx has no language-hint API; model auto-detects from audio
        languages = _VIBEVOICE_ASR_LANGUAGES
    else:
        languages = _WHISPER_LANGUAGES

    supports_translation = backend_type in ("whisper", "canary", "mlx_whisper")

    return {
        "languages": languages,
        "count": len(languages),
        "auto_detect": supports_auto_detect(model_name),
        "backend_type": backend_type,
        "supports_translation": supports_translation,
    }
