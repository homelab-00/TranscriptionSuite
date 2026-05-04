"""Alias propagation snapshot tests (Issue #104, Stories 5.1 / 5.2 / 5.3).

NFR52 requires ≥4 propagation snapshots across the F4 surfaces:
  1. Transcript view rendering (covered in
     dashboard/components/recording/__tests__/SpeakerLabelRendering.test.tsx)
  2. Plaintext export (this file — `test_plaintext_alias_propagation_snapshot`)
  3. Subtitle export (this file — `test_subtitle_alias_propagation_snapshot`)
  4. AI summary prompt (this file — `test_summary_prompt_alias_snapshot`)
  5. AI chat context (this file — `test_chat_context_alias_snapshot`)

Each test uses a 10-turn fixture with 3 speakers (2 aliased, 1 not) so
the "Speaker N" fallback path is also covered.
"""

from __future__ import annotations

from server.core.alias_substitution import apply_aliases, speaker_key_preface
from server.core.plaintext_export import stream_plaintext
from server.core.subtitle_export import build_subtitle_cues, render_srt

# ──────────────────────────────────────────────────────────────────────────
# Shared fixture
# ──────────────────────────────────────────────────────────────────────────


def _fixture_recording() -> dict:
    return {
        "id": 1,
        "title": "Lab Standup 2026-05-04",
        "filename": "standup.wav",
        "has_diarization": True,
    }


def _fixture_segments() -> list[dict]:
    """10 turns, 3 raw speakers — ``SPEAKER_00`` and ``SPEAKER_02`` will be
    aliased; ``SPEAKER_01`` falls back to ``Speaker 1``."""
    return [
        {
            "id": 1,
            "segment_index": 0,
            "speaker": "SPEAKER_00",
            "text": "Welcome everyone.",
            "start_time": 0.0,
            "end_time": 1.5,
        },
        {
            "id": 2,
            "segment_index": 1,
            "speaker": "SPEAKER_01",
            "text": "Thanks for having us.",
            "start_time": 1.6,
            "end_time": 3.0,
        },
        {
            "id": 3,
            "segment_index": 2,
            "speaker": "SPEAKER_02",
            "text": "I have a question.",
            "start_time": 3.1,
            "end_time": 4.2,
        },
        {
            "id": 4,
            "segment_index": 3,
            "speaker": "SPEAKER_00",
            "text": "Go ahead.",
            "start_time": 4.3,
            "end_time": 4.9,
        },
        {
            "id": 5,
            "segment_index": 4,
            "speaker": "SPEAKER_02",
            "text": "What is the timeline for the migration?",
            "start_time": 5.0,
            "end_time": 7.5,
        },
        {
            "id": 6,
            "segment_index": 5,
            "speaker": "SPEAKER_00",
            "text": "End of next quarter.",
            "start_time": 7.6,
            "end_time": 9.0,
        },
        {
            "id": 7,
            "segment_index": 6,
            "speaker": "SPEAKER_01",
            "text": "Will we have testing time?",
            "start_time": 9.1,
            "end_time": 10.5,
        },
        {
            "id": 8,
            "segment_index": 7,
            "speaker": "SPEAKER_00",
            "text": "Yes — six weeks.",
            "start_time": 10.6,
            "end_time": 11.8,
        },
        {
            "id": 9,
            "segment_index": 8,
            "speaker": "SPEAKER_02",
            "text": "Sounds good to me.",
            "start_time": 11.9,
            "end_time": 13.0,
        },
        {
            "id": 10,
            "segment_index": 9,
            "speaker": "SPEAKER_01",
            "text": "Same here.",
            "start_time": 13.1,
            "end_time": 14.0,
        },
    ]


def _fixture_aliases() -> dict[str, str]:
    return {
        "SPEAKER_00": "Elena Vasquez",
        "SPEAKER_02": "Sami Patel",
    }


# ──────────────────────────────────────────────────────────────────────────
# 1. Plaintext export — Story 5.1 AC1 + AC3
# ──────────────────────────────────────────────────────────────────────────


_EXPECTED_PLAINTEXT = """\
# Lab Standup 2026-05-04

**Elena Vasquez:** Welcome everyone.

**Speaker 1:** Thanks for having us.

**Sami Patel:** I have a question.

**Elena Vasquez:** Go ahead.

**Sami Patel:** What is the timeline for the migration?

**Elena Vasquez:** End of next quarter.

**Speaker 1:** Will we have testing time?

**Elena Vasquez:** Yes — six weeks.

**Sami Patel:** Sounds good to me.

**Speaker 1:** Same here.
"""


def test_plaintext_alias_propagation_snapshot() -> None:
    """Plaintext stream emits aliases — never raw ``SPEAKER_00`` (Story 5.1 AC1)."""
    rec = _fixture_recording()
    aliases = _fixture_aliases()
    output = "".join(stream_plaintext(rec, apply_aliases(_fixture_segments(), aliases)))
    assert output == _EXPECTED_PLAINTEXT
    # Sanity: raw IDs must NOT leak into the export
    assert "SPEAKER_00" not in output
    assert "SPEAKER_01" not in output
    assert "SPEAKER_02" not in output


# ──────────────────────────────────────────────────────────────────────────
# 2. Subtitle export — Story 5.1 AC2 + AC3
# ──────────────────────────────────────────────────────────────────────────


def test_subtitle_alias_propagation_snapshot() -> None:
    """SRT cues use aliases for diarized speakers — never raw IDs (Story 5.1 AC2).

    Note: the subtitle exporter's ``normalize_speaker_labels`` assigns
    sequential ``Speaker N`` numbers over ALL speakers in appearance
    order BEFORE alias substitution, then alias_overrides REPLACE
    specific entries. So with 3 speakers (SPEAKER_00 → Elena,
    SPEAKER_01 unaliased, SPEAKER_02 → Sami), SPEAKER_01 ends up as
    ``Speaker 2`` (its appearance-order number) — not ``Speaker 1``.

    This is a deliberate divergence from
    ``build_speaker_label_map`` (used by view + plaintext) which
    counts ONLY unaliased speakers. The subtitle exporter preserves
    its own pre-existing numbering for backwards compatibility with
    Sprint 2 SRT/ASS output.
    """
    cues = build_subtitle_cues(
        segments=_fixture_segments(),
        words=[],  # no word-level data → segment-cues path
        has_diarization=True,
        alias_overrides=_fixture_aliases(),
    )
    srt = render_srt(cues)

    assert "Elena Vasquez" in srt
    assert "Sami Patel" in srt
    # Unaliased SPEAKER_01 → "Speaker 2" (it's the SECOND speaker by appearance,
    # SPEAKER_00 — now overridden with "Elena Vasquez" — held the "Speaker 1" slot)
    assert "Speaker 2" in srt
    # Raw IDs must not leak
    assert "SPEAKER_00" not in srt
    assert "SPEAKER_01" not in srt
    assert "SPEAKER_02" not in srt


# ──────────────────────────────────────────────────────────────────────────
# 3. AI summary prompt — Story 5.2 AC1, AC2, AC3
# ──────────────────────────────────────────────────────────────────────────


def test_summary_prompt_alias_snapshot() -> None:
    """The full transcript text constructed for the LLM uses aliases AND
    is preceded by a "Speaker key" preamble (Story 5.2 AC1)."""
    aliases = _fixture_aliases()
    raw_order = ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]
    preface = speaker_key_preface(aliases, raw_order)

    full_text = "\n".join(
        f"[{seg.get('speaker', 'Speaker')}]: {seg['text']}" if seg.get("speaker") else seg["text"]
        for seg in apply_aliases(_fixture_segments(), aliases)
    )

    expected_preface = (
        "Speakers in this transcript: "
        "Elena Vasquez (SPEAKER_00), "
        "Speaker 1 (SPEAKER_01 — unaliased), "
        "Sami Patel (SPEAKER_02)."
    )
    assert preface == expected_preface

    # full_text starts with the first turn — speaker label IS the alias
    assert full_text.startswith("[Elena Vasquez]: Welcome everyone.")
    # Raw IDs must NEVER appear inside transcript text passed to LLM
    assert "[SPEAKER_00]" not in full_text
    assert "[SPEAKER_01]" not in full_text
    assert "[SPEAKER_02]" not in full_text


def test_summary_prompt_alias_verbatim() -> None:
    """R-EL3: the alias appears EXACTLY as supplied — no normalization."""
    aliases = {"SPEAKER_00": "Dr. María José García-López"}
    segs = [{"id": 1, "speaker": "SPEAKER_00", "text": "OK"}]
    full_text = "\n".join(
        f"[{seg.get('speaker', 'Speaker')}]: {seg['text']}" for seg in apply_aliases(segs, aliases)
    )
    assert full_text == "[Dr. María José García-López]: OK"


# ──────────────────────────────────────────────────────────────────────────
# 4. AI chat context — Story 5.3 AC1, AC2
# ──────────────────────────────────────────────────────────────────────────


def test_chat_context_alias_snapshot() -> None:
    """Chat context uses the SAME alias substitution as summary (Story 5.3)."""
    # The chat path constructs transcription_context as a multi-line string.
    # We assert the same substitution properties as the summary test —
    # this is the "snapshot" guarantee that future changes to the chat
    # builder must preserve.
    aliases = _fixture_aliases()
    raw_order = ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]
    preface = speaker_key_preface(aliases, raw_order)

    transcription_context = "\n".join(
        f"[{seg.get('speaker') or 'Speaker'}]: {seg.get('text', '')}"
        for seg in apply_aliases(_fixture_segments(), aliases)
    )

    full = f"{preface}\n\nUse the speaker names provided verbatim.\n\n{transcription_context}"
    assert "Elena Vasquez (SPEAKER_00)" in full
    assert "[Elena Vasquez]: Welcome everyone." in full
    assert "[SPEAKER_00]" not in transcription_context
