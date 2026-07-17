"""LLM-based restoration of the Greek final sigma (ς) for NeMo transcriptions.

The NeMo models (canary-1b-v2, parakeet-tdt-0.6b-v3 and their MLX ports) were
trained with SentencePiece vocabularies that lack U+03C2, so they cannot write
the Greek final sigma at all (upstream defect, unacknowledged:
https://huggingface.co/nvidia/canary-1b-v2/discussions/26).

On natural speech the models emit NOTHING at the sigma positions - the
recoverable " ⁇ " unk marker handled by greek_sigma.py only appears on
unnaturally crisp synthetic audio (verified against the user's real recordings:
y_sequence contains no unk id, under every decoding configuration tried,
including beam search with a strong length reward). The missing letter is
therefore unrecoverable from the model output, and the only robust restoration
is linguistic.

This module asks the user's configured OpenAI-compatible LLM provider (the
same integration the AI-summary feature uses) to re-insert the sigmas, then
accepts the reply through a deterministic guard:

* the reply must contain exactly the same number of whitespace tokens;
* per token, the only accepted edits are appending "ς" to a Greek word or
  turning a word-final "σ" into "ς", with trailing punctuation unchanged;
* every other difference is discarded, token by token.

Corruption is structurally impossible - the worst failure mode (LLM down,
misbehaving, or disabled) is "no repair", never a changed word. Applied in
``engine.transcribe_file`` so every longform path (WebSocket session, file
import, URL import, OpenAI-compatible route, notebook) is covered. Live mode
is not covered (its per-utterance latency budget cannot absorb an LLM call).
"""

from __future__ import annotations

import dataclasses
import logging
import re
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import cycle guard (engine imports us)
    from server.core.stt.engine import TranscriptionResult

logger = logging.getLogger(__name__)

# Backends whose tokenizer lacks ς. Whisper & friends are unaffected.
NEMO_BACKEND_NAMES = frozenset({"canary", "parakeet", "mlx_canary", "mlx_parakeet"})

# Greek and Greek Extended letters (final sigma only ever follows one), minus
# the punctuation code points inside the Greek block (U+037E, U+0387).
_GREEK_LETTER = re.compile(r"[Ͱ-ͽͿ-ΆΈ-Ͽἀ-῿]$")

# Trailing punctuation split off a token before the sigma comparison.
_TRAILING_PUNCT = re.compile(r"[.,!;:·»”’\"')\]…]+$")

# Character budget per LLM call. Greek averages ~3 chars per LLM token, and the
# reply echoes the input, so 1500 chars stays well inside small local models'
# context windows and the configured max_tokens.
_MAX_CHARS_PER_CALL = 1500

# Hard ceiling for the no-segment-alignment fallback (single call on the full
# text). Longer unaligned texts are left unrepaired rather than truncated.
_MAX_UNALIGNED_CHARS = 12000

_REPAIR_INSTRUCTION = (
    "The following Greek text was produced by a speech recognizer whose "
    "vocabulary lacks the final sigma (ς), so words that should end in ς "
    'appear truncated (e.g. "καλός" appears as "καλό"), or rarely with a '
    "final σ instead. Restore the missing final sigmas. Append ς (or turn a "
    "final σ into ς) only where Greek grammar requires it. Do not change, "
    "add, remove, or reorder any other words, letters, or punctuation. Reply "
    "with ONLY the corrected text - no explanations, no quotes."
)


# ---------------------------------------------------------------------------
# Deterministic guard
# ---------------------------------------------------------------------------


def _split_trailing_punct(token: str) -> tuple[str, str]:
    match = _TRAILING_PUNCT.search(token)
    if not match:
        return token, ""
    return token[: match.start()], match.group(0)


def _guard_token(original: str, corrected: str) -> str:
    """Return ``corrected`` only when it is a legal sigma repair of ``original``."""
    if corrected == original:
        return original

    orig_core, orig_punct = _split_trailing_punct(original)
    corr_core, corr_punct = _split_trailing_punct(corrected)
    if orig_punct != corr_punct or not orig_core:
        return original

    if corr_core == orig_core + "ς" and _GREEK_LETTER.search(orig_core):
        return corrected
    if orig_core.endswith("σ") and corr_core == orig_core[:-1] + "ς":
        return corrected
    return original


def apply_sigma_guard(original: str, corrected: str) -> str | None:
    """Filter an LLM reply down to legal sigma repairs of ``original``.

    Returns the guarded text, or ``None`` when the reply cannot be aligned
    with the original (token count mismatch) and must be discarded wholesale.
    """
    orig_tokens = original.split()
    corr_tokens = corrected.split()
    if len(orig_tokens) != len(corr_tokens):
        return None
    return " ".join(_guard_token(a, b) for a, b in zip(orig_tokens, corr_tokens, strict=True))


# ---------------------------------------------------------------------------
# LLM call (reuses the AI-summary provider integration)
# ---------------------------------------------------------------------------


def _repair_enabled() -> bool:
    """Config gate: local_llm.enabled AND local_llm.greek_sigma_repair."""
    try:
        from server.config import get_config

        llm_cfg = get_config().config.get("local_llm", {}) or {}
        return bool(llm_cfg.get("enabled", True)) and bool(llm_cfg.get("greek_sigma_repair", True))
    except Exception:  # noqa: BLE001 - config unavailable means no repair
        return False


def _call_llm(text: str) -> str | None:
    """Blocking chat-completion call via the shared LLM route helper.

    ``transcribe_file`` runs in worker threads, but one route calls it directly
    from the event-loop thread, so the coroutine always runs on a dedicated
    throwaway thread with its own loop. Any failure returns ``None``.
    """
    import asyncio

    # Deferred import - established core->routes pattern (auto_summary_engine).
    from server.api.routes.llm import LLMRequest, process_with_llm

    request = LLMRequest(
        transcription_text=text,
        user_prompt=_REPAIR_INSTRUCTION,
        temperature=0.0,
        max_tokens=max(512, len(text)),
    )

    outcome: dict[str, Any] = {}

    def _worker() -> None:
        try:
            response = asyncio.run(process_with_llm(request))
            outcome["text"] = response.response
        except Exception as exc:  # noqa: BLE001 - repair is best-effort
            outcome["error"] = exc

    thread = threading.Thread(target=_worker, name="greek-sigma-llm", daemon=True)
    thread.start()
    thread.join()

    if "text" in outcome:
        return str(outcome["text"]).strip() or None
    logger.info("Greek sigma LLM repair unavailable: %s", outcome.get("error"))
    return None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _batch_token_ranges(tokens: list[str], seg_token_counts: list[int]) -> list[tuple[int, int]]:
    """Group segment-aligned token ranges into <=_MAX_CHARS_PER_CALL batches."""
    ranges: list[tuple[int, int]] = []
    start = 0
    chars = 0
    pos = 0
    for count in seg_token_counts:
        seg_chars = sum(len(t) + 1 for t in tokens[pos : pos + count])
        if chars and chars + seg_chars > _MAX_CHARS_PER_CALL:
            ranges.append((start, pos))
            start = pos
            chars = 0
        chars += seg_chars
        pos += count
    if pos > start:
        ranges.append((start, pos))
    return ranges


def _apply_edit(token: str, edited_core_suffix: str) -> str:
    """Apply an accepted sigma edit shape to a possibly differently-cased or
    differently-punctuated rendering of the same token (segment/word entries
    can differ from the full text in first-letter case and final period)."""
    core, punct = _split_trailing_punct(token)
    if not core:
        return token
    if edited_core_suffix == "append":
        return core + "ς" + punct
    # final σ -> ς
    if core.endswith("σ"):
        return core[:-1] + "ς" + punct
    return token


def _patch_word_dicts(word_dicts: list[dict], edits: list[tuple[str, str]]) -> list[dict]:
    """Best-effort application of (original_core, edit_kind) pairs to word
    timestamp entries, in order. Unmatched edits are skipped silently."""
    patched = [dict(w) for w in word_dicts]
    cursor = 0
    for orig_core, edit_kind in edits:
        for i in range(cursor, len(patched)):
            entry_core, _ = _split_trailing_punct(str(patched[i].get("word", "")).strip())
            if entry_core.casefold() == orig_core.casefold():
                patched[i]["word"] = _apply_edit(str(patched[i]["word"]).strip(), edit_kind)
                cursor = i + 1
                break
    return patched


def repair_transcription_result(result: TranscriptionResult, backend_name: str | None):
    """Restore Greek final sigmas in a completed transcription result.

    Returns a NEW TranscriptionResult when anything was repaired; returns the
    input unchanged (same object) when the gates don't apply or the repair
    could not be performed. Never raises.
    """
    try:
        if backend_name not in NEMO_BACKEND_NAMES:
            return result
        if (result.language or "").lower() != "el":
            return result
        if not (result.text or "").strip():
            return result
        if not _repair_enabled():
            return result

        tokens = result.text.split()
        seg_texts = [str(s.get("text", "")) for s in result.segments]
        seg_token_counts = [len(t.split()) for t in seg_texts]
        aligned = sum(seg_token_counts) == len(tokens) and bool(seg_token_counts)

        if aligned:
            ranges = _batch_token_ranges(tokens, seg_token_counts)
        else:
            if len(result.text) > _MAX_UNALIGNED_CHARS:
                logger.info(
                    "Greek sigma repair skipped: %d chars without segment "
                    "alignment exceeds the single-call limit",
                    len(result.text),
                )
                return result
            ranges = [(0, len(tokens))]

        repaired_tokens = list(tokens)
        changed = False
        for start, end in ranges:
            batch_text = " ".join(tokens[start:end])
            reply = _call_llm(batch_text)
            if not reply:
                continue
            guarded = apply_sigma_guard(batch_text, reply)
            if guarded is None:
                logger.info(
                    "Greek sigma repair: LLM reply rejected (token mismatch) "
                    "for batch of %d tokens",
                    end - start,
                )
                continue
            guarded_tokens = guarded.split()
            for offset, new_token in enumerate(guarded_tokens):
                if new_token != tokens[start + offset]:
                    repaired_tokens[start + offset] = new_token
                    changed = True

        if not changed:
            return result

        new_text = " ".join(repaired_tokens)

        new_segments = [dict(s) for s in result.segments]
        if aligned:
            pos = 0
            for seg, count in zip(new_segments, seg_token_counts, strict=True):
                seg_slice = slice(pos, pos + count)
                edits: list[tuple[str, str]] = []
                seg_tokens = str(seg.get("text", "")).split()
                for i, (old, new) in enumerate(
                    zip(tokens[seg_slice], repaired_tokens[seg_slice], strict=True)
                ):
                    if old == new or i >= len(seg_tokens):
                        continue
                    old_core, _ = _split_trailing_punct(old)
                    new_core, _ = _split_trailing_punct(new)
                    kind = "append" if new_core == old_core + "ς" else "sigma_swap"
                    seg_tokens[i] = _apply_edit(seg_tokens[i], kind)
                    edits.append((old_core, kind))
                if edits:
                    seg["text"] = " ".join(seg_tokens)
                    if seg.get("words"):
                        seg["words"] = _patch_word_dicts(seg["words"], edits)
                pos += count

        new_words = [w for s in new_segments for w in (s.get("words") or [])]
        repaired_count = sum(
            1 for old, new in zip(tokens, repaired_tokens, strict=True) if old != new
        )
        logger.info("Greek sigma repair: restored %d word endings via LLM", repaired_count)

        return dataclasses.replace(
            result,
            text=new_text,
            segments=new_segments,
            words=new_words if new_words else result.words,
        )
    except Exception:  # noqa: BLE001 - repair must never break transcription
        logger.warning("Greek sigma LLM repair failed; keeping original", exc_info=True)
        return result
