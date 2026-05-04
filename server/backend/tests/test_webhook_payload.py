"""Webhook payload v1 (Issue #104, Story 7.6 / FR46 / R-EL31)."""

from __future__ import annotations

import logging

import pytest
from server.core.webhook_payload import (
    LARGE_PAYLOAD_WARN_BYTES,
    PAYLOAD_VERSION,
    WEBHOOK_VERSION,
    build_payload,
)


def test_default_metadata_only_payload_shape() -> None:
    """AC1 — exact key set when no transcript is opted in."""
    body = build_payload(recording_id=42, profile_id=7, summary_present=True)
    assert set(body.keys()) == {
        "event",
        "recording_id",
        "profile_id",
        "transcript_url",
        "summary_url",
        "payload_version",
        "webhook_version",
        "timestamp_iso",
    }
    assert "transcript_text" not in body


def test_event_is_transcription_completed() -> None:
    body = build_payload(recording_id=1, profile_id=None, summary_present=False)
    assert body["event"] == "transcription.completed"


def test_payload_version_is_string_1_0() -> None:
    body = build_payload(recording_id=1, profile_id=None, summary_present=False)
    assert body["payload_version"] == PAYLOAD_VERSION == "1.0"
    assert isinstance(body["payload_version"], str)


def test_webhook_version_is_int_1() -> None:
    """Forward-compat envelope — integer field separate from payload_version string."""
    body = build_payload(recording_id=1, profile_id=None, summary_present=False)
    assert body["webhook_version"] == WEBHOOK_VERSION == 1
    assert isinstance(body["webhook_version"], int)


def test_summary_url_null_when_summary_absent() -> None:
    body = build_payload(recording_id=1, profile_id=None, summary_present=False)
    assert body["summary_url"] is None


def test_summary_url_set_when_summary_present() -> None:
    body = build_payload(recording_id=42, profile_id=None, summary_present=True)
    assert body["summary_url"] == "/api/notebook/recordings/42"


def test_transcript_url_pattern() -> None:
    body = build_payload(recording_id=42, profile_id=None, summary_present=False)
    assert body["transcript_url"] == "/api/notebook/recordings/42/segments"


def test_timestamp_iso_is_utc() -> None:
    body = build_payload(recording_id=1, profile_id=None, summary_present=False)
    iso = body["timestamp_iso"]
    # ISO8601 UTC ends with +00:00 (datetime.isoformat) or 'Z' (rare).
    assert iso.endswith("+00:00") or iso.endswith("Z")


def test_profile_id_passthrough() -> None:
    body = build_payload(recording_id=1, profile_id=99, summary_present=False)
    assert body["profile_id"] == 99


def test_profile_id_can_be_none() -> None:
    """ON DELETE SET NULL — profile may have been deleted before delivery."""
    body = build_payload(recording_id=1, profile_id=None, summary_present=False)
    assert body["profile_id"] is None


# ──────────────────────────────────────────────────────────────────────────
# Opt-in transcript text (AC2)
# ──────────────────────────────────────────────────────────────────────────


def test_opt_in_transcript_text_added_to_body() -> None:
    body = build_payload(
        recording_id=1,
        profile_id=None,
        summary_present=False,
        transcript_text="hello world",
    )
    assert body["transcript_text"] == "hello world"


def test_empty_string_transcript_still_added() -> None:
    """Empty != None — empty is a valid (but degenerate) transcript."""
    body = build_payload(recording_id=1, profile_id=None, summary_present=False, transcript_text="")
    assert body["transcript_text"] == ""


def test_large_transcript_warns(caplog: pytest.LogCaptureFixture) -> None:
    """AC2 — payloads > 1 MB log a warning (delivery still proceeds)."""
    big = "x" * (LARGE_PAYLOAD_WARN_BYTES + 100)
    with caplog.at_level(logging.WARNING):
        build_payload(
            recording_id=42,
            profile_id=None,
            summary_present=False,
            transcript_text=big,
        )
    assert any(
        "Large webhook payload" in record.message and "42" in record.message
        for record in caplog.records
    )


def test_just_under_threshold_does_not_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    small = "x" * (LARGE_PAYLOAD_WARN_BYTES - 100)
    with caplog.at_level(logging.WARNING):
        build_payload(
            recording_id=1,
            profile_id=None,
            summary_present=False,
            transcript_text=small,
        )
    assert not any("Large webhook payload" in r.message for r in caplog.records)
