"""
Audio Notebook API endpoints for TranscriptionSuite server.

Handles:
- Recording CRUD operations
- Audio file management
- Transcription import and export
"""

import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from server.config import get_config
from server.core.audio_utils import convert_to_mp3, load_audio
from server.database.database import (
    delete_recording,
    get_all_recordings,
    get_recording,
    get_recordings_by_date_range,
    get_segments,
    get_words,
    save_longform_to_database,
    update_recording_title,
    update_recording_summary,
)

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


class RecordingDetailResponse(RecordingResponse):
    """Detailed recording response with segments and words."""

    segments: List[Dict[str, Any]] = []
    words: List[Dict[str, Any]] = []


class SummaryUpdate(BaseModel):
    """Request body for updating a recording's summary."""

    summary: str


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
    """
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    # Delete audio file if it exists
    try:
        audio_path = Path(recording["filepath"])
        if audio_path.exists():
            audio_path.unlink()
    except Exception as e:
        logger.warning(f"Could not delete audio file: {e}")

    # Delete from database
    if delete_recording(recording_id):
        return {"status": "deleted", "id": str(recording_id)}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete recording")


@router.put("/recordings/{recording_id}/summary")
async def update_summary_put(
    recording_id: int,
    summary: str,
) -> Dict[str, Any]:
    """
    Update the summary for a recording (PUT with query param).
    """
    if not get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")

    if update_recording_summary(recording_id, summary):
        return {"status": "updated", "id": recording_id, "summary": summary}
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

    if update_recording_summary(recording_id, body.summary):
        return {"status": "updated", "id": recording_id, "summary": body.summary}
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
async def get_audio_file(recording_id: int) -> FileResponse:
    """
    Stream the audio file for a recording.
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

    return FileResponse(
        path=audio_path,
        media_type=media_type,
        filename=recording["filename"],
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
        words_by_segment[seg_id].append({
            "word": word.get("word", ""),
            "start": word.get("start_time", 0),
            "end": word.get("end_time", 0),
            "confidence": word.get("confidence"),
        })

    # Build segments with embedded words
    result_segments = []
    for seg in segments:
        seg_id = seg.get("id")
        result_segments.append({
            "text": seg.get("text", ""),
            "start": seg.get("start_time", 0),
            "end": seg.get("end_time", 0),
            "speaker": seg.get("speaker"),
            "words": words_by_segment.get(seg_id, []),
        })

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
) -> Dict[str, Any]:
    """
    Upload an audio file, transcribe it, and save to the notebook database.
    
    Returns the recording_id for status tracking.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Save uploaded file to temp location
    suffix = Path(file.filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # Get transcription engine
        model_manager = request.app.state.model_manager
        engine = model_manager.transcription_engine

        # Transcribe
        logger.info(f"Transcribing uploaded file for notebook: {file.filename}")
        result = engine.transcribe_file(
            str(tmp_path),
            language=None,
            word_timestamps=enable_word_timestamps,
        )

        # Run diarization if enabled
        diarization_segments = None
        if enable_diarization:
            try:
                logger.info(f"Running diarization for: {file.filename}")
                model_manager.load_diarization_model()
                diar_engine = model_manager.diarization_engine
                
                # Load audio for diarization
                audio_data, sample_rate = load_audio(str(tmp_path), target_sample_rate=16000)
                diar_result = diar_engine.diarize_audio(audio_data, sample_rate)
                
                # Convert to list of dicts for database
                diarization_segments = [seg.to_dict() for seg in diar_result.segments]
                logger.info(f"Diarization complete: {diar_result.num_speakers} speakers found")
            except ValueError as e:
                # HF_TOKEN missing - log helpful message
                logger.error(f"Diarization requires HuggingFace token: {e}")
                logger.error("Set HUGGINGFACE_TOKEN env var when starting docker compose")
            except Exception as e:
                logger.error(f"Diarization failed (continuing without): {e}")
                # Don't fail the whole upload if diarization fails

        # Determine recorded_at timestamp
        recorded_at = None
        if file_created_at:
            try:
                recorded_at = datetime.fromisoformat(file_created_at.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"Invalid file_created_at format: {file_created_at}")

        # Convert audio to MP3 and save to permanent storage
        config = get_config()
        audio_dir = Path(config.get("audio_notebook", "audio_dir", default="/data/audio"))
        audio_dir.mkdir(parents=True, exist_ok=True)
        
        # Keep original filename, convert to .mp3 extension
        original_stem = Path(file.filename or "audio").stem
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
        word_timestamps_list = None
        if enable_word_timestamps:
            word_timestamps_list = []
            for seg in result.segments:
                word_timestamps_list.extend([w.to_dict() for w in seg.words])

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
            raise HTTPException(status_code=500, detail="Failed to save recording to database")

        return {
            "recording_id": recording_id,
            "message": f"Successfully transcribed and saved: {file.filename}",
        }

    except Exception as e:
        logger.error(f"Upload transcription failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Cleanup temp file
        try:
            tmp_path.unlink()
        except Exception:
            pass


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
