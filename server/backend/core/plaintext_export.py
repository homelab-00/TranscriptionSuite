"""Plain-text streaming exporter (Issue #104, Story 3.4).

Yields FR9-format chunks: one paragraph per speaker turn, separated by a
blank line. Speaker label bolded as ``**Speaker:**``. NO subtitle-style
timestamps. Designed to be wrapped in a FastAPI ``StreamingResponse``
so an 8-hour recording (~1 GB transcript) doesn't materialize the full
output in RAM (NFR48 — peak RSS < 200 MB).

This is distinct from the existing ``GET /export?format=txt`` route on
notebook.py which produces a verbose, header-laden TXT body for power
users. ``format=plaintext`` is the FR9-compliant Lurker happy-path
(J1 narrative).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any


def stream_plaintext(
    recording: dict[str, Any],
    segments: Iterable[dict[str, Any]],
) -> Iterator[str]:
    """Yield plaintext chunks for the given recording's segments.

    Format spec (FR9 / AC3.4.AC1):
      - One paragraph per speaker turn (consecutive segments with the
        same ``speaker`` value coalesce into one paragraph).
      - Paragraphs separated by a blank line.
      - Speaker label bolded as ``**SpeakerLabel:**`` at the start of
        the paragraph (when present).
      - No subtitle timestamps (``00:00:01,234 --> ...``).

    Memory bound (AC3.4.AC2):
      - ``segments`` is consumed lazily; no list materialization.
      - The current paragraph's text fragments are buffered in a small
        list, joined, and yielded as a single chunk per paragraph.
      - For an 8-hour recording with ~12 segments/min (~5760 segments
        for plain Whisper output, ~100k for word-level), peak alloc is
        a single paragraph plus the title — well under the 200 MB
        budget.
    """
    title = recording.get("title") or recording.get("filename") or "Recording"
    yield f"# {title}\n\n"

    # Sentinel value distinct from any real speaker label so the first
    # iteration always emits a label (or a bare paragraph if no speaker).
    _SENTINEL = object()
    current_speaker: object = _SENTINEL
    paragraph_parts: list[str] = []

    for seg in segments:
        speaker_raw = seg.get("speaker")
        speaker: str | None = str(speaker_raw).strip() if speaker_raw not in (None, "") else None
        text = str(seg.get("text") or "").strip()
        if not text:
            continue

        if speaker != current_speaker:
            # Flush the previous paragraph
            if paragraph_parts:
                yield " ".join(paragraph_parts)
                yield "\n\n"
                paragraph_parts = []
            current_speaker = speaker
            if speaker is not None:
                yield f"**{speaker}:** "

        paragraph_parts.append(text)

    # Flush the final paragraph
    if paragraph_parts:
        yield " ".join(paragraph_parts)
        yield "\n"
