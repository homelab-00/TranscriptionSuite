"""Token → word grouping for GigaAM decoders (no MLX dependency)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

_SP_WORD_START = "▁"


@dataclass
class TimedToken:
    """One emitted token: vocabulary id, encoder frame index, probability."""

    token_id: int
    frame: int
    probability: float


def tokens_to_words(
    tokens: Iterable[TimedToken],
    vocabulary: Sequence[str],
    *,
    sentencepiece: bool,
    frame_duration_s: float,
    offset_s: float = 0.0,
    control_token_ids: Iterable[int] = (),
) -> list[dict[str, Any]]:
    """Group timed tokens into ``{"word", "start", "end", "probability"}`` dicts.

    SentencePiece vocabularies (E2E models) start a word with ``▁``; char-wise
    vocabularies use a literal space token as the separator. A word spans from
    its first token's frame to the end of its last letter/digit token's frame:
    punctuation never extends a word, because RNN-T tends to emit it late.
    Detached punctuation (a ``▁,`` piece) is attached to the previous word.
    """
    control = set(control_token_ids)
    words: list[dict[str, Any]] = []
    pieces: list[str] = []
    probs: list[float] = []
    first_frame = last_frame = 0

    def flush() -> None:
        text = "".join(pieces)
        if text:
            start = round(offset_s + first_frame * frame_duration_s, 3)
            end = round(offset_s + (last_frame + 1) * frame_duration_s, 3)
            if words and not any(ch.isalnum() for ch in text):
                # Timing stays with the previous word: RNN-T often emits trailing
                # punctuation late, sometimes only at the end of the window.
                words[-1]["word"] += text
            else:
                words.append(
                    {
                        "word": text,
                        "start": start,
                        "end": end,
                        "probability": round(min(probs, default=1.0), 3),
                    }
                )
        pieces.clear()
        probs.clear()

    for tok in tokens:
        if tok.token_id in control or not 0 <= tok.token_id < len(vocabulary):
            continue
        piece = vocabulary[tok.token_id]
        if piece == "<unk>":
            continue
        if sentencepiece:
            if piece.startswith(_SP_WORD_START):
                flush()
                piece = piece[1:]
            if len(piece) == 6 and piece.startswith("<0x") and piece.endswith(">"):
                piece = bytes([int(piece[3:5], 16)]).decode("utf-8", errors="ignore")
        elif piece == " ":
            flush()
            continue
        if not piece:
            continue
        is_text = any(ch.isalnum() for ch in piece)
        if not pieces:
            first_frame = last_frame = tok.frame
        elif is_text:
            last_frame = tok.frame
        pieces.append(piece)
        if is_text:
            probs.append(tok.probability)
    flush()
    return words
