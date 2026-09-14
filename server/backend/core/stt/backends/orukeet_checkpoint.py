"""Resolve the pinned Orukeet NeMo checkpoint using the standard Hub cache."""

import hashlib
from pathlib import Path

ORUKEET_REPO_ID = "oruk/orukeet"
ORUKEET_REVISION = "555136b50265a132d4cea0d35560c26fc4f657ab"
ORUKEET_FILENAME = "orukeet-v0.1.0.nemo"
ORUKEET_SHA256 = "031c8ddab4845aeced904a7cde8e8aa57993b2e344716cf83a545b079c473b56"


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
    with Path(checkpoint).open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != ORUKEET_SHA256:
        raise ValueError(
            "Orukeet checkpoint checksum mismatch; remove the corrupted cached file and retry"
        )
    return checkpoint
