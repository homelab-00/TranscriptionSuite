"""OpenAI-compatible response formatters for transcription results."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from server.core.subtitle_export import (
    SubtitleCue,
    normalize_speaker_labels,
    render_srt,
)

if TYPE_CHECKING:
    from server.core.stt.engine import TranscriptionResult


def _normalize_speaker_value(raw: Any) -> str | None:
    """Return ``None`` for missing / empty / ``"UNKNOWN"`` speaker labels.

    ``speaker_merge.build_speaker_segments_nowords`` uses ``"UNKNOWN"`` as a
    sentinel when it cannot attribute a segment. That sentinel must never
    reach a JSON response body: a truthy check on ``"UNKNOWN"`` would emit
    ``"speaker": "UNKNOWN"`` alongside ``"num_speakers": 0`` — a contradictory
    shape. Funnel every speaker-field access through this helper so both
    formatters agree on the policy.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.upper() == "UNKNOWN":
        return None
    return text


def format_json(result: TranscriptionResult) -> dict:
    """Return minimal ``{"text": "..."}`` shape."""
    return {"text": result.text}


def format_text(result: TranscriptionResult) -> str:
    """Return the transcribed text as a plain string."""
    return result.text


def format_verbose_json(
    result: TranscriptionResult,
    task: str = "transcribe",
    include_words: bool = False,
) -> dict:
    """Return the full OpenAI verbose_json shape with segments and optional words.

    When the upstream result carries speaker labels (because diarization ran),
    each segment gets a ``speaker`` field and the body carries ``num_speakers``.
    """
    segments = []
    for idx, seg in enumerate(result.segments):
        entry = {
            "id": idx,
            "seek": 0,
            "start": seg.get("start_time", seg.get("start", 0.0)),
            "end": seg.get("end_time", seg.get("end", 0.0)),
            "text": seg.get("text", ""),
            "tokens": [],
            "temperature": 0.0,
            "avg_logprob": 0.0,
            "compression_ratio": 0.0,
            "no_speech_prob": 0.0,
        }
        speaker = _normalize_speaker_value(seg.get("speaker"))
        if speaker:
            entry["speaker"] = speaker
        segments.append(entry)

    body: dict = {
        "task": task,
        "language": result.language or "en",
        "duration": result.duration,
        "text": result.text,
        "segments": segments,
    }

    if result.num_speakers:
        body["num_speakers"] = result.num_speakers

    if include_words:
        words = []
        for w in result.words:
            entry = {
                "word": w.get("word", w.get("text", "")),
                "start": w.get("start_time", w.get("start", 0.0)),
                "end": w.get("end_time", w.get("end", 0.0)),
            }
            speaker = _normalize_speaker_value(w.get("speaker"))
            if speaker:
                entry["speaker"] = speaker
            words.append(entry)
        body["words"] = words

    return body


def format_diarized_json(
    result: TranscriptionResult,
    task: str = "transcribe",
    include_words: bool = False,
) -> dict:
    """Return a compact speaker-grouped JSON body.

    Shape: ``{task, language, duration, text, num_speakers, segments}``.
    Each segment carries ``speaker``, ``start``, ``end``, ``text`` and
    optionally ``words`` when word-level timestamps were requested.

    This format is requested via ``response_format=diarized_json`` on the
    OpenAI-compatible audio routes. It is intentionally non-standard so that
    clients can opt into speaker grouping without disturbing OpenAI's own
    ``verbose_json`` contract.
    """
    segments: list[dict] = []
    # Index flat ``result.words`` by their start time so we can fall back to
    # slicing them into a segment when the backend didn't bubble per-segment
    # ``words`` up. Without this, clients that ask for word granularity on a
    # plain-transcription fallback silently get zero words back.
    flat_words = list(getattr(result, "words", None) or [])
    for seg in result.segments:
        seg_start = seg.get("start_time", seg.get("start", 0.0))
        seg_end = seg.get("end_time", seg.get("end", 0.0))
        entry: dict = {
            "start": seg_start,
            "end": seg_end,
            "text": seg.get("text", ""),
        }
        speaker = _normalize_speaker_value(seg.get("speaker"))
        if speaker:
            entry["speaker"] = speaker
        if include_words:
            nested = seg.get("words")
            if nested:
                word_source = nested
            else:
                word_source = [
                    w
                    for w in flat_words
                    if seg_start <= w.get("start_time", w.get("start", 0.0)) < seg_end
                ]
            seg_words: list[dict] = []
            for w in word_source:
                w_entry = {
                    "word": w.get("word", w.get("text", "")),
                    "start": w.get("start_time", w.get("start", 0.0)),
                    "end": w.get("end_time", w.get("end", 0.0)),
                }
                w_speaker = _normalize_speaker_value(w.get("speaker"))
                if w_speaker:
                    w_entry["speaker"] = w_speaker
                seg_words.append(w_entry)
            entry["words"] = seg_words
        segments.append(entry)

    return {
        "task": task,
        "language": result.language or "en",
        "duration": result.duration,
        "text": result.text,
        "num_speakers": result.num_speakers,
        "segments": segments,
    }


def format_srt(result: TranscriptionResult) -> str:
    """Render transcription result as SRT subtitle format."""
    cues = _result_to_cues(result)
    return render_srt(cues)


def format_vtt(result: TranscriptionResult) -> str:
    """Render transcription result as WebVTT subtitle format."""
    cues = _result_to_cues(result)
    return _render_vtt(cues)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _result_to_cues(result: TranscriptionResult) -> list[SubtitleCue]:
    """Convert engine segments into :class:`SubtitleCue` objects.

    When diarization ran, raw speaker labels (e.g. ``SPEAKER_00``) are
    normalized via the same helper the longform pipeline uses and baked into
    the cue text as a ``"LABEL: text"`` prefix. ``render_srt`` / ``render_vtt``
    dump ``cue.text`` verbatim, so baking the prefix here is what makes the
    subtitle output diarized.
    """
    raw_labels: list[str] = []
    for seg in result.segments:
        spk = _normalize_speaker_value(seg.get("speaker"))
        if spk:
            raw_labels.append(spk)
    label_map = normalize_speaker_labels(raw_labels) if raw_labels else {}

    cues: list[SubtitleCue] = []
    for seg in result.segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        raw_speaker = _normalize_speaker_value(seg.get("speaker"))
        display_speaker = label_map.get(raw_speaker) if raw_speaker else None
        cue_text = f"{display_speaker}: {text}" if display_speaker else text
        cues.append(
            SubtitleCue(
                start=seg.get("start_time", seg.get("start", 0.0)),
                end=seg.get("end_time", seg.get("end", 0.0)),
                text=cue_text,
                speaker=display_speaker,
            )
        )
    return cues


def _format_vtt_timestamp(seconds: float) -> str:
    """Convert seconds to VTT timestamp ``HH:MM:SS.mmm``."""
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def _render_vtt(cues: list[SubtitleCue]) -> str:
    """Render subtitle cues into WebVTT format."""
    lines: list[str] = ["WEBVTT", ""]
    for index, cue in enumerate(cues, start=1):
        lines.append(str(index))
        lines.append(f"{_format_vtt_timestamp(cue.start)} --> {_format_vtt_timestamp(cue.end)}")
        lines.append(cue.text)
        lines.append("")
    return "\n".join(lines)
