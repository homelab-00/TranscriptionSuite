"""Repair of the Greek final sigma (ς) in NeMo Canary transcription output.

``nvidia/canary-1b-v2`` and ``nvidia/parakeet-tdt-0.6b-v3`` were trained with
SentencePiece vocabularies that do not contain U+03C2 (ς) - NVIDIA's Granary
data pipeline folded every word-final sigma away before the tokenizer was
trained, so ς encodes to ``<unk>`` (id 0) and the models cannot write it.
Upstream defect report (open, unanswered):
https://huggingface.co/nvidia/canary-1b-v2/discussions/26

How the missing letter surfaces depends on the audio:

* On unnaturally crisp synthetic speech, **Canary (AED)** emits the ``<unk>``
  token at final-sigma positions and SentencePiece renders it as " ⁇ "
  (U+2047) in the decoded text. That marker deterministically locates the
  missing ς and is repaired here.
* On natural speech both families - Canary included - emit **nothing** at
  those positions (verified against real recordings: y_sequence contains no
  unk id under any decoding configuration). Nothing marker-based can help
  there; the linguistic LLM restoration in ``greek_sigma_llm.py`` covers it.

This marker repair is kept because it is free, deterministic, and guarantees
no " ⁇ " garbage ever reaches the user (or the LLM pass). It is deliberately
conservative: a marker is rewritten to ς only when it directly follows a
Greek letter (ς is word-final only, so it always follows one). Markers in any
other position are left untouched.
"""

from __future__ import annotations

import re

from server.core.stt.backends.base import BackendSegment

# SentencePiece's default unk_surface is " ⁇ " (U+2047), stripped here to the
# bare marker character.
_UNK_MARKER = "⁇"

# Greek and Greek Extended letter ranges - a final sigma can only ever follow
# one of these. U+037E (Greek question mark) and U+0387 (ano teleia) are
# punctuation inside the Greek block and are excluded.
_GREEK_LETTER = "Ͱ-ͽͿ-ΆΈ-Ͽἀ-῿"

# A marker after a Greek letter, optionally followed by trailing punctuation
# that SentencePiece rendered space-separated ("σα ⁇ !" -> "σας!"). When the
# optional punctuation group does not match, following whitespace is left in
# place and collapsed afterwards ("Αυτέ ⁇  οι" -> "Αυτές οι").
_MARKER_AFTER_GREEK = re.compile(rf"(?<=[{_GREEK_LETTER}])\s*{_UNK_MARKER}(?:\s*([.,!;:·»”’)\]]))?")
_MULTI_SPACE = re.compile(r" {2,}")

# Word-timestamp entries containing only punctuation (the unk token splits
# canary's word grouping, leaving e.g. "!" as its own entry).
_PUNCT_ONLY = re.compile(r"^[.,!;:·»”’)\]]+$")
_ENDS_WITH_GREEK = re.compile(rf"[{_GREEK_LETTER}]$")


def repair_greek_final_sigma(text: str) -> str:
    """Restore final sigmas in Canary text output for Greek.

    Returns the input unchanged when it contains no unk marker.
    """
    if _UNK_MARKER not in text:
        return text
    repaired = _MARKER_AFTER_GREEK.sub(lambda m: "ς" + (m.group(1) or ""), text)
    return _MULTI_SPACE.sub(" ", repaired)


def _repair_words(words: list[dict]) -> list[dict]:
    """Merge marker-only word entries into their preceding Greek word.

    A repaired word absorbs the marker entry's end time, plus one directly
    following punctuation-only entry (matching canary's usual attached-
    punctuation rendering, e.g. "κόσμο.").
    """
    repaired: list[dict] = []
    absorb_punct = False
    for entry in words:
        token = str(entry.get("word", "")).strip()

        if (
            token == _UNK_MARKER
            and repaired
            and _ENDS_WITH_GREEK.search(str(repaired[-1].get("word", "")))
        ):
            prev = repaired[-1]
            repaired[-1] = {
                **prev,
                "word": str(prev.get("word", "")) + "ς",
                "end": entry.get("end", prev.get("end")),
            }
            absorb_punct = True
            continue

        if absorb_punct and _PUNCT_ONLY.match(token):
            prev = repaired[-1]
            repaired[-1] = {
                **prev,
                "word": str(prev.get("word", "")) + token,
                "end": entry.get("end", prev.get("end")),
            }
            absorb_punct = False
            continue

        absorb_punct = False
        repaired.append(dict(entry))

    return repaired


def repair_segments_greek_final_sigma(
    segments: list[BackendSegment],
) -> list[BackendSegment]:
    """Return new segments with text and word entries repaired.

    Input segments are not mutated.
    """
    return [
        BackendSegment(
            text=repair_greek_final_sigma(segment.text),
            start=segment.start,
            end=segment.end,
            words=_repair_words(segment.words),
        )
        for segment in segments
    ]
