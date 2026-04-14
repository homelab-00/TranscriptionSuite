"""OpenAI-compatible audio transcription endpoints.

Implements ``POST /v1/audio/transcriptions`` and ``POST /v1/audio/translations``
following the OpenAI Audio API spec so that any OpenAI-compatible client
(Open-WebUI, LM Studio, etc.) can use TranscriptionSuite as a drop-in STT backend.
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
from server.config import resolve_main_transcriber_model
from server.core.formatters import (
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

_VALID_RESPONSE_FORMATS = {"json", "text", "verbose_json", "srt", "vtt"}


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


def _build_response(result: Any, response_format: str, task: str, include_words: bool):
    """Serialize a :class:`TranscriptionResult` into the requested format."""
    if response_format == "text":
        return PlainTextResponse(format_text(result))
    if response_format == "srt":
        return PlainTextResponse(format_srt(result))
    if response_format == "vtt":
        return PlainTextResponse(format_vtt(result))
    if response_format == "verbose_json":
        return JSONResponse(format_verbose_json(result, task=task, include_words=include_words))
    # default: json
    return JSONResponse(format_json(result))


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
):
    """OpenAI-compatible audio transcription endpoint."""
    if response_format not in _VALID_RESPONSE_FORMATS:
        return _openai_error(
            400,
            f"Invalid response_format '{response_format}'. Must be one of: {', '.join(sorted(_VALID_RESPONSE_FORMATS))}",
        )

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
        detail_message = f"Backend dependency missing: {dep_err}{remedy_suffix}"
        logger.warning("OpenAI transcription pre-check failed — %s", detail_message)
        return _openai_error(503, detail_message, error_type="server_error")

    success, job_id, active_user = model_manager.job_tracker.try_start_job(client_name)
    if not success:
        return _openai_error(
            429,
            f"A transcription is already running (by {active_user})",
            error_type="rate_limit_error",
        )

    word_timestamps = False
    if timestamp_granularities and "word" in timestamp_granularities:
        word_timestamps = True

    suffix = Path(file.filename).suffix or ".wav"
    tmp_path: str | None = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            content = await file.read()
            tmp.write(content)

        engine = model_manager.transcription_engine
        result = engine.transcribe_file(
            tmp_path,
            language=language,
            task="transcribe",
            word_timestamps=word_timestamps,
            initial_prompt=prompt,
        )

        # Fire outgoing webhook for completed transcription
        result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
        from server.core.webhook import dispatch as dispatch_webhook

        await dispatch_webhook(
            "longform_complete",
            {
                "source": "longform",
                "text": result_dict.get("text", ""),
                "filename": file.filename or "",
                "duration": result_dict.get("duration", 0),
                "language": result_dict.get("language"),
                "num_speakers": result_dict.get("num_speakers", 0),
            },
        )

        include_words = word_timestamps and response_format == "verbose_json"
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
):
    """OpenAI-compatible audio translation endpoint (always translates to English)."""
    if response_format not in _VALID_RESPONSE_FORMATS:
        return _openai_error(
            400,
            f"Invalid response_format '{response_format}'. Must be one of: {', '.join(sorted(_VALID_RESPONSE_FORMATS))}",
        )

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
        detail_message = f"Backend dependency missing: {dep_err}{remedy_suffix}"
        logger.warning("OpenAI translation pre-check failed — %s", detail_message)
        return _openai_error(503, detail_message, error_type="server_error")

    success, job_id, active_user = model_manager.job_tracker.try_start_job(client_name)
    if not success:
        return _openai_error(
            429,
            f"A transcription is already running (by {active_user})",
            error_type="rate_limit_error",
        )

    word_timestamps = False
    if timestamp_granularities and "word" in timestamp_granularities:
        word_timestamps = True

    suffix = Path(file.filename).suffix or ".wav"
    tmp_path: str | None = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            content = await file.read()
            tmp.write(content)

        engine = model_manager.transcription_engine
        result = engine.transcribe_file(
            tmp_path,
            task="translate",
            translation_target_language="en",
            word_timestamps=word_timestamps,
            initial_prompt=prompt,
        )

        # Fire outgoing webhook for completed translation
        result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
        from server.core.webhook import dispatch as dispatch_webhook

        await dispatch_webhook(
            "longform_complete",
            {
                "source": "longform",
                "text": result_dict.get("text", ""),
                "filename": file.filename or "",
                "duration": result_dict.get("duration", 0),
                "language": result_dict.get("language"),
                "num_speakers": result_dict.get("num_speakers", 0),
            },
        )

        include_words = word_timestamps and response_format == "verbose_json"
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
