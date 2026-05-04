"""Auto-summary engine wrapper (Issue #104, Story 6.2).

Programmatic equivalent of the ``POST /api/llm/summarize/{id}`` route —
callable from the auto-action coordinator without going through HTTP.
Reuses the same alias-aware text builder, the same ``process_with_llm``
LLM call, and the same persistence path. The only difference is the
return shape: a plain dict the coordinator can inspect, instead of an
HTTP response.

Verbatim guarantee R-EL3: alias names are passed through
``apply_aliases`` exactly as stored — no normalization (Sprint 3 contract).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)


class AutoSummaryError(RuntimeError):
    """Raised when the LLM call fails for any reason — coordinator catches."""


async def summarize_for_auto_action(
    recording_id: int, public_fields: Mapping[str, Any]
) -> dict[str, Any]:
    """Summarize the recording's transcript via the configured LLM.

    Returns ``{"text": str, "model": str | None, "tokens_used": int | None,
    "truncated": bool}``. Truncation detection (Story 6.7 — commit F) is a
    follow-up; commit B always returns ``truncated=False``.

    Raises ``AutoSummaryError`` on any LLM/network failure so the
    coordinator can map it to status='failed'. Does NOT persist —
    the coordinator owns the Persist-Before-Deliver flow.
    """
    from fastapi import HTTPException
    from server.api.routes.llm import (
        _VERBATIM_DIRECTIVE,
        LLMRequest,
        _build_alias_aware_transcript_text,
        process_with_llm,
    )
    from server.database.database import get_recording, get_transcription

    recording = get_recording(recording_id)
    if not recording:
        raise AutoSummaryError(f"recording {recording_id} not found")

    transcription = get_transcription(recording_id)
    if not transcription or not transcription.get("segments"):
        raise AutoSummaryError(f"recording {recording_id} has no transcription")

    full_text, preface = _build_alias_aware_transcript_text(recording_id, transcription["segments"])
    if preface:
        full_text = f"{preface}\n\n{_VERBATIM_DIRECTIVE}\n\n{full_text}"

    custom_prompt = public_fields.get("summary_prompt_template")
    request = LLMRequest(
        transcription_text=full_text,
        user_prompt=custom_prompt or None,
    )

    try:
        llm_response = await process_with_llm(request)
    except HTTPException as exc:  # 503/504/etc — transient
        raise AutoSummaryError(f"LLM call failed: {exc.detail}") from exc
    except Exception as exc:  # network/timeout — also transient
        raise AutoSummaryError(f"LLM call failed: {exc}") from exc

    return {
        "text": llm_response.response or "",
        "model": llm_response.model,
        "tokens_used": llm_response.tokens_used,
        "truncated": False,  # Commit F (Story 6.7) will add the heuristic
    }
