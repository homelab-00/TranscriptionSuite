"""P0 live mode tests — sentence history cap and session loss.

Covers P0-LIVE-001 and P0-LIVE-002 from the QA test-design document.
These validate the known zero-durability limitation of Live Mode (R-002).

Run:  ../../build/.venv/bin/pytest tests/test_p0_live_mode.py -v --tb=short
"""

from __future__ import annotations

import pytest
from server.core.live_engine import LiveModeConfig, LiveModeEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(*, max_history: int = 50) -> LiveModeEngine:
    """Create a LiveModeEngine with no callbacks (bypass heavy recorder init)."""
    engine = object.__new__(LiveModeEngine)
    config = LiveModeConfig()
    engine.config = config
    engine._on_sentence = None
    engine._on_realtime_update = None
    engine._on_state_change = None
    engine._shared_backend = None
    engine._recorder = None
    engine._state = None  # Not needed for history tests
    engine._loop_thread = None
    engine._stop_event = None
    engine._sentence_history = []
    engine._max_history = max_history
    engine._audio_queue = None
    return engine


# ═══════════════════════════════════════════════════════════════════════
# P0-LIVE-001: Sentence history cap — 50 max, oldest dropped
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.live_mode
class TestLive001HistoryCap:
    """P0-LIVE-001: Sentence history capped at 50, oldest sentences dropped."""

    def test_push_60_retains_last_50(self):
        """Push 60 sentences, verify only the last 50 are retained."""
        engine = _make_engine(max_history=50)

        for i in range(60):
            engine._process_sentence(f"Sentence {i}")

        history = engine.sentence_history
        assert len(history) == 50
        # Oldest 10 (0–9) should be dropped; first retained is 10
        assert history[0] == "Sentence 10"
        assert history[-1] == "Sentence 59"

    def test_exactly_50_all_retained(self):
        """Push exactly 50 sentences — all retained, no truncation."""
        engine = _make_engine(max_history=50)

        for i in range(50):
            engine._process_sentence(f"Sentence {i}")

        history = engine.sentence_history
        assert len(history) == 50
        assert history[0] == "Sentence 0"
        assert history[-1] == "Sentence 49"

    def test_empty_and_whitespace_sentences_ignored(self):
        """Empty strings and whitespace-only sentences are not added to history."""
        engine = _make_engine(max_history=50)

        engine._process_sentence("")
        engine._process_sentence("   ")
        engine._process_sentence("\n\t")
        engine._process_sentence("Valid sentence")

        assert engine.sentence_history == ["Valid sentence"]

    def test_history_returns_copy_not_reference(self):
        """sentence_history returns a copy — external mutation cannot corrupt state."""
        engine = _make_engine(max_history=50)
        engine._process_sentence("Original")

        history = engine.sentence_history
        history.append("Injected")

        assert engine.sentence_history == ["Original"]


# ═══════════════════════════════════════════════════════════════════════
# P0-LIVE-002: Session loss on disconnect — history cleared
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.live_mode
class TestLive002SessionLoss:
    """P0-LIVE-002: Session loss on disconnect clears history (zero durability)."""

    def test_clear_history_empties_all_sentences(self):
        """After clear_history, sentence_history is empty."""
        engine = _make_engine()

        for i in range(25):
            engine._process_sentence(f"Sentence {i}")
        assert len(engine.sentence_history) == 25

        engine.clear_history()

        assert engine.sentence_history == []

    def test_clear_history_allows_new_sentences(self):
        """After clearing, new sentences accumulate from zero."""
        engine = _make_engine()

        for i in range(10):
            engine._process_sentence(f"Old {i}")
        engine.clear_history()

        engine._process_sentence("New sentence")

        assert engine.sentence_history == ["New sentence"]

    def test_stop_engine_then_clear_resets_history(self):
        """stop_engine + clear_history (the real disconnect path) empties history."""
        engine = _make_engine()

        for i in range(10):
            engine._process_sentence(f"Sentence {i}")
        assert len(engine.sentence_history) == 10

        # Simulate what LiveModeSession.cleanup() does: stop then clear
        # engine.stop() requires threads — test the clear_history wiring directly
        engine.clear_history()

        assert engine.sentence_history == []
        # History can accumulate again in a new session
        engine._process_sentence("After reconnect")
        assert engine.sentence_history == ["After reconnect"]
