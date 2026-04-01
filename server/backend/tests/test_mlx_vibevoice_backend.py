"""Unit tests for the MLX VibeVoice-ASR STT backend and factory detection.

These tests run in the standard CI environment (no Apple Silicon required).
Heavy dependencies (mlx_audio, mlx) are stubbed out so that the logic can be
verified on any platform.
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stt_output_stub(
    text: str = "Hello world.",
    segments: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Build a fake ``STTOutput`` returned by ``Model.generate()``."""
    out = MagicMock()
    out.text = text
    out.segments = segments or []
    out.language = "en"
    return out


def _install_mlx_audio_stubs() -> MagicMock:
    """Insert minimal ``mlx_audio`` / ``mlx`` stubs into ``sys.modules``."""
    mlx_mod = types.ModuleType("mlx")
    mlx_core = types.ModuleType("mlx.core")
    mlx_core.clear_cache = MagicMock()
    mlx_mod.core = mlx_core
    sys.modules["mlx"] = mlx_mod
    sys.modules["mlx.core"] = mlx_core

    mlx_audio = types.ModuleType("mlx_audio")
    mlx_audio_stt = types.ModuleType("mlx_audio.stt")
    mock_model = MagicMock()
    mlx_audio_stt.load = MagicMock(return_value=mock_model)
    mlx_audio.stt = mlx_audio_stt
    sys.modules["mlx_audio"] = mlx_audio
    sys.modules["mlx_audio.stt"] = mlx_audio_stt

    return mock_model


# ---------------------------------------------------------------------------
# Factory detection
# ---------------------------------------------------------------------------


class TestFactoryDetection:
    def test_detect_mlx_vibevoice(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("mlx-community/VibeVoice-ASR-bf16") == "mlx_vibevoice"

    def test_detect_mlx_vibevoice_4bit(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("mlx-community/VibeVoice-ASR-4bit") == "mlx_vibevoice"

    def test_detect_mlx_vibevoice_8bit(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("mlx-community/VibeVoice-ASR-8bit") == "mlx_vibevoice"

    def test_case_insensitive(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("MLX-COMMUNITY/VIBEVOICE-ASR-BF16") == "mlx_vibevoice"

    def test_generic_vibevoice_not_mlx(self) -> None:
        """microsoft/ prefix → Docker VibeVoice backend, not MLX."""
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("microsoft/VibeVoice-ASR") == "vibevoice_asr"

    def test_is_mlx_model_includes_vibevoice(self) -> None:
        from server.core.stt.backends.factory import is_mlx_model

        assert is_mlx_model("mlx-community/VibeVoice-ASR-bf16")

    def test_is_mlx_model_excludes_docker_vibevoice(self) -> None:
        from server.core.stt.backends.factory import is_mlx_model

        assert not is_mlx_model("microsoft/VibeVoice-ASR")

    def test_create_backend_returns_mlx_vibevoice(self) -> None:
        _install_mlx_audio_stubs()
        from server.core.stt.backends.factory import create_backend

        backend = create_backend("mlx-community/VibeVoice-ASR-bf16")
        assert type(backend).__name__ == "MLXVibeVoiceBackend"


# ---------------------------------------------------------------------------
# Backend basics (stubbed)
# ---------------------------------------------------------------------------


class TestMLXVibeVoiceBackend:
    def test_load_and_unload(self) -> None:
        mock_model = _install_mlx_audio_stubs()
        from server.core.stt.backends.mlx_vibevoice_backend import MLXVibeVoiceBackend

        backend = MLXVibeVoiceBackend()
        assert not backend.is_loaded()
        backend.load("mlx-community/VibeVoice-ASR-bf16", device="mps")
        assert backend.is_loaded()
        backend.unload()
        assert not backend.is_loaded()

    def test_supports_translation_is_false(self) -> None:
        _install_mlx_audio_stubs()
        from server.core.stt.backends.mlx_vibevoice_backend import MLXVibeVoiceBackend

        backend = MLXVibeVoiceBackend()
        assert backend.supports_translation() is False

    def test_preferred_sample_rate(self) -> None:
        _install_mlx_audio_stubs()
        from server.core.stt.backends.mlx_vibevoice_backend import MLXVibeVoiceBackend

        backend = MLXVibeVoiceBackend()
        assert backend.preferred_input_sample_rate_hz == 16000

    def test_transcribe_returns_segments(self) -> None:
        mock_model = _install_mlx_audio_stubs()
        from server.core.stt.backends.mlx_vibevoice_backend import MLXVibeVoiceBackend

        stt_output = _make_stt_output_stub(
            text="Hello world.",
            segments=[
                {"text": "Hello world.", "start": 0.0, "end": 2.5},
            ],
        )
        mock_model.generate.return_value = stt_output

        backend = MLXVibeVoiceBackend()
        backend.load("mlx-community/VibeVoice-ASR-bf16", device="mps")

        audio = np.zeros(16000, dtype=np.float32)
        segments, info = backend.transcribe(audio, audio_sample_rate=16000)

        assert len(segments) == 1
        assert segments[0].text == "Hello world."
        assert segments[0].start == 0.0
        assert segments[0].end == 2.5

    def test_transcribe_with_diarization(self) -> None:
        mock_model = _install_mlx_audio_stubs()
        from server.core.stt.backends.mlx_vibevoice_backend import MLXVibeVoiceBackend

        stt_output = _make_stt_output_stub(
            text="Speaker 0: Hello. Speaker 1: Hi there.",
            segments=[
                {"text": "Hello.", "start": 0.0, "end": 1.0, "speaker_id": "Speaker 0"},
                {"text": "Hi there.", "start": 1.2, "end": 2.5, "speaker_id": "Speaker 1"},
            ],
        )
        mock_model.generate.return_value = stt_output

        backend = MLXVibeVoiceBackend()
        backend.load("mlx-community/VibeVoice-ASR-bf16", device="mps")

        audio = np.zeros(16000 * 3, dtype=np.float32)
        result = backend.transcribe_with_diarization(audio, audio_sample_rate=16000)

        assert result is not None
        assert result.num_speakers == 2
        assert len(result.segments) == 2
        assert result.segments[0]["speaker"] == "Speaker 0"
        assert result.segments[0]["text"] == "Hello."
        assert result.segments[1]["speaker"] == "Speaker 1"
        assert result.segments[1]["text"] == "Hi there."

    def test_transcribe_fallback_on_empty_segments(self) -> None:
        """When segments are empty but text is present, create a single segment."""
        mock_model = _install_mlx_audio_stubs()
        from server.core.stt.backends.mlx_vibevoice_backend import MLXVibeVoiceBackend

        stt_output = _make_stt_output_stub(text="Fallback text.", segments=[])
        mock_model.generate.return_value = stt_output

        backend = MLXVibeVoiceBackend()
        backend.load("mlx-community/VibeVoice-ASR-bf16", device="mps")

        audio = np.zeros(16000, dtype=np.float32)
        segments, _info = backend.transcribe(audio, audio_sample_rate=16000)

        assert len(segments) == 1
        assert segments[0].text == "Fallback text."
        assert segments[0].start == 0.0
        assert segments[0].end == 1.0  # 16000 samples / 16000 Hz

    def test_backend_name(self) -> None:
        _install_mlx_audio_stubs()
        from server.core.stt.backends.mlx_vibevoice_backend import MLXVibeVoiceBackend

        backend = MLXVibeVoiceBackend()
        assert backend.backend_name == "mlx_vibevoice"
