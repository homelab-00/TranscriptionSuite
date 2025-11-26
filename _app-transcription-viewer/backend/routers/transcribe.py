"""
Transcribe API router - handles importing and transcribing audio files

This module uses the core TranscriptionSuite module (_core) for all transcription
work via subprocess, ensuring consistent settings and behavior with the standalone
orchestrator.
"""

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional
import json

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

# Paths to core module
CORE_DIR = Path(__file__).parent.parent.parent.parent / "_core"
SCRIPT_DIR = CORE_DIR / "SCRIPT"
VENV_PYTHON = CORE_DIR / ".venv" / "bin" / "python"

# Default audio settings
DEFAULT_AUDIO_BITRATE = 128  # kbps for MP3


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
    recording_id: int,
    audio_path: Path,
    wav_path: Path,
    enable_diarization: bool,
    enable_word_timestamps: bool,
):
    """
    Run transcription in background using the core transcription module.

    Args:
        recording_id: Database ID of the recording
        audio_path: Path to the stored MP3 file (for playback)
        wav_path: Path to the WAV file for transcription (will be deleted after)
        enable_diarization: Whether to run speaker diarization
        enable_word_timestamps: Whether to include word-level timestamps
    """
    import_status[recording_id] = ImportStatus(
        recording_id=recording_id,
        status="transcribing",
        progress=0.0,
        message="Starting transcription...",
    )

    try:
        # Always use subprocess to run transcription in the core venv
        # which has faster-whisper and all required dependencies
        run_transcription_subprocess(
            recording_id, wav_path, enable_diarization, enable_word_timestamps
        )

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
    recording_id: int,
    wav_path: Path,
    enable_diarization: bool,
    enable_word_timestamps: bool,
):
    """
    Run transcription as subprocess using the core _core module.

    This ensures the webapp uses the exact same transcription settings and code
    as the standalone orchestrator/static_transcriber.py, including:
    - Model configuration from config.yaml
    - VAD settings
    - Word timestamp handling
    - Diarization integration
    """

    if not VENV_PYTHON.exists():
        raise RuntimeError(f"Core venv not found at {VENV_PYTHON}")

    if not SCRIPT_DIR.exists():
        raise RuntimeError(f"Core SCRIPT directory not found: {SCRIPT_DIR}")

    # Build a runner script that uses static_transcriber.py properly
    # This script will:
    # 1. Load config.yaml settings
    # 2. Use the same transcription methods as the orchestrator
    # 3. Output JSON to stdout for the webapp to parse

    runner_script = f'''
import sys
import json
import os

# Add core paths
sys.path.insert(0, "{SCRIPT_DIR}")
sys.path.insert(0, "{CORE_DIR}")

# Suppress logging to stdout - we only want JSON output
import logging
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

try:
    from config_manager import ConfigManager
    from static_transcriber import StaticFileTranscriber, HAS_DIARIZATION
    import faster_whisper
    import soundfile as sf
    import torch
except ImportError as e:
    print(json.dumps({{"error": f"Missing dependency: {{e}}"}}), file=sys.stdout)
    sys.exit(1)

def run_transcription():
    """Run transcription using core module settings."""
    
    wav_path = "{wav_path}"
    enable_diarization = {str(enable_diarization)}
    enable_word_timestamps = {str(enable_word_timestamps)}
    
    try:
        # Load configuration from config.yaml (same as orchestrator uses)
        config = ConfigManager()
        
        # Get model settings from config
        main_config = config.get("main_transcriber", {{}})
        model_path = main_config.get("model", "Systran/faster-whisper-large-v3")
        compute_type = main_config.get("compute_type", "default")
        device = main_config.get("device", "cuda")
        beam_size = main_config.get("beam_size", 5)
        vad_filter = main_config.get("faster_whisper_vad_filter", True)
        
        # Get transcription options
        trans_options = config.get("transcription_options", {{}})
        language = trans_options.get("language")  # None for auto-detect
        
        # Get static transcription settings
        static_config = config.get("static_transcription", {{}})
        max_segment_chars = static_config.get("max_segment_chars", 500)
        
        # Read audio file
        audio_data, sample_rate = sf.read(wav_path, dtype="float32")
        audio_duration = len(audio_data) / sample_rate
        
        # Load model (using same settings as orchestrator)
        print(f"Loading model {{model_path}} on {{device}}...", file=sys.stderr)
        model = faster_whisper.WhisperModel(
            model_size_or_path=model_path,
            device=device,
            compute_type=compute_type,
        )
        
        # Transcribe with or without word timestamps
        print(f"Transcribing (word_timestamps={{enable_word_timestamps}})...", file=sys.stderr)
        segments_iter, info = model.transcribe(
            audio_data,
            language=language,
            beam_size=beam_size,
            word_timestamps=enable_word_timestamps,
            vad_filter=vad_filter,
        )
        
        # Convert to list of segment dicts
        segments = []
        for segment in segments_iter:
            words = []
            if enable_word_timestamps and segment.words:
                for word in segment.words:
                    words.append({{
                        "word": word.word.strip(),
                        "start": round(word.start, 3),
                        "end": round(word.end, 3),
                        "probability": round(word.probability, 3) if word.probability else 1.0,
                    }})
            
            segments.append({{
                "text": segment.text.strip(),
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "duration": round(segment.end - segment.start, 3),
                "words": words,
            }})
        
        # Perform diarization if enabled
        diarization_segments = None
        if enable_diarization and HAS_DIARIZATION:
            print("Running speaker diarization...", file=sys.stderr)
            try:
                from diarization_service import DiarizationService
                
                diar_config = config.get("diarization", {{}})
                min_speakers = diar_config.get("min_speakers")
                max_speakers = diar_config.get("max_speakers")
                
                diarization_service = DiarizationService()
                diarization_segments = diarization_service.diarize(
                    wav_path,
                    min_speakers=min_speakers,
                    max_speakers=max_speakers,
                )
                
                # Convert to list of dicts
                diarization_segments = [
                    {{"speaker": s.speaker, "start": s.start, "end": s.end}}
                    for s in diarization_segments
                ]
                print(f"Diarization complete: {{len(diarization_segments)}} segments", file=sys.stderr)
            except Exception as e:
                print(f"Diarization failed: {{e}}", file=sys.stderr)
                diarization_segments = None
        
        # Combine transcription with diarization if available
        if diarization_segments and enable_word_timestamps:
            segments = combine_with_diarization(segments, diarization_segments, max_segment_chars)
        
        # Clean up model to free GPU memory
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        # Output JSON result
        result = {{
            "segments": segments,
            "audio_duration": round(audio_duration, 2),
            "num_speakers": len(set(s.get("speaker") for s in segments if s.get("speaker"))) if diarization_segments else 0,
        }}
        print(json.dumps(result), file=sys.stdout)
        
    except Exception as e:
        import traceback
        print(json.dumps({{"error": str(e), "traceback": traceback.format_exc()}}), file=sys.stdout)
        sys.exit(1)


def combine_with_diarization(segments, diarization_segments, max_segment_chars):
    """Combine word-level transcription with speaker diarization."""
    
    # Collect all words with their times
    all_words = []
    for segment in segments:
        for word in segment.get("words", []):
            # Find the best matching speaker for this word
            word_mid = (word["start"] + word["end"]) / 2
            best_speaker = "SPEAKER_00"
            
            for diar_seg in diarization_segments:
                if diar_seg["start"] <= word_mid <= diar_seg["end"]:
                    best_speaker = diar_seg["speaker"]
                    break
            
            all_words.append((word, best_speaker))
    
    if not all_words:
        return segments
    
    # Group words into segments by speaker
    result_segments = []
    current_speaker = None
    current_words = []
    current_text = []
    current_char_count = 0
    segment_start = 0.0
    segment_end = 0.0
    
    for word, speaker in all_words:
        word_text = word["word"]
        word_chars = len(word_text)
        
        should_split = (
            speaker != current_speaker or
            (current_char_count + word_chars > max_segment_chars and current_words)
        )
        
        if should_split and current_words:
            result_segments.append({{
                "text": " ".join(current_text).strip(),
                "start": round(segment_start, 3),
                "end": round(segment_end, 3),
                "duration": round(segment_end - segment_start, 3),
                "speaker": current_speaker,
                "words": current_words.copy(),
            }})
            current_words = []
            current_text = []
            current_char_count = 0
        
        if not current_words:
            current_speaker = speaker
            segment_start = word["start"]
        
        current_words.append(word)
        current_text.append(word_text)
        current_char_count += word_chars + 1
        segment_end = word["end"]
    
    # Last segment
    if current_words:
        result_segments.append({{
            "text": " ".join(current_text).strip(),
            "start": round(segment_start, 3),
            "end": round(segment_end, 3),
            "duration": round(segment_end - segment_start, 3),
            "speaker": current_speaker,
            "words": current_words.copy(),
        }})
    
    return result_segments


if __name__ == "__main__":
    run_transcription()
'''

    import_status[recording_id].message = "Running transcription via core module..."
    import_status[recording_id].progress = 0.3

    result = subprocess.run(
        [str(VENV_PYTHON), "-c", runner_script],
        capture_output=True,
        text=True,
        cwd=str(SCRIPT_DIR),
    )

    # Check for errors
    if result.returncode != 0:
        stderr_msg = result.stderr.strip() if result.stderr else "Unknown error"
        raise RuntimeError(f"Transcription subprocess failed: {stderr_msg}")

    # Parse output
    output = result.stdout.strip()
    if not output:
        raise RuntimeError(f"Transcription produced no output. stderr: {result.stderr}")

    try:
        transcription_data = json.loads(output)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON output: {e}. Output was: {output[:500]}")

    # Check for error in response
    if "error" in transcription_data:
        error_msg = transcription_data["error"]
        tb = transcription_data.get("traceback", "")
        raise RuntimeError(f"Transcription error: {error_msg}\\n{tb}")

    import_status[recording_id].message = "Saving to database..."
    import_status[recording_id].progress = 0.8

    save_transcription_result(recording_id, transcription_data)

    import_status[recording_id] = ImportStatus(
        recording_id=recording_id,
        status="completed",
        progress=1.0,
        message="Transcription complete",
    )


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
        request.enable_word_timestamps,
    )

    return TranscribeResponse(
        recording_id=recording_id, message="Transcription started"
    )


@router.post("/upload", response_model=TranscribeResponse)
async def transcribe_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    enable_diarization: bool = False,
    enable_word_timestamps: bool = True,
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
    if not file.filename:
        raise HTTPException(status_code=400, detail="File must have a filename")

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
            enable_word_timestamps,
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
