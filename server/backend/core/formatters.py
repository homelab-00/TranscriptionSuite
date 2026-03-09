"""OpenAI-compatible response formatters for transcription results."""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.core.subtitle_export import SubtitleCue, render_srt

if TYPE_CHECKING:
    from server.core.stt.engine import TranscriptionResult


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
    """Return the full OpenAI verbose_json shape with segments and optional words."""
    segments = []
    for idx, seg in enumerate(result.segments):
        segments.append(
            {
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
        )

    body: dict = {
        "task": task,
        "language": result.language or "en",
        "duration": result.duration,
        "text": result.text,
        "segments": segments,
    }

    if include_words:
        words = []
        for w in result.words:
            words.append(
                {
                    "word": w.get("word", w.get("text", "")),
                    "start": w.get("start_time", w.get("start", 0.0)),
                    "end": w.get("end_time", w.get("end", 0.0)),
                }
            )
        body["words"] = words

    return body


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
    """Convert engine segments into :class:`SubtitleCue` objects."""
    cues: list[SubtitleCue] = []
    for seg in result.segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        cues.append(
            SubtitleCue(
                start=seg.get("start_time", seg.get("start", 0.0)),
                end=seg.get("end_time", seg.get("end", 0.0)),
                text=text,
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
