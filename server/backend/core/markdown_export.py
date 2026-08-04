"""Markdown conversation exporter (GH-279).

Yields a Markdown document shaped like the format requested in GH-279::

    # Friday Meeting - Part 2

    **Date:** July 10, 2026 at 02:53 PM

    ---

    **Speaker 3** *[00:44]*: There's not enough memory storage.
    **Speaker 1** *[00:48]*: Yes, I'll let you decide which one should go in.

One line per speaker turn (consecutive segments with the same ``speaker``
coalesce), each terminated with a Markdown hard break (two trailing spaces)
so renderers keep the turns on separate lines. Speaker labels arrive
pre-substituted — the caller wraps ``iter_segments`` in
``alias_substitution.apply_aliases`` so numbering matches the dashboard view.

Recordings without diarization degrade to plain paragraphs under the same
title/date header (no speaker prefix, no timestamps).

Streaming generator like ``plaintext_export.stream_plaintext`` — designed for
``StreamingResponse`` so long recordings never materialize fully in RAM.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Any


def format_markdown_timestamp(seconds: float) -> str:
    """Zero-padded ``MM:SS`` (minutes roll past 59 for recordings over an hour).

    Matches the txt-export timestamp convention in ``notebook.export_recording``
    — NOT the dashboard's ``formatRecSecs`` (which does not zero-pad minutes).
    """
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        total = 0
    return f"{total // 60:02d}:{total % 60:02d}"


def _format_date(recorded_at: Any) -> str:
    """Human-readable date, same format as the txt export header."""
    if not isinstance(recorded_at, str) or not recorded_at:
        return ""
    try:
        rec_dt = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        return rec_dt.strftime("%B %d, %Y at %I:%M %p")
    except ValueError:
        return recorded_at


def stream_markdown(
    recording: dict[str, Any],
    segments: Iterable[dict[str, Any]],
) -> Iterator[str]:
    """Yield Markdown chunks for the given recording's segments.

    ``segments`` must carry display-ready ``speaker`` labels (pass them
    through ``apply_aliases`` first) plus ``text`` and ``start_time``.
    """
    title = recording.get("title") or recording.get("filename") or "Recording"
    yield f"# {title}\n\n"

    date_str = _format_date(recording.get("recorded_at"))
    if date_str:
        yield f"**Date:** {date_str}\n\n"

    yield "---\n\n"

    # Sentinel distinct from any real speaker label so the first segment
    # always opens a turn (mirrors plaintext_export.stream_plaintext).
    _SENTINEL = object()
    current_speaker: object = _SENTINEL
    turn_start: float = 0.0
    turn_parts: list[str] = []

    def _flush() -> Iterator[str]:
        if not turn_parts:
            return
        text = " ".join(turn_parts)
        if current_speaker is None:
            # No diarization — plain paragraph, blank line between paragraphs.
            yield f"{text}\n\n"
        else:
            ts = format_markdown_timestamp(turn_start)
            # Two trailing spaces = Markdown hard line break.
            yield f"**{current_speaker}** *[{ts}]*: {text}  \n"

    for seg in segments:
        speaker_raw = seg.get("speaker")
        speaker: str | None = str(speaker_raw).strip() if speaker_raw not in (None, "") else None
        text = str(seg.get("text") or "").strip()
        if not text:
            continue

        if speaker != current_speaker:
            yield from _flush()
            turn_parts = []
            current_speaker = speaker
            try:
                turn_start = float(seg.get("start_time") or 0.0)
            except (TypeError, ValueError):
                turn_start = 0.0

        turn_parts.append(text)

    yield from _flush()
