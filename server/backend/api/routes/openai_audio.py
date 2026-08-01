"""OpenAI-compatible audio transcription endpoints.

Implements ``POST /v1/audio/transcriptions`` and ``POST /v1/audio/translations``
following the OpenAI Audio API spec so that any OpenAI-compatible client
(Open-WebUI, LM Studio, etc.) can use TranscriptionSuite as a drop-in STT backend.

Diarization support (GH-88): both endpoints accept optional ``diarization``,
``expected_speakers`` and ``parallel_diarization`` form fields. When diarization
is requested, the orchestration is delegated to
``core/diarization_dispatch.transcribe_with_optional_diarization`` (GH-274).
Any diarization failure falls through to a plain transcript — the endpoint
never raises because the speaker engine hiccuped.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from server.api.routes.utils import get_client_name
from server.config import resolve_main_transcriber_model, resolve_parallel_diarization_default
from server.core.formatters import (
    format_diarized_json,
    format_json,
    format_srt,
    format_text,
    format_verbose_json,
    format_vtt,
)
from server.core.model_manager import TranscriptionCancelledError
from server.core.stt.backends.base import BackendDependencyError

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

    GH-274: the whole diarization decision tree (integrated single-pass,
    two-pass parallel/sequential, plain transcription, speaker merge, failure
    classification) lives in ``core/diarization_dispatch``.

    The one route-specific edge kept here is the documented failure-tolerance
    contract ("never 5xxs on a diarization hiccup"): if the diarization
    orchestration itself crashes, fall back to ONE plain transcription attempt
    instead of surfacing a server error for a speaker-engine problem.
    Cancellation and audio-decode errors propagate — plain transcription would
    fail on them too, and the outer handlers own them (500-cancel / 400).
    """
    from server.core.audio_utils import AudioDecodeError
    from server.core.diarization_dispatch import transcribe_with_optional_diarization

    model_manager = request.app.state.model_manager
    engine = model_manager.transcription_engine

    sensevoice_engine_default = "funasr"
    resolved_parallel = parallel_diarization
    if diarization:
        app_config = getattr(request.app.state, "config", None)
        if app_config is not None:
            sensevoice_engine_default = app_config.get(
                "diarization", "sensevoice_engine", default="funasr"
            )
            if resolved_parallel is None:
                resolved_parallel = resolve_parallel_diarization_default(app_config)

    # Lambdas rather than functools.partial so the call sites stay visible to
    # the AST cancel-wiring guard (test_cancel_wiring.py).
    try:
        dispatched = await asyncio.to_thread(
            lambda: transcribe_with_optional_diarization(
                engine=engine,
                model_manager=model_manager,
                file_path=tmp_path,
                enable_diarization=diarization,
                language=language,
                task=task,
                translation_target_language=translation_target_language,
                word_timestamps=word_timestamps,
                initial_prompt=initial_prompt,
                expected_speakers=expected_speakers,
                parallel_diarization=resolved_parallel,
                sensevoice_engine_default=sensevoice_engine_default,
                cancellation_check=model_manager.job_tracker.is_cancelled,
            )
        )
        return dispatched.result
    except (TranscriptionCancelledError, AudioDecodeError):
        raise
    except Exception:
        if not diarization:
            # Plain transcription failed — a genuine error the caller owns.
            raise
        logger.warning(
            "OpenAI endpoint: diarization orchestration failed — falling back to plain transcription",
            exc_info=True,
        )

    dispatched = await asyncio.to_thread(
        lambda: transcribe_with_optional_diarization(
            engine=engine,
            model_manager=model_manager,
            file_path=tmp_path,
            enable_diarization=False,
            language=language,
            task=task,
            translation_target_language=translation_target_language,
            word_timestamps=word_timestamps,
            initial_prompt=initial_prompt,
            cancellation_check=model_manager.job_tracker.is_cancelled,
        )
    )
    return dispatched.result


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


def _set_diarization_status_header(
    response: JSONResponse | PlainTextResponse, result: Any, *, requested: bool
) -> None:
    """Surface whether a *requested* diarization actually produced speaker labels
    via an ``X-Diarization-Status`` header (GH #127).

    The OpenAI response body schema has no diarization field, so a swallowed
    diarization failure would otherwise be invisible — the header lets clients
    that care detect it (``ready`` vs ``unavailable``) while leaving the
    standardized body untouched. Not set when diarization was not requested.
    """
    if not requested:
        return
    performed = (getattr(result, "num_speakers", 0) or 0) > 0
    response.headers["X-Diarization-Status"] = "ready" if performed else "unavailable"


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
        api_response = _build_response(
            result, response_format, task="transcribe", include_words=include_words
        )
        _set_diarization_status_header(api_response, result, requested=diarization)
        return api_response

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

        # Must stay LAST in this finally - a cancellation landing inside the
        # await would otherwise skip end_job and the temp-file unlink above:
        # the single job slot has no timeout or admin force-release, so a
        # stranded slot 429s every later job until the server restarts.
        from server.core.audio_utils import post_job_gpu_cleanup

        await asyncio.to_thread(
            post_job_gpu_cleanup, "openai transcription", model_manager.gpu_device_index
        )


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
        api_response = _build_response(
            result, response_format, task="translate", include_words=include_words
        )
        _set_diarization_status_header(api_response, result, requested=diarization)
        return api_response

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

        # Must stay LAST in this finally - a cancellation landing inside the
        # await would otherwise skip end_job and the temp-file unlink above:
        # the single job slot has no timeout or admin force-release, so a
        # stranded slot 429s every later job until the server restarts.
        from server.core.audio_utils import post_job_gpu_cleanup

        await asyncio.to_thread(
            post_job_gpu_cleanup, "openai translation", model_manager.gpu_device_index
        )
