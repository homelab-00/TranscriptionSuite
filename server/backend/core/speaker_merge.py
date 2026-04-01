"""Speaker-label merge logic for combining ASR transcripts with diarization.

Assigns speaker labels from pyannote diarization segments to ASR words and
segments using timestamp overlap.  The algorithm is backend-agnostic — it
works identically for Whisper, Parakeet, and Canary outputs.

The merge follows a two-pass strategy:

1. **Word-level assignment** — each ASR word is matched to the diarization
   segment with the highest temporal overlap.  A small configurable padding
   (default ±40 ms) compensates for boundary jitter between the ASR and
   diarization timestamps.

2. **Micro-turn smoothing** — isolated single-word speaker flips that are
   sandwiched between runs of the same speaker are relabelled to the
   surrounding speaker, eliminating ping-pong artefacts on short function
   words (e.g. "uh", "yeah").
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default tuning constants (seconds)
# ---------------------------------------------------------------------------
DEFAULT_WORD_PADDING_S: float = 0.040  # ±40 ms jitter tolerance
DEFAULT_NEAREST_TURN_TOLERANCE_S: float = 0.120  # 120 ms fallback
DEFAULT_MICRO_TURN_MAX_WORDS: int = 1  # smoothing threshold


def assign_speakers_to_words(
    words: list[dict[str, Any]],
    diarization_segments: list[dict[str, Any]],
    *,
    word_padding_s: float = DEFAULT_WORD_PADDING_S,
    nearest_turn_tolerance_s: float = DEFAULT_NEAREST_TURN_TOLERANCE_S,
) -> list[dict[str, Any]]:
    """Assign a ``speaker`` key to each word dict based on diarization segments.

    Each word dict is expected to have ``start`` and ``end`` (or ``start_time``
    / ``end_time``) keys.  Each diarization segment dict must have ``start``,
    ``end``, and ``speaker``.

    The function returns a **new** list of word dicts (shallow copies) with
    an added ``speaker`` key.  The original dicts are not mutated.

    Fallback chain per word:
    1. Max-overlap diarization segment (with ±padding inflation)
    2. Midpoint containment
    3. Nearest diarization turn within *nearest_turn_tolerance_s*
    4. Previous word's speaker (if gap is small)
    5. ``"UNKNOWN"``
    """
    if not words or not diarization_segments:
        return [dict(w, speaker=w.get("speaker")) for w in words]

    # Pre-sort diarization segments by start time for efficiency
    diar = sorted(diarization_segments, key=lambda s: float(s.get("start", 0.0)))

    result: list[dict[str, Any]] = []
    prev_speaker: str | None = None
    prev_end: float = 0.0

    for w in words:
        w_start = float(w.get("start", w.get("start_time", 0.0)) or 0.0)
        w_end = float(w.get("end", w.get("end_time", w_start)) or w_start)
        w_mid = (w_start + w_end) / 2.0

        # Inflate word interval by padding for overlap computation
        padded_start = w_start - word_padding_s
        padded_end = w_end + word_padding_s

        best_speaker: str | None = None
        best_overlap: float = 0.0
        midpoint_speaker: str | None = None
        nearest_speaker: str | None = None
        nearest_distance: float | None = None

        for seg in diar:
            seg_start = float(seg.get("start", 0.0))
            seg_end = float(seg.get("end", 0.0))
            speaker = seg.get("speaker", "UNKNOWN")

            # Pass 1: overlap (with padding)
            overlap = max(0.0, min(padded_end, seg_end) - max(padded_start, seg_start))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker

            # Pass 2: midpoint containment (no padding)
            if midpoint_speaker is None and seg_start <= w_mid <= seg_end:
                midpoint_speaker = speaker

            # Pass 3: nearest turn within tolerance
            if w_mid < seg_start:
                dist = seg_start - w_mid
            elif w_mid > seg_end:
                dist = w_mid - seg_end
            else:
                dist = 0.0
            if dist <= nearest_turn_tolerance_s:
                if nearest_distance is None or dist < nearest_distance:
                    nearest_distance = dist
                    nearest_speaker = speaker

        # Apply fallback chain
        if best_speaker is not None and best_overlap > 0.0:
            chosen = best_speaker
        elif midpoint_speaker is not None:
            chosen = midpoint_speaker
        elif nearest_speaker is not None:
            chosen = nearest_speaker
        elif prev_speaker is not None and (w_start - prev_end) <= 0.200:
            chosen = prev_speaker
        else:
            chosen = "UNKNOWN"

        new_w = dict(w, speaker=chosen)
        result.append(new_w)
        prev_speaker = chosen
        prev_end = w_end

    return result


def smooth_micro_turns(
    words: list[dict[str, Any]],
    *,
    max_run_length: int = DEFAULT_MICRO_TURN_MAX_WORDS,
) -> list[dict[str, Any]]:
    """Relabel isolated micro-turns to the surrounding speaker.

    If a run of *max_run_length* or fewer consecutive words is assigned to
    speaker A, but both the preceding and following runs belong to speaker B,
    the short run is relabelled to B.  This removes the most common
    ping-pong artefacts (e.g. "uh" wrongly flipping speakers).

    Returns a new list of word dicts (shallow copies).
    """
    if len(words) < 3:
        return [dict(w) for w in words]

    # Build runs: list of (speaker, start_idx, length)
    runs: list[tuple[str, int, int]] = []
    i = 0
    while i < len(words):
        spk = words[i].get("speaker", "UNKNOWN")
        j = i + 1
        while j < len(words) and words[j].get("speaker", "UNKNOWN") == spk:
            j += 1
        runs.append((spk, i, j - i))
        i = j

    # Identify runs to relabel
    relabel: dict[int, str] = {}  # word_index -> new_speaker
    for r_idx in range(1, len(runs) - 1):
        spk, start_idx, length = runs[r_idx]
        if length > max_run_length:
            continue
        prev_spk = runs[r_idx - 1][0]
        next_spk = runs[r_idx + 1][0]
        if prev_spk == next_spk and prev_spk != spk:
            for wi in range(start_idx, start_idx + length):
                relabel[wi] = prev_spk

    result = []
    for idx, w in enumerate(words):
        if idx in relabel:
            result.append(dict(w, speaker=relabel[idx]))
        else:
            result.append(dict(w))
    return result


def merge_diarization_with_words(
    words: list[dict[str, Any]],
    diarization_segments: list[dict[str, Any]],
    *,
    word_padding_s: float = DEFAULT_WORD_PADDING_S,
    nearest_turn_tolerance_s: float = DEFAULT_NEAREST_TURN_TOLERANCE_S,
    smooth: bool = True,
    max_smooth_run: int = DEFAULT_MICRO_TURN_MAX_WORDS,
) -> list[dict[str, Any]]:
    """Full merge pipeline: assign speakers then optionally smooth.

    Convenience wrapper combining :func:`assign_speakers_to_words` and
    :func:`smooth_micro_turns`.
    """
    labelled = assign_speakers_to_words(
        words,
        diarization_segments,
        word_padding_s=word_padding_s,
        nearest_turn_tolerance_s=nearest_turn_tolerance_s,
    )
    if smooth and len(labelled) >= 3:
        labelled = smooth_micro_turns(labelled, max_run_length=max_smooth_run)
    return labelled


def build_speaker_segments(
    words: list[dict[str, Any]],
    diarization_segments: list[dict[str, Any]],
    *,
    word_padding_s: float = DEFAULT_WORD_PADDING_S,
    nearest_turn_tolerance_s: float = DEFAULT_NEAREST_TURN_TOLERANCE_S,
    smooth: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Build speaker-attributed segments and words for API responses.

    Returns:
        Tuple of (segments, words, num_speakers) where:
        - segments: list of dicts with ``text``, ``start``, ``end``, ``speaker``,
          ``words`` (the words belonging to that segment)
        - words: flat list of word dicts with ``speaker`` assigned
        - num_speakers: number of distinct speakers found
    """
    labelled_words = merge_diarization_with_words(
        words,
        diarization_segments,
        word_padding_s=word_padding_s,
        nearest_turn_tolerance_s=nearest_turn_tolerance_s,
        smooth=smooth,
    )

    if not labelled_words:
        return [], [], 0

    # Group words into contiguous speaker runs to form segments
    segments: list[dict[str, Any]] = []
    speakers: set[str] = set()
    current_speaker: str | None = None
    current_words: list[dict[str, Any]] = []

    for w in labelled_words:
        spk = w.get("speaker", "UNKNOWN")
        if spk != current_speaker and current_words:
            # Flush previous segment
            seg_text = " ".join(str(cw.get("word", "")).strip() for cw in current_words).strip()
            segments.append(
                {
                    "text": seg_text,
                    "start": round(
                        current_words[0].get("start", current_words[0].get("start_time", 0.0)), 3
                    ),
                    "end": round(
                        current_words[-1].get("end", current_words[-1].get("end_time", 0.0)), 3
                    ),
                    "speaker": current_speaker,
                    "words": current_words,
                }
            )
            current_words = []
        current_speaker = spk
        speakers.add(spk)
        current_words.append(w)

    # Flush final segment
    if current_words:
        seg_text = " ".join(str(cw.get("word", "")).strip() for cw in current_words).strip()
        segments.append(
            {
                "text": seg_text,
                "start": round(
                    current_words[0].get("start", current_words[0].get("start_time", 0.0)), 3
                ),
                "end": round(
                    current_words[-1].get("end", current_words[-1].get("end_time", 0.0)), 3
                ),
                "speaker": current_speaker,
                "words": current_words,
            }
        )

    speakers.discard("UNKNOWN")
    return segments, labelled_words, len(speakers)


def build_speaker_segments_nowords(
    stt_segments: list[dict[str, Any]],
    diar_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build speaker-attributed segments when word timestamps are unavailable.

    Falls back to proportional text distribution based on overlap duration
    between STT segments and diarization turns.  Each STT segment's text is
    split across overlapping diarization turns proportional to their duration
    overlap.  When only a single speaker overlaps a segment the whole text is
    assigned directly.

    Args:
        stt_segments: Transcription segments with ``text``, ``start``, ``end``
            (no ``words``).
        diar_segments: Diarization turns with ``speaker``, ``start``, ``end``.

    Returns:
        List of dicts with ``text``, ``start``, ``end``, ``speaker``.
    """
    if not stt_segments or not diar_segments:
        return []

    result_segments: list[dict[str, Any]] = []

    for stt_seg in stt_segments:
        seg_start = float(stt_seg.get("start", 0.0))
        seg_end = float(stt_seg.get("end", 0.0))
        seg_text = str(stt_seg.get("text", "")).strip()

        if not seg_text:
            continue

        # Find overlapping diarization segments and compute overlap durations
        overlaps: list[tuple[dict[str, Any], float]] = []
        for diar_seg in diar_segments:
            d_start = float(diar_seg.get("start", 0.0))
            d_end = float(diar_seg.get("end", 0.0))
            overlap_start = max(seg_start, d_start)
            overlap_end = min(seg_end, d_end)
            overlap_dur = overlap_end - overlap_start
            if overlap_dur > 0:
                overlaps.append((diar_seg, overlap_dur))

        if not overlaps:
            # No diarization coverage — keep text without speaker
            result_segments.append(
                {
                    "text": seg_text,
                    "start": round(seg_start, 3),
                    "end": round(seg_end, 3),
                    "speaker": "UNKNOWN",
                }
            )
            continue

        if len(overlaps) == 1:
            diar_seg, _ = overlaps[0]
            d_start = float(diar_seg.get("start", 0.0))
            d_end = float(diar_seg.get("end", 0.0))
            result_segments.append(
                {
                    "text": seg_text,
                    "start": round(max(seg_start, d_start), 3),
                    "end": round(min(seg_end, d_end), 3),
                    "speaker": diar_seg.get("speaker", "UNKNOWN"),
                }
            )
            continue

        # Multiple speakers — distribute text proportionally by overlap duration
        total_overlap = sum(dur for _, dur in overlaps)
        words = seg_text.split()
        n_words = len(words)

        word_idx = 0
        for i, (diar_seg, dur) in enumerate(overlaps):
            if word_idx >= n_words:
                break

            d_start = float(diar_seg.get("start", 0.0))
            d_end = float(diar_seg.get("end", 0.0))

            # Last overlap gets remaining words to avoid rounding errors
            if i == len(overlaps) - 1:
                chunk_words = words[word_idx:]
            else:
                fraction = dur / total_overlap
                n_chunk = max(1, round(fraction * n_words))
                chunk_words = words[word_idx : word_idx + n_chunk]
                word_idx += len(chunk_words)

            if not chunk_words:
                continue

            result_segments.append(
                {
                    "text": " ".join(chunk_words),
                    "start": round(max(seg_start, d_start), 3),
                    "end": round(min(seg_end, d_end), 3),
                    "speaker": diar_seg.get("speaker", "UNKNOWN"),
                }
            )

    return result_segments
