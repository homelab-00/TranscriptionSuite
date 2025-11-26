"""
Transcribe API router - handles importing and transcribing audio files
"""

import subprocess
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

# Storage directory for audio files (relative to backend/)
STORAGE_DIR = Path(__file__).parent.parent / "data" / "audio"
TEMP_DIR = Path("/tmp/transcription-suite")

# Default audio settings
DEFAULT_AUDIO_BITRATE = 128  # kbps for MP3


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


def convert_to_mp3(source_path: Path, dest_path: Path, bitrate: int = 128) -> bool:
    """
    Convert any audio/video file to MP3 for storage.

    Args:
        source_path: Path to source file
        dest_path: Path for output MP3 file
        bitrate: Audio bitrate in kbps (default 128)

    Returns:
        True if conversion successful, False otherwise
    """
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                str(source_path),
                "-vn",  # No video
                "-acodec",
                "libmp3lame",
                "-ab",
                f"{bitrate}k",
                "-ar",
                "44100",  # Standard sample rate for playback
                "-ac",
                "2",  # Stereo for playback quality
                "-y",  # Overwrite output
                str(dest_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg conversion error: {e.stderr}")
        return False


def convert_to_wav_for_whisper(source_path: Path, dest_path: Path) -> bool:
    """
    Convert any audio/video file to WAV format suitable for Whisper.

    Whisper requires: 16kHz, mono, 16-bit PCM WAV

    Args:
        source_path: Path to source file
        dest_path: Path for output WAV file

    Returns:
        True if conversion successful, False otherwise
    """
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                str(source_path),
                "-vn",  # No video
                "-acodec",
                "pcm_s16le",  # 16-bit PCM
                "-ar",
                "16000",  # 16kHz sample rate
                "-ac",
                "1",  # Mono
                "-y",  # Overwrite output
                str(dest_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg conversion error: {e.stderr}")
        return False


def run_transcription(
    recording_id: int, audio_path: Path, wav_path: Path, enable_diarization: bool
):
    """
    Run transcription in background using the core transcription module.

    Args:
        recording_id: Database ID of the recording
        audio_path: Path to the stored MP3 file (for playback)
        wav_path: Path to the WAV file for transcription (will be deleted after)
        enable_diarization: Whether to run speaker diarization
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
            from static_transcriber import StaticFileTranscriber

            transcriber = StaticFileTranscriber(None, None)

            import_status[recording_id].message = "Running transcription..."
            import_status[recording_id].progress = 0.2

            # Use the WAV file for transcription
            if enable_diarization and transcriber.is_diarization_available():
                result = transcriber.transcribe_file_with_diarization(str(wav_path))
            else:
                result = transcriber.transcribe_file_with_word_timestamps(str(wav_path))

            import_status[recording_id].progress = 0.8
            import_status[recording_id].message = "Saving to database..."

            # Convert TranscriptSegment objects to dict format
            if result:
                result_dict = {"segments": [seg.to_dict() for seg in result]}
            else:
                result_dict = {"segments": []}

            # Parse and save results
            save_transcription_result(recording_id, result_dict)

            import_status[recording_id] = ImportStatus(
                recording_id=recording_id,
                status="completed",
                progress=1.0,
                message="Transcription complete",
            )

        except ImportError:
            # Fallback: run as subprocess
            import_status[recording_id].message = "Running transcription subprocess..."
            run_transcription_subprocess(recording_id, wav_path, enable_diarization)

    except Exception as e:
        import_status[recording_id] = ImportStatus(
            recording_id=recording_id,
            status="failed",
            progress=0.0,
            message=f"Transcription failed: {str(e)}",
        )
    finally:
        # Clean up the temporary WAV file
        try:
            if wav_path.exists():
                wav_path.unlink()
        except Exception:
            pass


def run_transcription_subprocess(
    recording_id: int, wav_path: Path, enable_diarization: bool
):
    """Run transcription as subprocess when direct import is not available"""
    import json

    # Path to the core SCRIPT directory
    script_dir = Path(__file__).parent.parent.parent.parent / "_core" / "SCRIPT"

    if not script_dir.exists():
        raise RuntimeError(f"Transcription script directory not found: {script_dir}")

    # Create a simple runner script
    runner_code = f'''
import sys
import json
sys.path.insert(0, "{script_dir}")
from static_transcriber import StaticFileTranscriber

transcriber = StaticFileTranscriber(None, None)
result = transcriber.transcribe_file_with_word_timestamps("{wav_path}")
# Convert result to JSON-serializable format
if result:
    output = {{
        "segments": [seg.to_dict() for seg in result]
    }}
    print(json.dumps(output))
else:
    print("{{}}")
'''

    # Find the Python executable in the core venv
    venv_python = (
        Path(__file__).parent.parent.parent.parent
        / "_core"
        / ".venv"
        / "bin"
        / "python"
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
    Import and transcribe an audio/video file from the local filesystem.

    The source file is converted to:
    - MP3 (128kbps) for storage and playback
    - WAV (16kHz mono) for transcription (temporary, deleted after)
    """
    source_path = Path(request.filepath)

    if not source_path.exists():
        raise HTTPException(
            status_code=404, detail=f"File not found: {request.filepath}"
        )

    # Create directories
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # Determine MP3 destination path
    mp3_filename = source_path.stem + ".mp3"
    mp3_path = STORAGE_DIR / mp3_filename

    # Handle duplicate filenames
    if mp3_path.exists():
        counter = 1
        while mp3_path.exists():
            mp3_path = STORAGE_DIR / f"{source_path.stem}_{counter}.mp3"
            counter += 1

    # Create temporary WAV file for transcription
    wav_path = (
        TEMP_DIR / f"{source_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
    )

    # Convert source to MP3 for storage
    if not convert_to_mp3(source_path, mp3_path, DEFAULT_AUDIO_BITRATE):
        raise HTTPException(status_code=500, detail="Failed to convert audio to MP3")

    # Convert source to WAV for transcription
    if not convert_to_wav_for_whisper(source_path, wav_path):
        # Clean up MP3 if WAV conversion fails
        mp3_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500, detail="Failed to convert audio to WAV for transcription"
        )

    # Get audio metadata from the MP3
    duration = get_audio_duration(mp3_path)
    recorded_at = get_file_creation_time(source_path)

    # Insert recording into database (pointing to MP3)
    recording_id = insert_recording(
        filename=mp3_path.name,
        filepath=str(mp3_path),
        duration_seconds=duration,
        recorded_at=recorded_at.isoformat(),
        has_diarization=request.enable_diarization,
    )

    # Start background transcription (using WAV)
    background_tasks.add_task(
        run_transcription,
        recording_id,
        mp3_path,
        wav_path,
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
    Upload and transcribe an audio/video file.

    The uploaded file is converted to:
    - MP3 (128kbps) for storage and playback
    - WAV (16kHz mono) for transcription (temporary, deleted after)
    """
    # Create directories
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # Save uploaded file to temp location first
    original_stem = Path(file.filename).stem
    original_suffix = Path(file.filename).suffix
    temp_upload = (
        TEMP_DIR / f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}{original_suffix}"
    )

    with open(temp_upload, "wb") as f:
        content = await file.read()
        f.write(content)

    try:
        # Determine MP3 destination path
        mp3_filename = original_stem + ".mp3"
        mp3_path = STORAGE_DIR / mp3_filename

        # Handle duplicate filenames
        if mp3_path.exists():
            counter = 1
            while mp3_path.exists():
                mp3_path = STORAGE_DIR / f"{original_stem}_{counter}.mp3"
                counter += 1

        # Create WAV path for transcription
        wav_path = (
            TEMP_DIR / f"{original_stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        )

        # Convert to MP3 for storage
        if not convert_to_mp3(temp_upload, mp3_path, DEFAULT_AUDIO_BITRATE):
            raise HTTPException(
                status_code=500, detail="Failed to convert audio to MP3"
            )

        # Convert to WAV for transcription
        if not convert_to_wav_for_whisper(temp_upload, wav_path):
            mp3_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=500,
                detail="Failed to convert audio to WAV for transcription",
            )

        # Get audio metadata
        duration = get_audio_duration(mp3_path)

        # Insert recording into database
        recording_id = insert_recording(
            filename=mp3_path.name,
            filepath=str(mp3_path),
            duration_seconds=duration,
            recorded_at=datetime.now().isoformat(),
            has_diarization=enable_diarization,
        )

        # Start background transcription
        background_tasks.add_task(
            run_transcription,
            recording_id,
            mp3_path,
            wav_path,
            enable_diarization,
        )

        return TranscribeResponse(
            recording_id=recording_id, message="Transcription started"
        )

    finally:
        # Clean up the temporary upload file
        temp_upload.unlink(missing_ok=True)


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
