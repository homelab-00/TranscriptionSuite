"""Streaming SHA-256 helper tests (Issue #104, Story 2.2).

Verifies that ``server.core.audio_utils.sha256_streaming`` produces the same
digest as a one-shot ``hashlib.sha256(open(p, 'rb').read())`` call but
without holding the full file in memory.
"""

from __future__ import annotations

import hashlib
import os
import tracemalloc
from pathlib import Path

import pytest
from server.core.audio_utils import _SHA256_CHUNK_BYTES, sha256_streaming


@pytest.fixture()
def tiny_file(tmp_path: Path) -> Path:
    """64-byte file — smaller than the chunk size."""
    p = tmp_path / "tiny.bin"
    p.write_bytes(b"abc" * 21 + b"d")
    return p


@pytest.fixture()
def multi_chunk_file(tmp_path: Path) -> Path:
    """5 MiB of pseudo-random bytes — straddles 5 chunk boundaries."""
    p = tmp_path / "five_mib.bin"
    # Deterministic content — same input → same hash → reproducible test.
    data = bytes((i * 31 + 7) & 0xFF for i in range(5 * 1024 * 1024))
    p.write_bytes(data)
    return p


def _one_shot_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ──────────────────────────────────────────────────────────────────────────
# Correctness — match one-shot hashlib
# ──────────────────────────────────────────────────────────────────────────


def test_streaming_matches_one_shot_for_tiny_file(tiny_file: Path) -> None:
    assert sha256_streaming(tiny_file) == _one_shot_hash(tiny_file)


def test_streaming_matches_one_shot_for_multi_chunk_file(
    multi_chunk_file: Path,
) -> None:
    assert sha256_streaming(multi_chunk_file) == _one_shot_hash(multi_chunk_file)


def test_streaming_handles_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.bin"
    p.write_bytes(b"")
    # SHA-256 of empty input is well-known
    assert sha256_streaming(p) == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_streaming_accepts_str_path(multi_chunk_file: Path) -> None:
    assert sha256_streaming(str(multi_chunk_file)) == _one_shot_hash(multi_chunk_file)


# ──────────────────────────────────────────────────────────────────────────
# Memory bound — peak allocation stays near the chunk size, not file size
# ──────────────────────────────────────────────────────────────────────────


def test_streaming_memory_bound_under_chunk_plus_overhead(
    multi_chunk_file: Path,
) -> None:
    """Peak Python-allocated bytes during the hash should be well under
    the file size — proving the streaming pattern doesn't materialize the
    full file. We allow a generous margin (10× the chunk size) to absorb
    interpreter overhead unrelated to the buffer.
    """
    tracemalloc.start()
    try:
        sha256_streaming(multi_chunk_file)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    file_size = os.path.getsize(multi_chunk_file)
    # Peak should be far less than the file size — the whole point of
    # streaming. 10× chunk size = 10 MiB ceiling for a 5 MiB file.
    assert peak < _SHA256_CHUNK_BYTES * 10, (
        f"peak={peak}, chunk={_SHA256_CHUNK_BYTES}, file={file_size}"
    )
    # And much less than the file itself (which would imply we read it
    # whole into memory).
    assert peak < file_size
