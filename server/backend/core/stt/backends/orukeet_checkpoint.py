"""Resolve the pinned Orukeet NeMo checkpoint using the standard Hub cache."""

import hashlib
import os
import threading
from pathlib import Path

ORUKEET_REPO_ID = "oruk/orukeet"
ORUKEET_REVISION = "555136b50265a132d4cea0d35560c26fc4f657ab"
ORUKEET_FILENAME = "orukeet-v0.1.0.nemo"
ORUKEET_SHA256 = "031c8ddab4845aeced904a7cde8e8aa57993b2e344716cf83a545b079c473b56"

# Checkpoint files whose SHA-256 already matched in this process. Hashing the 2.5 GB
# checkpoint takes seconds and the backend reloads it on every Live Mode restore and
# lazy reload, so an unchanged file is hashed once per process. The key includes the
# stat fields that change when the file is replaced or rewritten, so a modified file
# is always hashed again. A failed check is never remembered.
_verified_checkpoints: set[tuple[str, str, int, int, int]] = set()
_verify_lock = threading.Lock()


def _sha256_file(path: str) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _verify_checksum(path: str) -> None:
    with _verify_lock:
        real_path = os.path.realpath(path)
        stat = os.stat(real_path)
        key = (ORUKEET_SHA256, real_path, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        if key in _verified_checkpoints:
            return
        if _sha256_file(real_path) != ORUKEET_SHA256:
            raise ValueError(
                "Orukeet checkpoint checksum mismatch; remove the corrupted cached file and retry"
            )
        _verified_checkpoints.add(key)


def resolve_orukeet_checkpoint() -> str:
    """Download the selected release, reusing cached files when available.

    A failed checksum or restore must not fall back to an unpinned model.
    """
    from huggingface_hub import hf_hub_download

    checkpoint = hf_hub_download(
        repo_id=ORUKEET_REPO_ID,
        filename=ORUKEET_FILENAME,
        revision=ORUKEET_REVISION,
    )
    _verify_checksum(checkpoint)
    return checkpoint
