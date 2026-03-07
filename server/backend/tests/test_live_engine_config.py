"""Tests for LiveModeState enum and LiveModeConfig dataclass.

Covers:
- ``LiveModeState`` enum values and membership
- ``LiveModeConfig`` default values
- ``LiveModeConfig`` custom overrides
- ``LiveModeEngine.is_running`` for each state
- ``LiveModeEngine`` initial state
- ``LiveModeEngine`` sentence history management
- ``LiveModeEngine._set_state`` callback invocation
"""

from __future__ import annotations

import pytest
from server.core.live_engine import LiveModeConfig, LiveModeEngine, LiveModeState

# ── LiveModeState ─────────────────────────────────────────────────────────


class TestLiveModeState:
    def test_all_states_present(self):
        expected = {"STOPPED", "STARTING", "LISTENING", "PROCESSING", "ERROR"}

        assert {s.name for s in LiveModeState} == expected

    def test_states_are_distinct(self):
        values = [s.value for s in LiveModeState]

        assert len(values) == len(set(values))

    @pytest.mark.parametrize(
        "state,expected",
        [
            (LiveModeState.STOPPED, False),
            (LiveModeState.STARTING, False),
            (LiveModeState.LISTENING, True),
            (LiveModeState.PROCESSING, True),
            (LiveModeState.ERROR, False),
        ],
    )
    def test_is_running_mapping(self, state: LiveModeState, expected: bool):
        """is_running should be True only for LISTENING and PROCESSING."""
        engine = LiveModeEngine()
        engine._state = state

        assert engine.is_running is expected


# ── LiveModeConfig defaults ──────────────────────────────────────────────


class TestLiveModeConfigDefaults:
    def test_model_default_empty(self):
        cfg = LiveModeConfig()

        assert cfg.model == ""

    def test_language_default_empty(self):
        cfg = LiveModeConfig()

        assert cfg.language == ""

    def test_translation_disabled_by_default(self):
        cfg = LiveModeConfig()

        assert cfg.translation_enabled is False
        assert cfg.translation_target_language == "en"

    def test_device_default_cuda(self):
        cfg = LiveModeConfig()

        assert cfg.device == "cuda"
        assert cfg.compute_type == "default"

    def test_vad_defaults(self):
        cfg = LiveModeConfig()

        assert cfg.silero_sensitivity == 0.6
        assert cfg.webrtc_sensitivity == 3
        assert cfg.post_speech_silence_duration == 1.0
        assert cfg.min_length_of_recording == 0.5
        assert cfg.min_gap_between_recordings == 0.3

    def test_sentence_behavior_defaults(self):
        cfg = LiveModeConfig()

        assert cfg.ensure_sentence_starting_uppercase is True
        assert cfg.ensure_sentence_ends_with_period is True

    def test_performance_defaults(self):
        cfg = LiveModeConfig()

        assert cfg.beam_size == 5
        assert cfg.batch_size == 16

    def test_gpu_device_index_default(self):
        cfg = LiveModeConfig()

        assert cfg.gpu_device_index == 0


# ── LiveModeConfig overrides ─────────────────────────────────────────────


class TestLiveModeConfigOverrides:
    def test_custom_model(self):
        cfg = LiveModeConfig(model="large-v3")

        assert cfg.model == "large-v3"

    def test_custom_vad_settings(self):
        cfg = LiveModeConfig(
            silero_sensitivity=0.8,
            post_speech_silence_duration=0.5,
        )

        assert cfg.silero_sensitivity == 0.8
        assert cfg.post_speech_silence_duration == 0.5

    def test_translation_enabled(self):
        cfg = LiveModeConfig(
            translation_enabled=True,
            translation_target_language="de",
        )

        assert cfg.translation_enabled is True
        assert cfg.translation_target_language == "de"


# ── LiveModeEngine initial state ──────────────────────────────────────────


class TestLiveModeEngineInit:
    def test_initial_state_stopped(self):
        engine = LiveModeEngine()

        assert engine.state is LiveModeState.STOPPED

    def test_is_running_false_initially(self):
        engine = LiveModeEngine()

        assert engine.is_running is False

    def test_sentence_history_empty_initially(self):
        engine = LiveModeEngine()

        assert engine.sentence_history == []

    def test_default_config_used_when_none(self):
        engine = LiveModeEngine()

        assert engine.config.model == ""
        assert engine.config.beam_size == 5

    def test_custom_config_passed_through(self):
        cfg = LiveModeConfig(model="medium", beam_size=3)

        engine = LiveModeEngine(config=cfg)

        assert engine.config.model == "medium"
        assert engine.config.beam_size == 3


# ── Sentence history ──────────────────────────────────────────────────────


class TestSentenceHistory:
    def test_process_sentence_adds_to_history(self):
        engine = LiveModeEngine()

        engine._process_sentence("Hello world.")

        assert engine.sentence_history == ["Hello world."]

    def test_process_sentence_strips_whitespace(self):
        engine = LiveModeEngine()

        engine._process_sentence("  Hello world.  ")

        assert engine.sentence_history == ["Hello world."]

    def test_process_sentence_ignores_empty(self):
        engine = LiveModeEngine()

        engine._process_sentence("")
        engine._process_sentence("   ")

        assert engine.sentence_history == []

    def test_history_capped_at_max(self):
        engine = LiveModeEngine()
        engine._max_history = 3

        for i in range(5):
            engine._process_sentence(f"Sentence {i}")

        assert len(engine.sentence_history) == 3
        assert engine.sentence_history[0] == "Sentence 2"
        assert engine.sentence_history[-1] == "Sentence 4"

    def test_clear_history(self):
        engine = LiveModeEngine()
        engine._process_sentence("Something")

        engine.clear_history()

        assert engine.sentence_history == []

    def test_sentence_history_returns_copy(self):
        engine = LiveModeEngine()
        engine._process_sentence("Hello")

        history = engine.sentence_history
        history.append("injected")

        assert engine.sentence_history == ["Hello"]


# ── State change callbacks ────────────────────────────────────────────────


class TestStateChangeCallback:
    def test_set_state_triggers_callback(self):
        received: list[LiveModeState] = []
        engine = LiveModeEngine(on_state_change=lambda s: received.append(s))

        engine._set_state(LiveModeState.LISTENING)

        assert received == [LiveModeState.LISTENING]

    def test_set_state_updates_property(self):
        engine = LiveModeEngine()

        engine._set_state(LiveModeState.PROCESSING)

        assert engine.state is LiveModeState.PROCESSING

    def test_callback_error_does_not_propagate(self):
        """A broken callback must not crash the engine."""

        def bad_callback(_state):
            raise RuntimeError("boom")

        engine = LiveModeEngine(on_state_change=bad_callback)

        # Should not raise
        engine._set_state(LiveModeState.ERROR)

        assert engine.state is LiveModeState.ERROR

    def test_sentence_callback_invoked(self):
        received: list[str] = []
        engine = LiveModeEngine(on_sentence=lambda t: received.append(t))

        engine._process_sentence("Hello world.")

        assert received == ["Hello world."]
