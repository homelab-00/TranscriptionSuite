"""Shared HTTP header helpers for the route modules.

Small, dependency-free utilities that more than one router needs. Kept
separate so a second caller never has to copy-paste a header builder whose
correctness is subtle (see ``_content_disposition`` and Issue #106).
"""

from urllib.parse import quote

# C0 control chars + backslash + quote violate RFC 7230 quoted-string rules.
_ASCII_FALLBACK_REPLACE = str.maketrans(
    {chr(c): "_" for c in range(0x20)} | {'"': "_", "\\": "_", "\x7f": "_"}
)


def _content_disposition(disposition: str, filename: str) -> str:
    """Build an RFC 6266 Content-Disposition value with both an ASCII
    fallback and a UTF-8 form so non-ASCII filenames (Greek, Cyrillic,
    CJK, etc.) survive Uvicorn's Latin-1 header encoding. Issue #106.
    """
    if not isinstance(filename, str) or not filename.strip():
        safe_name = "audio"
    else:
        # Round-trip through UTF-8 with replacement to scrub lone surrogates
        # that filesystems on some platforms leak; quote() would otherwise raise.
        safe_name = filename.encode("utf-8", "replace").decode("utf-8")
    ascii_fallback = (
        safe_name.encode("ascii", "replace").decode("ascii").translate(_ASCII_FALLBACK_REPLACE)
    )
    utf8_quoted = quote(safe_name, safe="")
    return f"{disposition}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{utf8_quoted}"
