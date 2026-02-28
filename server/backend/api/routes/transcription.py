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
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from server.api.routes.utils import get_client_name
from server.config import resolve_main_transcriber_model
from server.core.model_manager import TranscriptionCancelledError
from server.core.stt.backends.base import STTBackend

logger = logging.getLogger(__name__)

router = APIRouter()


def _assert_main_model_selected(request: Request) -> None:
    config = request.app.state.config
    model_name = resolve_main_transcriber_model(config)
    if model_name.strip():
        return
    raise HTTPException(
        status_code=409,
        detail="Main model not selected. Choose a main model in Server settings before transcription.",
    )


class TranscriptionRequest(BaseModel):
    """Request model for transcription."""

    language: str | None = None
    translation_enabled: bool = False
    translation_target_language: str | None = None
    word_timestamps: bool = True
    diarization: bool = False


class TranscriptionResponse(BaseModel):
    """Response model for transcription results."""

    text: str
    segments: list[dict[str, Any]]
    words: list[dict[str, Any]]
    language: str | None = None
    language_probability: float = 0.0
    duration: float = 0.0
    num_speakers: int = 0


@router.post("/audio", response_model=TranscriptionResponse)
@router.post("/file", response_model=TranscriptionResponse, include_in_schema=False)
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    language: str | None = Form(None),
    translation_enabled: bool = Form(False),
    translation_target_language: str | None = Form(None),
    word_timestamps: bool | None = Form(None),
    diarization: bool | None = Form(None),
    expected_speakers: int | None = Form(None),
    parallel_diarization: bool | None = Form(None),
) -> dict[str, Any]:
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
    _assert_main_model_selected(request)

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
        logger.debug("Standalone client defaults applied")
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

        # Check if the backend supports single-pass diarization (WhisperX)
        backend = engine._backend
        use_integrated_diarization = (
            diarization
            and backend is not None
            and type(backend).transcribe_with_diarization
            is not STTBackend.transcribe_with_diarization
        )

        if use_integrated_diarization:
            # --- Integrated backend single-pass path (e.g. WhisperX, VibeVoice) ---
            try:
                from server.core.audio_utils import load_audio

                backend_label = getattr(backend, "backend_name", "integrated")
                logger.info("Using %s single-pass diarization", backend_label)
                preferred_rate = int(
                    getattr(backend, "preferred_input_sample_rate_hz", 16000) or 16000
                )
                audio_data, audio_sample_rate = load_audio(
                    tmp_path, target_sample_rate=preferred_rate
                )

                diar_result = backend.transcribe_with_diarization(
                    audio_data,
                    audio_sample_rate=audio_sample_rate,
                    language=language,
                    task="translate" if translation_enabled else "transcribe",
                    beam_size=engine.beam_size,
                    num_speakers=expected_speakers,
                )

                from server.core.stt.engine import TranscriptionResult

                result = TranscriptionResult(
                    text=" ".join(seg.get("text", "") for seg in diar_result.segments).strip(),
                    segments=diar_result.segments,
                    words=diar_result.words,
                    language=diar_result.language,
                    language_probability=diar_result.language_probability,
                    duration=len(audio_data) / audio_sample_rate,
                    num_speakers=diar_result.num_speakers,
                )

                return result.to_dict()

            except Exception:
                logger.warning(
                    "Integrated backend diarization failed (returning transcript without speakers)",
                    exc_info=True,
                )
                # Fall through to standard transcription without diarization
                diarization = False

        # Force word timestamps when diarization is requested
        # (needed for proper text-to-speaker alignment)
        need_word_timestamps = word_timestamps or diarization

        if diarization:
            # Resolve parallel vs sequential diarization
            config = request.app.state.config
            use_parallel = (
                parallel_diarization
                if parallel_diarization is not None
                else config.get("diarization", "parallel", default=True)
            )

            if use_parallel:
                from server.core.parallel_diarize import transcribe_and_diarize

                diarize_fn = transcribe_and_diarize
            else:
                from server.core.parallel_diarize import transcribe_then_diarize

                diarize_fn = transcribe_then_diarize

            result, diar_result = diarize_fn(
                engine=engine,
                model_manager=model_manager,
                file_path=tmp_path,
                language=language,
                task="translate" if translation_enabled else "transcribe",
                translation_target_language=(
                    translation_target_language if translation_enabled else None
                ),
                word_timestamps=need_word_timestamps,
                expected_speakers=expected_speakers,
                cancellation_check=model_manager.job_tracker.is_cancelled,
            )

            if diar_result is not None:
                try:
                    from server.core.speaker_merge import build_speaker_segments

                    diar_dicts = [seg.to_dict() for seg in diar_result.segments]
                    merged_segments, merged_words, num_speakers = build_speaker_segments(
                        result.words, diar_dicts
                    )

                    if merged_segments:
                        result.segments = merged_segments
                        result.words = merged_words
                        result.num_speakers = num_speakers
                        logger.info(
                            "Speaker merge complete: %s speakers, %s segments",
                            num_speakers,
                            len(merged_segments),
                        )
                except Exception:
                    logger.warning(
                        "Speaker merge failed (returning transcript without speakers)",
                        exc_info=True,
                    )
        else:
            # Transcribe without diarization
            logger.info("Transcribing uploaded file")
            result = engine.transcribe_file(
                tmp_path,
                language=language,
                task="translate" if translation_enabled else "transcribe",
                translation_target_language=(
                    translation_target_language if translation_enabled else None
                ),
                word_timestamps=need_word_timestamps,
                cancellation_check=model_manager.job_tracker.is_cancelled,
            )

        return result.to_dict()

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    except TranscriptionCancelledError:
        logger.info("Transcription cancelled by user")
        raise HTTPException(status_code=499, detail="Transcription cancelled by user") from None

    except Exception as e:
        logger.error("Transcription failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e

    finally:
        # Release the job slot
        model_manager.job_tracker.end_job(job_id)

        # Cleanup temp file
        try:
            Path(tmp_path).unlink()
        except OSError:
            logger.warning("Failed to cleanup temp file %s", tmp_path, exc_info=True)


@router.post("/quick", response_model=TranscriptionResponse)
async def transcribe_quick(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    language: str | None = Form(None),
    translation_enabled: bool = Form(False),
    translation_target_language: str | None = Form(None),
) -> dict[str, Any]:
    """
    Quick transcription for Record view - text only, no word timestamps or diarization.

    Optimized for speed - returns just the transcription text and basic metadata.

    Returns 409 Conflict if another transcription job is already running.
    """
    _assert_main_model_selected(request)

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
        logger.info("Quick transcription started")
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
        raise HTTPException(status_code=400, detail=str(e)) from e

    except TranscriptionCancelledError:
        logger.info("Quick transcription cancelled by user")
        raise HTTPException(status_code=499, detail="Transcription cancelled by user") from None

    except Exception as e:
        logger.error("Quick transcription failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e

    finally:
        # Release the job slot
        model_manager.job_tracker.end_job(job_id)

        # Cleanup temp file
        try:
            Path(tmp_path).unlink()
        except OSError:
            logger.warning("Failed to cleanup temp file %s", tmp_path, exc_info=True)


@router.post("/cancel")
async def cancel_transcription(request: Request) -> dict[str, Any]:
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


def _sorted_languages(langs: dict[str, str]) -> dict[str, str]:
    """Return *langs* sorted: English first, then alphabetical by name."""
    items = sorted(langs.items(), key=lambda kv: (kv[1] != "English", kv[1]))
    return dict(items)


# 25 European languages supported by NeMo models (Parakeet & Canary).
_NEMO_LANGUAGES: dict[str, str] = _sorted_languages(
    {
        "bg": "Bulgarian",
        "hr": "Croatian",
        "cs": "Czech",
        "da": "Danish",
        "nl": "Dutch",
        "en": "English",
        "et": "Estonian",
        "fi": "Finnish",
        "fr": "French",
        "de": "German",
        "el": "Greek",
        "hu": "Hungarian",
        "it": "Italian",
        "lv": "Latvian",
        "lt": "Lithuanian",
        "mt": "Maltese",
        "pl": "Polish",
        "pt": "Portuguese",
        "ro": "Romanian",
        "ru": "Russian",
        "sk": "Slovak",
        "sl": "Slovenian",
        "es": "Spanish",
        "sv": "Swedish",
        "uk": "Ukrainian",
    }
)

# Full Whisper language set (90 languages).
_WHISPER_LANGUAGES: dict[str, str] = _sorted_languages(
    {
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
        "te": "Telugu",  # codespell:ignore te
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
        "fo": "Faroese",  # codespell:ignore fo
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
)

_VIBEVOICE_ASR_LANGUAGES: dict[str, str] = {}


@router.get("/languages")
async def get_supported_languages(request: Request) -> dict[str, Any]:
    """Get list of supported languages for the active transcription model.

    Returns different language sets depending on the backend:
    - **whisper**: All 90 Whisper languages, translation to English.
    - **parakeet**: 25 European languages, no translation.
    - **canary**: 25 European languages, bidirectional English ↔ EU translation.
    - **vibevoice_asr**: Auto-detect only (no explicit language selection in v1 UI).
    """
    from server.config import resolve_main_transcriber_model
    from server.core.stt.backends.factory import detect_backend_type

    try:
        config = request.app.state.config
        model_name = resolve_main_transcriber_model(config)
        backend_type = detect_backend_type(model_name)
    except Exception:
        backend_type = "whisper"

    if backend_type in ("parakeet", "canary"):
        languages = _NEMO_LANGUAGES
    elif backend_type == "vibevoice_asr":
        languages = _VIBEVOICE_ASR_LANGUAGES
    else:
        languages = _WHISPER_LANGUAGES

    supports_translation = backend_type in ("whisper", "canary")

    return {
        "languages": languages,
        "count": len(languages),
        "auto_detect": True,
        "backend_type": backend_type,
        "supports_translation": supports_translation,
    }
