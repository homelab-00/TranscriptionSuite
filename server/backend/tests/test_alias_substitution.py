"""Tests for server.core.alias_substitution (Issue #104).

Covers Story 4.4 (view rendering source-of-truth), Story 5.1
(propagation to exports), Story 5.2 (LLM prompt builder).
"""

from __future__ import annotations

from server.core.alias_substitution import (
    apply_aliases,
    build_speaker_label_map,
    speaker_key_preface,
)

# ──────────────────────────────────────────────────────────────────────────
# build_speaker_label_map
# ──────────────────────────────────────────────────────────────────────────


def test_build_label_map_empty():
    assert build_speaker_label_map([], {}) == {}


def test_build_label_map_first_appearance_order_no_aliases():
    segs = [
        {"speaker": "SPEAKER_01"},
        {"speaker": "SPEAKER_00"},
        {"speaker": "SPEAKER_01"},  # duplicate — counter does not advance
        {"speaker": "SPEAKER_02"},
    ]
    assert build_speaker_label_map(segs, {}) == {
        "SPEAKER_01": "Speaker 1",
        "SPEAKER_00": "Speaker 2",
        "SPEAKER_02": "Speaker 3",
    }


def test_build_label_map_alias_overrides_default():
    segs = [
        {"speaker": "SPEAKER_00"},
        {"speaker": "SPEAKER_01"},
        {"speaker": "SPEAKER_02"},
    ]
    aliases = {"SPEAKER_00": "Elena Vasquez", "SPEAKER_02": "Sami Patel"}
    assert build_speaker_label_map(segs, aliases) == {
        "SPEAKER_00": "Elena Vasquez",
        "SPEAKER_01": "Speaker 1",  # SPEAKER_00 took alias, counter for unaliased starts at 1
        "SPEAKER_02": "Sami Patel",
    }


def test_build_label_map_skips_segments_without_speaker():
    segs = [{"speaker": None}, {"speaker": ""}, {"speaker": "SPEAKER_00"}]
    assert build_speaker_label_map(segs, {}) == {"SPEAKER_00": "Speaker 1"}


def test_build_label_map_verbatim_alias_name():
    """R-EL3: alias_name is passed through unchanged."""
    aliases = {"SPEAKER_00": "Dr. María José García-López"}
    segs = [{"speaker": "SPEAKER_00"}]
    out = build_speaker_label_map(segs, aliases)
    assert out["SPEAKER_00"] == "Dr. María José García-López"
    assert out["SPEAKER_00"].encode("utf-8") == "Dr. María José García-López".encode()


# ──────────────────────────────────────────────────────────────────────────
# apply_aliases
# ──────────────────────────────────────────────────────────────────────────


def test_apply_aliases_substitutes_at_read_time():
    segs = [
        {"speaker": "SPEAKER_00", "text": "Hello"},
        {"speaker": "SPEAKER_01", "text": "Hi there"},
        {"speaker": "SPEAKER_00", "text": "Welcome"},
    ]
    out = list(apply_aliases(segs, {"SPEAKER_00": "Elena", "SPEAKER_01": "Marco"}))
    assert [(s["speaker"], s["text"]) for s in out] == [
        ("Elena", "Hello"),
        ("Marco", "Hi there"),
        ("Elena", "Welcome"),
    ]


def test_apply_aliases_does_not_mutate_input():
    """The stored transcript MUST stay untouched (R-EL3)."""
    original = [{"speaker": "SPEAKER_00", "text": "Hello"}]
    list(apply_aliases(original, {"SPEAKER_00": "Elena"}))
    assert original == [{"speaker": "SPEAKER_00", "text": "Hello"}]


def test_apply_aliases_falls_back_to_default_label():
    segs = [{"speaker": "SPEAKER_00"}, {"speaker": "SPEAKER_01"}]
    out = list(apply_aliases(segs, {"SPEAKER_00": "Elena"}))
    assert out[0]["speaker"] == "Elena"
    assert out[1]["speaker"] == "Speaker 1"


def test_apply_aliases_preserves_other_fields():
    segs = [
        {"speaker": "SPEAKER_00", "text": "Hi", "start_time": 0.0, "end_time": 1.5},
    ]
    out = list(apply_aliases(segs, {"SPEAKER_00": "Elena"}))
    assert out[0] == {"speaker": "Elena", "text": "Hi", "start_time": 0.0, "end_time": 1.5}


def test_apply_aliases_is_lazy():
    """Lazy generator — does not materialize the full list (NFR48 RAM bound)."""
    segs = ({"speaker": f"SPEAKER_{i:02d}", "text": f"Turn {i}"} for i in range(3))
    aliases = {"SPEAKER_00": "Elena"}
    gen = apply_aliases(segs, aliases)
    assert hasattr(gen, "__next__")  # is an iterator
    first = next(gen)
    assert first["speaker"] == "Elena"


# ──────────────────────────────────────────────────────────────────────────
# speaker_key_preface
# ──────────────────────────────────────────────────────────────────────────


def test_speaker_key_preface_empty():
    assert speaker_key_preface({}, []) == ""


def test_speaker_key_preface_all_aliased():
    aliases = {"SPEAKER_00": "Elena", "SPEAKER_01": "Marco"}
    raw_order = ["SPEAKER_00", "SPEAKER_01"]
    out = speaker_key_preface(aliases, raw_order)
    assert out == "Speakers in this transcript: Elena (SPEAKER_00), Marco (SPEAKER_01)."


def test_speaker_key_preface_mixed():
    """Aliased speakers appear first in raw_order; unaliased get sequential numbering."""
    aliases = {"SPEAKER_00": "Elena", "SPEAKER_02": "Sami"}
    raw_order = ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]
    out = speaker_key_preface(aliases, raw_order)
    assert (
        out
        == "Speakers in this transcript: Elena (SPEAKER_00), Speaker 1 (SPEAKER_01 — unaliased), Sami (SPEAKER_02)."
    )


def test_speaker_key_preface_dedupes_raw_order():
    aliases = {"SPEAKER_00": "Elena"}
    raw_order = ["SPEAKER_00", "SPEAKER_00", "SPEAKER_01"]
    out = speaker_key_preface(aliases, raw_order)
    assert (
        out
        == "Speakers in this transcript: Elena (SPEAKER_00), Speaker 1 (SPEAKER_01 — unaliased)."
    )


def test_speaker_key_preface_verbatim_alias():
    """R-EL3: alias names are preserved verbatim in the prompt preamble."""
    aliases = {"SPEAKER_00": "Dr. María José García-López"}
    out = speaker_key_preface(aliases, ["SPEAKER_00"])
    assert "Dr. María José García-López (SPEAKER_00)" in out
