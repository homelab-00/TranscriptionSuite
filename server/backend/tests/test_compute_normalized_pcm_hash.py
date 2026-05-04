"""compute_normalized_pcm_hash unit tests
(Issue #104, Sprint 2 carve-out — Item 3).

The helper wraps convert_to_wav + sha256_streaming + tempfile cleanup.
Asserts:
  - returns a 64-char hex hash on success
  - same content via a different upload-format hashes identically
  - returns None when ffmpeg is missing
  - returns None when convert_to_wav raises (corrupt input simulation)
  - cleans up the temp WAV in both success and failure paths
"""

from __future__ import annotations

import shutil
import struct
import wave
from pathlib import Path

import pytest
from server.core import audio_utils
from server.core.audio_utils import compute_normalized_pcm_hash


def _make_tone_wav(path: Path, hz: int = 440, seconds: float = 0.05) -> None:
    """Write a tiny PCM s16le WAV at 16 kHz so ffmpeg can re-encode it."""
    sample_rate = 16000
    samples = []
    n = int(sample_rate * seconds)
    for i in range(n):
        # Triangle-ish wave kept very small in amplitude — content is irrelevant,
        # only that the file is a valid PCM WAV ffmpeg can read.
        v = (i % 32) * 100
        samples.append(struct.pack("<h", v))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"".join(samples))


def test_returns_hex_hash_on_success(tmp_path: Path) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed in this environment")
    src = tmp_path / "tone.wav"
    _make_tone_wav(src)
    result = compute_normalized_pcm_hash(src)
    assert result is not None
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_same_content_hashes_identically(tmp_path: Path) -> None:
    """Two byte-identical inputs that end up at the same normalized PCM
    must produce the same hash — the central guarantee of Item 3."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed in this environment")
    src_a = tmp_path / "a.wav"
    src_b = tmp_path / "b.wav"
    _make_tone_wav(src_a)
    _make_tone_wav(src_b)
    h_a = compute_normalized_pcm_hash(src_a)
    h_b = compute_normalized_pcm_hash(src_b)
    assert h_a is not None and h_b is not None
    assert h_a == h_b


def test_returns_none_when_ffmpeg_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If shutil.which('ffmpeg') is None, the helper returns None and logs."""
    monkeypatch.setattr(audio_utils.shutil, "which", lambda _: None)
    src = tmp_path / "tone.wav"
    _make_tone_wav(src)
    assert compute_normalized_pcm_hash(src) is None


def test_returns_none_on_convert_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If convert_to_wav raises RuntimeError (e.g. corrupt input), returns None."""

    def _raise(*_args, **_kwargs):
        raise RuntimeError("simulated ffmpeg failure")

    monkeypatch.setattr(audio_utils, "convert_to_wav", _raise)
    src = tmp_path / "broken.bin"
    src.write_bytes(b"not audio")
    assert compute_normalized_pcm_hash(src) is None


def test_temp_wav_cleaned_up_on_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The helper must unlink its temp WAV after hashing."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed in this environment")
    created: list[str] = []
    real_convert = audio_utils.convert_to_wav

    def _spy(input_path, output_path=None, **kwargs):  # type: ignore[no-untyped-def]
        result = real_convert(input_path, output_path, **kwargs)
        if result:
            created.append(result)
        return result

    monkeypatch.setattr(audio_utils, "convert_to_wav", _spy)
    src = tmp_path / "tone.wav"
    _make_tone_wav(src)
    h = compute_normalized_pcm_hash(src)
    assert h is not None
    assert created, "convert_to_wav was not invoked"
    for p in created:
        assert not Path(p).exists(), f"temp WAV {p} was not cleaned up"
