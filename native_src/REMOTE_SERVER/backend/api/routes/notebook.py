"""
Audio Notebook API endpoints for TranscriptionSuite server.

Handles:
- Recording CRUD operations
- Audio file management
- Transcription import and export
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from server.database.database import (
    delete_recording,
    get_all_recordings,
    get_recording,
    get_recordings_by_date_range,
    get_segments,
    get_words,
    update_recording_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class RecordingResponse(BaseModel):
    """Response model for a recording."""

    id: int
    filename: str
    filepath: str
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
async def update_summary(
    recording_id: int,
    summary: str,
) -> Dict[str, Any]:
    """
    Update the summary for a recording.
    """
    if not get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")

    if update_recording_summary(recording_id, summary):
        return {"status": "updated", "id": recording_id, "summary": summary}
    else:
        raise HTTPException(status_code=500, detail="Failed to update summary")


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
