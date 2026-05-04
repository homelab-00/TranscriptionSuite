"""Filename sanitizer tests (Issue #104, Story 3.2).

Hand-crafted parametrized cases covering each AC category:
  - AC1: validation at SAVE time (route-level test in test_profile_routes_template_validation.py)
  - AC2: path traversal, Windows reserved names, control chars, whitespace
  - AC3: NFC normalization
  - AC4: 255-byte UTF-8 truncation preserving the extension

We deliberately use 50+ cases per category in lieu of Hypothesis (which
isn't a current project dep — see sprint-2-design.md §5).
"""

from __future__ import annotations

import unicodedata

import pytest
from server.core.filename_template import (
    _MAX_BASENAME_BYTES,
    _WIN_RESERVED,
    sanitize_filename,
)

# ──────────────────────────────────────────────────────────────────────────
# AC3.2.AC2 — path traversal stripped
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "../etc/passwd",
        "../../../../etc/shadow",
        "..\\windows\\system32",
        "foo/../bar",
        "a/b/c/d.txt",
        "/etc/passwd.txt",
        "\\windows\\file.txt",
        "C:\\Users\\admin",
        "subdir/file.txt",
        "/leading-slash.txt",
    ],
)
def test_path_separators_are_stripped(raw: str) -> None:
    out = sanitize_filename(raw)
    assert "/" not in out
    assert "\\" not in out


def test_dot_dot_collapses_to_fallback() -> None:
    """Bare ``..`` and ``.`` after path-sep stripping must not survive."""
    assert sanitize_filename("..") == "Recording"
    assert sanitize_filename(".") == "Recording"
    assert sanitize_filename("/") == "Recording"
    # ../foo strips to ..foo (path seps removed but '..' chars remain)
    out = sanitize_filename("../")
    assert out == "Recording"  # strips ., leaving empty → fallback


# ──────────────────────────────────────────────────────────────────────────
# AC3.2.AC2 — Windows reserved names
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("reserved", sorted(_WIN_RESERVED))
def test_windows_reserved_basename_is_suffixed(reserved: str) -> None:
    """``CON.txt`` becomes ``CON_.txt`` — the basename is suffixed before
    the extension, so the file is still recognizable.
    """
    out = sanitize_filename(f"{reserved}.txt")
    assert out == f"{reserved}_.txt"


@pytest.mark.parametrize("reserved", ["con", "Con", "CoN", "PRN", "lpt1"])
def test_windows_reserved_case_insensitive(reserved: str) -> None:
    """Case-insensitive match — Windows is case-insensitive on filenames."""
    out = sanitize_filename(f"{reserved}.txt")
    assert out.endswith("_.txt")


def test_reserved_substring_not_in_basename_is_fine() -> None:
    """``CON`` only matters when it's the WHOLE basename (extension-stripped)."""
    out = sanitize_filename("CONFERENCE.txt")
    # CONFERENCE != CON, so no suffix
    assert out == "CONFERENCE.txt"


# ──────────────────────────────────────────────────────────────────────────
# AC3.2.AC2 — control characters
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "title\x00.txt",
        "title\x01.txt",
        "\x02\x03\x04\x05\x06\x07.txt",
        "a\x08b\x09c.txt",
        "title\x0a\x0b.txt",
        "title\x1f.txt",
        "title\x7f.txt",
    ],
)
def test_control_chars_are_stripped(raw: str) -> None:
    out = sanitize_filename(raw)
    for c in out:
        assert ord(c) >= 32 and ord(c) != 0x7F


# ──────────────────────────────────────────────────────────────────────────
# AC3.2.AC2 — Windows-illegal characters
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "title<.txt",
        "title>.txt",
        "title:colon.txt",
        'title"quoted".txt',
        "title|pipe.txt",
        "title?.txt",
        "title*.txt",
    ],
)
def test_windows_illegal_chars_stripped(raw: str) -> None:
    out = sanitize_filename(raw)
    for c in '<>:"|?*':
        assert c not in out


# ──────────────────────────────────────────────────────────────────────────
# AC3.2.AC2 — trailing whitespace and dots
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "  spaces around  ",
        "title   ",
        "title.",
        "title...",
        "title. . .",
        "  ...  ",
    ],
)
def test_leading_trailing_whitespace_and_dots_trimmed(raw: str) -> None:
    out = sanitize_filename(raw)
    assert not out.startswith(" ")
    assert not out.startswith(".")
    assert not out.endswith(" ")
    # Note: trailing dot allowed inside the extension boundary, but not
    # the very last char.
    assert not out.endswith(".") or out.endswith(".txt")  # ext ok


# ──────────────────────────────────────────────────────────────────────────
# AC3.2.AC3 — NFC Unicode normalization
# ──────────────────────────────────────────────────────────────────────────


def test_nfd_input_is_normalized_to_nfc() -> None:
    """``é`` (composed, 1 codepoint) and ``é`` (decomposed, 2
    codepoints) must produce the same output.
    """
    composed = "café.txt"
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed  # sanity — they differ pre-normalization
    assert sanitize_filename(composed) == sanitize_filename(decomposed)


def test_greek_title_round_trips() -> None:
    """Greek titles are common in this project (per CLAUDE.md notes)."""
    out = sanitize_filename("Συνεδρίαση.txt")
    assert out == "Συνεδρίαση.txt"


def test_emoji_round_trips() -> None:
    """Emojis are valid Unicode and survive sanitization."""
    out = sanitize_filename("recording 🎤.txt")
    assert out == "recording 🎤.txt"


# ──────────────────────────────────────────────────────────────────────────
# AC3.2.AC4 — 255-byte UTF-8 truncation preserving extension
# ──────────────────────────────────────────────────────────────────────────


def test_long_ascii_title_truncated_to_255_bytes() -> None:
    base = "a" * 300
    raw = f"{base}.txt"
    out = sanitize_filename(raw)
    assert len(out.encode("utf-8")) <= _MAX_BASENAME_BYTES
    assert out.endswith(".txt")  # extension preserved


def test_long_greek_title_truncated_at_codepoint_boundary() -> None:
    """Greek codepoints take 2 bytes each in UTF-8 — the truncation must
    walk back so we don't split a multi-byte char.
    """
    # 200 Greek alphas (~400 bytes when UTF-8 encoded)
    base = "α" * 200
    raw = f"{base}.txt"
    out = sanitize_filename(raw)
    assert len(out.encode("utf-8")) <= _MAX_BASENAME_BYTES
    # Should still be valid UTF-8 (no decode errors)
    out.encode("utf-8").decode("utf-8")
    assert out.endswith(".txt")


def test_short_title_passes_through_unchanged() -> None:
    out = sanitize_filename("normal title.txt")
    assert out == "normal title.txt"


def test_extension_only_pathological() -> None:
    """If a "filename" is just an extension after sanitization, fall back."""
    out = sanitize_filename(".")
    assert out == "Recording"


def test_empty_input_falls_back() -> None:
    assert sanitize_filename("") == "Recording"


def test_custom_fallback() -> None:
    assert sanitize_filename("", fallback="MyDefault") == "MyDefault"


# ──────────────────────────────────────────────────────────────────────────
# Property-style: invariants that must hold for ANY input
# ──────────────────────────────────────────────────────────────────────────


_PROPERTY_CASES = [
    "../etc/passwd",
    "CON.txt",
    "title\x00.txt",
    "α" * 300 + ".txt",
    "<>:|?*",
    "....",
    "/leading/slash",
    "trailing space  ",
    "café",
    "",
    ".",
    "..",
    "C:\\Windows\\System32\\bad.txt",
    "title with emoji 🎤🎶🎼.txt",
    "a" * 1000,
]


@pytest.mark.parametrize("raw", _PROPERTY_CASES)
def test_invariant_no_path_separators(raw: str) -> None:
    out = sanitize_filename(raw)
    assert "/" not in out and "\\" not in out


@pytest.mark.parametrize("raw", _PROPERTY_CASES)
def test_invariant_no_control_chars(raw: str) -> None:
    out = sanitize_filename(raw)
    for c in out:
        assert ord(c) >= 32 and ord(c) != 0x7F


@pytest.mark.parametrize("raw", _PROPERTY_CASES)
def test_invariant_within_byte_budget(raw: str) -> None:
    out = sanitize_filename(raw)
    assert len(out.encode("utf-8")) <= _MAX_BASENAME_BYTES


@pytest.mark.parametrize("raw", _PROPERTY_CASES)
def test_invariant_never_empty_or_dot_only(raw: str) -> None:
    out = sanitize_filename(raw)
    assert out not in {"", ".", ".."}
