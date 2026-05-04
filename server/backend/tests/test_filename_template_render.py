"""Filename template engine tests (Issue #104, Story 3.1).

Covers:
  - AC1: base placeholders render correctly
  - AC2: extensible — registering a new resolver doesn't require engine
    code changes
  - AC3: unknown placeholders pass through as literal text

Uses ``frozen_clock``-style explicit timestamps via ``recorded_at`` so tests
are deterministic without monkey-patching ``datetime.now``.
"""

from __future__ import annotations

import pytest
from server.core.filename_template import (
    DEFAULT_TEMPLATE,
    PLACEHOLDER_RESOLVERS,
    find_unknown_placeholders,
    render,
)

SAMPLE_RECORDING = {
    "id": 42,
    "title": "language session",
    "model_id": "parakeet-tdt-0.6b-v2",
    "recorded_at": "2026-05-08T10:30:00Z",
}


# ──────────────────────────────────────────────────────────────────────────
# AC3.1.AC1 — base placeholders
# ──────────────────────────────────────────────────────────────────────────


def test_render_full_template() -> None:
    out = render("{date} {title} - {model}.txt", SAMPLE_RECORDING)
    assert out == "2026-05-08 language session - parakeet-tdt-0.6b-v2.txt"


def test_render_default_template() -> None:
    out = render(DEFAULT_TEMPLATE, SAMPLE_RECORDING)
    assert out == "2026-05-08 - language session.txt"


def test_render_recording_id() -> None:
    out = render("{recording_id}.txt", SAMPLE_RECORDING)
    assert out == "42.txt"


def test_render_falls_back_when_recorded_at_missing() -> None:
    """Date placeholder degrades to today's UTC date — never crashes."""
    rec = {"title": "x", "id": 1, "model_id": "m"}
    out = render("{date}.txt", rec)
    # Just assert the shape, since today's date varies in CI
    assert out.endswith(".txt")
    assert len(out) == len("YYYY-MM-DD.txt")


def test_render_title_falls_back_to_filename() -> None:
    rec = {"id": 1, "filename": "my-file.wav", "model_id": "m"}
    out = render("{title}.txt", rec)
    assert out == "my-file.wav.txt"


def test_render_title_falls_back_to_recording_default() -> None:
    rec = {"id": 1, "model_id": "m"}
    out = render("{title}.txt", rec)
    assert out == "Recording.txt"


# ──────────────────────────────────────────────────────────────────────────
# AC3.1.AC3 — unknown placeholders pass through
# ──────────────────────────────────────────────────────────────────────────


def test_unknown_placeholder_passes_through() -> None:
    out = render("{nonexistent}.txt", SAMPLE_RECORDING)
    assert out == "{nonexistent}.txt"


def test_mixed_known_and_unknown_placeholders() -> None:
    out = render("{date}-{unknown}-{title}.txt", SAMPLE_RECORDING)
    assert out == "2026-05-08-{unknown}-language session.txt"


def test_unterminated_brace_passes_through_as_literal() -> None:
    out = render("{date} {title", SAMPLE_RECORDING)
    assert out == "2026-05-08 {title"


def test_literal_text_with_no_placeholders() -> None:
    out = render("plain.txt", SAMPLE_RECORDING)
    assert out == "plain.txt"


# ──────────────────────────────────────────────────────────────────────────
# AC3.1.AC2 — extensibility (registering a new resolver works)
# ──────────────────────────────────────────────────────────────────────────


def test_register_new_placeholder_via_resolver_dict() -> None:
    """Adding a placeholder is a one-line change — no engine code needed.

    This test demonstrates Vassilis's J5 ask: register ``{audio_hash}``
    that emits the first 6 chars of the recording's audio_hash. The test
    restores the dict in cleanup so other tests don't see the new resolver.
    """
    sentinel_recording = {**SAMPLE_RECORDING, "audio_hash": "abcdef1234567890"}
    PLACEHOLDER_RESOLVERS["audio_hash"] = lambda r: str(r.get("audio_hash", ""))[:6]
    try:
        out = render("{audio_hash}-{title}.txt", sentinel_recording)
        assert out == "abcdef-language session.txt"
    finally:
        del PLACEHOLDER_RESOLVERS["audio_hash"]


# ──────────────────────────────────────────────────────────────────────────
# find_unknown_placeholders (Story 3.2 AC1 backbone)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("{date}.txt", []),
        ("{nonexistent}.txt", ["nonexistent"]),
        ("{date}-{title}.txt", []),
        ("{date}-{foo}-{bar}.txt", ["foo", "bar"]),
        ("plain text no placeholders.txt", []),
        # Unterminated braces are NOT classified as unknown (regex doesn't match)
        ("{date", []),
        # Numeric-prefixed names aren't valid identifiers — regex skips them
        ("{2date}.txt", []),
    ],
)
def test_find_unknown_placeholders(template: str, expected: list[str]) -> None:
    assert find_unknown_placeholders(template) == expected
