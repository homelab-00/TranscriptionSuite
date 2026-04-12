"""Regression tests for WhisperX backend signature compatibility."""

from __future__ import annotations

import dataclasses
import importlib
import logging
import sys
import types
import warnings

import numpy as np
import pytest

# Ensure the torch stub from conftest.py is installed for every test in this module.
pytestmark = pytest.mark.usefixtures("torch_stub")


def _install_soundfile_stub() -> None:
    """Stub soundfile so backend imports in the lightweight test env."""
    if "soundfile" not in sys.modules:
        soundfile_stub = types.ModuleType("soundfile")
        soundfile_stub.read = lambda *args, **kwargs: (
            np.zeros(16000, dtype=np.float32),
            16000,
        )
        sys.modules["soundfile"] = soundfile_stub


def _import_whisperx_backend():
    _install_soundfile_stub()
    return importlib.import_module("server.core.stt.backends.whisperx_backend")


@dataclasses.dataclass
class _FakeOptions:
    beam_size: int = 5
    initial_prompt: str | None = None
    suppress_tokens: list[int] = dataclasses.field(default_factory=lambda: [-1])
    vad_filter: bool = True
    no_speech_threshold: float = 0.6
    compression_ratio_threshold: float = 2.4


class _ModernFakeModel:
    """Mimics WhisperX 3.8.x pipeline.transcribe signature."""

    def __init__(self) -> None:
        self.options = _FakeOptions()
        self.calls: list[dict[str, object]] = []
        self.options_seen: list[_FakeOptions] = []

    def transcribe(self, audio, language=None, task=None, batch_size=None):
        self.calls.append(
            {
                "language": language,
                "task": task,
                "audio": audio,
                "batch_size": batch_size,
            }
        )
        self.options_seen.append(self.options)
        return {
            "segments": [{"text": "hello", "start": 0.0, "end": 1.0}],
            "language": "en",
        }


class _LegacyFakeModel:
    """Mimics older WhisperX pipeline.transcribe signature accepting decode kwargs."""

    def __init__(self) -> None:
        self.options = _FakeOptions()
        self.calls: list[dict[str, object]] = []

    def transcribe(
        self,
        audio,
        language=None,
        task=None,
        batch_size=None,
        beam_size=None,
        initial_prompt=None,
        suppress_tokens=None,
        vad_filter=None,
        no_speech_threshold=None,
        compression_ratio_threshold=None,
    ):
        self.calls.append(
            {
                "language": language,
                "task": task,
                "batch_size": batch_size,
                "beam_size": beam_size,
                "initial_prompt": initial_prompt,
                "suppress_tokens": suppress_tokens,
                "vad_filter": vad_filter,
                "no_speech_threshold": no_speech_threshold,
                "compression_ratio_threshold": compression_ratio_threshold,
                "audio": audio,
            }
        )
        return {
            "segments": [{"text": "legacy", "start": 0.0, "end": 0.5}],
            "language": "en",
        }


def test_whisperx_backend_patches_decode_options_for_modern_signature(caplog) -> None:
    module = _import_whisperx_backend()
    caplog.set_level(logging.INFO, logger=module.__name__)
    backend = module.WhisperXBackend()
    fake_model = _ModernFakeModel()
    backend._model = fake_model

    original_options = fake_model.options
    audio = np.zeros(16000, dtype=np.float32)

    segments, info = backend.transcribe(
        audio,
        task="transcribe",
        beam_size=7,
        initial_prompt="system prompt",
        suppress_tokens=[-1, 42],
        word_timestamps=False,
    )

    assert len(fake_model.calls) == 1
    assert fake_model.calls[0]["language"] is None
    assert fake_model.calls[0]["task"] == "transcribe"
    assert fake_model.calls[0]["audio"] is audio
    assert fake_model.options_seen[0].beam_size == 7
    assert fake_model.options_seen[0].initial_prompt == "system prompt"
    assert fake_model.options_seen[0].suppress_tokens == [-1, 42]
    assert fake_model.options is original_options
    assert segments[0].text == "hello"
    assert info.language == "en"
    assert "WhisperX compatibility mode enabled" in caplog.text


def test_whisperx_global_torchcodec_warning_filter_installed() -> None:
    """The module installs a process-global filter for pyannote's torchcodec warning."""
    module = _import_whisperx_backend()

    # Verify the module defines the pattern constant used for the global filter
    assert hasattr(module, "_PYANNOTE_TORCHCODEC_WARNING_RE")
    assert "torchcodec" in module._PYANNOTE_TORCHCODEC_WARNING_RE

    # Functionally verify: re-apply the filter (same as module level) and confirm suppression
    with warnings.catch_warnings(record=True) as caught:
        warnings.filterwarnings(
            "ignore",
            message=module._PYANNOTE_TORCHCODEC_WARNING_RE,
            category=UserWarning,
        )
        warnings.warn(
            "torchcodec is not installed correctly so built-in audio decoding will fail. test",
            UserWarning,
            stacklevel=2,
        )
    torchcodec_caught = [w for w in caught if "torchcodec" in str(w.message)]
    assert len(torchcodec_caught) == 0, "torchcodec warning should be suppressed"


def test_whisperx_backend_uses_legacy_kwargs_when_supported() -> None:
    module = _import_whisperx_backend()
    backend = module.WhisperXBackend()
    fake_model = _LegacyFakeModel()
    backend._model = fake_model

    original_options = fake_model.options
    audio = np.zeros(16000, dtype=np.float32)

    segments, info = backend.transcribe(
        audio,
        language="en",
        task="transcribe",
        beam_size=9,
        initial_prompt="legacy prompt",
        suppress_tokens=[-1, 7],
        word_timestamps=False,
    )

    assert len(fake_model.calls) == 1
    assert fake_model.calls[0]["language"] == "en"
    assert fake_model.calls[0]["task"] == "transcribe"
    assert fake_model.calls[0]["beam_size"] == 9
    assert fake_model.calls[0]["initial_prompt"] == "legacy prompt"
    assert fake_model.calls[0]["suppress_tokens"] == [-1, 7]
    assert fake_model.calls[0]["audio"] is audio
    assert fake_model.options is original_options
    assert segments[0].text == "legacy"
    assert info.language == "en"


def test_whisperx_diarization_path_uses_compat_transcribe(monkeypatch) -> None:
    module = _import_whisperx_backend()
    backend = module.WhisperXBackend()
    fake_model = _ModernFakeModel()
    backend._model = fake_model
    backend._device = "cpu"
    backend._align = lambda wx_result, audio, language: wx_result

    whisperx_mod = types.ModuleType("whisperx")

    def assign_word_speakers(diarize_segments, wx_result):
        assert diarize_segments == [{"speaker": "SPEAKER_00"}]
        wx_result["segments"][0]["speaker"] = "SPEAKER_00"
        wx_result["segments"][0]["words"] = [
            {
                "word": "hi",
                "start": 0.0,
                "end": 0.1,
                "score": 0.9,
                "speaker": "SPEAKER_00",
            }
        ]
        return wx_result

    whisperx_mod.assign_word_speakers = assign_word_speakers

    diarize_mod = types.ModuleType("whisperx.diarize")

    class FakeDiarizationPipeline:
        def __init__(self, use_auth_token, device) -> None:
            assert use_auth_token == "hf_test"
            assert device == "cpu"

        def __call__(self, audio, **kwargs):
            assert kwargs == {}
            return [{"speaker": "SPEAKER_00"}]

    diarize_mod.DiarizationPipeline = FakeDiarizationPipeline

    monkeypatch.setitem(sys.modules, "whisperx", whisperx_mod)
    monkeypatch.setitem(sys.modules, "whisperx.diarize", diarize_mod)

    original_options = fake_model.options
    audio = np.zeros(16000, dtype=np.float32)
    result = backend.transcribe_with_diarization(audio, beam_size=3, hf_token="hf_test")

    assert result is not None
    assert result.num_speakers == 1
    assert result.language == "en"
    assert len(fake_model.calls) == 1
    assert fake_model.calls[0]["language"] is None
    assert fake_model.calls[0]["task"] == "transcribe"
    assert fake_model.calls[0]["audio"] is audio
    assert fake_model.options_seen[0].beam_size == 3
    assert fake_model.options is original_options


def test_whisperx_backend_forwards_batch_size_modern_signature() -> None:
    """batch_size stored during load() must be forwarded to model.transcribe()."""
    module = _import_whisperx_backend()
    backend = module.WhisperXBackend()
    fake_model = _ModernFakeModel()
    backend._model = fake_model
    backend._batch_size = 32

    audio = np.zeros(16000, dtype=np.float32)
    segments, info = backend.transcribe(audio, word_timestamps=False)

    assert len(fake_model.calls) == 1
    assert fake_model.calls[0]["batch_size"] == 32
    assert segments[0].text == "hello"
    assert info.language == "en"


def test_whisperx_backend_forwards_batch_size_legacy_signature() -> None:
    """batch_size must also be forwarded when the model accepts it as a direct kwarg."""
    module = _import_whisperx_backend()
    backend = module.WhisperXBackend()
    fake_model = _LegacyFakeModel()
    backend._model = fake_model
    backend._batch_size = 24

    audio = np.zeros(16000, dtype=np.float32)
    segments, info = backend.transcribe(audio, word_timestamps=False)

    assert len(fake_model.calls) == 1
    assert fake_model.calls[0]["batch_size"] == 24
    assert segments[0].text == "legacy"
    assert info.language == "en"


def test_whisperx_backend_default_batch_size_from_load(monkeypatch) -> None:
    """load() should store batch_size from kwargs (defaulting to 16)."""
    module = _import_whisperx_backend()
    backend = module.WhisperXBackend()

    whisperx_mod = types.ModuleType("whisperx")
    whisperx_mod.load_model = lambda *args, **kwargs: _ModernFakeModel()

    real_import_module = module.importlib.import_module

    def fake_import_module(name: str):
        if name == "whisperx":
            return whisperx_mod
        return real_import_module(name)

    monkeypatch.setattr(module.importlib, "import_module", fake_import_module)

    # Without explicit batch_size → defaults to 16
    backend.load("Systran/faster-whisper-large-v3", "cpu")
    assert backend._batch_size == 16

    # With explicit batch_size
    backend.load("Systran/faster-whisper-large-v3", "cpu", batch_size=4)
    assert backend._batch_size == 4


# ------------------------------------------------------------------
# GH-74: vad_filter forwarding
# ------------------------------------------------------------------


def test_whisperx_vad_filter_patched_on_modern_signature() -> None:
    """vad_filter must reach model via options patch on modern (3.8.x) signature."""
    module = _import_whisperx_backend()
    backend = module.WhisperXBackend()
    fake_model = _ModernFakeModel()
    backend._model = fake_model

    audio = np.zeros(16000, dtype=np.float32)
    backend.transcribe(audio, vad_filter=False, word_timestamps=False)

    # Modern model doesn't accept vad_filter as kwarg → patched onto options
    assert fake_model.options_seen[0].vad_filter is False


def test_whisperx_vad_filter_passed_as_kwarg_on_legacy_signature() -> None:
    """vad_filter must be passed directly when the model signature accepts it."""
    module = _import_whisperx_backend()
    backend = module.WhisperXBackend()
    fake_model = _LegacyFakeModel()
    backend._model = fake_model

    audio = np.zeros(16000, dtype=np.float32)
    backend.transcribe(audio, vad_filter=False, word_timestamps=False)

    assert fake_model.calls[0]["vad_filter"] is False


def test_whisperx_vad_filter_default_is_true() -> None:
    """Default vad_filter=True must still reach the model (backward compat)."""
    module = _import_whisperx_backend()
    backend = module.WhisperXBackend()
    fake_model = _ModernFakeModel()
    backend._model = fake_model

    audio = np.zeros(16000, dtype=np.float32)
    backend.transcribe(audio, word_timestamps=False)

    # Default is True → patched onto options
    assert fake_model.options_seen[0].vad_filter is True


# ------------------------------------------------------------------
# GH-74: decode_options forwarding
# ------------------------------------------------------------------


def test_whisperx_decode_options_patched_on_modern_signature() -> None:
    """Extra decode options from configure_decode_options() must reach model.options."""
    module = _import_whisperx_backend()
    backend = module.WhisperXBackend()
    fake_model = _ModernFakeModel()
    backend._model = fake_model

    backend.configure_decode_options(
        {
            "no_speech_threshold": 0.3,
            "compression_ratio_threshold": 1.8,
        }
    )

    audio = np.zeros(16000, dtype=np.float32)
    backend.transcribe(audio, word_timestamps=False)

    # Modern model doesn't accept these as kwargs → patched onto options
    assert fake_model.options_seen[0].no_speech_threshold == 0.3
    assert fake_model.options_seen[0].compression_ratio_threshold == 1.8


def test_whisperx_decode_options_passed_as_kwargs_on_legacy_signature() -> None:
    """Extra decode options must be passed as kwargs when signature accepts them."""
    module = _import_whisperx_backend()
    backend = module.WhisperXBackend()
    fake_model = _LegacyFakeModel()
    backend._model = fake_model

    backend.configure_decode_options(
        {
            "no_speech_threshold": 0.4,
            "compression_ratio_threshold": 2.0,
        }
    )

    audio = np.zeros(16000, dtype=np.float32)
    backend.transcribe(audio, word_timestamps=False)

    assert fake_model.calls[0]["no_speech_threshold"] == 0.4
    assert fake_model.calls[0]["compression_ratio_threshold"] == 2.0


def test_whisperx_decode_options_default_empty() -> None:
    """Without configure_decode_options(), no extra keys should appear."""
    module = _import_whisperx_backend()
    backend = module.WhisperXBackend()
    fake_model = _LegacyFakeModel()
    backend._model = fake_model

    audio = np.zeros(16000, dtype=np.float32)
    backend.transcribe(audio, word_timestamps=False)

    # no_speech_threshold should not be passed (defaults to None from kwarg)
    assert fake_model.calls[0]["no_speech_threshold"] is None


def test_whisperx_options_restored_after_transcribe() -> None:
    """Pipeline options must be restored even when decode_options are patched."""
    module = _import_whisperx_backend()
    backend = module.WhisperXBackend()
    fake_model = _ModernFakeModel()
    backend._model = fake_model

    original_options = fake_model.options
    backend.configure_decode_options({"no_speech_threshold": 0.2})

    audio = np.zeros(16000, dtype=np.float32)
    backend.transcribe(audio, vad_filter=False, word_timestamps=False)

    # Options must be restored to original after transcribe
    assert fake_model.options is original_options
    assert fake_model.options.no_speech_threshold == 0.6  # original default


# ------------------------------------------------------------------
# GH-74: diarization path param forwarding
# ------------------------------------------------------------------


def test_whisperx_diarization_forwards_initial_prompt_and_suppress_tokens(monkeypatch) -> None:
    """transcribe_with_diarization() must forward initial_prompt, suppress_tokens, vad_filter."""
    module = _import_whisperx_backend()
    backend = module.WhisperXBackend()
    fake_model = _ModernFakeModel()
    backend._model = fake_model
    backend._device = "cpu"
    backend._align = lambda wx_result, audio, language: wx_result

    whisperx_mod = types.ModuleType("whisperx")

    def assign_word_speakers(diarize_segments, wx_result):
        wx_result["segments"][0]["speaker"] = "SPEAKER_00"
        wx_result["segments"][0]["words"] = [
            {"word": "hi", "start": 0.0, "end": 0.1, "score": 0.9, "speaker": "SPEAKER_00"}
        ]
        return wx_result

    whisperx_mod.assign_word_speakers = assign_word_speakers

    diarize_mod = types.ModuleType("whisperx.diarize")

    class FakeDiarizationPipeline:
        def __init__(self, use_auth_token, device) -> None:
            pass

        def __call__(self, audio, **kwargs):
            return [{"speaker": "SPEAKER_00"}]

    diarize_mod.DiarizationPipeline = FakeDiarizationPipeline

    monkeypatch.setitem(sys.modules, "whisperx", whisperx_mod)
    monkeypatch.setitem(sys.modules, "whisperx.diarize", diarize_mod)

    audio = np.zeros(16000, dtype=np.float32)
    result = backend.transcribe_with_diarization(
        audio,
        beam_size=3,
        initial_prompt="technical meeting",
        suppress_tokens=[-1, 50],
        vad_filter=False,
        hf_token="hf_test",
    )

    assert result is not None

    # Verify beam_size was patched (existing behavior)
    assert fake_model.options_seen[0].beam_size == 3

    # Verify initial_prompt was forwarded (NOT None like before)
    assert fake_model.options_seen[0].initial_prompt == "technical meeting"

    # Verify suppress_tokens was forwarded (NOT None like before)
    assert fake_model.options_seen[0].suppress_tokens == [-1, 50]

    # Verify vad_filter was forwarded
    assert fake_model.options_seen[0].vad_filter is False


# ------------------------------------------------------------------
# GH-74: configure_decode_options base class
# ------------------------------------------------------------------


def test_configure_decode_options_creates_instance_copy() -> None:
    """configure_decode_options() must store an instance copy, not mutate class default."""
    module = _import_whisperx_backend()
    backend1 = module.WhisperXBackend()
    backend2 = module.WhisperXBackend()

    backend1.configure_decode_options({"no_speech_threshold": 0.1})

    # backend2 should still have the empty class default
    assert backend2._decode_options == {}
    assert backend1._decode_options == {"no_speech_threshold": 0.1}
