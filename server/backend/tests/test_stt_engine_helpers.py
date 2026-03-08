"""Tests for stt/engine.py helper classes and methods — no ML dependencies.

Covers:
- ``TranscriptionResult`` data class and ``to_dict()`` serialisation
- ``TranscriptionResult`` defaults
- ``_preprocess_output()`` text post-processing (uppercase, period, whitespace)
- ``INT16_MAX_ABS_VALUE`` and ``SAMPLE_RATE`` constants
- ``AudioToTextRecorder.get_status()`` for a bare-minimum recorder
- ``AudioToTextRecorder`` shutdown idempotency
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Stub heavy dependencies before importing the engine module.
# The engine has a top-level ``import torch`` (unconditional) plus imports
# from server.config, server.core.stt.backends.factory,
# server.core.stt.capabilities, and server.core.stt.vad.
# We install lightweight stubs so the module can be collected.
# ---------------------------------------------------------------------------


def _ensure_engine_importable() -> None:
    """Install lightweight stubs for engine top-level imports."""
    # torch — must exist before ``import torch`` in engine.py
    if "torch" not in sys.modules:
        torch_stub = types.ModuleType("torch")
        torch_stub.Tensor = type("Tensor", (), {})  # type: ignore[attr-defined]
        torch_stub.float16 = "float16"  # type: ignore[attr-defined]
        torch_stub.float32 = "float32"  # type: ignore[attr-defined]
        torch_stub.from_numpy = lambda x: x  # type: ignore[attr-defined]
        torch_stub.cuda = types.SimpleNamespace(  # type: ignore[attr-defined]
            is_available=lambda: False,
        )
        sys.modules["torch"] = torch_stub

    # scipy.signal.resample
    if "scipy" not in sys.modules:
        scipy = types.ModuleType("scipy")
        scipy_signal = types.ModuleType("scipy.signal")
        scipy_signal.resample = lambda *a, **kw: np.array([])  # type: ignore[attr-defined]
        scipy.signal = scipy_signal  # type: ignore[attr-defined]
        sys.modules["scipy"] = scipy
        sys.modules["scipy.signal"] = scipy_signal

    # server.core.stt.backends.factory
    factory_mod_name = "server.core.stt.backends.factory"
    if factory_mod_name not in sys.modules:
        factory_stub = types.ModuleType(factory_mod_name)
        factory_stub.create_backend = MagicMock()  # type: ignore[attr-defined]
        factory_stub.detect_backend_type = MagicMock(return_value="whisper")  # type: ignore[attr-defined]
        sys.modules[factory_mod_name] = factory_stub

    # server.core.stt.capabilities — the real module has no heavy deps
    # (only imports ``re``), so we let it import naturally instead of stubbing.
    # This avoids poisoning sys.modules for other test files that test the
    # real capabilities functions.

    # server.core.stt.vad
    vad_mod_name = "server.core.stt.vad"
    if vad_mod_name not in sys.modules:
        vad_stub = types.ModuleType(vad_mod_name)

        class _FakeVAD:
            def __init__(self, **kw: Any):
                pass

            def reset_states(self) -> None:
                pass

        vad_stub.VoiceActivityDetector = _FakeVAD  # type: ignore[attr-defined]
        sys.modules[vad_mod_name] = vad_stub


_ensure_engine_importable()

# Stub server.config to avoid needing a real config.yaml
_mock_cfg = MagicMock()
_mock_cfg.get.return_value = {}
_mock_cfg.stt = MagicMock()
_mock_cfg.stt.get.return_value = None

with (
    patch("server.config.get_config", return_value=_mock_cfg),
    patch("server.config.resolve_main_transcriber_model", return_value="tiny"),
):
    from server.core.stt.engine import (
        INT16_MAX_ABS_VALUE,
        SAMPLE_RATE,
        AudioToTextRecorder,
        TranscriptionResult,
    )


# ── Constants ─────────────────────────────────────────────────────────────


class TestConstants:
    def test_sample_rate(self):
        assert SAMPLE_RATE == 16000

    def test_int16_max(self):
        assert INT16_MAX_ABS_VALUE == 32768.0


# ── TranscriptionResult ──────────────────────────────────────────────────


class TestTranscriptionResult:
    def test_defaults(self):
        r = TranscriptionResult(text="hello")

        assert r.text == "hello"
        assert r.language is None
        assert r.language_probability == 0.0
        assert r.duration == 0.0
        assert r.segments == []
        assert r.words == []
        assert r.num_speakers == 0

    def test_to_dict_keys(self):
        r = TranscriptionResult(text="test")

        d = r.to_dict()

        expected_keys = {
            "text",
            "segments",
            "words",
            "language",
            "language_probability",
            "duration",
            "num_speakers",
            "total_words",
            "metadata",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_text(self):
        r = TranscriptionResult(text="Hello world")

        d = r.to_dict()

        assert d["text"] == "Hello world"

    def test_to_dict_rounds_language_probability(self):
        r = TranscriptionResult(text="x", language_probability=0.98765)

        d = r.to_dict()

        assert d["language_probability"] == 0.988

    def test_to_dict_rounds_duration(self):
        r = TranscriptionResult(text="x", duration=12.34567)

        d = r.to_dict()

        assert d["duration"] == 12.346

    def test_to_dict_total_words_count(self):
        words = [{"word": "hello"}, {"word": "world"}]
        r = TranscriptionResult(text="hello world", words=words)

        d = r.to_dict()

        assert d["total_words"] == 2

    def test_to_dict_metadata_num_segments(self):
        segments = [
            {"text": "seg1", "start": 0.0, "end": 1.0},
            {"text": "seg2", "start": 1.0, "end": 2.0},
        ]
        r = TranscriptionResult(text="seg1 seg2", segments=segments)

        d = r.to_dict()

        assert d["metadata"]["num_segments"] == 2

    def test_to_dict_preserves_segments_and_words(self):
        segments = [{"text": "a", "start": 0.0, "end": 0.5}]
        words = [{"word": "a", "start": 0.0, "end": 0.5}]
        r = TranscriptionResult(text="a", segments=segments, words=words)

        d = r.to_dict()

        assert d["segments"] == segments
        assert d["words"] == words

    def test_to_dict_with_all_fields(self):
        r = TranscriptionResult(
            text="Hello",
            language="en",
            language_probability=0.95,
            duration=1.5,
            segments=[{"text": "Hello", "start": 0.0, "end": 1.5}],
            words=[{"word": "Hello", "start": 0.0, "end": 1.5}],
            num_speakers=1,
        )

        d = r.to_dict()

        assert d["language"] == "en"
        assert d["num_speakers"] == 1
        assert d["total_words"] == 1

    def test_empty_text(self):
        r = TranscriptionResult(text="")

        d = r.to_dict()

        assert d["text"] == ""
        assert d["total_words"] == 0
        assert d["metadata"]["num_segments"] == 0


# ── _preprocess_output ────────────────────────────────────────────────────


class TestPreprocessOutput:
    """Test the text post-processing method in isolation.

    We create a minimal recorder just to access ``_preprocess_output``.
    """

    @pytest.fixture()
    def recorder(self):
        """Build a recorder with model loading stubbed out."""
        with (
            patch("server.config.get_config", return_value=_mock_cfg),
            patch("server.config.resolve_main_transcriber_model", return_value="tiny"),
            patch.object(AudioToTextRecorder, "_load_model"),
            patch.object(AudioToTextRecorder, "_recording_worker"),
        ):
            rec = object.__new__(AudioToTextRecorder)
            rec.ensure_sentence_starting_uppercase = True
            rec.ensure_sentence_ends_with_period = True
        return rec

    def test_capitalize_first_letter(self, recorder):
        result = recorder._preprocess_output("hello world")

        assert result[0] == "H"

    def test_adds_period(self, recorder):
        result = recorder._preprocess_output("hello world")

        assert result.endswith(".")

    def test_no_double_period(self, recorder):
        result = recorder._preprocess_output("hello world.")

        assert result == "Hello world."

    def test_collapse_whitespace(self, recorder):
        result = recorder._preprocess_output("  hello   world  ")

        assert result == "Hello world."

    def test_empty_string(self, recorder):
        result = recorder._preprocess_output("")

        assert result == ""

    def test_no_uppercase_when_disabled(self, recorder):
        recorder.ensure_sentence_starting_uppercase = False

        result = recorder._preprocess_output("hello")

        assert result[0] == "h"

    def test_no_period_when_disabled(self, recorder):
        recorder.ensure_sentence_ends_with_period = False

        result = recorder._preprocess_output("hello")

        assert result == "Hello"

    def test_newline_and_tab_collapsed(self, recorder):
        result = recorder._preprocess_output("hello\n\tworld")

        assert result == "Hello world."

    def test_single_char(self, recorder):
        result = recorder._preprocess_output("a")

        assert result == "A."

    def test_already_ends_with_punctuation(self, recorder):
        for punct in ["!", "?", ","]:
            result = recorder._preprocess_output(f"hello{punct}")
            # Period should NOT be added since last char is not alphanumeric
            assert not result.endswith(f"{punct}.")


# ── AudioToTextRecorder.get_status ────────────────────────────────────────


class TestGetStatus:
    @pytest.fixture()
    def recorder(self):
        """Minimal recorder with no model loading."""
        rec = object.__new__(AudioToTextRecorder)
        rec.model_name = "tiny"
        rec.device = "cpu"
        rec.compute_type = "default"
        rec._model_loaded = False
        rec._backend = None
        rec.language = ""
        rec.task = "transcribe"
        rec.translation_target_language = "en"
        rec.state = "inactive"
        return rec

    def test_status_keys(self, recorder):
        status = recorder.get_status()

        expected_keys = {
            "model",
            "device",
            "compute_type",
            "loaded",
            "backend",
            "language",
            "task",
            "translation_target_language",
            "state",
        }
        assert set(status.keys()) == expected_keys

    def test_not_loaded_shows_false(self, recorder):
        status = recorder.get_status()

        assert status["loaded"] is False
        assert status["backend"] is None

    def test_language_empty_shows_none(self, recorder):
        status = recorder.get_status()

        assert status["language"] is None

    def test_language_set(self, recorder):
        recorder.language = "en"

        status = recorder.get_status()

        assert status["language"] == "en"

    def test_state_reflects_current(self, recorder):
        recorder.state = "recording"

        status = recorder.get_status()

        assert status["state"] == "recording"

    def test_backend_name_when_loaded(self, recorder):
        mock_backend = MagicMock()
        mock_backend.backend_name = "whisperx"
        recorder._backend = mock_backend
        recorder._model_loaded = True

        status = recorder.get_status()

        assert status["loaded"] is True
        assert status["backend"] == "whisperx"
