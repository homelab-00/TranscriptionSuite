"""
Transcription API endpoints for TranscriptionSuite server.

Handles:
- Audio file transcription
- Real-time audio streaming (WebSocket)
- Transcription status and results
"""

import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from server.config import get_config
from server.core.token_store import get_token_store

logger = logging.getLogger(__name__)


def _get_client_name(request: Request) -> str:
    """
    Extract the client name from the request's authentication token.

    Returns the client_name from the token, or a default value if not found.
    """
    # Try Authorization header first
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        # Try cookie
        token = request.cookies.get("auth_token")

    if token:
        token_store = get_token_store()
        stored_token = token_store.validate_token(token)
        if stored_token:
            return stored_token.client_name

    return "Unknown Client"

router = APIRouter()


class TranscriptionRequest(BaseModel):
    """Request model for transcription."""

    language: Optional[str] = None
    word_timestamps: bool = True
    diarization: bool = False


class TranscriptionResponse(BaseModel):
    """Response model for transcription results."""

    text: str
    segments: List[Dict[str, Any]]
    words: List[Dict[str, Any]]
    language: str
    language_probability: float
    duration: float
    num_speakers: int = 0


@router.post("/audio", response_model=TranscriptionResponse)
@router.post("/file", response_model=TranscriptionResponse, include_in_schema=False)
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    word_timestamps: Optional[bool] = Form(None),
    diarization: Optional[bool] = Form(None),
) -> Dict[str, Any]:
    """
    Transcribe an uploaded audio file.

    Accepts audio/video files and returns transcription with:
    - Full text
    - Segments with timing
    - Word-level timestamps (optional)
    - Speaker labels (optional, if diarization enabled)

    Client detection:
    - Standalone client (X-Client-Type: standalone): Uses static_transcription config
    - Web UI clients: Uses API defaults (word_timestamps=True, diarization=False)

    Returns 409 Conflict if another transcription job is already running.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Get model manager and check if busy
    model_manager = request.app.state.model_manager
    client_name = _get_client_name(request)

    # Try to acquire a job slot
    success, job_id, active_user = model_manager.job_tracker.try_start_job(client_name)
    if not success:
        raise HTTPException(
            status_code=409,
            detail=f"A transcription is already running for {active_user}",
        )

    # Detect standalone client via header
    client_type = request.headers.get("X-Client-Type", "")

    # Apply defaults based on client type
    if client_type == "standalone":
        # Use static_transcription config for standalone clients
        config = get_config()
        static_cfg = config.get("static_transcription", default={})
        if word_timestamps is None:
            word_timestamps = static_cfg.get("word_timestamps", False)
        if diarization is None:
            diarization = static_cfg.get("enable_diarization", False)
        logger.debug(
            f"Standalone client: word_timestamps={word_timestamps}, "
            f"diarization={diarization}"
        )
    else:
        # Recorder web UI: always disable word_timestamps and diarization
        if word_timestamps is None:
            word_timestamps = False
        if diarization is None:
            diarization = False

    # Save uploaded file to temp location
    suffix = Path(file.filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Get transcription engine
        engine = model_manager.transcription_engine

        # Transcribe
        logger.info(f"Transcribing uploaded file: {file.filename}")
        result = engine.transcribe_file(
            tmp_path,
            language=language,
            word_timestamps=word_timestamps,
        )

        # Handle diarization if requested
        if diarization:
            try:
                model_manager.load_diarization_model()
                # TODO: Integrate diarization with transcription results
                logger.info("Diarization requested but not yet integrated")
            except Exception as e:
                logger.warning(f"Diarization failed: {e}")

        return result.to_dict()

    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Release the job slot
        model_manager.job_tracker.end_job(job_id)

        # Cleanup temp file
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass


@router.post("/quick", response_model=TranscriptionResponse)
async def transcribe_quick(
    request: Request,
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
) -> Dict[str, Any]:
    """
    Quick transcription for Record view - text only, no word timestamps or diarization.

    Optimized for speed - returns just the transcription text and basic metadata.

    Returns 409 Conflict if another transcription job is already running.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Get model manager and check if busy
    model_manager = request.app.state.model_manager
    client_name = _get_client_name(request)

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
        tmp_path = tmp.name

    try:
        # Get transcription engine
        engine = model_manager.transcription_engine

        # Transcribe without word timestamps for speed
        logger.info(f"Quick transcription for: {file.filename}")
        result = engine.transcribe_file(
            tmp_path,
            language=language,
            word_timestamps=False,  # No word timestamps for speed
        )

        return result.to_dict()

    except Exception as e:
        logger.error(f"Quick transcription failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Release the job slot
        model_manager.job_tracker.end_job(job_id)

        # Cleanup temp file
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass


@router.get("/languages")
async def get_supported_languages() -> Dict[str, Any]:
    """Get list of supported languages."""
    # Whisper supported languages
    languages = {
        "en": "English",
        "zh": "Chinese",
        "de": "German",
        "es": "Spanish",
        "ru": "Russian",
        "ko": "Korean",
        "fr": "French",
        "ja": "Japanese",
        "pt": "Portuguese",
        "tr": "Turkish",
        "pl": "Polish",
        "ca": "Catalan",
        "nl": "Dutch",
        "ar": "Arabic",
        "sv": "Swedish",
        "it": "Italian",
        "id": "Indonesian",
        "hi": "Hindi",
        "fi": "Finnish",
        "vi": "Vietnamese",
        "he": "Hebrew",
        "uk": "Ukrainian",
        "el": "Greek",
        "ms": "Malay",
        "cs": "Czech",
        "ro": "Romanian",
        "da": "Danish",
        "hu": "Hungarian",
        "ta": "Tamil",
        "no": "Norwegian",
        "th": "Thai",
        "ur": "Urdu",
        "hr": "Croatian",
        "bg": "Bulgarian",
        "lt": "Lithuanian",
        "la": "Latin",
        "mi": "Maori",
        "ml": "Malayalam",
        "cy": "Welsh",
        "sk": "Slovak",
        "te": "Telugu",
        "fa": "Persian",
        "lv": "Latvian",
        "bn": "Bengali",
        "sr": "Serbian",
        "az": "Azerbaijani",
        "sl": "Slovenian",
        "kn": "Kannada",
        "et": "Estonian",
        "mk": "Macedonian",
        "br": "Breton",
        "eu": "Basque",
        "is": "Icelandic",
        "hy": "Armenian",
        "ne": "Nepali",
        "mn": "Mongolian",
        "bs": "Bosnian",
        "kk": "Kazakh",
        "sq": "Albanian",
        "sw": "Swahili",
        "gl": "Galician",
        "mr": "Marathi",
        "pa": "Punjabi",
        "si": "Sinhala",
        "km": "Khmer",
        "sn": "Shona",
        "yo": "Yoruba",
        "so": "Somali",
        "af": "Afrikaans",
        "oc": "Occitan",
        "ka": "Georgian",
        "be": "Belarusian",
        "tg": "Tajik",
        "sd": "Sindhi",
        "gu": "Gujarati",
        "am": "Amharic",
        "yi": "Yiddish",
        "lo": "Lao",
        "uz": "Uzbek",
        "fo": "Faroese",
        "ht": "Haitian Creole",
        "ps": "Pashto",
        "tk": "Turkmen",
        "nn": "Nynorsk",
        "mt": "Maltese",
        "sa": "Sanskrit",
        "lb": "Luxembourgish",
        "my": "Myanmar",
        "bo": "Tibetan",
        "tl": "Tagalog",
        "mg": "Malagasy",
        "as": "Assamese",
        "tt": "Tatar",
        "haw": "Hawaiian",
        "ln": "Lingala",
        "ha": "Hausa",
        "ba": "Bashkir",
        "jw": "Javanese",
        "su": "Sundanese",
    }

    return {
        "languages": languages,
        "count": len(languages),
        "auto_detect": True,
    }
