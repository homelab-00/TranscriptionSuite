"""
API endpoints for native client communication with the container.

These endpoints allow the native client (tray app) to:
- Check server status
- Upload and transcribe audio files
- Get transcription results
"""

import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/client", tags=["Native Client"])

# Lazy-loaded transcription engine
_engine = None


def _get_engine():
    """Get or create the transcription engine (lazy loading)."""
    global _engine
    if _engine is None:
        from MAIN.config_manager import ConfigManager
        from REMOTE_SERVER.transcription_engine import TranscriptionEngine

        # Load config from default location
        config_path = Path(__file__).parent.parent.parent / "config.yaml"
        config_manager = ConfigManager(str(config_path))
        config = config_manager.load_or_create_config()

        _engine = TranscriptionEngine(config)
    return _engine


class TranscriptionResponse(BaseModel):
    """Transcription result."""

    text: str
    segments: List[Dict[str, Any]] = []
    words: List[Dict[str, Any]] = []
    duration_seconds: float
    language: Optional[str] = None
    language_probability: Optional[float] = None


class StatusResponse(BaseModel):
    """Server status."""

    status: str
    models_loaded: bool
    gpu_available: bool
    gpu_name: Optional[str] = None
    cuda_version: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    service: str


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """Get server status for native client."""
    import torch

    gpu_name = None
    cuda_version = None

    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        cuda_version = torch.version.cuda

    return StatusResponse(
        status="ready",
        models_loaded=_engine is not None and _engine._model_loaded,
        gpu_available=torch.cuda.is_available(),
        gpu_name=gpu_name,
        cuda_version=cuda_version,
    )


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Basic health check endpoint."""
    return HealthResponse(status="healthy", service="transcription-api")


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    language: Optional[str] = Query(None, description="Language code (e.g., 'en', 'el')"),
    enable_diarization: bool = Query(False, description="Enable speaker diarization"),
):
    """
    Transcribe audio file uploaded from native client.

    This is the main endpoint the native client uses after recording.
    Accepts WAV, MP3, FLAC, OGG, M4A files.
    """
    import subprocess

    import soundfile as sf

    # Validate file type
    allowed_extensions = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".webm", ".mp4"}
    file_ext = Path(file.filename).suffix.lower() if file.filename else ".wav"

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file_ext}. Allowed: {allowed_extensions}",
        )

    # Save uploaded file to temp location
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
        content = await file.read()
        tmp.write(content)
        input_path = Path(tmp.name)

    # Convert to WAV if needed
    wav_path = None
    try:
        # Convert to 16kHz mono WAV using ffmpeg
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as wav_tmp:
            wav_path = Path(wav_tmp.name)

        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(input_path),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(wav_path),
                ],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg conversion failed: {e.stderr.decode()}")
            raise HTTPException(
                status_code=400, detail=f"Audio conversion failed: {e.stderr.decode()}"
            )

        # Read audio data
        audio_data, sample_rate = sf.read(wav_path, dtype="float32")

        # Get transcription engine
        engine = _get_engine()

        # Transcribe
        logger.info(f"Transcribing {len(audio_data) / 16000:.2f}s of audio")
        result = engine.transcribe(audio_data, language)

        return TranscriptionResponse(
            text=result.get("text", ""),
            words=result.get("words", []),
            duration_seconds=result.get("duration", 0.0),
            language=result.get("language"),
            language_probability=result.get("language_probability"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Transcription failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Cleanup temp files
        if input_path.exists():
            input_path.unlink()
        if wav_path and wav_path.exists():
            wav_path.unlink()


@router.post("/preload-model")
async def preload_model():
    """
    Preload the transcription model.

    Call this to warm up the model before sending transcription requests.
    """
    try:
        engine = _get_engine()
        engine.load_model()
        return {"status": "ok", "message": "Model loaded"}
    except Exception as e:
        logger.exception(f"Model preload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/unload-model")
async def unload_model():
    """
    Unload the transcription model to free GPU memory.
    """
    global _engine
    try:
        if _engine is not None:
            _engine.unload_model()
            _engine = None
        return {"status": "ok", "message": "Model unloaded"}
    except Exception as e:
        logger.exception(f"Model unload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
