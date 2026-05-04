"""Auto-summary engine wrapper (Issue #104, Story 6.2 + Story 6.7).

Programmatic equivalent of the ``POST /api/llm/summarize/{id}`` route —
callable from the auto-action coordinator without going through HTTP.
Reuses the same alias-aware text builder, the same ``process_with_llm``
LLM call, and the same persistence path. The only difference is the
return shape: a plain dict the coordinator can inspect, instead of an
HTTP response.

Story 6.7 (R-EL17) truncation detection — heuristic until provider
hooks land:
  - If ``tokens_used`` is at least ``max_tokens * 0.95`` (within 5% of
    the cap) AND the text does not end in terminal punctuation
    (``.``, ``!``, ``?``, ``"``, or whitespace-stripped equivalents),
    treat as truncated.
  - Smaller responses are never flagged truncated even if they end mid
    word — the heuristic only fires when we're at the token budget.

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

    text = llm_response.response or ""
    tokens_used = llm_response.tokens_used
    return {
        "text": text,
        "model": llm_response.model,
        "tokens_used": tokens_used,
        "truncated": _looks_truncated(text, tokens_used),
    }


_TERMINAL_PUNCT = {".", "!", "?", '"', "'", ")", "]"}


def _looks_truncated(text: str, tokens_used: int | None) -> bool:
    """Heuristic truncation detector (Story 6.7 / R-EL17).

    Provider-specific signals (OpenAI ``finish_reason='length'``, Anthropic
    ``stop_reason='max_tokens'``) are not currently surfaced through
    ``process_with_llm``; this heuristic catches the common case until
    that lands.

    A response is treated as truncated when:
      1. ``tokens_used`` reaches at least 95% of the configured max
         (proxied via the LLM config), AND
      2. The trimmed text does not end in terminal punctuation.

    Empty/short text is never flagged truncated — Story 6.7 AC1's
    ``summary_empty`` predicate handles those.
    """
    if not text or tokens_used is None:
        return False
    stripped = text.rstrip()
    if not stripped:
        return False
    if stripped[-1] in _TERMINAL_PUNCT:
        return False
    # Pull max_tokens from the same config the LLM call used.
    try:
        from server.api.routes.llm import get_llm_config

        cfg = get_llm_config()
        max_tokens = int(cfg.get("max_tokens", 0) or 0)
    except Exception:  # noqa: BLE001 — config unavailable, skip heuristic
        return False
    if max_tokens <= 0:
        return False
    return tokens_used >= int(max_tokens * 0.95)
