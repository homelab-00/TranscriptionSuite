"""
Audio Notebook API endpoints for TranscriptionSuite server.

Handles:
- Recording CRUD operations
- Audio file management
- Transcription import and export
"""

import asyncio
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import aiofiles
from fastapi import (
    APIRouter,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from server.api.routes.utils import get_client_name, sanitize_for_log
from server.config import get_config
from server.core.stt.backends.factory import detect_backend_type
from server.core.subtitle_export import _to_float, build_subtitle_cues, render_ass, render_srt
from server.database.backup import DatabaseBackupManager

# NOTE: audio_utils is imported lazily inside upload_and_transcribe() to avoid
# loading torch at module import time. This reduces server startup time.
from server.database.database import (
    check_time_slot_overlap,
    delete_recording,
    get_all_recordings,
    get_db_path,
    get_recording,
    get_recordings_by_date_range,
    get_segments,
    get_time_slot_info,
    get_words,
    save_longform_to_database,
    update_recording_date,
    update_recording_summary,
    update_recording_title,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# C0 control chars + backslash + quote violate RFC 7230 quoted-string rules.
_ASCII_FALLBACK_REPLACE = str.maketrans(
    {chr(c): "_" for c in range(0x20)} | {'"': "_", "\\": "_", "\x7f": "_"}
)


def _content_disposition(disposition: str, filename: str) -> str:
    """Build an RFC 6266 Content-Disposition value with both an ASCII
    fallback and a UTF-8 form so non-ASCII filenames (Greek, Cyrillic,
    CJK, etc.) survive Uvicorn's Latin-1 header encoding. Issue #106.
    """
    if not isinstance(filename, str) or not filename.strip():
        safe_name = "audio"
    else:
        # Round-trip through UTF-8 with replacement to scrub lone surrogates
        # that filesystems on some platforms leak; quote() would otherwise raise.
        safe_name = filename.encode("utf-8", "replace").decode("utf-8")
    ascii_fallback = (
        safe_name.encode("ascii", "replace").decode("ascii").translate(_ASCII_FALLBACK_REPLACE)
    )
    utf8_quoted = quote(safe_name, safe="")
    return f"{disposition}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{utf8_quoted}"


class RecordingResponse(BaseModel):
    """Response model for a recording."""

    id: int
    filename: str
    filepath: str
    title: str | None = None
    duration_seconds: float
    recorded_at: str
    imported_at: str | None = None
    word_count: int = 0
    has_diarization: bool = False
    summary: str | None = None
    summary_model: str | None = None
    transcription_backend: str | None = None


class RecordingDetailResponse(RecordingResponse):
    """Detailed recording response with segments and words."""

    segments: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []


class SummaryUpdate(BaseModel):
    """Request body for updating a recording's summary."""

    summary: str | None = None
    summary_model: str | None = None


class TitleUpdate(BaseModel):
    """Request body for updating a recording's title."""

    title: str


class DateUpdate(BaseModel):
    """Request body for updating a recording's recorded_at date."""

    recorded_at: str


class TurnConfidence(BaseModel):
    """One per-turn diarization confidence entry. Story 5.4 (Issue #104)."""

    turn_index: int
    speaker_id: str | None = None
    confidence: float


class DiarizationConfidenceResponse(BaseModel):
    """Response shape for ``GET /recordings/{id}/diarization-confidence``."""

    recording_id: int
    turns: list[TurnConfidence]


class DiarizationReviewState(BaseModel):
    """ADR-009 lifecycle state for a recording (Story 5.6 / 5.7)."""

    recording_id: int
    status: str | None = None  # None when no row exists
    reviewed_turns_json: str | None = None


class DiarizationReviewSubmit(BaseModel):
    """POST body for the lifecycle endpoint (Stories 5.7 / 5.9)."""

    action: str  # 'open' (Story 5.7 banner CTA) | 'complete' (Story 5.9 Run summary now)
    reviewed_turns: list[dict] | None = None  # populated when action='complete'


class AliasItem(BaseModel):
    """One speaker alias entry. Story 4.2 (Issue #104)."""

    speaker_id: str
    alias_name: str


class AliasesPayload(BaseModel):
    """PUT body — full-replace list of aliases for a recording."""

    aliases: list[AliasItem]


class AliasesResponse(BaseModel):
    """GET / PUT response shape for the alias endpoints."""

    recording_id: int
    aliases: list[AliasItem]


@router.get("/recordings", response_model=list[RecordingResponse])
async def list_recordings(
    start_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
) -> list[dict[str, Any]]:
    """
    List all recordings, optionally filtered by date range.
    """
    try:
        if start_date and end_date:
            recordings = get_recordings_by_date_range(start_date, end_date)
        else:
            recordings = get_all_recordings()

        return recordings

    except Exception as e:
        logger.error(f"Failed to list recordings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/recordings/{recording_id}", response_model=RecordingDetailResponse)
async def get_recording_detail(recording_id: int) -> dict[str, Any]:
    """
    Get a single recording with full details including segments and words.
    """
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    # Get segments and words
    segments = get_segments(recording_id)
    words = get_words(recording_id)

    return {
        **recording,
        "segments": segments,
        "words": words,
    }


@router.delete("/recordings/{recording_id}")
async def remove_recording(
    recording_id: int,
    delete_artifacts: bool = False,
    artifact_profile_id: int | None = None,
) -> dict[str, Any]:
    """
    Delete a recording and all associated data.

    Deletion order is important for data integrity:
    1. Delete from database first (can be rolled back, critical data)
    2. Then delete audio file (orphan file is safer than orphan record)
    3. (Story 3.7) When ``delete_artifacts=true`` AND
       ``artifact_profile_id`` references an existing profile, derive the
       expected on-disk transcript filename from that profile's template +
       destination_folder, render it against the recording's metadata,
       sanitize, and unlink (best-effort). Default is to LEAVE on-disk
       files (FR48 — least surprise).

    Notebook recordings don't carry a profile snapshot, so the active
    profile id supplied by the renderer (``artifact_profile_id``) is the
    only signal the server has for which template was used at export
    time. If a previous export used a DIFFERENT profile, the derived
    path won't match and the file remains on disk — harmless, the user
    can clean it up manually.
    """
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    audio_path = Path(recording["filepath"])

    # 1. Delete from database FIRST (critical - can be rolled back)
    if not delete_recording(recording_id):
        raise HTTPException(status_code=500, detail="Failed to delete recording")

    artifact_failures: list[str] = []

    # 2. Delete audio file AFTER database success
    # If this fails, we have an orphan file (harmless) rather than an orphan record
    try:
        if audio_path.exists():
            audio_path.unlink()
    except Exception as e:
        logger.warning(f"Orphan file cleanup needed for {audio_path}: {e}")
        artifact_failures.append(str(audio_path))

    # 3. (Story 3.7 AC3) Opt-in delete of on-disk transcript/summary
    # export artifacts. Best-effort — surface failures via artifact_failures
    # but never block the DB delete (right-to-erasure best-effort, R-EL32).
    if delete_artifacts and artifact_profile_id is not None:
        from server.core.filename_template import render_and_sanitize
        from server.database import profile_repository

        profile = profile_repository.get_profile(artifact_profile_id)
        if profile is not None:
            public = profile.get("public_fields", {}) or {}
            template = public.get("filename_template") or "{date} - {title}.txt"
            destination = public.get("destination_folder")
            if destination:
                rendered = render_and_sanitize(template, recording)
                target = Path(destination) / rendered
                try:
                    if target.exists():
                        target.unlink()
                except Exception as e:
                    logger.warning(f"Artifact cleanup failed for {target}: {e}")
                    artifact_failures.append(str(target))

    return {
        "status": "deleted",
        "id": str(recording_id),
        "artifact_failures": artifact_failures,
    }


@router.put("/recordings/{recording_id}/summary")
async def update_summary_put(
    recording_id: int,
    summary: str,
    summary_model: str | None = None,
) -> dict[str, Any]:
    """
    Update the summary for a recording (PUT with query param).
    """
    if not get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")

    if update_recording_summary(recording_id, summary, summary_model):
        return {
            "status": "updated",
            "id": recording_id,
            "summary": summary,
            "summary_model": summary_model if summary else None,
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to update summary")


@router.patch("/recordings/{recording_id}/summary")
async def update_summary_patch(
    recording_id: int,
    body: SummaryUpdate,
) -> dict[str, Any]:
    """
    Update the summary for a recording (PATCH with JSON body).
    """
    if not get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")

    if update_recording_summary(recording_id, body.summary, body.summary_model):
        return {
            "status": "updated",
            "id": recording_id,
            "summary": body.summary,
            "summary_model": body.summary_model if body.summary else None,
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to update summary")


@router.patch("/recordings/{recording_id}/title")
async def update_title_patch(
    recording_id: int,
    body: TitleUpdate,
) -> dict[str, Any]:
    """Update the title for a recording (PATCH with JSON body)."""
    if not get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")

    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")

    if update_recording_title(recording_id, title):
        return {"status": "updated", "id": recording_id, "title": title}
    else:
        raise HTTPException(status_code=500, detail="Failed to update title")


@router.patch("/recordings/{recording_id}/date")
async def update_date_patch(
    recording_id: int,
    body: DateUpdate,
) -> dict[str, Any]:
    """Update the recorded_at date for a recording."""
    if not get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")

    recorded_at = body.recorded_at.strip()
    if not recorded_at:
        raise HTTPException(status_code=400, detail="Date cannot be empty")

    if update_recording_date(recording_id, recorded_at):
        return {"status": "updated", "id": recording_id, "recorded_at": recorded_at}
    else:
        raise HTTPException(status_code=500, detail="Failed to update date")


# ---------------------------------------------------------------------------
# Speaker aliases (Issue #104, Story 4.2)
# ---------------------------------------------------------------------------
# Mounted on the notebook router rather than a top-level /api/recordings
# router because notebook recordings are the only entity that owns
# speaker labels in this codebase. URL-prefix override is documented in
# `_bmad-output/implementation-artifacts/sprint-3-design.md` §1.


@router.get(
    "/recordings/{recording_id}/diarization-review",
    response_model=DiarizationReviewState,
)
async def get_diarization_review_state(
    recording_id: int,
) -> DiarizationReviewState:
    """Return the current ADR-009 lifecycle state (Issue #104, Story 5.7).

    Returns ``status: null`` (no row) when no review has been triggered
    for this recording — the dashboard treats null as "no banner".
    """
    if not get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    from server.database import diarization_review_repository as repo

    row = repo.get_review(recording_id)
    return DiarizationReviewState(
        recording_id=recording_id,
        status=row["status"] if row else None,
        reviewed_turns_json=row["reviewed_turns_json"] if row else None,
    )


@router.post(
    "/recordings/{recording_id}/diarization-review",
    response_model=DiarizationReviewState,
)
async def submit_diarization_review(
    recording_id: int,
    payload: DiarizationReviewSubmit,
) -> DiarizationReviewState:
    """Lifecycle trigger endpoint (Stories 5.7 / 5.9).

    Actions:
      - ``open``     — pending → in_review (banner CTA invokes this)
      - ``complete`` — in_review → completed; persists ``reviewed_turns_json``;
                       Sprint 4 Story 6.2 calls ``on_auto_summary_fired()``
                       to flip to ``released``

    Persist-Before-Deliver (NFR16): each lifecycle trigger commits before
    returning, so the response reflects committed state.
    """
    if not get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")

    import json

    from server.core.diarization_review_lifecycle import (
        IllegalReviewTransitionError,
        on_review_view_opened,
        on_run_summary_now_clicked,
    )
    from server.database import diarization_review_repository as repo

    try:
        if payload.action == "open":
            on_review_view_opened(recording_id)
        elif payload.action == "complete":
            # Lifecycle transition FIRST — illegal-transition failure
            # must leave reviewed_turns_json untouched. Writing the JSON
            # before the transition would produce orphan data when the
            # transition raises (e.g. someone raced and the row is no
            # longer in_review). After the transition succeeds, the
            # JSON write commits separately but is functionally a follow-up
            # decoration of an already-completed row.
            on_run_summary_now_clicked(recording_id)
            if payload.reviewed_turns is not None:
                repo.update_reviewed_turns(
                    recording_id,
                    json.dumps(payload.reviewed_turns, ensure_ascii=False, sort_keys=True),
                )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid action: {payload.action!r}. Expected 'open' or 'complete'.",
            )
    except IllegalReviewTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    row = repo.get_review(recording_id)
    return DiarizationReviewState(
        recording_id=recording_id,
        status=row["status"] if row else None,
        reviewed_turns_json=row["reviewed_turns_json"] if row else None,
    )


@router.get(
    "/recordings/{recording_id}/diarization-confidence",
    response_model=DiarizationConfidenceResponse,
)
async def get_diarization_confidence(
    recording_id: int,
) -> DiarizationConfidenceResponse:
    """Per-turn diarization confidence (Issue #104, Story 5.4).

    Returns ``{recording_id, turns: [{turn_index, speaker_id, confidence}, ...]}``.
    Older recordings without word-level confidence return ``turns: []`` —
    the dashboard treats absent turns as "no chip rendering" (Story 5.5).
    """
    if not get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    from server.core.diarization_confidence import per_turn_confidence

    segments = get_segments(recording_id)
    words = get_words(recording_id)
    return DiarizationConfidenceResponse(
        recording_id=recording_id,
        turns=[TurnConfidence(**t) for t in per_turn_confidence(segments, words)],
    )


@router.get(
    "/recordings/{recording_id}/aliases",
    response_model=AliasesResponse,
)
async def list_recording_aliases(recording_id: int) -> AliasesResponse:
    """List speaker aliases for a recording.

    Returns an empty array when no aliases are stored — never 404 for
    a missing alias set (Story 4.2 AC1). Returns 404 only when the
    recording itself does not exist.
    """
    if not get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    from server.database import alias_repository

    return AliasesResponse(
        recording_id=recording_id,
        aliases=[AliasItem(**row) for row in alias_repository.list_aliases(recording_id)],
    )


@router.put(
    "/recordings/{recording_id}/aliases",
    response_model=AliasesResponse,
)
async def update_recording_aliases(
    recording_id: int,
    payload: AliasesPayload,
) -> AliasesResponse:
    """Full-replace upsert of recording aliases (Story 4.2 AC2).

    Each item in ``payload.aliases`` is upserted on
    ``(recording_id, speaker_id)``. Pre-existing rows whose
    ``speaker_id`` is NOT in the request body are deleted.

    The ``alias_name`` is preserved verbatim (R-EL3) — only surrounding
    whitespace is stripped. Empty alias names (after strip) are
    skipped, which has the effect of CLEARING the alias for that
    speaker_id.
    """
    if not get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")

    from server.database import alias_repository

    cleaned: list[dict[str, str]] = []
    for entry in payload.aliases:
        # Validate speaker_id — must be a non-empty token. Whitespace and
        # NUL bytes are rejected because `speaker_id` is used as a join
        # key against `segments.speaker` and a malformed value would
        # silently produce a label miss (the alias never matches a turn).
        speaker_id = entry.speaker_id.strip() if entry.speaker_id else ""
        if not speaker_id or "\x00" in speaker_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid speaker_id: {entry.speaker_id!r} — must be a "
                    "non-empty string without NUL bytes."
                ),
            )
        trimmed = entry.alias_name.strip()
        if not trimmed:
            # Empty alias → drop the row (full-replace semantics handle it)
            continue
        cleaned.append({"speaker_id": speaker_id, "alias_name": trimmed})

    alias_repository.replace_aliases(recording_id, cleaned)

    return AliasesResponse(
        recording_id=recording_id,
        aliases=[AliasItem(**row) for row in alias_repository.list_aliases(recording_id)],
    )


@router.get("/recordings/{recording_id}/audio")
async def get_audio_file(
    recording_id: int,
    range: str | None = Header(None, alias="Range"),
) -> Response:
    """
    Stream the audio file for a recording with HTTP Range request support.

    Supports partial content requests (HTTP 206) for efficient seeking in large files.
    """
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    audio_path = Path(recording["filepath"])
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    # Determine media type
    suffix = audio_path.suffix.lower()
    media_types = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
    }
    media_type = media_types.get(suffix, "audio/mpeg")

    file_size = audio_path.stat().st_size

    # Check for Range header
    if range:
        # Parse range header: "bytes=start-end"
        range_match = re.match(r"bytes=(\d+)-(\d*)", range)
        if range_match:
            start = int(range_match.group(1))
            end_str = range_match.group(2)
            end = int(end_str) if end_str else file_size - 1

            # Validate range
            if start >= file_size:
                raise HTTPException(
                    status_code=416,
                    detail="Range Not Satisfiable",
                    headers={"Content-Range": f"bytes */{file_size}"},
                )

            end = min(end, file_size - 1)
            content_length = end - start + 1

            async def stream_range():
                async with aiofiles.open(audio_path, "rb") as f:
                    await f.seek(start)
                    remaining = content_length
                    chunk_size = 64 * 1024  # 64KB chunks
                    while remaining > 0:
                        chunk = await f.read(min(chunk_size, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            return StreamingResponse(
                stream_range(),
                status_code=206,
                media_type=media_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(content_length),
                    "Content-Disposition": _content_disposition("inline", recording["filename"]),
                },
            )

    # No Range header - return full file with Accept-Ranges header
    return FileResponse(
        path=audio_path,
        media_type=media_type,
        filename=recording["filename"],
        headers={"Accept-Ranges": "bytes"},
    )


@router.get("/recordings/{recording_id}/transcription")
async def get_transcription(recording_id: int) -> dict[str, Any]:
    """
    Get the transcription for a recording (segments with words).
    """
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    segments = get_segments(recording_id)
    words = get_words(recording_id)

    # Group words by segment_id
    words_by_segment: dict[int, list[dict[str, Any]]] = {}
    for word in words:
        seg_id = word.get("segment_id")
        if seg_id not in words_by_segment:
            words_by_segment[seg_id] = []
        words_by_segment[seg_id].append(
            {
                "word": word.get("word", ""),
                "start": word.get("start_time", 0),
                "end": word.get("end_time", 0),
                "confidence": word.get("confidence"),
            }
        )

    # Build segments with embedded words
    result_segments = []
    for seg in segments:
        seg_id = seg.get("id")
        result_segments.append(
            {
                "text": seg.get("text", ""),
                "start": seg.get("start_time", 0),
                "end": seg.get("end_time", 0),
                "speaker": seg.get("speaker"),
                "words": words_by_segment.get(seg_id, []),
            }
        )

    return {
        "recording_id": recording_id,
        "segments": result_segments,
    }


class UploadResponse(BaseModel):
    """Response model for file upload."""

    recording_id: int
    message: str
    diarization: dict[str, Any]


class AcceptedResponse(BaseModel):
    """Response model for accepted transcription job (202)."""

    job_id: str


def _run_transcription(
    *,
    model_manager: Any,
    tmp_path: Path,
    filename: str,
    language: str | None,
    translation_enabled: bool,
    translation_target_language: str | None,
    enable_diarization: bool,
    enable_word_timestamps: bool,
    file_created_at: str | None,
    expected_speakers: int | None,
    parallel_diarization: bool | None,
    use_parallel_default: bool,
    title: str | None,
    job_id: str,
    event_loop: Any = None,
    audio_hash: str | None = None,
    normalized_audio_hash: str | None = None,
    profile_snapshot: dict[str, Any] | None = None,
) -> None:
    """
    Run transcription in a background thread.

    This is a synchronous function intended to be called via asyncio.to_thread().
    It performs the full transcription pipeline and stores the result (or error)
    in model_manager.job_tracker so that clients can poll for completion.
    """
    # Lazy import to avoid loading torch at module import time
    from server.core.audio_utils import convert_to_mp3, load_audio

    try:
        # Progress callback to update job tracker with chunk progress
        def on_progress(current: int, total: int) -> None:
            model_manager.job_tracker.update_progress(current, total)

        # Get transcription engine, lazily reloading the model if a prior
        # Live-Mode restore or sequential-diarization swap left it detached.
        # See ModelManager.ensure_transcription_loaded() for the full rationale
        # (Issue #76).
        engine = model_manager.ensure_transcription_loaded()

        # Check if the backend supports single-pass diarization (WhisperX)
        from server.core.stt.backends.base import STTBackend

        backend = engine._backend
        use_integrated_diarization = (
            enable_diarization
            and backend is not None
            and type(backend).transcribe_with_diarization
            is not STTBackend.transcribe_with_diarization
        )

        # Run diarization if enabled
        diarization_segments = None
        diarization_outcome: dict[str, Any] = {
            "requested": bool(enable_diarization),
            "performed": False,
            "reason": None,
        }

        if use_integrated_diarization:
            # --- Integrated backend single-pass path (e.g. WhisperX, VibeVoice) ---
            try:
                backend_label = getattr(backend, "backend_name", "integrated")
                logger.info(
                    "Using %s single-pass diarization for: %s",
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

                diarization_segments = diar_result.segments
                diarization_outcome["performed"] = True
                diarization_outcome["reason"] = "ready"
                logger.info(
                    "%s diarization complete: %s speakers found",
                    backend_label,
                    diar_result.num_speakers,
                )

            except ValueError as e:
                logger.error(f"Diarization requires HuggingFace token: {e}")
                logger.error("Set HUGGINGFACE_TOKEN env var when starting docker compose")
                diarization_outcome["reason"] = model_manager.get_diarization_feature_status().get(
                    "reason", "token_missing"
                )
                # Fall back to transcription without diarization
                use_integrated_diarization = False
            except Exception as e:
                logger.error("Integrated backend diarization failed (continuing without): %s", e)
                diarization_outcome["reason"] = "unavailable"
                # Fall back to transcription without diarization
                use_integrated_diarization = False

        if not use_integrated_diarization:
            # --- Standard path (NeMo backends or WhisperX fallback) ---
            # Force word timestamps if diarization is enabled
            # (needed for proper text-to-speaker alignment, even if user doesn't want to save words)
            need_word_timestamps = enable_word_timestamps or enable_diarization

            if enable_diarization and not diarization_outcome["performed"]:
                # Resolve parallel vs sequential diarization
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
                    diarization_segments = [seg.to_dict() for seg in diar_result.segments]
                    diarization_outcome["performed"] = True
                    diarization_outcome["reason"] = "ready"
                    logger.info(
                        "Diarization complete: %s speakers found",
                        diar_result.num_speakers,
                    )
                else:
                    diarization_outcome["reason"] = (
                        model_manager.get_diarization_feature_status().get("reason", "unavailable")
                    )
            else:
                # Transcribe without diarization
                logger.info(f"Transcribing uploaded file for notebook: {filename}")
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

        # Determine recorded_at timestamp
        recorded_at = None
        if file_created_at:
            try:
                recorded_at = datetime.fromisoformat(file_created_at.replace("Z", "+00:00"))
            except ValueError:
                logger.warning(
                    f"Invalid file_created_at format: {sanitize_for_log(file_created_at)}"
                )

        # Check for time slot overlap before saving
        check_time = recorded_at or datetime.now()
        overlap = check_time_slot_overlap(check_time, result.duration)
        if overlap:
            overlap_title = overlap.get("title") or overlap.get("filename", "Unknown")
            raise ValueError(
                f"Time slot conflict: overlaps with existing recording '{overlap_title}' "
                f"(recorded at {overlap.get('recorded_at', 'unknown time')})"
            )

        # Convert audio to MP3 and save to permanent storage
        config = get_config()
        _data_dir = os.environ.get("DATA_DIR", "/data")
        audio_dir = Path(config.get("audio_notebook", "audio_dir", default=f"{_data_dir}/audio"))
        audio_dir.mkdir(parents=True, exist_ok=True)

        # Keep original filename, convert to .mp3 extension
        # Sanitize filename to prevent path traversal
        raw_stem = Path(filename or "audio").stem
        # Remove any path separators and sanitize to alphanumeric + safe chars
        original_stem = "".join(c for c in raw_stem if c.isalnum() or c in "._- ")[:100]
        if not original_stem:
            original_stem = "audio"
        dest_filename = f"{original_stem}.mp3"
        dest_path = audio_dir / dest_filename

        # Handle duplicates by adding -2, -3, etc. suffix
        counter = 2
        while dest_path.exists():
            dest_filename = f"{original_stem}-{counter}.mp3"
            dest_path = audio_dir / dest_filename
            counter += 1

        # Convert to MP3 for storage efficiency
        convert_to_mp3(str(tmp_path), str(dest_path))

        # Extract word timestamps from segments
        # Diarization automatically enables word timestamps (they're needed for alignment anyway)
        word_timestamps_list = None

        # Extract words from segments if they were computed
        if result.segments and "words" in result.segments[0]:
            word_timestamps_list = []
            for seg in result.segments:
                if "words" in seg:
                    word_timestamps_list.extend(seg["words"])

        # When diarization was performed but no word timestamps are available
        # (e.g. MLX Canary backend), fall back to segment-level speaker
        # attribution so that the DB segments carry text instead of being empty.
        if diarization_segments and not word_timestamps_list:
            from server.core.speaker_merge import build_speaker_segments_nowords

            diarization_segments = build_speaker_segments_nowords(
                result.segments, diarization_segments
            )

        # Save to database
        # Use provided title if given, otherwise database falls back to filename stem
        clean_title = title.strip() if title else None
        transcription_backend = detect_backend_type(getattr(engine, "model_name", "") or "")
        recording_id = save_longform_to_database(
            audio_path=dest_path,
            duration_seconds=result.duration,
            transcription_text=result.text,
            word_timestamps=word_timestamps_list,
            diarization_segments=diarization_segments,
            recorded_at=recorded_at,
            title=clean_title or None,
            transcription_backend=transcription_backend,
            audio_hash=audio_hash,
            normalized_audio_hash=normalized_audio_hash,
        )

        if not recording_id:
            raise RuntimeError("Failed to save recording to database")

        # Store successful result for client polling
        model_manager.job_tracker.end_job(
            job_id,
            result={
                "job_id": job_id[:8],
                "recording_id": recording_id,
                "message": f"Successfully transcribed and saved: {filename}",
                "diarization": diarization_outcome,
            },
        )
        logger.info(
            f"Background transcription job {job_id[:8]} completed: recording_id={recording_id}"
        )

        # Issue #104, Story 5.6 — diarization-review lifecycle hook +
        # Story 6.2 / 6.3 — auto-action coordinator dispatch.
        # Both fire AFTER the transcript has been committed (Persist-Before-Deliver).
        if event_loop is not None:
            from server.core.auto_action_coordinator import trigger_auto_actions
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
                # Lifecycle bookkeeping must never crash the transcription pipeline.
                logger.exception(
                    "diarization-review lifecycle hook failed for recording %d",
                    recording_id,
                )

            # Fire-and-forget the auto-action coordinator on the main loop.
            # Disabled toggles are a no-op inside the coordinator.
            try:
                asyncio.run_coroutine_threadsafe(
                    trigger_auto_actions(recording_id, profile_snapshot),
                    event_loop,
                )
            except Exception:
                logger.exception(
                    "trigger_auto_actions dispatch failed for recording %d",
                    recording_id,
                )

        # Fire outgoing webhook (background thread — use fire-and-forget)
        if event_loop is not None:
            from server.core.webhook import dispatch_fire_and_forget

            dispatch_fire_and_forget(
                event_loop,
                "longform_complete",
                {
                    "source": "longform",
                    "text": result.text,
                    "filename": filename or "",
                    "duration": result.duration,
                    "language": result.language,
                    "num_speakers": result.num_speakers,
                },
            )

    except Exception as e:
        logger.error(f"Background transcription job {job_id[:8]} failed: {e}", exc_info=True)
        # Surface the BackendDependencyError remedy so the dashboard can render
        # an actionable hint instead of just the bare error string (Issue #76).
        from server.core.stt.backends.base import BackendDependencyError

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
        # Store error result for client polling
        model_manager.job_tracker.end_job(
            job_id,
            result=error_payload,
        )

    finally:
        # Cleanup temp file
        try:
            tmp_path.unlink()
        except Exception as e:
            logger.warning(f"Failed to cleanup temp file {tmp_path}: {e}")


@router.post("/transcribe/upload", response_model=AcceptedResponse, status_code=202)
async def upload_and_transcribe(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    language: str | None = Form(None),
    translation_enabled: bool = Form(False),
    translation_target_language: str | None = Form(None),
    enable_diarization: bool = Form(False),
    enable_word_timestamps: bool = Form(True),
    file_created_at: str | None = Form(None),
    expected_speakers: int | None = Form(None),
    parallel_diarization: bool | None = Form(None),
    title: str | None = Form(None),
    profile_id: int | None = Form(None),
) -> dict[str, Any]:
    """
    Upload an audio file and start transcription in the background.

    Returns 202 Accepted immediately with a job_id. Clients should poll
    GET /api/admin/status to check job_tracker.result for completion.

    Parameters:
    - expected_speakers: Exact number of speakers (2-10). Forces diarization to
      identify exactly this many speakers. Useful for podcasts with known hosts
      where occasional clips should be attributed to the main speakers.
    - parallel_diarization: Override the server default for parallel vs sequential
      diarization. When False, transcription completes before diarization starts
      (lower VRAM usage). When None, uses the server config default.

    Returns 409 Conflict if another transcription job is already running.
    """
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

    # Compute audio_hash for dedup (Issue #104, Sprint 2 carve-out — Item 2).
    # Hash the raw upload bytes — same approach as /api/transcribe/import. The
    # hash is written atomically with the recordings row in
    # save_longform_to_database; the dashboard can later call dedup-check to
    # match notebook recordings against transcription_jobs and other notebook
    # recordings.
    # Sprint 2 Item 3 — also compute the normalized PCM hash for
    # format-agnostic dedup. ffmpeg failure → NULL second hash, upload still
    # proceeds.
    from server.core.audio_utils import (
        compute_normalized_pcm_hash as _norm_sha,
    )
    from server.core.audio_utils import sha256_streaming as _sha

    try:
        audio_hash: str | None = _sha(tmp_path)
    except OSError as hash_err:
        # Tempfile vanished or unreadable — release the job slot and surface
        # the failure before any DB row is created (mirrors the request-path
        # invariant: failed pre-conditions never produce orphan records).
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        model_manager.job_tracker.cancel_job()
        raise HTTPException(
            status_code=500,
            detail="Failed to compute audio hash for upload",
        ) from hash_err
    normalized_audio_hash: str | None = _norm_sha(tmp_path)

    # Resolve parallel diarization default from config before entering background thread
    config = request.app.state.config
    use_parallel_default = config.get("diarization", "parallel", default=True)

    # Issue #104, Story 6.2 — snapshot the profile at upload time so the
    # background thread (which may finish minutes later) sees the SAME
    # toggles even if the user edits the profile during transcription.
    profile_snapshot: dict[str, Any] | None = None
    if profile_id is not None:
        from server.database import profile_repository

        profile_row = profile_repository.get_profile(profile_id)
        if profile_row is not None:
            profile_snapshot = {
                "profile_id": profile_id,
                "schema_version": profile_row.get("schema_version"),
                "public_fields": profile_row.get("public_fields") or {},
            }

    # Capture event loop for webhook dispatch from background thread
    loop = asyncio.get_running_loop()

    # Launch background transcription task (runs on thread pool, doesn't block event loop)
    loop.create_task(
        asyncio.to_thread(
            _run_transcription,
            model_manager=model_manager,
            tmp_path=tmp_path,
            filename=file.filename,
            language=language,
            translation_enabled=translation_enabled,
            translation_target_language=translation_target_language,
            enable_diarization=enable_diarization,
            enable_word_timestamps=enable_word_timestamps,
            file_created_at=file_created_at,
            expected_speakers=expected_speakers,
            parallel_diarization=parallel_diarization,
            use_parallel_default=use_parallel_default,
            title=title,
            job_id=job_id,
            event_loop=loop,
            audio_hash=audio_hash,
            normalized_audio_hash=normalized_audio_hash,
            profile_snapshot=profile_snapshot,
        )
    )

    # Return immediately — client polls /api/admin/status for result
    return {"job_id": job_id[:8]}


@router.get("/calendar")
async def get_calendar_data(
    year: int = Query(..., description="Year"),
    month: int = Query(..., description="Month (1-12)"),
) -> dict[str, Any]:
    """
    Get recordings grouped by day for calendar view.
    """
    try:
        # Get date range for the month
        start_date = f"{year:04d}-{month:02d}-01"
        if month == 12:
            end_date = f"{year + 1:04d}-01-01"
        else:
            end_date = f"{year:04d}-{month + 1:02d}-01"

        recordings = get_recordings_by_date_range(start_date, end_date)

        # Group by day
        days: dict[str, list[dict[str, Any]]] = {}
        for rec in recordings:
            recorded_at = rec.get("recorded_at", "")
            if recorded_at:
                day = recorded_at[:10]  # YYYY-MM-DD
                if day not in days:
                    days[day] = []
                days[day].append(rec)

        return {
            "year": year,
            "month": month,
            "days": days,
            "total_recordings": len(recordings),
        }

    except Exception as e:
        logger.error(f"Failed to get calendar data: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/timeslot")
async def get_timeslot_info(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    hour: int = Query(..., ge=0, le=23, description="Hour (0-23)"),
) -> dict[str, Any]:
    """
    Get information about a specific time slot.

    Returns:
    - recordings: List of recordings in this slot
    - next_available: ISO timestamp of next available start time (or null if full)
    - total_duration: Total duration of recordings in seconds
    - available_seconds: Remaining seconds available in the slot
    - is_full: Whether the slot is completely full
    """
    try:
        info = get_time_slot_info(date, hour)
        return info

    except Exception as e:
        logger.error(f"Failed to get time slot info: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/recordings/{recording_id}/export")
async def export_recording(
    recording_id: int,
    format: str = Query(
        "txt",
        description="Export format: 'txt', 'srt', 'ass', or 'plaintext'",
    ),
) -> Response:
    """
    Export a recording's transcription.

    Includes:
    - Recording metadata (title, date, duration)
    - Full transcription text
    - Subtitle cue rendering from word-level timestamps (if present)
    - Speaker labels (if diarization is present)

    Formats:
    - txt: Verbose human-readable text — full metadata header + transcript
    - plaintext: FR9 streaming format — paragraph-per-speaker-turn, no
      subtitle timestamps, no metadata header. Used by the Sprint 2
      "Download transcript" button (Issue #104, Story 3.4).
    - srt: SubRip subtitle format
    - ass: Advanced SubStation Alpha subtitle format
    """
    requested_format = format.strip().lower()
    if requested_format not in {"txt", "srt", "ass", "plaintext"}:
        raise HTTPException(
            status_code=400,
            detail="Unsupported export format. Supported formats: txt, plaintext, srt, ass.",
        )

    # Story 3.4 — plaintext is a streaming response that bypasses the
    # full materialization path used by txt/srt/ass. We branch early so
    # we don't pay the cost of get_words() / cue building for plaintext.
    if requested_format == "plaintext":
        recording = get_recording(recording_id)
        if not recording:
            raise HTTPException(status_code=404, detail="Recording not found")
        from server.core.alias_substitution import apply_aliases
        from server.core.plaintext_export import stream_plaintext
        from server.database import alias_repository
        from server.database.database import iter_segments

        title = recording.get("title") or recording.get("filename") or "Recording"
        rendered_filename = (
            f"{title.replace(' ', '_')}.txt" if title else f"recording_{recording_id}.txt"
        )
        # Story 5.1 — alias propagation. ``apply_aliases`` is a lazy
        # generator over ``iter_segments``, so the bounded-RAM property
        # of the streaming exporter is preserved.
        aliases = alias_repository.alias_map(recording_id)
        return StreamingResponse(
            stream_plaintext(
                recording,
                apply_aliases(iter_segments(recording_id), aliases),
            ),
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": _content_disposition("attachment", rendered_filename),
            },
        )

    try:
        recording = get_recording(recording_id)
        if not recording:
            raise HTTPException(status_code=404, detail="Recording not found")

        segments = get_segments(recording_id)
        words = get_words(recording_id)

        # Parse recording date
        recorded_at = recording.get("recorded_at", "")
        try:
            rec_dt = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
            date_str = rec_dt.strftime("%B %d, %Y at %I:%M %p")
        except (ValueError, AttributeError):
            date_str = recorded_at or ""

        # Format duration — coerce so a NULL duration_seconds doesn't crash arithmetic (Issue #98).
        duration = _to_float(recording.get("duration_seconds"), default=0.0)
        if duration < 60:
            duration_str = f"{int(duration)} seconds"
        elif duration < 3600:
            mins = int(duration // 60)
            secs = int(duration % 60)
            duration_str = f"{mins} min {secs} sec"
        else:
            hours = int(duration // 3600)
            mins = int((duration % 3600) // 60)
            duration_str = f"{hours} hr {mins} min"

        title = recording.get("title") or recording.get("filename") or "Recording"
        has_diarization = bool(recording.get("has_diarization"))
        has_words = len(words) > 0
        is_pure_note = (not has_diarization) and (not has_words)

        if is_pure_note and requested_format != "txt":
            raise HTTPException(
                status_code=400,
                detail="This recording only supports TXT export. SRT/ASS require word timestamps or diarization.",
            )

        if (not is_pure_note) and requested_format == "txt":
            raise HTTPException(
                status_code=400,
                detail="This recording supports subtitle export only. Use SRT or ASS.",
            )

        if requested_format == "txt":
            # Human-readable text export
            lines = []
            lines.append("=" * 60)
            lines.append("TRANSCRIPTION EXPORT")
            lines.append("=" * 60)
            lines.append("")
            lines.append(f"Title: {title}")
            lines.append(f"Date: {date_str}")
            lines.append(f"Duration: {duration_str}")
            lines.append(f"Word Count: {recording.get('word_count') or 0}")
            if has_diarization:
                lines.append("Speaker Diarization: Yes")
            lines.append("")

            if recording.get("summary"):
                lines.append("-" * 40)
                lines.append("SUMMARY")
                lines.append("-" * 40)
                lines.append(recording["summary"])
                lines.append("")

            lines.append("-" * 40)
            lines.append("TRANSCRIPTION")
            lines.append("-" * 40)
            lines.append("")

            if has_diarization and segments:
                # Group by speaker with timestamps
                current_speaker = None
                for seg in segments:
                    speaker = seg.get("speaker") or "Unknown"
                    start = _to_float(seg.get("start_time"), default=0.0)
                    text = str(seg.get("text") or "").strip()

                    # Format timestamp
                    mins = int(start // 60)
                    secs = int(start % 60)
                    timestamp = f"[{mins:02d}:{secs:02d}]"

                    if speaker != current_speaker:
                        lines.append("")
                        lines.append(f"{speaker}:")
                        current_speaker = speaker

                    lines.append(f"  {timestamp} {text}")
            else:
                # Simple text output with timestamps
                for seg in segments:
                    start = _to_float(seg.get("start_time"), default=0.0)
                    text = str(seg.get("text") or "").strip()
                    mins = int(start // 60)
                    secs = int(start % 60)
                    lines.append(f"[{mins:02d}:{secs:02d}] {text}")

            # Add word-level timestamps section if present
            if words:
                lines.append("")
                lines.append("-" * 40)
                lines.append("WORD-LEVEL TIMESTAMPS")
                lines.append("-" * 40)
                lines.append("")

                word_lines = []
                for w in words:
                    word = str(w.get("word") or "")
                    start = _to_float(w.get("start_time"), default=0.0)
                    end = _to_float(w.get("end_time"), default=0.0)
                    conf = w.get("confidence")
                    conf_str = f" ({conf:.2f})" if isinstance(conf, (int, float)) else ""
                    word_lines.append(f"{word} [{start:.2f}s-{end:.2f}s]{conf_str}")

                # Group words into lines of ~80 chars
                current_line = []
                current_len = 0
                for wl in word_lines:
                    if current_len + len(wl) + 2 > 80 and current_line:
                        lines.append("  ".join(current_line))
                        current_line = [wl]
                        current_len = len(wl)
                    else:
                        current_line.append(wl)
                        current_len += len(wl) + 2
                if current_line:
                    lines.append("  ".join(current_line))

            lines.append("")
            lines.append("=" * 60)
            lines.append("End of Export")
            lines.append("=" * 60)

            content = "\n".join(lines)
            filename = f"{title.replace(' ', '_')}_export.txt"
            media_type = "text/plain; charset=utf-8"
        else:
            # Story 5.1 — alias propagation to subtitle exports.
            from server.database import alias_repository

            cues = build_subtitle_cues(
                segments=segments,
                words=words,
                has_diarization=has_diarization,
                alias_overrides=alias_repository.alias_map(recording_id),
            )

            if requested_format == "srt":
                content = render_srt(cues)
                filename = f"{title.replace(' ', '_')}_export.srt"
                media_type = "application/x-subrip; charset=utf-8"
            else:
                content = render_ass(cues, title=title)
                filename = f"{title.replace(' ', '_')}_export.ass"
                media_type = "text/x-ass; charset=utf-8"

        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": _content_disposition("attachment", filename),
            },
        )
    except HTTPException:
        # Intentional 400/404 responses — pass through unchanged.
        raise
    except Exception as e:
        # Issue #98: surface the real cause to the client instead of FastAPI's
        # generic "Internal server error" envelope so users can report something
        # actionable. Full traceback still lands in the server log.
        logger.error(
            "Export failed for recording %s (format=%s): %s",
            recording_id,
            requested_format,
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Export failed: {type(e).__name__}: {e}",
        ) from e


# ──────────────────────────────────────────────────────────────────────────
# Re-export with current profile (Issue #104, Story 3.6)
# ──────────────────────────────────────────────────────────────────────────


class ReexportRequest(BaseModel):
    """Body for ``POST /api/notebook/recordings/{id}/reexport`` (Story 3.6)."""

    profile_id: int


class ReexportResponse(BaseModel):
    """Response shape for the re-export endpoint."""

    status: str
    path: str
    filename: str


@router.post("/recordings/{recording_id}/reexport", response_model=ReexportResponse)
async def reexport_recording(recording_id: int, body: ReexportRequest) -> ReexportResponse:
    """Render the recording's plaintext export using the CURRENT active
    profile's template and write a NEW file to that profile's
    destination_folder (FR17 forward-only).

    AC3.6.AC3: the original file from a prior export is NOT deleted —
    re-export is purely additive. Caller chooses to clean up the old file
    via the deletion dialog (Story 3.7).
    """
    from server.core.filename_template import render_and_sanitize
    from server.core.plaintext_export import stream_plaintext
    from server.database import profile_repository
    from server.database.database import iter_segments

    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    profile = profile_repository.get_profile(body.profile_id)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "profile_not_found", "id": body.profile_id},
        )

    public = profile.get("public_fields", {}) or {}
    template = public.get("filename_template") or "{date} - {title}.txt"
    destination = public.get("destination_folder") or ""
    if not destination:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "destination_folder_unset",
                "message": (
                    "The active profile has no destination_folder. "
                    "Set one in the profile editor before re-exporting."
                ),
            },
        )

    rendered = render_and_sanitize(template, recording)
    target_path = Path(destination) / rendered
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Stream to disk so an 8-hour transcript doesn't OOM the server.
    try:
        with open(target_path, "w", encoding="utf-8") as f:
            for chunk in stream_plaintext(recording, iter_segments(recording_id)):
                f.write(chunk)
    except OSError as exc:
        logger.error(
            "Re-export write failed for recording %s to %s: %s",
            recording_id,
            target_path,
            exc,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": "reexport_write_failed", "message": str(exc)},
        ) from exc

    return ReexportResponse(
        status="reexported",
        path=str(target_path),
        filename=rendered,
    )


def _get_backup_manager() -> DatabaseBackupManager:
    """Get the backup manager instance with configured paths."""
    config = get_config()
    db_path = get_db_path()
    backup_dir = db_path.parent / "backups"
    max_backups = config.get("backup", "max_backups", default=10)
    return DatabaseBackupManager(
        db_path=db_path,
        backup_dir=backup_dir,
        max_backups=max_backups,
    )


@router.get("/backups")
async def list_backups() -> dict[str, Any]:
    """
    List all available database backups.

    Returns:
        Dict with list of backups and their metadata
    """
    try:
        manager = _get_backup_manager()
        backups = manager.list_backups_with_info()
        return {
            "backups": backups,
            "count": len(backups),
        }
    except Exception as e:
        logger.error(f"Failed to list backups: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/backup")
async def create_backup() -> dict[str, Any]:
    """
    Create a manual database backup.

    Returns:
        Dict with backup info if successful
    """
    try:
        manager = _get_backup_manager()
        backup_path = manager.create_backup()

        if backup_path:
            info = manager.get_backup_info(backup_path)
            return {
                "success": True,
                "message": "Backup created successfully",
                "backup": info,
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to create backup")

    except Exception as e:
        logger.error(f"Failed to create backup: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


class RestoreRequest(BaseModel):
    """Request body for restore operation."""

    filename: str


@router.post("/restore")
async def restore_backup(body: RestoreRequest) -> dict[str, Any]:
    """
    Restore the database from a backup.

    This operation:
    1. Creates a safety backup of the current database
    2. Verifies the backup file integrity
    3. Restores the database from the backup

    Warning: This will replace all current data with the backup data.
    """
    try:
        manager = _get_backup_manager()

        # Find the backup file
        backups = manager.get_all_backups()
        backup_path = None
        for b in backups:
            if b.name == body.filename:
                backup_path = b
                break

        if not backup_path:
            raise HTTPException(status_code=404, detail=f"Backup not found: {body.filename}")

        # Verify backup is valid
        if not manager.verify_backup(backup_path):
            raise HTTPException(status_code=400, detail="Backup file is invalid or corrupted")

        # Perform restore
        success = manager.restore_backup(backup_path)

        if success:
            return {
                "success": True,
                "message": f"Database restored from {body.filename}",
                "restored_from": body.filename,
            }
        else:
            raise HTTPException(status_code=500, detail="Restore operation failed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to restore backup: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
