"""OpenAI-compatible audio transcription endpoints.

Implements ``POST /v1/audio/transcriptions`` and ``POST /v1/audio/translations``
following the OpenAI Audio API spec so that any OpenAI-compatible client
(Open-WebUI, LM Studio, etc.) can use TranscriptionSuite as a drop-in STT backend.

Diarization support (GH-88): both endpoints accept optional ``diarization``,
``expected_speakers`` and ``parallel_diarization`` form fields. When diarization
is requested, the orchestration mirrors ``routes/transcription.py``: WhisperX
integrated single-pass path → ``transcribe_and_diarize`` / ``transcribe_then_diarize``
+ ``speaker_merge.build_speaker_segments``. Any diarization failure falls
through to a plain transcript — the endpoint never raises because the speaker
engine hiccuped.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from server.api.routes.utils import get_client_name
from server.config import resolve_main_transcriber_model
from server.core.formatters import (
    format_diarized_json,
    format_json,
    format_srt,
    format_text,
    format_verbose_json,
    format_vtt,
)
from server.core.model_manager import TranscriptionCancelledError
from server.core.stt.backends.base import BackendDependencyError, STTBackend

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_RESPONSE_FORMATS = {"json", "text", "verbose_json", "srt", "vtt", "diarized_json"}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _openai_error(
    status_code: int,
    message: str,
    error_type: str = "invalid_request_error",
    param: str | None = None,
    code: str | None = None,
) -> JSONResponse:
    """Return an error response shaped like the OpenAI API."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "param": param,
                "code": code,
            }
        },
    )


def _assert_model_loaded(request: Request) -> None:
    """Raise 503 if no main transcription model is configured/loaded."""
    config = request.app.state.config
    model_name = resolve_main_transcriber_model(config)
    if not model_name.strip():
        raise HTTPException(status_code=503, detail="No transcription model loaded")


def _build_response(
    result: Any,
    response_format: str,
    task: str,
    include_words: bool,
):
    """Serialize a :class:`TranscriptionResult` into the requested format."""
    if response_format == "text":
        return PlainTextResponse(format_text(result))
    if response_format == "srt":
        return PlainTextResponse(format_srt(result))
    if response_format == "vtt":
        return PlainTextResponse(format_vtt(result))
    if response_format == "verbose_json":
        return JSONResponse(format_verbose_json(result, task=task, include_words=include_words))
    if response_format == "diarized_json":
        return JSONResponse(format_diarized_json(result, task=task, include_words=include_words))
    # default: json
    return JSONResponse(format_json(result))


async def _run_transcription(
    *,
    request: Request,
    tmp_path: str,
    task: str,
    language: str | None,
    translation_target_language: str | None,
    initial_prompt: str | None,
    word_timestamps: bool,
    diarization: bool,
    expected_speakers: int | None,
    parallel_diarization: bool | None,
) -> Any:
    """Run transcription (optionally with diarization) and return a TranscriptionResult.

    Mirrors the three-path orchestration from ``routes/transcription.py``:

    1. **Integrated single-pass** — if the active backend overrides
       ``transcribe_with_diarization`` (WhisperX, VibeVoice-ASR). On exception
       we fall back to the standard path with ``diarization`` disabled (same
       policy the reference route uses).
    2. **Parallel or sequential diarize+transcribe** via ``parallel_diarize``.
       Choice is driven by ``parallel_diarization`` form param, else
       ``config.diarization.parallel``. After STT + diar finish, word-level
       speaker merge is performed via ``speaker_merge.build_speaker_segments``
       (with a segment-level fallback when no word timestamps exist).
    3. **Plain transcription** via ``engine.transcribe_file`` when diarization
       was not requested, or every diarization branch fell through.

    Diarization failures at any stage log a warning and return the transcript
    without speakers — consistent with the non-OpenAI route's behavior.
    """
    model_manager = request.app.state.model_manager
    engine = model_manager.transcription_engine

    # Diarization requires word-level alignment data. Force it on internally —
    # the caller controls whether words are *emitted* via include_words on the
    # response formatter, separate from whether they are *computed* here.
    need_word_timestamps = word_timestamps or diarization

    # --- Path 1: integrated single-pass diarization (WhisperX / VibeVoice-ASR) ---
    backend = getattr(engine, "_backend", None)
    use_integrated_diarization = (
        diarization
        and backend is not None
        and type(backend).transcribe_with_diarization is not STTBackend.transcribe_with_diarization
    )

    if use_integrated_diarization:
        try:
            from server.core.audio_utils import load_audio
            from server.core.stt.engine import TranscriptionResult

            backend_label = getattr(backend, "backend_name", "integrated")
            logger.info("OpenAI endpoint using %s single-pass diarization", backend_label)
            preferred_rate = int(getattr(backend, "preferred_input_sample_rate_hz", 16000) or 16000)
            audio_data, audio_sample_rate = await asyncio.to_thread(
                load_audio, tmp_path, target_sample_rate=preferred_rate
            )

            diar_result = await asyncio.to_thread(
                functools.partial(
                    backend.transcribe_with_diarization,
                    audio_data,
                    audio_sample_rate=audio_sample_rate,
                    language=language,
                    task=task,
                    beam_size=engine.beam_size,
                    initial_prompt=initial_prompt or engine.initial_prompt,
                    suppress_tokens=engine.suppress_tokens,
                    vad_filter=engine.faster_whisper_vad_filter,
                    num_speakers=expected_speakers,
                )
            )

            return TranscriptionResult(
                text=" ".join(seg.get("text", "") for seg in diar_result.segments).strip(),
                segments=diar_result.segments,
                words=diar_result.words,
                language=diar_result.language,
                language_probability=diar_result.language_probability,
                duration=len(audio_data) / audio_sample_rate,
                num_speakers=diar_result.num_speakers,
            )
        except TranscriptionCancelledError:
            raise
        except Exception:
            # Fail open — the spec's I/O matrix lists missing HF token as a
            # fail-open case, and WhisperX raises ``ValueError`` for that
            # specific misconfiguration. Treat every non-cancellation error
            # as a fallback trigger. If the error was a genuine client-input
            # problem (malformed language code, etc.), Path 3 (plain
            # ``engine.transcribe_file``) will surface it again and the route's
            # outer ``except ValueError`` handler still returns a 400.
            logger.warning(
                "OpenAI endpoint: integrated backend diarization failed — falling back to transcript without speakers",
                exc_info=True,
            )
            diarization = False
            # Fall through to the standard path below.

    # --- Path 2: parallel / sequential diarize + merge ---
    if diarization:
        config = request.app.state.config
        use_parallel = (
            parallel_diarization
            if parallel_diarization is not None
            else config.get("diarization", "parallel", default=True)
        )

        if use_parallel:
            from server.core.parallel_diarize import transcribe_and_diarize as diarize_fn
        else:
            from server.core.parallel_diarize import transcribe_then_diarize as diarize_fn

        try:
            result, diar_result = await asyncio.to_thread(
                functools.partial(
                    diarize_fn,
                    engine=engine,
                    model_manager=model_manager,
                    file_path=tmp_path,
                    language=language,
                    task=task,
                    translation_target_language=translation_target_language,
                    word_timestamps=need_word_timestamps,
                    expected_speakers=expected_speakers,
                    cancellation_check=model_manager.job_tracker.is_cancelled,
                )
            )
        except TranscriptionCancelledError:
            raise
        except Exception:
            logger.warning(
                "OpenAI endpoint: diarization orchestration failed — falling back to plain transcription",
                exc_info=True,
            )
            result, diar_result = None, None

        if result is not None and diar_result is not None:
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
                elif not result.words and result.segments:
                    from server.core.speaker_merge import build_speaker_segments_nowords

                    fallback = build_speaker_segments_nowords(result.segments, diar_dicts)
                    if fallback:
                        speakers = {s["speaker"] for s in fallback} - {"UNKNOWN"}
                        result.segments = fallback
                        result.num_speakers = len(speakers)
            except Exception:
                logger.warning(
                    "OpenAI endpoint: speaker merge failed — returning transcript without speakers",
                    exc_info=True,
                )

        if result is not None:
            return result
        # diarize_fn failed entirely — fall through to plain transcription.

    # --- Path 3: plain transcription ---
    return await asyncio.to_thread(
        functools.partial(
            engine.transcribe_file,
            tmp_path,
            language=language,
            task=task,
            translation_target_language=translation_target_language,
            word_timestamps=need_word_timestamps,
            initial_prompt=initial_prompt,
        )
    )


def _validate_expected_speakers(expected_speakers: int | None) -> JSONResponse | None:
    """Return an OpenAI-shaped 400 if ``expected_speakers`` is out of range."""
    if expected_speakers is None:
        return None
    if expected_speakers < 1 or expected_speakers > 10:
        return _openai_error(
            400,
            "expected_speakers must be between 1 and 10",
            param="expected_speakers",
        )
    return None


async def _dispatch_completion_webhook(*, source_label: str, result: Any, filename: str) -> None:
    result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
    from server.core.webhook import dispatch as dispatch_webhook

    await dispatch_webhook(
        source_label,
        {
            "source": "longform",
            "text": result_dict.get("text", ""),
            "filename": filename or "",
            "duration": result_dict.get("duration", 0),
            "language": result_dict.get("language"),
            "num_speakers": result_dict.get("num_speakers", 0),
        },
    )


# ------------------------------------------------------------------
# POST /v1/audio/transcriptions
# ------------------------------------------------------------------


@router.post("/transcriptions")
async def create_transcription(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    model: str = Form("whisper-1"),
    language: str | None = Form(None),
    prompt: str | None = Form(None),
    response_format: str = Form("json"),
    temperature: float | None = Form(None),
    timestamp_granularities: list[str] | None = Form(None, alias="timestamp_granularities[]"),  # noqa: B008
    diarization: bool = Form(False),
    expected_speakers: int | None = Form(None),
    parallel_diarization: bool | None = Form(None),
):
    """OpenAI-compatible audio transcription endpoint."""
    if response_format not in _VALID_RESPONSE_FORMATS:
        return _openai_error(
            400,
            f"Invalid response_format '{response_format}'. Must be one of: {', '.join(sorted(_VALID_RESPONSE_FORMATS))}",
        )

    speaker_err = _validate_expected_speakers(expected_speakers)
    if speaker_err is not None:
        return speaker_err

    try:
        _assert_model_loaded(request)
    except HTTPException:
        return _openai_error(503, "No transcription model loaded", error_type="server_error")

    if not file.filename:
        return _openai_error(400, "No audio file provided", param="file")

    model_manager = request.app.state.model_manager
    client_name = get_client_name(request)

    # Lazy-reload the backend BEFORE acquiring a job slot (Issue #76 pattern
    # mirrored from routes/transcription.py:128-134) so a failed reload doesn't
    # occupy the single-slot tracker. `model_manager.engine` was a typo — the
    # attribute does not exist; ensure_transcription_loaded() is the canonical
    # self-heal path and returns the attached engine.
    try:
        await asyncio.to_thread(model_manager.ensure_transcription_loaded)
    except BackendDependencyError as dep_err:
        remedy_suffix = f". {dep_err.remedy}" if dep_err.remedy else ""
        logger.warning(
            "OpenAI transcription pre-check failed — Backend dependency missing: %s%s",
            dep_err,
            remedy_suffix,
        )
        return _openai_error(503, "Backend dependency unavailable", error_type="server_error")

    success, job_id, active_user = model_manager.job_tracker.try_start_job(client_name)
    if not success:
        return _openai_error(
            429,
            f"A transcription is already running (by {active_user})",
            error_type="rate_limit_error",
        )

    client_requested_word_timestamps = bool(
        timestamp_granularities and "word" in timestamp_granularities
    )
    suffix = Path(file.filename).suffix or ".wav"
    tmp_path: str | None = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            content = await file.read()
            tmp.write(content)

        result = await _run_transcription(
            request=request,
            tmp_path=tmp_path,
            task="transcribe",
            language=language,
            translation_target_language=None,
            initial_prompt=prompt,
            word_timestamps=client_requested_word_timestamps,
            diarization=diarization,
            expected_speakers=expected_speakers,
            parallel_diarization=parallel_diarization,
        )

        await _dispatch_completion_webhook(
            source_label="longform_complete",
            result=result,
            filename=file.filename or "",
        )

        include_words = client_requested_word_timestamps and response_format in {
            "verbose_json",
            "diarized_json",
        }
        return _build_response(
            result, response_format, task="transcribe", include_words=include_words
        )

    except TranscriptionCancelledError:
        return _openai_error(500, "Transcription was cancelled", error_type="server_error")
    except ValueError:
        logger.warning("OpenAI transcription endpoint: invalid request", exc_info=True)
        return _openai_error(400, "Invalid request parameters", error_type="invalid_request_error")
    except HTTPException:
        raise
    except Exception:
        logger.exception("OpenAI transcription endpoint error")
        return _openai_error(500, "Internal server error", error_type="server_error")
    finally:
        model_manager.job_tracker.end_job(job_id)
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


# ------------------------------------------------------------------
# POST /v1/audio/translations
# ------------------------------------------------------------------


@router.post("/translations")
async def create_translation(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    model: str = Form("whisper-1"),
    prompt: str | None = Form(None),
    response_format: str = Form("json"),
    temperature: float | None = Form(None),
    timestamp_granularities: list[str] | None = Form(None, alias="timestamp_granularities[]"),  # noqa: B008
    diarization: bool = Form(False),
    expected_speakers: int | None = Form(None),
    parallel_diarization: bool | None = Form(None),
):
    """OpenAI-compatible audio translation endpoint (always translates to English)."""
    if response_format not in _VALID_RESPONSE_FORMATS:
        return _openai_error(
            400,
            f"Invalid response_format '{response_format}'. Must be one of: {', '.join(sorted(_VALID_RESPONSE_FORMATS))}",
        )

    speaker_err = _validate_expected_speakers(expected_speakers)
    if speaker_err is not None:
        return speaker_err

    try:
        _assert_model_loaded(request)
    except HTTPException:
        return _openai_error(503, "No transcription model loaded", error_type="server_error")

    if not file.filename:
        return _openai_error(400, "No audio file provided", param="file")

    model_manager = request.app.state.model_manager
    client_name = get_client_name(request)

    # Lazy-reload BEFORE try_start_job (Issue #76 pattern); see the
    # transcription handler above for the full rationale.
    try:
        await asyncio.to_thread(model_manager.ensure_transcription_loaded)
    except BackendDependencyError as dep_err:
        remedy_suffix = f". {dep_err.remedy}" if dep_err.remedy else ""
        logger.warning(
            "OpenAI translation pre-check failed — Backend dependency missing: %s%s",
            dep_err,
            remedy_suffix,
        )
        return _openai_error(503, "Backend dependency unavailable", error_type="server_error")

    success, job_id, active_user = model_manager.job_tracker.try_start_job(client_name)
    if not success:
        return _openai_error(
            429,
            f"A transcription is already running (by {active_user})",
            error_type="rate_limit_error",
        )

    client_requested_word_timestamps = bool(
        timestamp_granularities and "word" in timestamp_granularities
    )
    suffix = Path(file.filename).suffix or ".wav"
    tmp_path: str | None = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            content = await file.read()
            tmp.write(content)

        result = await _run_transcription(
            request=request,
            tmp_path=tmp_path,
            task="translate",
            language=None,
            translation_target_language="en",
            initial_prompt=prompt,
            word_timestamps=client_requested_word_timestamps,
            diarization=diarization,
            expected_speakers=expected_speakers,
            parallel_diarization=parallel_diarization,
        )

        await _dispatch_completion_webhook(
            source_label="longform_complete",
            result=result,
            filename=file.filename or "",
        )

        include_words = client_requested_word_timestamps and response_format in {
            "verbose_json",
            "diarized_json",
        }
        return _build_response(
            result, response_format, task="translate", include_words=include_words
        )

    except TranscriptionCancelledError:
        return _openai_error(500, "Transcription was cancelled", error_type="server_error")
    except ValueError:
        logger.warning("OpenAI translation endpoint: invalid request", exc_info=True)
        return _openai_error(400, "Invalid request parameters", error_type="invalid_request_error")
    except HTTPException:
        raise
    except Exception:
        logger.exception("OpenAI translation endpoint error")
        return _openai_error(500, "Internal server error", error_type="server_error")
    finally:
        model_manager.job_tracker.end_job(job_id)
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
