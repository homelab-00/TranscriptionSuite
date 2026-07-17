"""Tests for the LLM-based Greek final-sigma restoration (greek_sigma_llm.py).

On natural Greek speech the NeMo models emit NOTHING at final-sigma positions
(no recoverable unk marker - that only appears on unnaturally crisp synthetic
audio), so the marker repair in greek_sigma.py cannot help. The only robust
restoration is linguistic: ask the user's configured OpenAI-compatible LLM to
re-insert the sigmas, then accept its output through a deterministic guard
that permits exactly two per-word edits - append "ς", or turn a word-final
"σ" into "ς" - and discards everything else. Corruption is therefore
structurally impossible: the worst failure mode is "no repair".

Fixture strings are the user's real transcriptions from canary-1b-v2.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

import pytest
from server.core.stt import greek_sigma_llm
from server.core.stt.greek_sigma_llm import (
    apply_sigma_guard,
    repair_transcription_result,
)


@dataclass
class TranscriptionResult:
    """Minimal stand-in for engine.TranscriptionResult (avoids the ML import
    chain - same pattern as test_formatters.py). The repair module only uses
    attribute access and dataclasses.replace, so a structural twin suffices."""

    text: str
    language: str | None = None
    language_probability: float = 0.0
    duration: float = 0.0
    segments: list[dict[str, Any]] = field(default_factory=list)
    words: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Guard: the only edits that may survive are append-ς and final σ->ς
# ---------------------------------------------------------------------------


class TestApplySigmaGuard:
    def test_accepts_appended_sigmas(self):
        original = "Αυτό ο άντρα είναι πολύ ψηλό και γρήγορο."
        corrected = "Αυτός ο άντρας είναι πολύ ψηλός και γρήγορος."
        assert apply_sigma_guard(original, corrected) == corrected

    def test_accepts_final_sigma_normalisation(self):
        # Model occasionally writes a medial σ at word end.
        assert apply_sigma_guard("ο καλόσ φίλος", "ο καλός φίλος") == "ο καλός φίλος"

    def test_preserves_trailing_punctuation(self):
        assert apply_sigma_guard("γαλανό και καθαρό.", "γαλανός και καθαρός.") == (
            "γαλανός και καθαρός."
        )

    def test_rejects_punctuation_changes(self):
        # The LLM may not swap punctuation while appending the sigma.
        assert apply_sigma_guard("πολύ γρήγορο.", "πολύ γρήγορος!") == "πολύ γρήγορο."

    def test_rejects_word_rewrites_but_keeps_valid_edits(self):
        # "άντρα" -> "άνδρας" is a spelling change, not a sigma append: rejected.
        original = "Αυτό ο άντρα είναι ψηλό"
        corrected = "Αυτός ο άνδρας είναι ψηλός"
        assert apply_sigma_guard(original, corrected) == "Αυτός ο άντρα είναι ψηλός"

    def test_rejects_case_changes(self):
        assert apply_sigma_guard("αυτό ο άντρα", "Αυτός ο άντρας") == ("αυτό ο άντρας")

    def test_rejects_sigma_on_non_greek_words(self):
        assert apply_sigma_guard("ok τότε", "okς τότε") == "ok τότε"

    def test_rejects_token_count_mismatch_wholesale(self):
        assert apply_sigma_guard("ένα δύο τρία", "ένα δύο τρία τέσσερα") is None

    def test_identical_text_passes_through(self):
        text = "Καλημέρα σε όλους."
        assert apply_sigma_guard(text, text) == text


# ---------------------------------------------------------------------------
# Orchestrator: gating, propagation to segments/words, immutability
# ---------------------------------------------------------------------------


def _make_result() -> TranscriptionResult:
    return TranscriptionResult(
        text="Αυτό ο άντρα είναι πολύ ψηλό και γρήγορο.",
        language="el",
        language_probability=1.0,
        duration=10.0,
        segments=[
            {
                "text": "Αυτό ο άντρα είναι πολύ ψηλό και γρήγορο.",
                "start": 0.0,
                "end": 10.0,
                "duration": 10.0,
                "words": [
                    {"word": "Αυτό", "start": 0.0, "end": 0.5, "probability": 0.9},
                    {"word": "ο", "start": 0.5, "end": 0.6, "probability": 0.9},
                    {"word": "άντρα", "start": 0.6, "end": 1.1, "probability": 0.9},
                    {"word": "είναι", "start": 1.1, "end": 1.5, "probability": 0.9},
                    {"word": "πολύ", "start": 1.5, "end": 1.9, "probability": 0.9},
                    {"word": "ψηλό", "start": 1.9, "end": 2.4, "probability": 0.9},
                    {"word": "και", "start": 2.4, "end": 2.7, "probability": 0.9},
                    {"word": "γρήγορο.", "start": 2.7, "end": 3.3, "probability": 0.9},
                ],
            }
        ],
        words=[],
    )


@pytest.fixture()
def llm_spy(monkeypatch):
    calls: list[str] = []

    def fake_call(text: str) -> str | None:
        calls.append(text)
        return "Αυτός ο άντρας είναι πολύ ψηλός και γρήγορος."

    monkeypatch.setattr(greek_sigma_llm, "_call_llm", fake_call)
    monkeypatch.setattr(greek_sigma_llm, "_repair_enabled", lambda: True)
    return calls


class TestRepairTranscriptionResult:
    def test_repairs_text_segments_and_words(self, llm_spy):
        result = _make_result()
        result = dataclasses.replace(result, words=list(result.segments[0]["words"]))

        repaired = repair_transcription_result(result, backend_name="canary")

        assert repaired.text == "Αυτός ο άντρας είναι πολύ ψηλός και γρήγορος."
        assert repaired.segments[0]["text"] == ("Αυτός ο άντρας είναι πολύ ψηλός και γρήγορος.")
        repaired_words = [w["word"] for w in repaired.segments[0]["words"]]
        assert repaired_words == [
            "Αυτός",
            "ο",
            "άντρας",
            "είναι",
            "πολύ",
            "ψηλός",
            "και",
            "γρήγορος.",
        ]
        # Flat words list mirrors the per-segment dicts.
        assert [w["word"] for w in repaired.words] == repaired_words
        # Timing/probability metadata is preserved.
        assert repaired.segments[0]["words"][2]["start"] == 0.6
        assert repaired.segments[0]["words"][2]["probability"] == 0.9

    def test_input_result_not_mutated(self, llm_spy):
        result = _make_result()

        repair_transcription_result(result, backend_name="canary")

        assert result.text == "Αυτό ο άντρα είναι πολύ ψηλό και γρήγορο."
        assert result.segments[0]["words"][0]["word"] == "Αυτό"

    def test_parakeet_is_also_repaired(self, llm_spy):
        repaired = repair_transcription_result(_make_result(), backend_name="parakeet")
        assert repaired.text.endswith("γρήγορος.")

    def test_non_greek_language_skips_llm(self, llm_spy):
        result = dataclasses.replace(_make_result(), language="en")
        repaired = repair_transcription_result(result, backend_name="canary")
        assert repaired is result
        assert llm_spy == []

    def test_whisper_backend_skips_llm(self, llm_spy):
        result = _make_result()
        repaired = repair_transcription_result(result, backend_name="whisper")
        assert repaired is result
        assert llm_spy == []

    def test_disabled_config_skips_llm(self, monkeypatch, llm_spy):
        monkeypatch.setattr(greek_sigma_llm, "_repair_enabled", lambda: False)
        result = _make_result()
        repaired = repair_transcription_result(result, backend_name="canary")
        assert repaired is result
        assert llm_spy == []

    def test_empty_text_skips_llm(self, llm_spy):
        result = dataclasses.replace(_make_result(), text="", segments=[], words=[])
        repaired = repair_transcription_result(result, backend_name="canary")
        assert repaired is result
        assert llm_spy == []

    def test_llm_failure_keeps_original(self, monkeypatch):
        monkeypatch.setattr(greek_sigma_llm, "_call_llm", lambda text: None)
        monkeypatch.setattr(greek_sigma_llm, "_repair_enabled", lambda: True)
        result = _make_result()
        repaired = repair_transcription_result(result, backend_name="canary")
        assert repaired is result

    def test_garbage_llm_output_keeps_original(self, monkeypatch):
        monkeypatch.setattr(
            greek_sigma_llm,
            "_call_llm",
            lambda text: "Sure! Here is the corrected text you asked for.",
        )
        monkeypatch.setattr(greek_sigma_llm, "_repair_enabled", lambda: True)
        result = _make_result()
        repaired = repair_transcription_result(result, backend_name="canary")
        assert repaired is result


# ---------------------------------------------------------------------------
# Engine wiring: transcribe_file must route its result through the repair hook
# ---------------------------------------------------------------------------


class TestEngineWiring:
    def test_transcribe_file_source_calls_repair_hook(self):
        """Source-text check (same spirit as test_cancel_wiring): the
        transcribe_file body must invoke repair_transcription_result.
        find_spec locates engine.py without executing its ML import chain."""
        import importlib.util
        from pathlib import Path

        spec = importlib.util.find_spec("server.core.stt.engine")
        assert spec is not None and spec.origin
        source = Path(spec.origin).read_text(encoding="utf-8")
        transcribe_file_body = source.split("def transcribe_file", 1)[1]
        # Stop at the next method definition at class-body indentation.
        transcribe_file_body = transcribe_file_body.split("\n    def ", 1)[0]
        assert "repair_transcription_result" in transcribe_file_body
