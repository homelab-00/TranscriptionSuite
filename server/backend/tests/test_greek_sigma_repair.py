"""Tests for the Greek final-sigma (ς) repair applied to NeMo Canary output.

``nvidia/canary-1b-v2`` and ``nvidia/parakeet-tdt-0.6b-v3`` were trained with
SentencePiece vocabularies that do not contain U+03C2 (ς). Every Greek
word-final sigma in their training targets became ``<unk>`` (id 0), so the
models cannot write ς at all (upstream defect, unacknowledged: HF discussion
https://huggingface.co/nvidia/canary-1b-v2/discussions/26).

Canary (AED) still *emits* that ``<unk>`` token at each final-sigma position
and SentencePiece renders it as " ⁇ " (U+2047) in the decoded text - a
deterministic marker we can map back to ς. Parakeet (RNNT/TDT) emits nothing
recoverable, so it only gets a server-side warning.

Every Greek fixture string below is a verbatim canary-1b-v2 output captured
from real inference on Greek audio (see PR for the capture methodology).
"""

from __future__ import annotations

import logging

import numpy as np
import pytest
from server.core.stt.backends.base import BackendSegment, BackendTranscriptionInfo
from server.core.stt.backends.canary_backend import CanaryBackend
from server.core.stt.backends.parakeet_backend import SAMPLE_RATE, ParakeetBackend
from server.core.stt.greek_sigma import (
    repair_greek_final_sigma,
    repair_segments_greek_final_sigma,
)

# ---------------------------------------------------------------------------
# Text-level repair
# ---------------------------------------------------------------------------


class TestRepairGreekFinalSigmaText:
    def test_marker_before_exclamation(self):
        assert repair_greek_final_sigma("Καλησπέρα σα ⁇ !") == "Καλησπέρα σας!"

    def test_markers_between_words_double_spaced(self):
        # Plain hypothesis.text rendering: double space after the marker.
        raw = "Αυτέ ⁇  οι λέξει ⁇  έχουν πολλέ ⁇  καταλήξει ⁇ ."
        assert repair_greek_final_sigma(raw) == "Αυτές οι λέξεις έχουν πολλές καταλήξεις."

    def test_marker_before_comma(self):
        raw = "Τι κάνει ⁇ , που πηγαίνει ⁇ , ίσω ⁇  αύριο"
        assert repair_greek_final_sigma(raw) == "Τι κάνεις, που πηγαίνεις, ίσως αύριο"

    def test_marker_at_end_of_text(self):
        assert repair_greek_final_sigma("ο καιρός είναι καλό ⁇") == "ο καιρός είναι καλός"

    def test_single_spaced_segment_timestamp_rendering(self):
        # Segment-timestamp texts render with single spaces around the marker.
        raw = "ένα ⁇ καλό ⁇ φίλο ⁇ ."
        assert repair_greek_final_sigma(raw) == "ένας καλός φίλος."

    def test_greek_without_marker_unchanged(self):
        assert repair_greek_final_sigma("Καλημέρα σας.") == "Καλημέρα σας."

    def test_english_with_marker_unchanged(self):
        assert repair_greek_final_sigma("Hello ⁇ world") == "Hello ⁇ world"

    def test_marker_after_digits_unchanged(self):
        assert repair_greek_final_sigma("123 ⁇") == "123 ⁇"

    def test_empty_string(self):
        assert repair_greek_final_sigma("") == ""


# ---------------------------------------------------------------------------
# Segment-level repair (text + word timestamp entries)
# ---------------------------------------------------------------------------


def _word(text: str, start: float, end: float, probability: float = 1.0) -> dict:
    return {"word": text, "start": start, "end": end, "probability": probability}


class TestRepairSegments:
    def test_marker_word_merged_into_previous_word(self):
        # Verbatim word entries: "σα" [0.96-1.04], "⁇" [1.04-1.12], "!" [1.12-1.2]
        seg = BackendSegment(
            text="Καλησπέρα σα ⁇ !",
            start=0.0,
            end=1.2,
            words=[
                _word("Καλησπέρα", 0.0, 0.96),
                _word("σα", 0.96, 1.04, probability=0.9),
                _word("⁇", 1.04, 1.12),
                _word("!", 1.12, 1.2),
            ],
        )

        (repaired,) = repair_segments_greek_final_sigma([seg])

        assert repaired.text == "Καλησπέρα σας!"
        assert [w["word"] for w in repaired.words] == ["Καλησπέρα", "σας!"]
        merged = repaired.words[1]
        assert merged["start"] == 0.96
        assert merged["end"] == 1.2  # extended over the marker and the "!"
        assert merged["probability"] == 0.9  # keeps the original word's confidence

    def test_marker_without_following_punctuation(self):
        # Verbatim pattern: "ένα" "⁇" "καλό" "⁇" "φίλο" "⁇" "."
        seg = BackendSegment(
            text="ένα ⁇ καλό ⁇ φίλο ⁇ .",
            start=7.52,
            end=8.8,
            words=[
                _word("ένα", 7.52, 7.6),
                _word("⁇", 7.68, 7.76),
                _word("καλό", 7.76, 7.84),
                _word("⁇", 8.08, 8.16),
                _word("φίλο", 8.32, 8.64),
                _word("⁇", 8.64, 8.72),
                _word(".", 8.72, 8.8),
            ],
        )

        (repaired,) = repair_segments_greek_final_sigma([seg])

        assert repaired.text == "ένας καλός φίλος."
        assert [w["word"] for w in repaired.words] == ["ένας", "καλός", "φίλος."]
        assert repaired.words[0]["end"] == 7.76
        assert repaired.words[2]["end"] == 8.8

    def test_leading_marker_left_untouched(self):
        # No previous Greek word to attach to - conservative: keep the entry.
        seg = BackendSegment(
            text="⁇ καλημέρα",
            start=0.0,
            end=1.0,
            words=[_word("⁇", 0.0, 0.1), _word("καλημέρα", 0.1, 1.0)],
        )

        (repaired,) = repair_segments_greek_final_sigma([seg])

        assert [w["word"] for w in repaired.words] == ["⁇", "καλημέρα"]

    def test_input_segments_not_mutated(self):
        seg = BackendSegment(
            text="σα ⁇ !",
            start=0.0,
            end=1.0,
            words=[_word("σα", 0.0, 0.5), _word("⁇", 0.5, 0.8), _word("!", 0.8, 1.0)],
        )

        repair_segments_greek_final_sigma([seg])

        assert seg.text == "σα ⁇ !"
        assert [w["word"] for w in seg.words] == ["σα", "⁇", "!"]
        assert seg.words[0]["end"] == 0.5


# ---------------------------------------------------------------------------
# CanaryBackend gating: repair only when the OUTPUT language is Greek
# ---------------------------------------------------------------------------


def _fake_short_canary(captured: dict):
    """Build a _transcribe_short_canary replacement returning marked segments."""

    def fake(self, audio, *, source_lang, target_lang, word_timestamps=True):
        captured["source_lang"] = source_lang
        captured["target_lang"] = target_lang
        segments = [
            BackendSegment(
                text="Καλησπέρα σα ⁇ !",
                start=0.0,
                end=1.2,
                words=[
                    _word("σα", 0.96, 1.04),
                    _word("⁇", 1.04, 1.12),
                    _word("!", 1.12, 1.2),
                ],
            )
        ]
        info = BackendTranscriptionInfo(language=source_lang, language_probability=1.0)
        return segments, info

    return fake


class TestCanaryBackendGreekRepairGating:
    @pytest.fixture()
    def backend(self, monkeypatch):
        b = CanaryBackend()
        b._model = object()  # bypass the not-loaded guard
        self.captured: dict = {}
        monkeypatch.setattr(
            CanaryBackend, "_transcribe_short_canary", _fake_short_canary(self.captured)
        )
        return b

    def _run(self, backend, **kwargs):
        audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
        segments, _info = backend.transcribe(audio, **kwargs)
        return segments

    def test_greek_transcription_is_repaired(self, backend):
        segments = self._run(backend, language="el", task="transcribe")
        assert segments[0].text == "Καλησπέρα σας!"
        assert [w["word"] for w in segments[0].words] == ["σας!"]

    def test_english_transcription_untouched(self, backend):
        segments = self._run(backend, language="en", task="transcribe")
        assert segments[0].text == "Καλησπέρα σα ⁇ !"

    def test_translation_into_greek_is_repaired(self, backend):
        segments = self._run(
            backend,
            language="en",
            task="translate",
            translation_target_language="el",
        )
        assert self.captured["target_lang"] == "el"
        assert segments[0].text == "Καλησπέρα σας!"

    def test_translation_out_of_greek_untouched(self, backend):
        segments = self._run(backend, language="el", task="translate")
        assert self.captured["target_lang"] == "en"
        assert segments[0].text == "Καλησπέρα σα ⁇ !"


# ---------------------------------------------------------------------------
# ParakeetBackend: unrepairable - must warn once per instance for Greek
# ---------------------------------------------------------------------------


class TestParakeetGreekWarning:
    @pytest.fixture()
    def backend(self, monkeypatch):
        b = ParakeetBackend()
        b._model = object()
        b._warmup_complete = True

        def fake_short(self, audio, *, word_timestamps=True, language=None):
            info = BackendTranscriptionInfo(language=language or "en")
            return [], info

        monkeypatch.setattr(ParakeetBackend, "_transcribe_short", fake_short)
        return b

    def test_greek_request_logs_warning_once(self, backend, caplog):
        audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
        with caplog.at_level(logging.WARNING):
            backend.transcribe(audio, language="el")
            backend.transcribe(audio, language="el")

        sigma_warnings = [r for r in caplog.records if "ς" in r.getMessage()]
        assert len(sigma_warnings) == 1

    def test_non_greek_request_does_not_warn(self, backend, caplog):
        audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
        with caplog.at_level(logging.WARNING):
            backend.transcribe(audio, language="en")

        assert not [r for r in caplog.records if "ς" in r.getMessage()]
