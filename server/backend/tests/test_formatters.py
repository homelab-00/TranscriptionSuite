"""Tests for server.core.formatters — OpenAI-compatible response formatters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from server.core.formatters import (
    format_json,
    format_srt,
    format_text,
    format_verbose_json,
    format_vtt,
)


@dataclass
class _FakeResult:
    """Minimal stand-in for TranscriptionResult (avoids ML import chain)."""

    text: str = ""
    language: str | None = None
    language_probability: float = 0.0
    duration: float = 0.0
    segments: list[dict[str, Any]] = field(default_factory=list)
    words: list[dict[str, Any]] = field(default_factory=list)
    num_speakers: int = 0


def _make_result(**overrides) -> _FakeResult:
    defaults = {
        "text": "Hello world",
        "language": "en",
        "language_probability": 0.95,
        "duration": 3.5,
        "segments": [
            {"start_time": 0.0, "end_time": 1.5, "text": "Hello"},
            {"start_time": 1.5, "end_time": 3.5, "text": "world"},
        ],
        "words": [
            {"word": "Hello", "start_time": 0.0, "end_time": 1.0},
            {"word": "world", "start_time": 1.5, "end_time": 3.5},
        ],
    }
    defaults.update(overrides)
    return _FakeResult(**defaults)


# ── format_json ──────────────────────────────────────────────


def test_format_json_shape():
    result = _make_result()
    out = format_json(result)
    assert out == {"text": "Hello world"}


def test_format_json_empty_text():
    result = _make_result(text="")
    out = format_json(result)
    assert out == {"text": ""}


# ── format_text ──────────────────────────────────────────────


def test_format_text_returns_plain_string():
    result = _make_result()
    out = format_text(result)
    assert out == "Hello world"
    assert isinstance(out, str)


# ── format_verbose_json ──────────────────────────────────────


def test_format_verbose_json_basic():
    result = _make_result()
    out = format_verbose_json(result, task="transcribe")
    assert out["task"] == "transcribe"
    assert out["language"] == "en"
    assert out["duration"] == 3.5
    assert out["text"] == "Hello world"
    assert len(out["segments"]) == 2
    assert "words" not in out


def test_format_verbose_json_with_words():
    result = _make_result()
    out = format_verbose_json(result, task="transcribe", include_words=True)
    assert "words" in out
    assert len(out["words"]) == 2
    assert out["words"][0]["word"] == "Hello"
    assert out["words"][1]["start"] == 1.5


def test_format_verbose_json_segment_shape():
    result = _make_result()
    out = format_verbose_json(result)
    seg = out["segments"][0]
    assert seg["id"] == 0
    assert seg["start"] == 0.0
    assert seg["end"] == 1.5
    assert seg["text"] == "Hello"
    assert seg["tokens"] == []
    assert seg["temperature"] == 0.0
    assert seg["avg_logprob"] == 0.0
    assert seg["compression_ratio"] == 0.0
    assert seg["no_speech_prob"] == 0.0


def test_format_verbose_json_translate_task():
    result = _make_result()
    out = format_verbose_json(result, task="translate")
    assert out["task"] == "translate"


def test_format_verbose_json_defaults_language_to_en():
    result = _make_result(language=None)
    out = format_verbose_json(result)
    assert out["language"] == "en"


# ── format_srt ───────────────────────────────────────────────


def test_format_srt_output():
    result = _make_result()
    out = format_srt(result)
    assert out.startswith("1\n")
    assert "00:00:00,000 --> 00:00:01,500" in out
    assert "Hello" in out
    assert "00:00:01,500 --> 00:00:03,500" in out
    assert "world" in out


def test_format_srt_empty_segments():
    result = _make_result(segments=[])
    out = format_srt(result)
    assert out == ""


# ── format_vtt ───────────────────────────────────────────────


def test_format_vtt_output():
    result = _make_result()
    out = format_vtt(result)
    assert out.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:01.500" in out
    assert "Hello" in out
    assert "00:00:01.500 --> 00:00:03.500" in out
    assert "world" in out


def test_format_vtt_empty_segments():
    result = _make_result(segments=[])
    out = format_vtt(result)
    assert out == "WEBVTT\n"


def test_format_vtt_uses_dot_separator():
    """VTT uses '.' for milliseconds, not ',' like SRT."""
    result = _make_result()
    out = format_vtt(result)
    assert "." in out.split("-->")[0]
    assert "," not in out.split("-->")[0].split("\n")[-1]


# ── Edge cases ───────────────────────────────────────────────


def test_format_srt_skips_empty_text_segments():
    result = _make_result(
        segments=[
            {"start_time": 0.0, "end_time": 1.0, "text": "Hello"},
            {"start_time": 1.0, "end_time": 2.0, "text": "   "},
            {"start_time": 2.0, "end_time": 3.0, "text": "world"},
        ]
    )
    out = format_srt(result)
    # Only 2 cues (the whitespace-only segment is skipped)
    lines = [line for line in out.strip().split("\n\n") if line.strip()]
    assert len(lines) == 2


def test_format_zero_duration():
    result = _make_result(
        duration=0.0,
        segments=[{"start_time": 0.0, "end_time": 0.0, "text": "test"}],
    )
    out = format_verbose_json(result)
    assert out["duration"] == 0.0
    assert out["segments"][0]["start"] == 0.0
    assert out["segments"][0]["end"] == 0.0
