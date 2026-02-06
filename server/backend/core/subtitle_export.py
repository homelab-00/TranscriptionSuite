"""
Subtitle export helpers for Audio Notebook transcription exports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

MAX_CUE_DURATION = 5.0
MIN_CUE_DURATION = 0.7
WORD_GAP_SPLIT = 0.8
MAX_CUE_CHARS = 84
PREFERRED_LINE_CHARS = 42
PUNCT_SPLIT = {".", "?", "!"}

_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(slots=True)
class SubtitleCue:
    start: float
    end: float
    text: str
    speaker: str | None = None


def normalize_speaker_labels(raw_labels_in_order: Iterable[str]) -> dict[str, str]:
    """Map raw diarization labels to Speaker 1/2/... by first appearance."""
    mapping: dict[str, str] = {}
    next_index = 1
    for raw_label in raw_labels_in_order:
        label = _normalize_label(raw_label)
        if not label:
            continue
        if label not in mapping:
            mapping[label] = f"Speaker {next_index}"
            next_index += 1
    return mapping


def build_subtitle_cues(
    segments: list[dict[str, Any]],
    words: list[dict[str, Any]],
    has_diarization: bool,
) -> list[SubtitleCue]:
    """Build readable subtitle cues from words (preferred) or segments."""
    sorted_segments = sorted(
        segments,
        key=lambda seg: (
            _to_int(seg.get("segment_index"), default=0),
            _to_float(seg.get("start_time"), default=0.0),
        ),
    )

    segment_speaker_by_id: dict[int, str] = {}
    for seg in sorted_segments:
        seg_id = _to_int(seg.get("id"))
        if seg_id is None:
            continue
        raw_speaker = _normalize_label(seg.get("speaker"))
        if raw_speaker:
            segment_speaker_by_id[seg_id] = raw_speaker

    sorted_words = sorted(
        words,
        key=lambda word: (
            _to_float(word.get("start_time", word.get("start")), default=0.0),
            _to_float(word.get("end_time", word.get("end")), default=0.0),
        ),
    )

    raw_speaker_order: list[str] = []
    if has_diarization:
        if sorted_words:
            for word in sorted_words:
                seg_id = _to_int(word.get("segment_id"))
                if seg_id is None:
                    continue
                raw = segment_speaker_by_id.get(seg_id)
                if raw:
                    raw_speaker_order.append(raw)
        else:
            for seg in sorted_segments:
                raw = _normalize_label(seg.get("speaker"))
                if raw:
                    raw_speaker_order.append(raw)
    normalized_speakers = normalize_speaker_labels(raw_speaker_order)

    if sorted_words:
        return _build_word_cues(
            sorted_words=sorted_words,
            normalized_speakers=normalized_speakers,
            segment_speaker_by_id=segment_speaker_by_id,
            has_diarization=has_diarization,
        )
    return _build_segment_cues(
        sorted_segments=sorted_segments,
        normalized_speakers=normalized_speakers,
        has_diarization=has_diarization,
    )


def render_srt(cues: list[SubtitleCue]) -> str:
    """Render subtitle cues into SRT format."""
    lines: list[str] = []
    for index, cue in enumerate(cues, start=1):
        lines.append(str(index))
        lines.append(
            f"{_format_srt_timestamp(cue.start)} --> {_format_srt_timestamp(cue.end)}"
        )
        lines.append(cue.text)
        lines.append("")
    return "\n".join(lines)


def render_ass(cues: list[SubtitleCue], title: str) -> str:
    """Render subtitle cues into ASS format."""
    safe_title = _collapse_whitespace(title).replace("\n", " ").strip() or "Export"

    lines = [
        "[Script Info]",
        f"Title: {safe_title}",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Arial,42,&H00FFFFFF,&H0000FFFF,&H001A1A1A,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,24,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for cue in cues:
        text = _escape_ass_text(cue.text)
        lines.append(
            "Dialogue: 0,"
            f"{_format_ass_timestamp(cue.start)},"
            f"{_format_ass_timestamp(cue.end)},"
            f"Default,,0,0,0,,{text}"
        )

    return "\n".join(lines)


def _build_word_cues(
    sorted_words: list[dict[str, Any]],
    normalized_speakers: dict[str, str],
    segment_speaker_by_id: dict[int, str],
    has_diarization: bool,
) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    current_words: list[str] = []
    current_start = 0.0
    current_end = 0.0
    current_speaker: str | None = None

    def flush_current() -> None:
        nonlocal current_words, current_start, current_end, current_speaker
        if not current_words:
            return

        cue_text = _format_cue_text(" ".join(current_words), current_speaker)
        current_words = []

        if not cue_text:
            current_start = 0.0
            current_end = 0.0
            current_speaker = None
            return

        cue_start, cue_end = _normalize_cue_times(current_start, current_end)
        cues.append(
            SubtitleCue(
                start=cue_start,
                end=cue_end,
                text=cue_text,
                speaker=current_speaker,
            )
        )

        current_start = 0.0
        current_end = 0.0
        current_speaker = None

    for word in sorted_words:
        word_text = _collapse_whitespace(str(word.get("word", "")).strip())
        if not word_text:
            continue

        start = _to_float(word.get("start_time", word.get("start")), default=0.0)
        end = _to_float(word.get("end_time", word.get("end")), default=start)
        if end < start:
            end = start

        speaker: str | None = None
        if has_diarization:
            seg_id = _to_int(word.get("segment_id"))
            if seg_id is not None:
                raw_speaker = segment_speaker_by_id.get(seg_id)
                if raw_speaker:
                    speaker = normalized_speakers.get(raw_speaker)

        if not current_words:
            current_words = [word_text]
            current_start = start
            current_end = end
            current_speaker = speaker
        else:
            current_duration = current_end - current_start
            gap = max(0.0, start - current_end)
            projected_chars = len(" ".join(current_words)) + 1 + len(word_text)

            should_split = False
            if speaker != current_speaker:
                should_split = True
            elif gap > WORD_GAP_SPLIT and current_duration >= MIN_CUE_DURATION:
                should_split = True
            elif (
                projected_chars > MAX_CUE_CHARS and current_duration >= MIN_CUE_DURATION
            ):
                should_split = True
            elif end - current_start > MAX_CUE_DURATION:
                should_split = True

            if should_split:
                flush_current()
                current_words = [word_text]
                current_start = start
                current_end = end
                current_speaker = speaker
            else:
                current_words.append(word_text)
                current_end = end

        current_duration = current_end - current_start
        if (
            current_words
            and _ends_with_split_punctuation(current_words[-1])
            and current_duration >= 1.2
        ):
            flush_current()

    flush_current()
    return cues


def _build_segment_cues(
    sorted_segments: list[dict[str, Any]],
    normalized_speakers: dict[str, str],
    has_diarization: bool,
) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    for seg in sorted_segments:
        raw_text = str(seg.get("text", "")).strip()
        text = _collapse_whitespace(raw_text)
        if not text:
            continue

        speaker: str | None = None
        if has_diarization:
            raw_speaker = _normalize_label(seg.get("speaker"))
            if raw_speaker:
                speaker = normalized_speakers.get(raw_speaker)

        cue_text = _format_cue_text(text, speaker)
        if not cue_text:
            continue

        start = _to_float(seg.get("start_time"), default=0.0)
        end = _to_float(seg.get("end_time"), default=start)
        cue_start, cue_end = _normalize_cue_times(start, end)

        cues.append(
            SubtitleCue(
                start=cue_start,
                end=cue_end,
                text=cue_text,
                speaker=speaker,
            )
        )
    return cues


def _format_cue_text(text: str, speaker: str | None) -> str:
    normalized_text = _collapse_whitespace(text)
    if not normalized_text:
        return ""
    prefixed = f"{speaker}: {normalized_text}" if speaker else normalized_text
    return _wrap_text(prefixed, PREFERRED_LINE_CHARS)


def _normalize_cue_times(start: float, end: float) -> tuple[float, float]:
    safe_start = max(0.0, start)
    safe_end = max(0.0, end)
    if safe_end <= safe_start:
        safe_end = safe_start + 0.1
    return safe_start, safe_end


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_ass_timestamp(seconds: float) -> str:
    total_cs = max(0, int(round(seconds * 100)))
    hours, rem = divmod(total_cs, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, centis = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _escape_ass_text(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("{", r"\{").replace("}", r"\}")
    return escaped.replace("\n", r"\N")


def _wrap_text(text: str, max_chars: int) -> str:
    words = text.split()
    if not words:
        return ""

    lines: list[str] = []
    current_line = words[0]

    for word in words[1:]:
        if len(current_line) + 1 + len(word) <= max_chars:
            current_line = f"{current_line} {word}"
        else:
            lines.append(current_line)
            current_line = word

    lines.append(current_line)
    return "\n".join(lines)


def _collapse_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _normalize_label(value: Any) -> str:
    return _collapse_whitespace(str(value)) if value is not None else ""


def _ends_with_split_punctuation(word: str) -> bool:
    stripped = word.rstrip()
    return bool(stripped) and stripped[-1] in PUNCT_SPLIT


def _to_float(value: Any, default: float | None = None) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        if default is None:
            return 0.0
        return default


def _to_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
