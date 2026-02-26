"""Regression tests for VibeVoice-ASR backend import compatibility."""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pytest


def _install_minimal_torch_stub() -> None:
    if "torch" in sys.modules:
        return

    torch_stub = types.ModuleType("torch")
    torch_stub.float16 = "float16"
    torch_stub.float32 = "float32"
    torch_stub.bfloat16 = "bfloat16"
    torch_stub.dtype = object
    torch_stub.cuda = types.SimpleNamespace(
        is_available=lambda: False,
        is_bf16_supported=lambda: False,
        empty_cache=lambda: None,
        synchronize=lambda: None,
    )
    sys.modules["torch"] = torch_stub


def _ensure_server_package_alias() -> None:
    if "server" in sys.modules:
        return

    backend_root = Path(__file__).resolve().parents[1]
    init_file = backend_root / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "server",
        init_file,
        submodule_search_locations=[str(backend_root)],
    )
    assert spec is not None and spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules["server"] = module
    spec.loader.exec_module(module)


def _import_vibevoice_backend_module():
    _install_minimal_torch_stub()
    _ensure_server_package_alias()
    return importlib.import_module("server.core.stt.backends.vibevoice_asr_backend")


class _FakeConfig:
    def get(self, key: str, default=None):  # type: ignore[no-untyped-def]
        del key
        return default


class _FakeProcessor:
    calls: list[tuple[str, dict[str, object]]] = []

    @classmethod
    def from_pretrained(cls, model_name: str, **kwargs: object) -> _FakeProcessor:
        cls.calls.append((model_name, kwargs))
        return cls()


class _FakeModelInstance:
    def __init__(self) -> None:
        self.device: str | None = None
        self.evaluated = False

    def to(self, device: str) -> _FakeModelInstance:
        self.device = device
        return self

    def eval(self) -> None:
        self.evaluated = True


class _FakeModel:
    calls: list[tuple[str, dict[str, object]]] = []
    last_instance: _FakeModelInstance | None = None

    @classmethod
    def from_pretrained(cls, model_name: str, **kwargs: object) -> _FakeModelInstance:
        cls.calls.append((model_name, kwargs))
        instance = _FakeModelInstance()
        cls.last_instance = instance
        return instance


def _reset_fake_classes() -> None:
    _FakeProcessor.calls = []
    _FakeModel.calls = []
    _FakeModel.last_instance = None


def _module_with_symbol(symbol_name: str, symbol: object) -> types.ModuleType:
    mod = types.ModuleType(f"stub_{symbol_name}")
    setattr(mod, symbol_name, symbol)
    return mod


def test_vibevoice_backend_load_supports_legacy_import_layout(monkeypatch) -> None:
    module = _import_vibevoice_backend_module()
    _reset_fake_classes()
    monkeypatch.setattr(module, "get_config", _FakeConfig)

    import_calls: list[str] = []

    def fake_import_module(name: str):  # type: ignore[no-untyped-def]
        import_calls.append(name)
        if name == "vibevoice":
            return types.ModuleType("vibevoice")
        if name == "vibevoice.modeling_vibevoice_asr":
            return _module_with_symbol("VibeVoiceASRForConditionalGeneration", _FakeModel)
        if name == "vibevoice.processor.vibevoice_asr_processing":
            return _module_with_symbol("VibeVoiceASRProcessor", _FakeProcessor)
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(module.importlib, "import_module", fake_import_module)

    backend = module.VibeVoiceASRBackend()
    backend.load(model_name="microsoft/VibeVoice-ASR", device="cpu")

    assert backend.is_loaded()
    assert _FakeProcessor.calls
    assert _FakeModel.calls
    assert import_calls[:3] == [
        "vibevoice",
        "vibevoice.modeling_vibevoice_asr",
        "vibevoice.processor.vibevoice_asr_processing",
    ]


def test_vibevoice_backend_load_falls_back_to_modular_import_layout(monkeypatch) -> None:
    module = _import_vibevoice_backend_module()
    _reset_fake_classes()
    monkeypatch.setattr(module, "get_config", _FakeConfig)

    import_calls: list[str] = []

    def fake_import_module(name: str):  # type: ignore[no-untyped-def]
        import_calls.append(name)
        if name == "vibevoice":
            return types.ModuleType("vibevoice")
        if name in {
            "vibevoice.modeling_vibevoice_asr",
            "vibevoice.processor.vibevoice_asr_processing",
        }:
            raise ModuleNotFoundError(name)
        if name == "vibevoice.modular.modeling_vibevoice_asr":
            return _module_with_symbol("VibeVoiceASRForConditionalGeneration", _FakeModel)
        if name == "vibevoice.processor.vibevoice_asr_processor":
            return _module_with_symbol("VibeVoiceASRProcessor", _FakeProcessor)
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(module.importlib, "import_module", fake_import_module)

    backend = module.VibeVoiceASRBackend()
    backend.load(model_name="microsoft/VibeVoice-ASR", device="cpu")

    assert backend.is_loaded()
    assert "vibevoice.modeling_vibevoice_asr" in import_calls
    assert "vibevoice.modular.modeling_vibevoice_asr" in import_calls
    assert import_calls.index("vibevoice.modeling_vibevoice_asr") < import_calls.index(
        "vibevoice.modular.modeling_vibevoice_asr"
    )


def test_vibevoice_import_error_includes_layout_drift_diagnostics(monkeypatch) -> None:
    module = _import_vibevoice_backend_module()

    def fake_import_module(name: str):  # type: ignore[no-untyped-def]
        if name == "vibevoice":
            return types.ModuleType("vibevoice")
        raise ModuleNotFoundError(f"No module named {name}")

    monkeypatch.setattr(module.importlib, "import_module", fake_import_module)

    with pytest.raises(ImportError) as exc_info:
        module._import_vibevoice_asr_classes()

    message = str(exc_info.value)
    assert "possible upstream package layout drift" in message
    assert "VIBEVOICE_ASR_PACKAGE_SPEC" in message
    assert "vibevoice.modeling_vibevoice_asr" in message
    assert "vibevoice.modular.modeling_vibevoice_asr" in message


def test_call_vibevoice_processor_prefers_raw_array_format() -> None:
    module = _import_vibevoice_backend_module()

    class _Processor:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def __call__(self, **kwargs: object):  # type: ignore[no-untyped-def]
            self.calls.append(kwargs)
            return {"ok": True}

    processor = _Processor()
    audio = np.zeros(16, dtype=np.float32)

    result, mode = module._call_vibevoice_processor(processor, audio=audio, sample_rate=24000)

    assert result == {"ok": True}
    assert mode == "raw-array"
    assert len(processor.calls) == 1
    assert processor.calls[0]["sampling_rate"] == 24000
    audio_arg = processor.calls[0]["audio"]
    assert isinstance(audio_arg, list) and len(audio_arg) == 1
    np.testing.assert_allclose(audio_arg[0], audio)


def test_call_vibevoice_processor_falls_back_to_tuple_format() -> None:
    module = _import_vibevoice_backend_module()

    class _Processor:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def __call__(self, **kwargs: object):  # type: ignore[no-untyped-def]
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise ValueError("setting an array element with a sequence")
            return {"ok": True}

    processor = _Processor()
    audio = np.zeros(8, dtype=np.float32)

    result, mode = module._call_vibevoice_processor(processor, audio=audio, sample_rate=24000)

    assert result == {"ok": True}
    assert mode == "tuple+sr"
    assert len(processor.calls) == 2
    assert processor.calls[0]["sampling_rate"] == 24000
    assert processor.calls[1]["sampling_rate"] is None
    audio_arg = processor.calls[1]["audio"]
    assert isinstance(audio_arg, list) and len(audio_arg) == 1
    item = audio_arg[0]
    assert isinstance(item, tuple) and len(item) == 2
    np.testing.assert_allclose(item[0], audio)
    assert item[1] == 24000


def test_vibevoice_backend_reports_preferred_input_sample_rate() -> None:
    module = _import_vibevoice_backend_module()
    backend = module.VibeVoiceASRBackend()

    assert backend.preferred_input_sample_rate_hz == 24000

    backend._target_sample_rate = 32000
    assert backend.preferred_input_sample_rate_hz == 32000


def test_vibevoice_transcribe_with_diarization_accepts_audio_sample_rate_kwarg() -> None:
    module = _import_vibevoice_backend_module()
    backend = module.VibeVoiceASRBackend()

    calls: list[dict[str, object]] = []

    backend._generate_segments = lambda *args, **kwargs: (  # type: ignore[method-assign]
        calls.append(kwargs)
        or [
            {"text": "hello", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
            {"text": "world", "start": 1.0, "end": 2.0, "speaker": "SPEAKER_01"},
        ]
    )

    result = backend.transcribe_with_diarization(
        np.zeros(32, dtype=np.float32),
        audio_sample_rate=24000,
        beam_size=3,
    )

    assert result is not None
    assert result.num_speakers == 2
    assert len(result.segments) == 2
    assert calls[0]["audio_sample_rate"] == 24000
    assert calls[0]["beam_size"] == 3


def test_resample_audio_noop_when_sample_rate_matches() -> None:
    module = _import_vibevoice_backend_module()
    audio = np.array([0.0, 0.25, -0.5], dtype=np.float32)

    out = module._resample_audio(audio, src_rate=24000, dst_rate=24000)

    assert out.dtype == np.float32
    np.testing.assert_allclose(out, audio)
