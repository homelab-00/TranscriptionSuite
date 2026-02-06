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

from server.api.routes.utils import get_client_name, sanitize_for_log
from server.config import get_config
from server.core.model_manager import TranscriptionCancelledError

logger = logging.getLogger(__name__)

router = APIRouter()


class TranscriptionRequest(BaseModel):
    """Request model for transcription."""

    language: Optional[str] = None
    translation_enabled: bool = False
    translation_target_language: Optional[str] = None
    word_timestamps: bool = True
    diarization: bool = False


class TranscriptionResponse(BaseModel):
    """Response model for transcription results."""

    text: str
    segments: List[Dict[str, Any]]
    words: List[Dict[str, Any]]
    language: Optional[str] = None
    language_probability: float = 0.0
    duration: float = 0.0
    num_speakers: int = 0


@router.post("/audio", response_model=TranscriptionResponse)
@router.post("/file", response_model=TranscriptionResponse, include_in_schema=False)
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    translation_enabled: bool = Form(False),
    translation_target_language: Optional[str] = Form(None),
    word_timestamps: Optional[bool] = Form(None),
    diarization: Optional[bool] = Form(None),
    expected_speakers: Optional[int] = Form(None),
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

    Parameters:
    - expected_speakers: Exact number of speakers (2-10). Forces diarization to
      identify exactly this many speakers. Useful for podcasts with known hosts
      where occasional clips should be attributed to the main speakers.

    Returns 409 Conflict if another transcription job is already running.
    """
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

    # Detect standalone client via header
    client_type = request.headers.get("X-Client-Type", "")

    # Apply defaults based on client type
    if client_type == "standalone":
        # Standalone client defaults (Audio Notebook handles diarization/timestamps)
        if word_timestamps is None:
            word_timestamps = False
        if diarization is None:
            diarization = False
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

        # Transcribe with cancellation support
        logger.info(f"Transcribing uploaded file: {file.filename}")
        result = engine.transcribe_file(
            tmp_path,
            language=language,
            task="translate" if translation_enabled else "transcribe",
            translation_target_language=(
                translation_target_language if translation_enabled else None
            ),
            word_timestamps=word_timestamps,
            cancellation_check=model_manager.job_tracker.is_cancelled,
        )

        # Handle diarization if requested
        if diarization:
            try:
                logger.info("Running diarization on transcribed audio")
                model_manager.load_diarization_model()
                diar_engine = model_manager.diarization_engine

                # Load audio for diarization
                from server.core.audio_utils import load_audio

                audio_data, sample_rate = load_audio(tmp_path, target_sample_rate=16000)

                # Run diarization with expected_speakers parameter
                diar_result = diar_engine.diarize_audio(
                    audio_data, sample_rate, num_speakers=expected_speakers
                )

                logger.info(
                    f"Diarization complete: {diar_result.num_speakers} speakers found"
                )

                # TODO: Integrate diarization segments with transcription results
                # For now, just log success - full integration requires aligning
                # speaker labels with transcript segments based on timestamps
            except Exception as e:
                logger.warning(f"Diarization failed: {e}")

        return result.to_dict()

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except TranscriptionCancelledError:
        logger.info(f"Transcription cancelled for file: {file.filename}")
        raise HTTPException(status_code=499, detail="Transcription cancelled by user")

    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Release the job slot
        model_manager.job_tracker.end_job(job_id)

        # Cleanup temp file
        try:
            Path(tmp_path).unlink()
        except Exception as e:
            logger.warning(f"Failed to cleanup temp file {tmp_path}: {e}")


@router.post("/quick", response_model=TranscriptionResponse)
async def transcribe_quick(
    request: Request,
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    translation_enabled: bool = Form(False),
    translation_target_language: Optional[str] = Form(None),
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
        tmp_path = tmp.name

    try:
        # Get transcription engine
        engine = model_manager.transcription_engine

        # Transcribe without word timestamps for speed, with cancellation support
        logger.info(f"Quick transcription for: {file.filename}")
        result = engine.transcribe_file(
            tmp_path,
            language=language,
            task="translate" if translation_enabled else "transcribe",
            translation_target_language=(
                translation_target_language if translation_enabled else None
            ),
            word_timestamps=False,  # No word timestamps for speed
            cancellation_check=model_manager.job_tracker.is_cancelled,
        )

        return result.to_dict()

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except TranscriptionCancelledError:
        logger.info(f"Quick transcription cancelled for file: {file.filename}")
        raise HTTPException(status_code=499, detail="Transcription cancelled by user")

    except Exception as e:
        logger.error(f"Quick transcription failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Release the job slot
        model_manager.job_tracker.end_job(job_id)

        # Cleanup temp file
        try:
            Path(tmp_path).unlink()
        except Exception as e:
            logger.warning(f"Failed to cleanup temp file {tmp_path}: {e}")


@router.post("/cancel")
async def cancel_transcription(request: Request) -> Dict[str, Any]:
    """
    Cancel the currently running transcription job.

    This requests cancellation of any active transcription. The actual cancellation
    happens between segments during processing, so there may be a brief delay.

    Returns:
        - success: Whether a job was cancelled
        - cancelled_user: The user whose job was cancelled (if any)
        - message: Human-readable status message
    """
    model_manager = request.app.state.model_manager
    success, cancelled_user = model_manager.job_tracker.cancel_job()

    if success:
        return {
            "success": True,
            "cancelled_user": cancelled_user,
            "message": f"Cancellation requested for {cancelled_user}'s transcription",
        }
    else:
        return {
            "success": False,
            "cancelled_user": None,
            "message": "No transcription job is currently running",
        }


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
