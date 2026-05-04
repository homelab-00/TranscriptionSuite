"""Webhook payload construction (Issue #104, Story 7.6 / FR46 / R-EL31).

The payload is metadata-default — only stable identifiers + URLs the
receiver can use to fetch the actual transcript on demand. The
``transcript_text`` field is opt-in per profile (``webhook_include_transcript_text``)
and includes the alias-substituted plaintext.

Two version fields are present:

  * ``payload_version`` — string, AC1-mandated. Future schema changes
    that are non-breaking land as ``"1.1"``, ``"1.2"``, etc.
  * ``webhook_version`` — integer, defensive forward-compat. A breaking
    schema change increments to ``2``; receivers must opt in.

The receiver is expected to know the server's base URL out-of-band (it
configured the webhook). URLs in the body are server-relative — the
receiver appends them to the base URL it has on file.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

PAYLOAD_VERSION = "1.0"
WEBHOOK_VERSION = 1

# Threshold above which we log an advisory warning. The payload still
# goes out as-is — this is just a "you might want to switch to URL fetch"
# nudge for the operator.
LARGE_PAYLOAD_WARN_BYTES = 1_048_576  # 1 MB


def build_payload(
    *,
    recording_id: int,
    profile_id: int | None,
    summary_present: bool,
    transcript_text: str | None = None,
) -> dict[str, Any]:
    """Construct the metadata-default payload, optionally with transcript text.

    Args:
        recording_id: The recording the event refers to.
        profile_id: Source profile that fired the webhook (None if profile
            was deleted before delivery — historical attempts persist via
            ``ON DELETE SET NULL``).
        summary_present: Whether the recording has a ``summary`` value.
            Determines whether ``summary_url`` is non-null.
        transcript_text: If supplied, the alias-substituted full plaintext
            is included as ``transcript_text``. ``None`` means metadata-only.
    """
    body: dict[str, Any] = {
        "event": "transcription.completed",
        "recording_id": recording_id,
        "profile_id": profile_id,
        "transcript_url": f"/api/notebook/recordings/{recording_id}/segments",
        "summary_url": (f"/api/notebook/recordings/{recording_id}" if summary_present else None),
        "payload_version": PAYLOAD_VERSION,
        "webhook_version": WEBHOOK_VERSION,
        "timestamp_iso": datetime.now(UTC).isoformat(),
    }
    if transcript_text is not None:
        body["transcript_text"] = transcript_text
        size_bytes = len(transcript_text.encode("utf-8"))
        if size_bytes > LARGE_PAYLOAD_WARN_BYTES:
            logger.warning(
                "Large webhook payload — recording_id=%d transcript_size_bytes=%d "
                "(consider URL fetch instead of inline transcript_text)",
                recording_id,
                size_bytes,
            )
    return body


__all__ = (
    "PAYLOAD_VERSION",
    "WEBHOOK_VERSION",
    "LARGE_PAYLOAD_WARN_BYTES",
    "build_payload",
)
