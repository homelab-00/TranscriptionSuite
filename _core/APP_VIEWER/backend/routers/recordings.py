"""
Recordings API router
"""

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database import (
    get_recording,
    get_all_recordings,
    get_recordings_by_date_range,
    get_recordings_for_month,
    get_recordings_for_hour,
    get_transcription,
    delete_recording,
    update_recording_date,
    update_recording_summary,
    get_recording_summary,
)
from webapp_logging import get_api_logger

router = APIRouter()
logger = get_api_logger()


class RecordingResponse(BaseModel):
    id: int
    filename: str
    filepath: str
    duration_seconds: float
    recorded_at: str
    imported_at: str
    word_count: int
    has_diarization: bool
    summary: Optional[str] = None


class TranscriptWordResponse(BaseModel):
    word: str
    start: float
    end: float
    confidence: Optional[float] = None


class TranscriptSegmentResponse(BaseModel):
    speaker: Optional[str]
    text: str
    start: float
    end: float
    words: list[TranscriptWordResponse]


class TranscriptionResponse(BaseModel):
    recording_id: int
    segments: list[TranscriptSegmentResponse]


@router.get("")
async def list_recordings(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    year: Optional[int] = Query(None, description="Year for month view"),
    month: Optional[int] = Query(None, description="Month for month view (1-12)"),
    group_by_date: bool = Query(True, description="Group recordings by date"),
) -> Union[dict[str, list[RecordingResponse]], list[RecordingResponse]]:
    """List all recordings, optionally filtered by date range or month.

    When start_date and end_date are provided, returns recordings grouped by date.
    Otherwise returns a flat list.
    """
    if year is not None and month is not None:
        recordings = get_recordings_for_month(year, month)
    elif start_date and end_date:
        recordings = get_recordings_by_date_range(start_date, end_date)
    else:
        recordings = get_all_recordings()

    recording_responses = [
        RecordingResponse(
            id=r["id"],
            filename=r["filename"],
            filepath=r["filepath"],
            duration_seconds=r["duration_seconds"],
            recorded_at=r["recorded_at"],
            imported_at=r["imported_at"],
            word_count=r["word_count"],
            has_diarization=bool(r["has_diarization"]),
            summary=r.get("summary"),
        )
        for r in recordings
    ]

    # Group by date when filtering by date range
    if (start_date and end_date) or group_by_date:
        grouped: dict[str, list[RecordingResponse]] = defaultdict(list)
        for rec in recording_responses:
            # Parse the recorded_at timestamp and extract the date
            try:
                dt = datetime.fromisoformat(rec.recorded_at.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
            except (ValueError, AttributeError, TypeError):
                date_str = rec.recorded_at[:10]  # Fallback: take first 10 chars
            grouped[date_str].append(rec)
        return dict(grouped)

    return recording_responses


@router.get("/{recording_id}", response_model=RecordingResponse)
async def get_recording_by_id(recording_id: int):
    """Get a specific recording by ID"""
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    return RecordingResponse(
        id=recording["id"],
        filename=recording["filename"],
        filepath=recording["filepath"],
        duration_seconds=recording["duration_seconds"],
        recorded_at=recording["recorded_at"],
        imported_at=recording["imported_at"],
        word_count=recording["word_count"],
        has_diarization=bool(recording["has_diarization"]),
        summary=recording.get("summary"),
    )


@router.get("/{recording_id}/transcription", response_model=TranscriptionResponse)
async def get_recording_transcription(recording_id: int):
    """Get the full transcription for a recording"""
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    transcription = get_transcription(recording_id)
    return TranscriptionResponse(**transcription)


@router.get("/{recording_id}/audio")
async def get_recording_audio(recording_id: int):
    """Stream the audio file for a recording"""
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    filepath = Path(recording["filepath"])
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    # Determine media type from extension
    media_types = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".opus": "audio/opus",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
    }
    media_type = media_types.get(filepath.suffix.lower(), "audio/mpeg")

    return FileResponse(filepath, media_type=media_type)


@router.delete("/{recording_id}")
async def delete_recording_by_id(recording_id: int):
    """Delete a recording and its transcription"""
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    # Delete the audio file from storage
    filepath = Path(recording["filepath"])
    if filepath.exists():
        try:
            filepath.unlink()
        except Exception:
            pass  # Continue even if file deletion fails

    if not delete_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")

    return {"message": "Recording deleted"}


class UpdateRecordingDateRequest(BaseModel):
    recorded_at: str


@router.patch("/{recording_id}/date")
async def update_recording_date_endpoint(
    recording_id: int, request: UpdateRecordingDateRequest
):
    """Update the recorded_at timestamp for a recording"""
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    # Validate the datetime format
    try:
        datetime.fromisoformat(request.recorded_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid datetime format. Use ISO format."
        )

    if not update_recording_date(recording_id, request.recorded_at):
        raise HTTPException(status_code=500, detail="Failed to update recording date")

    return {"message": "Recording date updated"}


class UpdateSummaryRequest(BaseModel):
    summary: Optional[str] = None


@router.patch("/{recording_id}/summary")
async def update_recording_summary_endpoint(
    recording_id: int, request: UpdateSummaryRequest
):
    """Update the AI summary for a recording"""
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    if not update_recording_summary(recording_id, request.summary):
        raise HTTPException(status_code=500, detail="Failed to update summary")

    return {"message": "Summary updated", "summary": request.summary}


@router.get("/{recording_id}/summary")
async def get_recording_summary_endpoint(recording_id: int):
    """Get the AI summary for a recording"""
    recording = get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    summary = get_recording_summary(recording_id)
    return {"summary": summary}


@router.get("/next-minute/{date}/{hour}")
async def get_next_available_minute(date: str, hour: int):
    """Get the next available timestamp for a manual entry in a specific hour.

    Returns the minute and second that should be used for a new entry,
    calculated as 1 minute after the latest recording's end time.
    """
    # Validate inputs
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD."
        )

    if hour < 0 or hour > 23:
        raise HTTPException(status_code=400, detail="Hour must be between 0 and 23.")

    recordings = get_recordings_for_hour(date, hour)

    if not recordings:
        # No recordings in this hour block - start at minute 1
        return {"next_minute": 1, "next_second": 0}

    # Find the recording with the latest end time
    latest_end_seconds = 0  # seconds from start of the hour

    for rec in recordings:
        try:
            rec_dt = datetime.fromisoformat(rec["recorded_at"].replace("Z", "+00:00"))
            if rec_dt.tzinfo is not None:
                rec_dt = rec_dt.replace(tzinfo=None)

            # Calculate seconds from start of the hour
            start_offset = rec_dt.minute * 60 + rec_dt.second
            end_offset = start_offset + rec["duration_seconds"]

            if end_offset > latest_end_seconds:
                latest_end_seconds = end_offset
        except (ValueError, KeyError, TypeError):
            continue

    # Add 1 minute (60 seconds) to the latest end time
    new_offset = latest_end_seconds + 60

    new_minute = int(new_offset // 60)
    new_second = int(new_offset % 60)

    # Check if we've exceeded the hour block
    if new_minute >= 60:
        raise HTTPException(
            status_code=400,
            detail="Hour block is full. Cannot add more recordings to this hour.",
        )

    return {"next_minute": new_minute, "next_second": new_second}
