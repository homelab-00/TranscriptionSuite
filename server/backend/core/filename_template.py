"""Filename template engine + sanitizer (Issue #104, Stories 3.1 + 3.2).

The engine renders ``{placeholder}`` tokens against a recording-like dict
and pass-throughs unknown placeholders verbatim. Adding a new placeholder
is a one-line change to ``PLACEHOLDER_RESOLVERS`` (AC3.1.AC2 extensibility).

The sanitizer makes any rendered string safe to write as a filename on
Linux, macOS, and Windows: NFC-normalized, control chars stripped, path
separators removed, Windows reserved names suffixed, and 255-byte UTF-8
truncation that walks back to a valid codepoint boundary.

Cross-references:
  - FR12 (template configurability)
  - FR13 (live preview consumes ``render``)
  - FR15 (sane defaults — see ``DEFAULT_TEMPLATE``)
  - NFR14 (filesystem safety)
  - R-EL2 (extensible placeholder grammar)
  - R-EL24 (reject malformed templates at SAVE time)
  - cross-feature constraint #4 (sanitization sits between engine and disk)

The frontend mirrors this resolver dict in
``dashboard/src/utils/filenameTemplate.ts``; a sync test asserts they
remain in lock-step.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

# ──────────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────────

DEFAULT_TEMPLATE = "{date} - {title}.txt"

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _coerce_date(raw: Any) -> str:
    """Best-effort YYYY-MM-DD from various input shapes (ISO string,
    datetime, None). Falls back to today's UTC date if parsing fails.
    """
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, str) and raw.strip():
        # Accept ``2026-05-08T12:00:00Z`` / ``2026-05-08`` / etc.
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            # Already a date-only string?
            try:
                return datetime.strptime(raw[:10], "%Y-%m-%d").date().isoformat()
            except ValueError:
                pass
    return datetime.now(UTC).date().isoformat()


PLACEHOLDER_RESOLVERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "date": lambda r: _coerce_date(r.get("recorded_at") or r.get("created_at")),
    "title": lambda r: str(r.get("title") or r.get("filename") or "Recording"),
    "recording_id": lambda r: str(r.get("id") or r.get("recording_id") or ""),
    "model": lambda r: str(r.get("model_id") or r.get("model") or "model"),
}


def render(template: str, recording: dict[str, Any]) -> str:
    """Render ``template`` against ``recording``.

    Unknown placeholders pass through as literal text including the braces
    — the validation step (``find_unknown_placeholders``) is what rejects
    them at SAVE time. This split keeps the engine forward-compatible:
    a profile saved against a future schema_version with a new placeholder
    won't crash an older backend; it'll just render the literal token.
    """
    out: list[str] = []
    i = 0
    while i < len(template):
        if template[i] == "{":
            close = template.find("}", i + 1)
            if close == -1:
                # Unterminated — pass-through (validation is at SAVE)
                out.append(template[i:])
                break
            name = template[i + 1 : close]
            resolver = PLACEHOLDER_RESOLVERS.get(name)
            if resolver is None:
                # Pass-through literal — preserve braces around the name
                out.append(template[i : close + 1])
            else:
                out.append(resolver(recording))
            i = close + 1
        else:
            out.append(template[i])
            i += 1
    return "".join(out)


def find_unknown_placeholders(template: str) -> list[str]:
    """Return every ``{name}`` in ``template`` whose name is NOT a
    registered resolver. Used by Story 3.2's PUT validation and Story
    3.3's live preview to flag invalid templates BEFORE save.

    Note: unterminated braces (e.g. ``{date``) and malformed names (e.g.
    ``{2date}``) are silently ignored by the regex — they pass through
    ``render`` as literals and are not classified as "unknown placeholders".
    The regex requires the same identifier shape as Python: ``[a-z_][a-z0-9_]*``.
    """
    found = _PLACEHOLDER_RE.findall(template)
    return [n for n in found if n not in PLACEHOLDER_RESOLVERS]


# ──────────────────────────────────────────────────────────────────────────
# Sanitizer
# ──────────────────────────────────────────────────────────────────────────

_WIN_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{n}" for n in range(1, 10)),
        *(f"LPT{n}" for n in range(1, 10)),
    }
)
_CONTROL_CHARS = frozenset(chr(c) for c in range(32)) | {"\x7f"}
_PATH_SEPS = frozenset("/\\")
# Windows-illegal filename characters: < > : " | ? *
_WIN_ILLEGAL = frozenset('<>:"|?*')
_MAX_BASENAME_BYTES = 255  # POSIX/NTFS shared limit, applied to UTF-8 bytes


def sanitize_filename(rendered: str, *, fallback: str = "Recording") -> str:
    """Make ``rendered`` safe to write to disk on Linux/macOS/Windows.

    Pipeline order matters — see sprint-2-design.md §2.3 for the rationale:
      1. NFC-normalize (so byte-length checks count grapheme bytes correctly)
      2. Strip control characters
      3. Strip path separators (``/`` and ``\\``) BEFORE the ``..`` check so
         ``..\\foo`` is caught the same way as ``../foo``
      4. Strip Windows-illegal characters
      5. Trim leading/trailing whitespace AND dots (Windows rejects names
         ending in ``.`` or `` ``)
      6. Reject empty / ``.`` / ``..`` (collapse to fallback)
      7. If basename matches a Windows reserved name (case-insensitive,
         extension-stripped), suffix with ``_``
      8. UTF-8 byte-truncate basename to 255 bytes preserving extension
    """
    s = unicodedata.normalize("NFC", rendered)
    s = "".join(c for c in s if c not in _CONTROL_CHARS)
    s = "".join(c for c in s if c not in _PATH_SEPS)
    s = "".join(c for c in s if c not in _WIN_ILLEGAL)
    s = s.strip().strip(". ")
    if s in {"", ".", ".."}:
        s = fallback

    base, dot, ext = s.rpartition(".")
    if not dot:
        base, ext = s, ""
    if base.upper() in _WIN_RESERVED:
        base = base + "_"

    full = f"{base}.{ext}" if ext else base
    encoded = full.encode("utf-8")
    if len(encoded) <= _MAX_BASENAME_BYTES:
        return full

    # Truncate basename — preserve the extension. Walk back to a valid
    # UTF-8 boundary so a multi-byte codepoint isn't split.
    ext_bytes_len = len(f".{ext}".encode()) if ext else 0
    budget = _MAX_BASENAME_BYTES - ext_bytes_len
    if budget <= 0:
        # Pathological: extension itself is over the limit. Drop the
        # extension; fall back to truncating the entire string.
        truncated_bytes = encoded[:_MAX_BASENAME_BYTES]
        while truncated_bytes:
            try:
                return truncated_bytes.decode("utf-8")
            except UnicodeDecodeError:
                truncated_bytes = truncated_bytes[:-1]
        return fallback

    base_bytes = base.encode("utf-8")[:budget]
    while base_bytes:
        try:
            base_truncated = base_bytes.decode("utf-8")
            break
        except UnicodeDecodeError:
            base_bytes = base_bytes[:-1]
    else:
        base_truncated = fallback
    return f"{base_truncated}.{ext}" if ext else base_truncated


def render_and_sanitize(
    template: str, recording: dict[str, Any], *, fallback: str = "Recording"
) -> str:
    """Convenience: render then sanitize. Exported so callers don't need
    to chain the two steps consistently.
    """
    return sanitize_filename(render(template, recording), fallback=fallback)
