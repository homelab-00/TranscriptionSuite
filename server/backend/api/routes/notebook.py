"""
Audio Notebook API endpoints for TranscriptionSuite server.

Handles:
- Recording CRUD operations
- Audio file management
- Transcription import and export
"""

import logging
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from server.core.subtitle_export import build_subtitle_cues, render_ass, render_srt

# NOTE: audio_utils is imported lazily inside upload_and_transcribe() to avoid
# loading torch at module import time. This reduces server startup time.
from server.database.database import (
    check_time_slot_overlap,
    delete_recording,
    get_all_recordings,
    get_db_path,
    get_next_available_start_time,
    get_recording,
    get_recordings_by_date_range,
    get_segments,
    get_time_slot_info,
    get_words,
    save_longform_to_database,
    update_recording_title,
    update_recording_summary,
)
from server.database.backup import DatabaseBackupManager

logger = logging.getLogger(__name__)

router = APIRouter()


class RecordingResponse(BaseModel):
    """Response model for a recording."""

    id: int
    filename: str
    filepath: str
    title: Optional[str] = None
    duration_seconds: float
    recorded_at: str
    imported_at: Optional[str] = None
    word_count: int = 0
    has_diarization: bool = False
    summary: Optional[str] = None
    summary_model: Optional[str] = None


class RecordingDetailResponse(RecordingResponse):
    """Detailed recording response with segments and words."""

    segments: List[Dict[str, Any]] = []
    words: List[Dict[str, Any]] = []


class SummaryUpdate(BaseModel):
    """Request body for updating a recording's summary."""

    summary: Optional[str] = None
    summary_model: Optional[str] = None


class TitleUpdate(BaseModel):
    """Request body for updating a recording's title."""

    title: str


@router.get("/recordings", response_model=List[RecordingResponse])
async def list_recordings(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
) -> List[Dict[str, Any]]:
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
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recordings/{recording_id}", response_model=RecordingDetailResponse)
async def get_recording_detail(recording_id: int) -> Dict[str, Any]:
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
async def remove_recording(recording_id: int) -> Dict[str, str]:
    """
    Delete a recording and all associated data.

    Deletion order is important for data integrity:
    1. Delete from database first (can be rolled back, critical data)
    2. Then delete audio file (orphan file is safer than orphan record)
    """
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    audio_path = Path(recording["filepath"])

    # 1. Delete from database FIRST (critical - can be rolled back)
    if not delete_recording(recording_id):
        raise HTTPException(status_code=500, detail="Failed to delete recording")

    # 2. Delete audio file AFTER database success
    # If this fails, we have an orphan file (harmless) rather than an orphan record
    try:
        if audio_path.exists():
            audio_path.unlink()
    except Exception as e:
        logger.warning(f"Orphan file cleanup needed for {audio_path}: {e}")

    return {"status": "deleted", "id": str(recording_id)}


@router.put("/recordings/{recording_id}/summary")
async def update_summary_put(
    recording_id: int,
    summary: str,
    summary_model: Optional[str] = None,
) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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


@router.get("/recordings/{recording_id}/audio")
async def get_audio_file(
    recording_id: int,
    range: Optional[str] = Header(None, alias="Range"),
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
                    "Content-Disposition": f'inline; filename="{recording["filename"]}"',
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
async def get_transcription(recording_id: int) -> Dict[str, Any]:
    """
    Get the transcription for a recording (segments with words).
    """
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    segments = get_segments(recording_id)
    words = get_words(recording_id)

    # Group words by segment_id
    words_by_segment: Dict[int, List[Dict[str, Any]]] = {}
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


@router.post("/transcribe/upload", response_model=UploadResponse)
async def upload_and_transcribe(
    request: Request,
    file: UploadFile = File(...),
    enable_diarization: bool = Form(False),
    enable_word_timestamps: bool = Form(True),
    file_created_at: Optional[str] = Form(None),
    expected_speakers: Optional[int] = Form(None),
) -> Dict[str, Any]:
    """
    Upload an audio file, transcribe it, and save to the notebook database.

    Returns the recording_id for status tracking.

    Parameters:
    - expected_speakers: Exact number of speakers (2-10). Forces diarization to
      identify exactly this many speakers. Useful for podcasts with known hosts
      where occasional clips should be attributed to the main speakers.

    Returns 409 Conflict if another transcription job is already running.
    """
    # Lazy import to avoid loading torch at module import time
    from server.core.audio_utils import convert_to_mp3, load_audio

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

    # Save uploaded file to temp location
    suffix = Path(file.filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # Get transcription engine
        engine = model_manager.transcription_engine

        # Force word timestamps if diarization is enabled
        # (needed for proper text-to-speaker alignment, even if user doesn't want to save words)
        need_word_timestamps = enable_word_timestamps or enable_diarization

        # Transcribe
        logger.info(f"Transcribing uploaded file for notebook: {file.filename}")
        result = engine.transcribe_file(
            str(tmp_path),
            language=None,
            word_timestamps=need_word_timestamps,
        )

        # Run diarization if enabled
        diarization_segments = None
        if enable_diarization:
            try:
                logger.info(f"Running diarization for: {file.filename}")
                model_manager.load_diarization_model()
                diar_engine = model_manager.diarization_engine

                # Load audio for diarization
                audio_data, sample_rate = load_audio(
                    str(tmp_path), target_sample_rate=16000
                )
                diar_result = diar_engine.diarize_audio(
                    audio_data, sample_rate, num_speakers=expected_speakers
                )

                # Convert to list of dicts for database
                diarization_segments = [seg.to_dict() for seg in diar_result.segments]
                logger.info(
                    f"Diarization complete: {diar_result.num_speakers} speakers found"
                )
            except ValueError as e:
                # HF_TOKEN missing - log helpful message
                logger.error(f"Diarization requires HuggingFace token: {e}")
                logger.error(
                    "Set HUGGINGFACE_TOKEN env var when starting docker compose"
                )
            except Exception as e:
                logger.error(f"Diarization failed (continuing without): {e}")
                # Don't fail the whole upload if diarization fails

        # Determine recorded_at timestamp
        recorded_at = None
        if file_created_at:
            try:
                recorded_at = datetime.fromisoformat(
                    file_created_at.replace("Z", "+00:00")
                )
            except ValueError:
                logger.warning(
                    f"Invalid file_created_at format: {sanitize_for_log(file_created_at)}"
                )

        # Check for time slot overlap before saving
        check_time = recorded_at or datetime.now()
        overlap = check_time_slot_overlap(check_time, result.duration)
        if overlap:
            overlap_title = overlap.get("title") or overlap.get("filename", "Unknown")
            raise HTTPException(
                status_code=409,
                detail=f"Time slot conflict: overlaps with existing recording '{overlap_title}' "
                f"(recorded at {overlap.get('recorded_at', 'unknown time')})",
            )

        # Convert audio to MP3 and save to permanent storage
        config = get_config()
        audio_dir = Path(
            config.get("audio_notebook", "audio_dir", default="/data/audio")
        )
        audio_dir.mkdir(parents=True, exist_ok=True)

        # Keep original filename, convert to .mp3 extension
        # Sanitize filename to prevent path traversal
        raw_stem = Path(file.filename or "audio").stem
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

        # Save to database
        recording_id = save_longform_to_database(
            audio_path=dest_path,
            duration_seconds=result.duration,
            transcription_text=result.text,
            word_timestamps=word_timestamps_list,
            diarization_segments=diarization_segments,
            recorded_at=recorded_at,
        )

        if not recording_id:
            raise HTTPException(
                status_code=500, detail="Failed to save recording to database"
            )

        return {
            "recording_id": recording_id,
            "message": f"Successfully transcribed and saved: {file.filename}",
        }

    except Exception as e:
        logger.error(f"Upload transcription failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Release the job slot
        model_manager.job_tracker.end_job(job_id)

        # Cleanup temp file
        try:
            tmp_path.unlink()
        except Exception as e:
            logger.warning(f"Failed to cleanup temp file {tmp_path}: {e}")


@router.get("/calendar")
async def get_calendar_data(
    year: int = Query(..., description="Year"),
    month: int = Query(..., description="Month (1-12)"),
) -> Dict[str, Any]:
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
        days: Dict[str, List[Dict[str, Any]]] = {}
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
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/timeslot")
async def get_timeslot_info(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    hour: int = Query(..., ge=0, le=23, description="Hour (0-23)"),
) -> Dict[str, Any]:
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
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recordings/{recording_id}/export")
async def export_recording(
    recording_id: int,
    format: str = Query("txt", description="Export format: 'txt', 'srt', or 'ass'"),
) -> Response:
    """
    Export a recording's transcription.

    Includes:
    - Recording metadata (title, date, duration)
    - Full transcription text
    - Subtitle cue rendering from word-level timestamps (if present)
    - Speaker labels (if diarization is present)

    Formats:
    - txt: Human-readable text format for pure transcription notes
    - srt: SubRip subtitle format
    - ass: Advanced SubStation Alpha subtitle format
    """
    requested_format = format.strip().lower()
    if requested_format not in {"txt", "srt", "ass"}:
        raise HTTPException(
            status_code=400,
            detail="Unsupported export format. Supported formats: txt, srt, ass.",
        )

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
        date_str = recorded_at

    # Format duration
    duration = recording.get("duration_seconds", 0)
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
        lines.append(f"Word Count: {recording.get('word_count', 0)}")
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
                start = seg.get("start_time", 0)
                text = seg.get("text", "").strip()

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
                start = seg.get("start_time", 0)
                text = seg.get("text", "").strip()
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
                word = w.get("word", "")
                start = w.get("start_time", 0)
                end = w.get("end_time", 0)
                conf = w.get("confidence")
                conf_str = f" ({conf:.2f})" if conf is not None else ""
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
        cues = build_subtitle_cues(
            segments=segments,
            words=words,
            has_diarization=has_diarization,
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
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
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
async def list_backups() -> Dict[str, Any]:
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
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backup")
async def create_backup() -> Dict[str, Any]:
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
        raise HTTPException(status_code=500, detail=str(e))


class RestoreRequest(BaseModel):
    """Request body for restore operation."""

    filename: str


@router.post("/restore")
async def restore_backup(body: RestoreRequest) -> Dict[str, Any]:
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
            raise HTTPException(
                status_code=404, detail=f"Backup not found: {body.filename}"
            )

        # Verify backup is valid
        if not manager.verify_backup(backup_path):
            raise HTTPException(
                status_code=400, detail="Backup file is invalid or corrupted"
            )

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
        raise HTTPException(status_code=500, detail=str(e))
