"""Read-time speaker-alias substitution (Issue #104, Stories 4.4 / 5.1 / 5.2 / 5.3).

This module is the SINGLE backend source of truth for "what speaker name
does the surface display?". Consumers:
  - subtitle exporter (Story 5.1)
  - plaintext exporter (Story 5.1)
  - AI summary prompt builder (Story 5.2)
  - AI chat context (Story 5.3)

The dashboard mirror lives at ``dashboard/src/utils/aliasSubstitution.ts``.
A sync test (``tests/test_alias_substitution_sync.py``) reads both files
and asserts they implement the same first-appearance algorithm so that
``Speaker 1`` is consistent across the view, plain-text, and the AI
prompt.

Verbatim guarantee (R-EL3):
  - The alias_name is passed through UNCHANGED — no .strip(), no .lower(),
    no NFC normalization.
  - SQLite TEXT preserves UTF-8 bytes byte-for-byte; the LLM prompt builder
    sees exactly what the user typed.

The stored transcript (``segments.speaker``) is NEVER mutated. All
substitution is at READ time.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from typing import Any


def build_speaker_label_map(
    segments: Iterable[Mapping[str, Any]],
    aliases: Mapping[str, str],
) -> dict[str, str]:
    """Return ``raw_speaker_id → display_label`` for the given segments.

    For each NEW raw value of ``segment["speaker"]`` (in segment order):
      - if ``raw in aliases`` → the alias name (verbatim)
      - else → ``"Speaker {N}"`` where N is the first-appearance counter
        (1-indexed)

    Mirrors the dashboard's ``buildSpeakerLabelMap`` in
    ``dashboard/src/utils/aliasSubstitution.ts``.
    """
    labels: dict[str, str] = {}
    next_index = 1
    for seg in segments:
        raw = seg.get("speaker")
        if not raw or raw in labels:
            continue
        if raw in aliases:
            labels[raw] = aliases[raw]
        else:
            labels[raw] = f"Speaker {next_index}"
            next_index += 1
    return labels


def apply_aliases(
    segments: Iterable[Mapping[str, Any]],
    aliases: Mapping[str, str],
) -> Iterator[dict[str, Any]]:
    """Yield COPIES of ``segments`` with ``speaker`` replaced by display label.

    Lazy generator — preserves the bounded-RAM property of
    ``server.database.database.iter_segments`` (used by the Sprint 2
    plaintext exporter).
    """
    label_map: dict[str, str] = {}
    next_index = 1

    for seg in segments:
        raw = seg.get("speaker")
        if raw and raw not in label_map:
            if raw in aliases:
                label_map[raw] = aliases[raw]
            else:
                label_map[raw] = f"Speaker {next_index}"
                next_index += 1
        copy = dict(seg)
        if raw:
            copy["speaker"] = label_map[raw]
        yield copy


def speaker_key_preface(
    aliases: Mapping[str, str],
    raw_order: list[str],
) -> str:
    """Build the "Speaker key:" preamble injected into LLM prompts (Story 5.2).

    Format::

        Speakers in this transcript: Elena Vasquez (SPEAKER_00),
        Marco Rivera (SPEAKER_01), Speaker 3 (SPEAKER_02 — unaliased).

    The preface tells the LLM authoritative speaker names and their raw
    diarization IDs so it can disambiguate. The prompt builder ALSO
    appends a system-prompt directive forbidding the LLM from inferring
    nicknames or merging names (R-EL3 guard).
    """
    if not raw_order:
        return ""
    parts: list[str] = []
    next_index = 1
    seen: set[str] = set()
    for raw in raw_order:
        if raw in seen:
            continue
        seen.add(raw)
        if raw in aliases:
            parts.append(f"{aliases[raw]} ({raw})")
        else:
            parts.append(f"Speaker {next_index} ({raw} — unaliased)")
            next_index += 1
    return "Speakers in this transcript: " + ", ".join(parts) + "."
