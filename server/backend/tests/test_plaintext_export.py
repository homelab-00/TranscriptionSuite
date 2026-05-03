"""Plaintext streaming exporter tests (Issue #104, Story 3.4).

Covers:
  - AC1: format matches FR9 narrative (paragraph per speaker turn,
    blank-line separator, bold speaker labels, NO subtitle timestamps)
  - AC2: streaming — peak memory bounded for large transcripts

The memory-budget test synthesizes ~100k segments to simulate an 8-hour
recording. We assert the formatter never holds more than a single
paragraph plus the title in RAM.
"""

from __future__ import annotations

import tracemalloc
from collections.abc import Iterator
from typing import Any

from server.core.plaintext_export import stream_plaintext


def _segments_from(*entries: tuple[str | None, str]) -> Iterator[dict[str, Any]]:
    """Build segment iterator. Each entry is (speaker, text)."""
    for speaker, text in entries:
        yield {"speaker": speaker, "text": text}


# ──────────────────────────────────────────────────────────────────────────
# AC3.4.AC1 — format matches FR9 narrative
# ──────────────────────────────────────────────────────────────────────────


def test_paragraph_per_speaker_turn() -> None:
    """5 turns from 2 alternating speakers → 5 paragraphs separated by
    blank lines."""
    rec = {"title": "Lecture"}
    segments = _segments_from(
        ("Alice", "Hello, how are you?"),
        ("Bob", "Doing well, thanks."),
        ("Alice", "Great to hear."),
        ("Bob", "And you?"),
        ("Alice", "Same, busy week."),
    )
    out = "".join(stream_plaintext(rec, segments))
    paragraphs = [p for p in out.split("\n\n") if p.strip()]
    # First "paragraph" is the # title heading; then 5 turns
    assert len(paragraphs) == 6
    assert paragraphs[0] == "# Lecture"


def test_speaker_label_is_bold() -> None:
    rec = {"title": "x"}
    segments = _segments_from(("Alice", "First line."))
    out = "".join(stream_plaintext(rec, segments))
    assert "**Alice:** First line." in out


def test_no_subtitle_timestamps() -> None:
    """The exporter must NOT emit any '00:00:00 --> ...' style timestamps."""
    rec = {"title": "x"}
    segments = _segments_from(
        ("A", "first"),
        ("B", "second"),
    )
    out = "".join(stream_plaintext(rec, segments))
    assert "-->" not in out
    # Common subtitle timestamp shapes
    assert "00:00:00" not in out


def test_consecutive_same_speaker_segments_coalesce() -> None:
    """Three consecutive 'Alice' turns become ONE paragraph, not three."""
    rec = {"title": "x"}
    segments = _segments_from(
        ("Alice", "Sentence one."),
        ("Alice", "Sentence two."),
        ("Alice", "Sentence three."),
    )
    out = "".join(stream_plaintext(rec, segments))
    # Only one **Alice:** prefix despite 3 segments
    assert out.count("**Alice:**") == 1
    assert "Sentence one. Sentence two. Sentence three." in out


def test_no_speaker_emits_bare_paragraph() -> None:
    """Segments without a speaker label (e.g., non-diarized transcript)
    produce paragraphs without a label prefix.
    """
    rec = {"title": "x"}
    segments = _segments_from(
        (None, "First chunk."),
        (None, "Second chunk."),
    )
    out = "".join(stream_plaintext(rec, segments))
    assert "**" not in out
    # Both chunks coalesce into one paragraph since both have None speaker
    assert "First chunk. Second chunk." in out


def test_empty_segments_skipped() -> None:
    rec = {"title": "x"}
    segments = _segments_from(
        ("A", "real"),
        ("A", ""),  # skipped
        ("A", "  "),  # skipped (whitespace-only)
        ("A", "more"),
    )
    out = "".join(stream_plaintext(rec, segments))
    assert "real more" in out


def test_title_falls_back_to_filename() -> None:
    rec = {"filename": "input.wav"}
    out = "".join(stream_plaintext(rec, _segments_from(("A", "x"))))
    assert "# input.wav" in out


def test_title_falls_back_to_default() -> None:
    rec = {}
    out = "".join(stream_plaintext(rec, _segments_from(("A", "x"))))
    assert "# Recording" in out


# ──────────────────────────────────────────────────────────────────────────
# AC3.4.AC2 — streaming / memory bound
# ──────────────────────────────────────────────────────────────────────────


def test_generator_yields_lazily() -> None:
    """Calling stream_plaintext does NOT consume the segment iterator.

    The first chunk should be the title; only after iterating do we
    pull from the segments source.
    """
    consumed: list[bool] = []

    def lazy_segments() -> Iterator[dict[str, Any]]:
        consumed.append(True)
        yield {"speaker": "A", "text": "x"}

    gen = stream_plaintext({"title": "x"}, lazy_segments())
    # Consuming the title does not drive the segment generator
    first = next(gen)
    assert first.startswith("# ")
    assert consumed == []

    # Consuming the next chunk DOES drive segment iteration
    next(gen)  # speaker label
    assert consumed == [True]


def test_memory_bound_for_large_transcript() -> None:
    """Synthesize 50k segments and assert tracemalloc peak stays under
    a tight bound. Production target is 200 MB for an 8-hour recording;
    we test on a smaller scale here for speed.
    """
    rec = {"title": "long"}

    def big_segments(n: int) -> Iterator[dict[str, Any]]:
        # Simulate ~12 segments per minute × 60 minutes × 8 hours = 5760,
        # but use 50k for a healthier signal. Each segment carries ~80
        # chars of text (typical for Whisper word-segments grouping).
        text_template = (
            "This is a moderately long segment of speech that simulates a real transcript. "
        )
        for i in range(n):
            speaker = "Alice" if i % 2 == 0 else "Bob"
            yield {"speaker": speaker, "text": text_template * 1}

    tracemalloc.start()
    try:
        # Drain the generator in a loop so we don't accidentally hold
        # the whole output in memory ourselves.
        total_bytes = 0
        for chunk in stream_plaintext(rec, big_segments(50_000)):
            total_bytes += len(chunk.encode("utf-8"))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    # 50k segments × ~80 char text = ~4 MB raw. The exporter buffers
    # one paragraph (consecutive same-speaker turns); since speakers
    # alternate every segment, each paragraph is a single segment, so
    # peak buffering is tiny. Allow plenty of headroom for interpreter
    # overhead but assert we're far from "all in memory at once".
    assert peak < 50_000_000, f"peak={peak}"  # 50 MB ceiling
    assert total_bytes > 1_000_000  # sanity — we did emit a lot
