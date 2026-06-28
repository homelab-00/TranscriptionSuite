"""Unit tests for SenseVoiceBackend (funasr stubbed — no model download)."""

from __future__ import annotations

import os
import re
import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


class _FakeAutoModel:
    """Minimal stub for ``funasr.AutoModel``."""

    def __init__(self, result: list[dict[str, Any]] | None = None):
        # Default: one merged-text result, no sentence_info, no timestamps.
        self._result = (
            result
            if result is not None
            else [{"key": "x", "text": "<|en|><|NEUTRAL|><|Speech|>Hello world."}]
        )
        self.generate = MagicMock(side_effect=lambda **kw: self._result)


def _make_funasr_stub(model: _FakeAutoModel | None = None) -> dict[str, Any]:
    """sys.modules patch dict stubbing funasr + its postprocess submodule."""
    fake = model or _FakeAutoModel()

    funasr_mod = types.ModuleType("funasr")
    funasr_mod.AutoModel = MagicMock(return_value=fake)  # type: ignore[attr-defined]

    utils_mod = types.ModuleType("funasr.utils")
    postproc_mod = types.ModuleType("funasr.utils.postprocess_utils")
    # Strip every <|...|> rich-transcription token, like the real helper does.
    postproc_mod.rich_transcription_postprocess = (  # type: ignore[attr-defined]
        lambda s: re.sub(r"<\|[^|]*\|>", "", s).strip()
    )
    return {
        "funasr": funasr_mod,
        "funasr.utils": utils_mod,
        "funasr.utils.postprocess_utils": postproc_mod,
    }


class TestLifecycle:
    def test_not_loaded_initially(self) -> None:
        from server.core.stt.backends.sensevoice_backend import SenseVoiceBackend

        assert SenseVoiceBackend().is_loaded() is False

    def test_load_sets_loaded_and_cuda_device(self) -> None:
        from server.core.stt.backends.sensevoice_backend import SenseVoiceBackend

        stubs = _make_funasr_stub()
        with patch.dict(sys.modules, stubs):
            backend = SenseVoiceBackend()
            backend.load("iic/SenseVoiceSmall", device="cuda", gpu_device_index=0)
            assert backend.is_loaded()
            call_kwargs = stubs["funasr"].AutoModel.call_args.kwargs
            assert call_kwargs["model"] == "iic/SenseVoiceSmall"
            assert call_kwargs["device"] == "cuda:0"
            assert call_kwargs["vad_model"] == "fsmn-vad"
            assert call_kwargs["hub"] == "hf"

    def test_unload_clears_model(self) -> None:
        from server.core.stt.backends.sensevoice_backend import SenseVoiceBackend

        stubs = _make_funasr_stub()
        with patch.dict(sys.modules, stubs):
            backend = SenseVoiceBackend()
            backend.load("iic/SenseVoiceSmall", device="cpu")
        with patch("server.core.stt.backends.sensevoice_backend.clear_gpu_cache"):
            backend.unload()
        assert backend.is_loaded() is False

    def test_metadata(self) -> None:
        from server.core.stt.backends.sensevoice_backend import SenseVoiceBackend

        backend = SenseVoiceBackend()
        assert backend.backend_name == "sensevoice"
        assert backend.supports_translation() is False

    def test_load_cpu_device_passes_through(self) -> None:
        from server.core.stt.backends.sensevoice_backend import SenseVoiceBackend

        stubs = _make_funasr_stub()
        with patch.dict(sys.modules, stubs):
            backend = SenseVoiceBackend()
            backend.load("iic/SenseVoiceSmall", device="cpu")
            call_kwargs = stubs["funasr"].AutoModel.call_args.kwargs
            assert call_kwargs["device"] == "cpu"

    def test_load_without_funasr_raises_dependency_error(self) -> None:
        from server.core.stt.backends.base import BackendDependencyError
        from server.core.stt.backends.sensevoice_backend import SenseVoiceBackend

        # sys.modules["funasr"] = None makes `import funasr` raise ImportError.
        with patch.dict(sys.modules, {"funasr": None}):
            with pytest.raises(BackendDependencyError, match="FunASR"):
                SenseVoiceBackend().load("iic/SenseVoiceSmall", device="cpu")

    def test_warmup_noop_when_not_loaded(self) -> None:
        from server.core.stt.backends.sensevoice_backend import SenseVoiceBackend

        # No model loaded — must return without error and without calling generate.
        SenseVoiceBackend().warmup()


class TestTranscribe:
    def _loaded(self, model: _FakeAutoModel) -> Any:
        from server.core.stt.backends.sensevoice_backend import SenseVoiceBackend

        stubs = _make_funasr_stub(model)
        with patch.dict(sys.modules, stubs):
            backend = SenseVoiceBackend()
            backend.load("iic/SenseVoiceSmall", device="cpu")
        return backend, stubs

    def test_raises_if_not_loaded(self) -> None:
        from server.core.stt.backends.sensevoice_backend import SenseVoiceBackend

        with pytest.raises(RuntimeError, match="not loaded"):
            SenseVoiceBackend().transcribe(np.zeros(16000, dtype=np.float32))

    def test_merged_text_single_segment_strips_tokens(self) -> None:
        fake = _FakeAutoModel([{"text": "<|en|><|HAPPY|><|Speech|>Hello world."}])
        backend, stubs = self._loaded(fake)
        audio = np.zeros(32000, dtype=np.float32)  # 2.0 s @ 16 kHz
        with patch.dict(sys.modules, stubs):
            segments, info = backend.transcribe(audio, audio_sample_rate=16000)
        assert len(segments) == 1
        assert segments[0].text == "Hello world."
        assert segments[0].start == 0.0
        assert segments[0].end == pytest.approx(2.0)
        assert segments[0].words == []
        assert info.language == "en"

    def test_sentence_info_yields_per_sentence_segments(self) -> None:
        fake = _FakeAutoModel(
            [
                {
                    "text": "<|zh|>whatever",
                    "sentence_info": [
                        {"text": "<|en|>First.", "start": 0, "end": 1000},
                        {"text": "<|en|>Second.", "start": 1000, "end": 2500},
                    ],
                }
            ]
        )
        backend, stubs = self._loaded(fake)
        with patch.dict(sys.modules, stubs):
            segments, _ = backend.transcribe(np.zeros(40000, dtype=np.float32))
        assert [s.text for s in segments] == ["First.", "Second."]
        assert segments[0].start == 0.0 and segments[0].end == pytest.approx(1.0)
        assert segments[1].start == pytest.approx(1.0) and segments[1].end == pytest.approx(2.5)

    def test_empty_result_is_safe(self) -> None:
        backend, stubs = self._loaded(_FakeAutoModel([]))
        with patch.dict(sys.modules, stubs):
            segments, info = backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert segments == []
        assert info.language is None

    def test_unsupported_language_falls_back_to_auto(self) -> None:
        fake = _FakeAutoModel()
        backend, stubs = self._loaded(fake)
        with patch.dict(sys.modules, stubs):
            backend.transcribe(np.zeros(16000, dtype=np.float32), language="el")
        # funasr.generate was called with language="auto" (Greek is unsupported).
        assert fake.generate.call_args.kwargs["language"] == "auto"

    def test_forced_language_used_when_no_token_in_text(self) -> None:
        # No <|xx|> token in text, but a supported language was explicitly requested.
        fake = _FakeAutoModel([{"text": "Hello with no token."}])
        backend, stubs = self._loaded(fake)
        with patch.dict(sys.modules, stubs):
            segments, info = backend.transcribe(np.zeros(16000, dtype=np.float32), language="ja")
        assert info.language == "ja"
        assert segments[0].text == "Hello with no token."

    def test_temp_wav_removed_on_generate_error(self) -> None:
        import server.core.stt.backends.sensevoice_backend as mod

        fake = _FakeAutoModel()
        backend, stubs = self._loaded(fake)
        fake.generate.side_effect = RuntimeError("decode failed")

        created: list[str] = []
        orig_write = mod._write_temp_wav

        def spy(audio, sr):
            path = orig_write(audio, sr)
            created.append(path)
            return path

        with patch.dict(sys.modules, stubs), patch.object(mod, "_write_temp_wav", spy):
            with pytest.raises(RuntimeError, match="decode failed"):
                backend.transcribe(np.zeros(16000, dtype=np.float32))
        # The finally-block must have removed the temp file despite the error.
        assert created and not os.path.exists(created[0])
