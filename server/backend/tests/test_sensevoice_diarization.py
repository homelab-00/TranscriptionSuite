"""Tests for SenseVoice diarization: engine resolver, route predicate,
CAM++ single-pass parsing, and the harmonized transcribe parser.
funasr is stubbed via sys.modules — no model download."""

from __future__ import annotations

import sys  # noqa: F401
import types  # noqa: F401
from typing import Any  # noqa: F401
from unittest.mock import MagicMock, patch  # noqa: F401

import numpy as np  # noqa: F401
import pytest  # noqa: F401

# --- config.resolve_sensevoice_diarization_engine --------------------------


class TestResolveEngine:
    def _resolve(
        self,
        model_name: str | None,
        request_value: str | None,
        config_default: str | None,
        available: bool,
    ) -> str:
        from server.config import resolve_sensevoice_diarization_engine

        return resolve_sensevoice_diarization_engine(
            model_name,
            request_value,
            config_default,
            funasr_diar_available=available,
        )

    def test_non_sensevoice_always_pyannote(self) -> None:
        assert (
            self._resolve("Systran/faster-whisper-large-v3", "funasr", "funasr", True) == "pyannote"
        )
        assert self._resolve(None, "funasr", "funasr", True) == "pyannote"

    def test_sensevoice_auto_uses_config_default(self) -> None:
        assert self._resolve("iic/SenseVoiceSmall", "auto", "funasr", True) == "funasr"
        assert self._resolve("iic/SenseVoiceSmall", None, "pyannote", True) == "pyannote"
        # config_default=None → falls back to DEFAULT_SENSEVOICE_DIARIZATION_ENGINE ("funasr")
        assert self._resolve("iic/SenseVoiceSmall", None, None, True) == "funasr"
        assert self._resolve("iic/SenseVoiceSmall", "auto", None, True) == "funasr"

    def test_sensevoice_explicit_override(self) -> None:
        assert self._resolve("iic/SenseVoiceSmall", "pyannote", "funasr", True) == "pyannote"
        assert self._resolve("iic/SenseVoiceSmall", "funasr", "pyannote", True) == "funasr"

    def test_funasr_unavailable_falls_back_to_pyannote(self) -> None:
        assert self._resolve("iic/SenseVoiceSmall", "funasr", "funasr", False) == "pyannote"

    def test_unknown_value_falls_back_to_pyannote(self) -> None:
        assert self._resolve("iic/SenseVoiceSmall", "garbage", "funasr", True) == "pyannote"
