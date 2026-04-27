"""Tests for the notebook audio route and the RFC 6266 Content-Disposition helper.

Covers Issue #106: audio playback for recordings with non-ASCII filenames
(Greek, Cyrillic, CJK) used to break because the 206 Range branch built
Content-Disposition with a raw f-string, which Uvicorn cannot encode as
Latin-1.
"""

from __future__ import annotations

import pytest
from server.api.routes import notebook

# ─── Helper unit tests ────────────────────────────────────────────────────


def test_content_disposition_ascii_only() -> None:
    """ASCII-only filenames keep the legacy filename= form intact."""
    cd = notebook._content_disposition("inline", "audio.mp3")
    assert 'filename="audio.mp3"' in cd
    assert "filename*=UTF-8''audio.mp3" in cd
    assert cd.startswith("inline; ")


def test_content_disposition_greek_filename() -> None:
    """Greek characters survive via percent-encoded UTF-8 form."""
    cd = notebook._content_disposition("inline", "γρηγόρης.mp3")
    # ASCII fallback replaces each non-ASCII codepoint with '?' (γρηγόρης = 8 letters).
    assert 'filename="????????.mp3"' in cd
    # UTF-8 form preserves the original via percent-encoding.
    assert "filename*=UTF-8''%CE%B3%CF%81%CE%B7%CE%B3%CF%8C%CF%81%CE%B7%CF%82.mp3" in cd
    # Header is Latin-1 safe (the fix's whole point).
    cd.encode("latin-1")


def test_content_disposition_cyrillic_filename() -> None:
    """Cyrillic characters round-trip through the UTF-8 form."""
    cd = notebook._content_disposition("attachment", "запись.mp3")
    assert "filename*=UTF-8''%D0%B7%D0%B0%D0%BF%D0%B8%D1%81%D1%8C.mp3" in cd
    cd.encode("latin-1")


def test_content_disposition_embedded_quote_and_newlines() -> None:
    """Quotes and CR/LF in the ASCII fallback are sanitized to underscores."""
    cd = notebook._content_disposition("attachment", 'foo"\r\nbar.mp3')
    assert 'filename="foo___bar.mp3"' in cd
    # UTF-8 form percent-encodes everything
    assert "filename*=UTF-8''foo%22%0D%0Abar.mp3" in cd


def test_content_disposition_empty_filename() -> None:
    """Empty filename yields a safe non-empty fallback ('audio') instead of crashing."""
    cd = notebook._content_disposition("inline", "")
    assert 'filename="audio"' in cd
    assert "filename*=UTF-8''audio" in cd


@pytest.mark.parametrize("bad_input", [None, "   ", "\t\n  ", b"bytes-not-str"])
def test_content_disposition_invalid_inputs_fall_back_safely(bad_input) -> None:
    """None, bytes, and whitespace-only inputs fall back to 'audio' without crashing."""
    cd = notebook._content_disposition("inline", bad_input)  # type: ignore[arg-type]
    assert 'filename="audio"' in cd
    assert "filename*=UTF-8''audio" in cd


def test_content_disposition_lone_surrogate_does_not_crash() -> None:
    """Lone surrogate codepoints (filesystems on Windows can leak these) are scrubbed,
    not propagated to quote() which would raise UnicodeEncodeError.
    """
    cd = notebook._content_disposition("inline", "broken\ud800name.mp3")
    # The lone surrogate is replaced (utf-8 "replace" yields U+FFFD), so quote() succeeds.
    assert "filename*=UTF-8''" in cd
    cd.encode("latin-1")  # the whole point: header must be Latin-1 safe.


def test_content_disposition_control_chars_and_backslash_scrubbed() -> None:
    """NUL, TAB, backslash, DEL — all C0/forbidden chars become '_' in the ASCII fallback."""
    cd = notebook._content_disposition("attachment", "a\x00b\tc\\d\x7fe.mp3")
    assert 'filename="a_b_c_d_e.mp3"' in cd
    cd.encode("latin-1")


# ─── Audio route tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audio_range_with_greek_filename(monkeypatch, tmp_path) -> None:
    """A 206 Range response succeeds for a Greek-named recording (regression for #106)."""
    audio_path = tmp_path / "γρηγόρης.mp3"
    payload = b"\xff\xfb\x90\x00" * 256  # 1024 bytes of plausible mp3 frame bytes
    audio_path.write_bytes(payload)

    recording = {
        "id": 1,
        "filename": "γρηγόρης.mp3",
        "filepath": str(audio_path),
    }
    monkeypatch.setattr(notebook, "get_recording", lambda recording_id: recording)

    response = await notebook.get_audio_file(1, range="bytes=0-1023")

    assert response.status_code == 206
    assert response.headers["Content-Range"] == f"bytes 0-1023/{len(payload)}"
    cd = response.headers["Content-Disposition"]
    assert "filename*=UTF-8''%CE%B3%CF%81%CE%B7%CE%B3%CF%8C%CF%81%CE%B7%CF%82.mp3" in cd
    assert 'filename="????????.mp3"' in cd
    # Header must encode under Latin-1 — that's what Uvicorn requires.
    cd.encode("latin-1")


@pytest.mark.asyncio
async def test_audio_range_with_ascii_filename_unchanged(monkeypatch, tmp_path) -> None:
    """ASCII filenames keep the same legacy filename="..." form (back-compat)."""
    audio_path = tmp_path / "audio.mp3"
    payload = b"\x00" * 2048
    audio_path.write_bytes(payload)

    recording = {
        "id": 7,
        "filename": "audio.mp3",
        "filepath": str(audio_path),
    }
    monkeypatch.setattr(notebook, "get_recording", lambda recording_id: recording)

    response = await notebook.get_audio_file(7, range="bytes=0-1023")

    assert response.status_code == 206
    cd = response.headers["Content-Disposition"]
    assert 'filename="audio.mp3"' in cd
    assert "filename*=UTF-8''audio.mp3" in cd
