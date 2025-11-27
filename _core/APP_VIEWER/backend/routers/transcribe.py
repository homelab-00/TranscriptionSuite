"""
Transcribe API router - handles importing and transcribing audio files.

This module is part of APP_VIEWER/backend, which runs inside the
orchestrator process. The orchestrator exposes a transcription endpoint
that this router calls for actual transcription work.

Start with: python orchestrator.py --audio-notebook
Or via dev.sh (which does the same thing)
"""

import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel

from database import (
    get_recording,
    insert_recording,
    insert_segment,
    insert_words_batch,
    update_recording_word_count,
)

router = APIRouter()

# Directories - inside _core/APP_VIEWER/backend/
STORAGE_DIR = Path(__file__).parent.parent / "data" / "audio"
TEMP_DIR = Path("/tmp/transcription-suite")

# Logging - project root is TranscriptionSuite/
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
LOG_FILE = PROJECT_ROOT / "transcription_suite.log"

logger = logging.getLogger("transcribe_router")
logger.setLevel(logging.DEBUG)
if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    fh.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(fh)

# Orchestrator API - we're running inside the same process, but call via HTTP
# Port can be overridden via environment variable
ORCHESTRATOR_PORT = int(os.environ.get("ORCHESTRATOR_PORT", "8000"))
ORCHESTRATOR_API_URL = f"http://localhost:{ORCHESTRATOR_PORT}/api"

# Audio settings
DEFAULT_AUDIO_BITRATE = 128


# --- Pydantic Models ---


class TranscribeRequest(BaseModel):
    filepath: str
    copy_file: bool = True
    enable_diarization: bool = False
    enable_word_timestamps: bool = True


class TranscribeResponse(BaseModel):
    recording_id: int
    message: str


class ImportStatus(BaseModel):
    recording_id: int
    status: str
    progress: Optional[float] = None
    message: Optional[str] = None


# In-memory status tracking
import_status: dict[int, ImportStatus] = {}


# --- Helper Functions ---


def get_audio_duration(filepath: Path) -> float:
    """Get audio duration using ffprobe."""
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
    """Get file creation/modification time."""
    stat = filepath.stat()
    timestamp = getattr(stat, "st_birthtime", None) or stat.st_mtime
    return datetime.fromtimestamp(timestamp)


def convert_to_mp3(source: Path, dest: Path, bitrate: int = 128) -> bool:
    """Convert audio to MP3 for storage."""
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                str(source),
                "-vn",
                "-acodec",
                "libmp3lame",
                "-ab",
                f"{bitrate}k",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-y",
                str(dest),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"MP3 conversion failed: {e.stderr}")
        return False


def convert_to_wav(source: Path, dest: Path) -> bool:
    """Convert audio to 16kHz mono WAV for Whisper."""
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                str(source),
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-y",
                str(dest),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"WAV conversion failed: {e.stderr}")
        return False


def save_transcription_result(recording_id: int, result: dict):
    """Save transcription result to database."""
    segments = result.get("segments", [])
    words_batch = []
    word_index = 0

    for seg_idx, segment in enumerate(segments):
        segment_id = insert_segment(
            recording_id=recording_id,
            segment_index=seg_idx,
            text=segment.get("text", ""),
            start_time=segment.get("start", 0.0),
            end_time=segment.get("end", 0.0),
            speaker=segment.get("speaker"),
        )

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

    if words_batch:
        insert_words_batch(words_batch)
    update_recording_word_count(recording_id)


# --- Transcription Logic ---


def run_transcription(
    recording_id: int,
    audio_path: Path,
    wav_path: Path,
    enable_diarization: bool,
    enable_word_timestamps: bool,
):
    """Run transcription via orchestrator API."""
    logger.info(f"Starting transcription for recording {recording_id}")
    logger.info(f"  WAV: {wav_path}, Diarization: {enable_diarization}")

    import_status[recording_id] = ImportStatus(
        recording_id=recording_id,
        status="transcribing",
        progress=0.0,
        message="Starting transcription...",
    )

    try:
        # Check orchestrator health
        try:
            with httpx.Client(timeout=2.0) as client:
                health = client.get(f"{ORCHESTRATOR_API_URL}/health").json()
                if not health.get("models_loaded"):
                    raise RuntimeError("Orchestrator models not loaded yet")
        except httpx.ConnectError:
            raise RuntimeError(
                "Orchestrator API not running. Start with: python orchestrator.py --mode audio-notebook"
            )

        import_status[recording_id].message = "Transcribing..."
        import_status[recording_id].progress = 0.3

        # Call orchestrator API
        with httpx.Client(timeout=600.0) as client:
            response = client.post(
                f"{ORCHESTRATOR_API_URL}/orchestrator/transcribe",
                json={
                    "wav_path": str(wav_path),
                    "enable_diarization": enable_diarization,
                    "enable_word_timestamps": enable_word_timestamps,
                },
            )
            if response.status_code != 200:
                raise RuntimeError(f"Orchestrator error: {response.text}")
            transcription_data = response.json()

        import_status[recording_id].message = "Saving to database..."
        import_status[recording_id].progress = 0.8

        save_transcription_result(recording_id, transcription_data)

        import_status[recording_id] = ImportStatus(
            recording_id=recording_id,
            status="completed",
            progress=1.0,
            message="Transcription complete",
        )
        logger.info(f"Transcription completed for recording {recording_id}")

    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        import_status[recording_id] = ImportStatus(
            recording_id=recording_id,
            status="failed",
            progress=0.0,
            message=f"Failed: {str(e)}",
        )
    finally:
        # Cleanup temp WAV
        try:
            if wav_path.exists():
                wav_path.unlink()
        except Exception:
            pass


# --- API Endpoints ---


@router.post("/file", response_model=TranscribeResponse)
async def transcribe_file(
    background_tasks: BackgroundTasks,
    request: TranscribeRequest,
):
    """Import and transcribe a local audio file."""
    source_path = Path(request.filepath)
    if not source_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {request.filepath}")

    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # Generate unique MP3 path
    mp3_path = STORAGE_DIR / f"{source_path.stem}.mp3"
    counter = 1
    while mp3_path.exists():
        mp3_path = STORAGE_DIR / f"{source_path.stem}_{counter}.mp3"
        counter += 1

    wav_path = (
        TEMP_DIR / f"{source_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
    )

    if not convert_to_mp3(source_path, mp3_path, DEFAULT_AUDIO_BITRATE):
        raise HTTPException(status_code=500, detail="Failed to convert to MP3")

    if not convert_to_wav(source_path, wav_path):
        mp3_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Failed to convert to WAV")

    duration = get_audio_duration(mp3_path)
    recorded_at = get_file_creation_time(source_path)

    recording_id = insert_recording(
        filename=mp3_path.name,
        filepath=str(mp3_path),
        duration_seconds=duration,
        recorded_at=recorded_at.isoformat(),
        has_diarization=request.enable_diarization,
    )

    background_tasks.add_task(
        run_transcription,
        recording_id,
        mp3_path,
        wav_path,
        request.enable_diarization,
        request.enable_word_timestamps,
    )

    return TranscribeResponse(recording_id=recording_id, message="Transcription started")


@router.post("/upload", response_model=TranscribeResponse)
async def transcribe_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    enable_diarization: bool = False,
    enable_word_timestamps: bool = True,
):
    """Upload and transcribe an audio file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename required")

    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    original_stem = Path(file.filename).stem
    original_suffix = Path(file.filename).suffix
    temp_upload = (
        TEMP_DIR / f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}{original_suffix}"
    )

    with open(temp_upload, "wb") as f:
        f.write(await file.read())

    try:
        mp3_path = STORAGE_DIR / f"{original_stem}.mp3"
        counter = 1
        while mp3_path.exists():
            mp3_path = STORAGE_DIR / f"{original_stem}_{counter}.mp3"
            counter += 1

        wav_path = (
            TEMP_DIR / f"{original_stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        )

        if not convert_to_mp3(temp_upload, mp3_path, DEFAULT_AUDIO_BITRATE):
            raise HTTPException(status_code=500, detail="Failed to convert to MP3")

        if not convert_to_wav(temp_upload, wav_path):
            mp3_path.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail="Failed to convert to WAV")

        duration = get_audio_duration(mp3_path)

        recording_id = insert_recording(
            filename=mp3_path.name,
            filepath=str(mp3_path),
            duration_seconds=duration,
            recorded_at=datetime.now().isoformat(),
            has_diarization=enable_diarization,
        )

        background_tasks.add_task(
            run_transcription,
            recording_id,
            mp3_path,
            wav_path,
            enable_diarization,
            enable_word_timestamps,
        )

        return TranscribeResponse(
            recording_id=recording_id, message="Transcription started"
        )

    finally:
        temp_upload.unlink(missing_ok=True)


@router.get("/status/{recording_id}", response_model=ImportStatus)
async def get_transcription_status(recording_id: int):
    """Get transcription job status."""
    if recording_id in import_status:
        return import_status[recording_id]

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
