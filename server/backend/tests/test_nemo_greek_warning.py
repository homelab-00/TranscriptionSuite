"""NeMo backends must warn (once per instance) when asked for Greek output.

The NeMo tokenizers (canary-1b-v2, parakeet-tdt-0.6b-v3) lack ς (U+03C2), so
Greek word endings come out truncated ("σας" -> "σα"), occasionally with a
stray " ⁇ " unk marker in their place. This is an unfixable upstream model
defect (https://huggingface.co/nvidia/canary-1b-v2/discussions/26); the
backends surface it in the server log and the dashboard shows a matching
warning (modelCapabilities.truncatesGreekFinalSigma).
"""

from __future__ import annotations

import logging

import numpy as np
import pytest
from server.core.stt.backends.base import BackendSegment, BackendTranscriptionInfo
from server.core.stt.backends.canary_backend import CanaryBackend
from server.core.stt.backends.parakeet_backend import SAMPLE_RATE, ParakeetBackend


def _sigma_warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "ς" in r.getMessage()]


class TestParakeetGreekWarning:
    @pytest.fixture()
    def backend(self, monkeypatch):
        b = ParakeetBackend()
        b._model = object()
        b._warmup_complete = True

        def fake_short(self, audio, *, word_timestamps=True, language=None):
            return [], BackendTranscriptionInfo(language=language or "en")

        monkeypatch.setattr(ParakeetBackend, "_transcribe_short", fake_short)
        return b

    def test_greek_request_logs_warning_once(self, backend, caplog):
        audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
        with caplog.at_level(logging.WARNING):
            backend.transcribe(audio, language="el")
            backend.transcribe(audio, language="el")

        assert len(_sigma_warnings(caplog)) == 1

    def test_non_greek_request_does_not_warn(self, backend, caplog):
        audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
        with caplog.at_level(logging.WARNING):
            backend.transcribe(audio, language="en")

        assert _sigma_warnings(caplog) == []


class TestCanaryGreekWarning:
    @pytest.fixture()
    def backend(self, monkeypatch):
        b = CanaryBackend()
        b._model = object()

        def fake_short(self, audio, *, source_lang, target_lang, word_timestamps=True):
            segments = [BackendSegment(text="ok", start=0.0, end=1.0)]
            return segments, BackendTranscriptionInfo(language=source_lang)

        monkeypatch.setattr(CanaryBackend, "_transcribe_short_canary", fake_short)
        return b

    def test_greek_transcription_logs_warning_once(self, backend, caplog):
        audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
        with caplog.at_level(logging.WARNING):
            backend.transcribe(audio, language="el", task="transcribe")
            backend.transcribe(audio, language="el", task="transcribe")

        assert len(_sigma_warnings(caplog)) == 1

    def test_translation_into_greek_also_warns(self, backend, caplog):
        audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
        with caplog.at_level(logging.WARNING):
            backend.transcribe(
                audio, language="en", task="translate", translation_target_language="el"
            )

        assert len(_sigma_warnings(caplog)) == 1

    def test_translation_out_of_greek_does_not_warn(self, backend, caplog):
        # el -> en translation produces English text: final sigma is irrelevant.
        audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
        with caplog.at_level(logging.WARNING):
            backend.transcribe(audio, language="el", task="translate")

        assert _sigma_warnings(caplog) == []
