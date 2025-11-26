"""
Transcribe API router - handles importing and transcribing audio files
"""

import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel

from database import (
    insert_recording,
    insert_segment,
    insert_words_batch,
    update_recording_word_count,
)

router = APIRouter()

# Storage directory for audio files
STORAGE_DIR = Path(__file__).parent.parent / "backend" / "data" / "audio"


class TranscribeRequest(BaseModel):
    filepath: str
    copy_file: bool = True
    enable_diarization: bool = False


class TranscribeResponse(BaseModel):
    recording_id: int
    message: str


class ImportStatus(BaseModel):
    recording_id: int
    status: str
    progress: Optional[float] = None
    message: Optional[str] = None


# In-memory status tracking (in production, use Redis or similar)
import_status: dict[int, ImportStatus] = {}


def get_audio_duration(filepath: Path) -> float:
    """Get audio duration using ffprobe"""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(filepath),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def get_file_creation_time(filepath: Path) -> datetime:
    """Get file creation/modification time as recorded_at timestamp"""
    stat = filepath.stat()
    # Use birth time if available (Linux with certain filesystems), otherwise mtime
    timestamp = getattr(stat, "st_birthtime", None) or stat.st_mtime
    return datetime.fromtimestamp(timestamp)


def run_transcription(recording_id: int, filepath: Path, enable_diarization: bool):
    """
    Run transcription in background using the core transcription module
    """
    import_status[recording_id] = ImportStatus(
        recording_id=recording_id,
        status="transcribing",
        progress=0.0,
        message="Starting transcription...",
    )

    try:
        # Try to import the transcription module
        try:
            from static_transcriber import StaticTranscriber

            transcriber = StaticTranscriber()

            import_status[recording_id].message = "Running transcription..."
            import_status[recording_id].progress = 0.2

            if enable_diarization and transcriber.is_diarization_available():
                result = transcriber.transcribe_file_with_diarization(str(filepath))
            else:
                result = transcriber.transcribe_file_with_word_timestamps(str(filepath))

            import_status[recording_id].progress = 0.8
            import_status[recording_id].message = "Saving to database..."

            # Parse and save results
            save_transcription_result(recording_id, result)

            import_status[recording_id] = ImportStatus(
                recording_id=recording_id,
                status="completed",
                progress=1.0,
                message="Transcription complete",
            )

        except ImportError as e:
            # Fallback: run as subprocess
            import_status[recording_id].message = f"Running transcription subprocess..."
            run_transcription_subprocess(recording_id, filepath, enable_diarization)

    except Exception as e:
        import_status[recording_id] = ImportStatus(
            recording_id=recording_id,
            status="failed",
            progress=0.0,
            message=f"Transcription failed: {str(e)}",
        )


def run_transcription_subprocess(
    recording_id: int, filepath: Path, enable_diarization: bool
):
    """Run transcription as subprocess when direct import is not available"""
    import json

    # Path to the core SCRIPT directory
    script_dir = Path(__file__).parent.parent.parent / "_core" / "SCRIPT"

    if not script_dir.exists():
        raise RuntimeError(f"Transcription script directory not found: {script_dir}")

    # Create a simple runner script
    runner_code = f'''
import sys
sys.path.insert(0, "{script_dir}")
from static_transcriber import StaticTranscriber

transcriber = StaticTranscriber()
result = transcriber.transcribe_file_with_word_timestamps("{filepath}")
print(result)
'''

    # Find the Python executable in the core venv
    venv_python = (
        Path(__file__).parent.parent.parent / "_core" / ".venv" / "bin" / "python"
    )
    if not venv_python.exists():
        venv_python = "python"  # Fallback

    result = subprocess.run(
        [str(venv_python), "-c", runner_code],
        capture_output=True,
        text=True,
        cwd=str(script_dir),
    )

    if result.returncode != 0:
        raise RuntimeError(f"Transcription failed: {result.stderr}")

    # Parse output
    output = result.stdout.strip()
    transcription_data = json.loads(output)

    save_transcription_result(recording_id, transcription_data)


def save_transcription_result(recording_id: int, result: dict):
    """Save transcription result to database"""
    segments = result.get("segments", [])

    words_batch = []
    word_index = 0

    for seg_idx, segment in enumerate(segments):
        # Insert segment
        segment_id = insert_segment(
            recording_id=recording_id,
            segment_index=seg_idx,
            text=segment.get("text", ""),
            start_time=segment.get("start", 0.0),
            end_time=segment.get("end", 0.0),
            speaker=segment.get("speaker"),
        )

        # Collect words for batch insert
        for word_data in segment.get("words", []):
            words_batch.append(
                {
                    "recording_id": recording_id,
                    "segment_id": segment_id,
                    "word_index": word_index,
                    "word": word_data.get("word", "").strip(),
                    "start_time": word_data.get("start", 0.0),
                    "end_time": word_data.get("end", 0.0),
                    "confidence": word_data.get("probability"),
                }
            )
            word_index += 1

    # Batch insert words
    if words_batch:
        insert_words_batch(words_batch)

    # Update word count
    update_recording_word_count(recording_id)


@router.post("/file", response_model=TranscribeResponse)
async def transcribe_file(
    background_tasks: BackgroundTasks,
    request: TranscribeRequest,
):
    """
    Import and transcribe an audio file from the local filesystem
    """
    source_path = Path(request.filepath)

    if not source_path.exists():
        raise HTTPException(
            status_code=404, detail=f"File not found: {request.filepath}"
        )

    # Determine storage path
    if request.copy_file:
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        dest_path = STORAGE_DIR / source_path.name

        # Handle duplicate filenames
        if dest_path.exists():
            stem = source_path.stem
            suffix = source_path.suffix
            counter = 1
            while dest_path.exists():
                dest_path = STORAGE_DIR / f"{stem}_{counter}{suffix}"
                counter += 1

        shutil.copy2(source_path, dest_path)
        audio_path = dest_path
    else:
        audio_path = source_path

    # Get audio metadata
    duration = get_audio_duration(audio_path)
    recorded_at = get_file_creation_time(source_path)

    # Insert recording into database
    recording_id = insert_recording(
        filename=audio_path.name,
        filepath=str(audio_path),
        duration_seconds=duration,
        recorded_at=recorded_at.isoformat(),
        has_diarization=request.enable_diarization,
    )

    # Start background transcription
    background_tasks.add_task(
        run_transcription,
        recording_id,
        audio_path,
        request.enable_diarization,
    )

    return TranscribeResponse(
        recording_id=recording_id, message="Transcription started"
    )


@router.post("/upload", response_model=TranscribeResponse)
async def transcribe_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    enable_diarization: bool = False,
):
    """
    Upload and transcribe an audio file
    """
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    # Save uploaded file
    dest_path = STORAGE_DIR / file.filename

    # Handle duplicate filenames
    if dest_path.exists():
        stem = Path(file.filename).stem
        suffix = Path(file.filename).suffix
        counter = 1
        while dest_path.exists():
            dest_path = STORAGE_DIR / f"{stem}_{counter}{suffix}"
            counter += 1

    with open(dest_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Get audio metadata
    duration = get_audio_duration(dest_path)

    # Insert recording into database
    recording_id = insert_recording(
        filename=dest_path.name,
        filepath=str(dest_path),
        duration_seconds=duration,
        recorded_at=datetime.now().isoformat(),
        has_diarization=enable_diarization,
    )

    # Start background transcription
    background_tasks.add_task(
        run_transcription,
        recording_id,
        dest_path,
        enable_diarization,
    )

    return TranscribeResponse(
        recording_id=recording_id, message="Transcription started"
    )


@router.get("/status/{recording_id}", response_model=ImportStatus)
async def get_transcription_status(recording_id: int):
    """Get the status of a transcription job"""
    if recording_id in import_status:
        return import_status[recording_id]

    # Check if recording exists and has words
    from database import get_recording

    recording = get_recording(recording_id)

    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    if recording["word_count"] > 0:
        return ImportStatus(
            recording_id=recording_id,
            status="completed",
            progress=1.0,
            message="Transcription complete",
        )

    return ImportStatus(
        recording_id=recording_id,
        status="pending",
        progress=0.0,
        message="Transcription pending",
    )
