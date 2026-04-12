"""Tests for stt/engine.py helper classes and methods — no ML dependencies.

Covers:
- ``TranscriptionResult`` data class and ``to_dict()`` serialisation
- ``TranscriptionResult`` defaults
- ``_preprocess_output()`` text post-processing (uppercase, period, whitespace)
- ``INT16_MAX_ABS_VALUE`` and ``SAMPLE_RATE`` constants
- ``AudioToTextRecorder.get_status()`` for a bare-minimum recorder
- ``AudioToTextRecorder`` shutdown idempotency
- GH-60: ``compute_type`` auto-correction on pre-Volta GPUs
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
        _model_not_loaded_message,
    )


# ── Constants ─────────────────────────────────────────────────────────────


class TestConstants:
    def test_sample_rate(self):
        assert SAMPLE_RATE == 16000

    def test_int16_max(self):
        assert INT16_MAX_ABS_VALUE == 32768.0


# ── _model_not_loaded_message ─────────────────────────────────────────────


class TestModelNotLoadedMessage:
    """Issue #62 follow-up: make the backend-missing error actionable.

    The previous message — ``"STT model is not loaded"`` — told users nothing
    about *why* the backend was missing or what to do next. The new message
    must: (a) name the configured model, (b) point at the download / reload
    flow, and (c) call out the whisper.cpp sidecar dependency for GGML
    models.
    """

    def test_names_the_configured_model(self):
        msg = _model_not_loaded_message("ggml-large-v3-turbo-q8_0.bin")
        assert "ggml-large-v3-turbo-q8_0.bin" in msg

    def test_handles_unset_model(self):
        assert "<unset>" in _model_not_loaded_message(None)
        assert "<unset>" in _model_not_loaded_message("")

    def test_mentions_download_or_downloaded(self):
        """User must see a recovery hint referencing the model-download flow."""
        msg = _model_not_loaded_message("anything.bin").lower()
        # A bare "download" without context would pass a looser OR-gate. Pin
        # the phrase that tells the user what to do with the download.
        assert "still downloading" in msg or "is downloaded" in msg

    def test_mentions_settings_and_reload_by_name(self):
        """Recovery must reference BOTH the location (Settings) and the action (Reload)."""
        msg = _model_not_loaded_message("anything.bin").lower()
        assert "settings" in msg, "user must be told where to go"
        assert "reload" in msg, "user must be told what action to take"

    def test_mentions_sidecar_for_whispercpp_users(self):
        msg = _model_not_loaded_message("ggml-base.bin")
        # Users running a GGML model need the whisper-server sidecar up.
        assert "whisper-server" in msg or "sidecar" in msg

    def test_format_string_metachars_in_model_name_are_safe(self):
        """A model name containing ``{}`` must not trigger f-string evaluation.

        Defence-in-depth: the helper uses ``repr()`` which adds quotes, and
        f-strings do not re-interpret already-built strings, so there is no
        injection path today. But pin it so a refactor to ``%``-formatting
        or ``.format()`` cannot regress.
        """
        msg = _model_not_loaded_message("{evil}")
        assert "{evil}" in msg
        # Must not have raised KeyError or swapped in a variable value.


class TestTranscribeGuardsRaiseActionableError:
    """Integration: confirm the engine *actually* raises with the new message.

    ``TestModelNotLoadedMessage`` pins the formatter. This pins the glue —
    if a refactor accidentally reverts one of the guard sites back to the
    bare ``"STT model is not loaded"`` literal, the message-text assertions
    above would still pass but the user experience would regress.
    """

    @staticmethod
    def _bare_recorder(model_name: str = "ggml-base.bin"):
        import threading

        rec = object.__new__(AudioToTextRecorder)
        rec.transcription_lock = threading.Lock()
        rec.model_name = model_name
        rec.language = "en"
        rec.task = "transcribe"
        rec.translation_target_language = None
        rec.initial_prompt = None
        rec.beam_size = 5
        rec.suppress_tokens = None
        rec.faster_whisper_vad_filter = True
        rec.normalize_audio = False
        rec._backend = None
        # ``_perform_transcription``'s except/finally uses ``_set_state`` which
        # reads ``self.state`` — set it so the guard can raise cleanly without
        # cascading into an unrelated AttributeError.
        rec.state = "transcribing"
        rec.on_transcription_start = None
        return rec

    def test_perform_transcription_raises_with_actionable_message(self):
        rec = self._bare_recorder()
        audio = np.ones(16000, dtype=np.float32) * 0.1
        with pytest.raises(RuntimeError) as excinfo:
            rec._perform_transcription(audio=audio)
        msg = str(excinfo.value)
        assert "ggml-base.bin" in msg
        # Use ``and`` so a mutation that dropped the whisper-server line
        # while keeping "sidecar" would fail loudly. The helper's contract
        # is to mention BOTH hints.
        assert "sidecar" in msg, "must mention the sidecar dependency"
        assert "whisper-server" in msg, "must name the whisper-server container"

    def test_transcribe_audio_raises_with_actionable_message(self):
        """The other guard site (batch ``transcribe_audio``) uses the same helper."""
        rec = self._bare_recorder(model_name="tiny.en")
        audio = np.ones(16000, dtype=np.float32) * 0.1
        with pytest.raises(RuntimeError) as excinfo:
            rec.transcribe_audio(audio, sample_rate=16000)
        msg = str(excinfo.value)
        assert "tiny.en" in msg
        # ``and`` not ``or`` — the helper contract is that BOTH words appear.
        assert "Reload" in msg, "must tell the user the action"
        assert "Settings" in msg, "must tell the user where"


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


# ── GH-60: compute_type auto-correction on pre-Volta GPUs ───────────────


class TestComputeTypeAutoCorrection:
    """Verify compute_type="default" is overridden to "auto" on GPUs < sm_70.

    Uses object.__new__() to create a bare recorder, then manually assigns the
    fields that the auto-correction logic reads (device, compute_type) and
    replays just the correction branch.
    """

    @staticmethod
    def _apply_correction(recorder: AudioToTextRecorder) -> None:
        """Replay the GH-60 auto-correction block from __init__."""
        import logging as _logging

        _logger = _logging.getLogger("server.core.stt.engine")

        if recorder.device == "cuda" and recorder.compute_type == "default":
            from server.core.audio_utils import get_cuda_compute_capability

            cc = get_cuda_compute_capability()
            if cc is not None and cc < (7, 0):
                _logger.warning(
                    "GPU compute capability %d.%d < 7.0 — overriding compute_type "
                    '"default" → "auto" to avoid float16 crash (GH-60)',
                    cc[0],
                    cc[1],
                )
                recorder.compute_type = "auto"

    def test_pascal_gpu_overrides_default_to_auto(self, caplog):
        import logging

        rec = object.__new__(AudioToTextRecorder)
        rec.device = "cuda"
        rec.compute_type = "default"

        with (
            caplog.at_level(logging.WARNING),
            patch(
                "server.core.audio_utils.get_cuda_compute_capability",
                return_value=(6, 1),
            ),
        ):
            self._apply_correction(rec)

        assert rec.compute_type == "auto"
        assert "GH-60" in caplog.text
        assert "6.1" in caplog.text

    def test_volta_gpu_preserves_default(self):
        rec = object.__new__(AudioToTextRecorder)
        rec.device = "cuda"
        rec.compute_type = "default"

        with patch(
            "server.core.audio_utils.get_cuda_compute_capability",
            return_value=(7, 0),
        ):
            self._apply_correction(rec)

        assert rec.compute_type == "default"

    def test_ampere_gpu_preserves_default(self):
        rec = object.__new__(AudioToTextRecorder)
        rec.device = "cuda"
        rec.compute_type = "default"

        with patch(
            "server.core.audio_utils.get_cuda_compute_capability",
            return_value=(8, 6),
        ):
            self._apply_correction(rec)

        assert rec.compute_type == "default"

    def test_explicit_int8_never_overridden(self):
        rec = object.__new__(AudioToTextRecorder)
        rec.device = "cuda"
        rec.compute_type = "int8"

        with patch(
            "server.core.audio_utils.get_cuda_compute_capability",
            return_value=(6, 1),
        ):
            self._apply_correction(rec)

        assert rec.compute_type == "int8"

    def test_explicit_float32_never_overridden(self):
        rec = object.__new__(AudioToTextRecorder)
        rec.device = "cuda"
        rec.compute_type = "float32"

        with patch(
            "server.core.audio_utils.get_cuda_compute_capability",
            return_value=(6, 1),
        ):
            self._apply_correction(rec)

        assert rec.compute_type == "float32"

    def test_cpu_device_skips_check(self):
        rec = object.__new__(AudioToTextRecorder)
        rec.device = "cpu"
        rec.compute_type = "default"

        with patch(
            "server.core.audio_utils.get_cuda_compute_capability",
        ) as mock_cc:
            self._apply_correction(rec)

        assert rec.compute_type == "default"
        mock_cc.assert_not_called()

    def test_capability_unavailable_preserves_default(self):
        rec = object.__new__(AudioToTextRecorder)
        rec.device = "cuda"
        rec.compute_type = "default"

        with patch(
            "server.core.audio_utils.get_cuda_compute_capability",
            return_value=None,
        ):
            self._apply_correction(rec)

        assert rec.compute_type == "default"

    def test_maxwell_gpu_overrides_default(self):
        """Maxwell (GTX 980, sm_52) should also be corrected."""
        rec = object.__new__(AudioToTextRecorder)
        rec.device = "cuda"
        rec.compute_type = "default"

        with patch(
            "server.core.audio_utils.get_cuda_compute_capability",
            return_value=(5, 2),
        ):
            self._apply_correction(rec)

        assert rec.compute_type == "auto"
