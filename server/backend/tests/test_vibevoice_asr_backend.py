"""Regression tests for VibeVoice-ASR backend import compatibility."""

from __future__ import annotations

import importlib
import types

import numpy as np
import pytest

# Ensure the torch stub from conftest.py is installed for every test in this module.
pytestmark = pytest.mark.usefixtures("torch_stub")


def _import_vibevoice_backend_module():
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


def test_vibevoice_backend_load_falls_back_to_modular_import_layout(
    monkeypatch,
) -> None:
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


def test_parse_vibevoice_structured_output_handles_assistant_prefixed_json() -> None:
    module = _import_vibevoice_backend_module()
    text = 'Assistant [{"Start":0,"End":9.8,"Speaker":0,"Content":"hello from vibevoice"}]'

    segments = module._parse_vibevoice_structured_output(text)

    assert segments == [
        {
            "text": "hello from vibevoice",
            "start": 0.0,
            "end": 9.8,
            "speaker": "SPEAKER_00",
        }
    ]


def test_parse_vibevoice_structured_output_repairs_missing_closers() -> None:
    module = _import_vibevoice_backend_module()
    text = '[{"Start":0,"End":1.2,"Speaker":0,"Content":"hello"}'

    segments, mode, stats = module._parse_vibevoice_structured_output_detailed(text)

    assert mode in {"embedded_json", "repaired_json"}
    assert stats["unbalanced"] is True
    assert segments == [
        {"text": "hello", "start": 0.0, "end": 1.2, "speaker": "SPEAKER_00"},
    ]


def test_parse_vibevoice_structured_output_salvages_complete_objects_from_truncated_array() -> None:
    module = _import_vibevoice_backend_module()
    text = (
        '[{"Start":0,"End":1.0,"Speaker":0,"Content":"alpha"},'
        '{"Start":1.0,"End":2.0,"Speaker":1,"Content.'
    )

    segments, mode, _stats = module._parse_vibevoice_structured_output_detailed(text)

    assert mode in {"embedded_json", "segment_salvage", "repaired_json"}
    assert segments
    assert segments[0]["text"] == "alpha"
    assert segments[0]["speaker"] == "SPEAKER_00"


def test_normalize_vibevoice_segments_accepts_single_segment_title_case_dict() -> None:
    module = _import_vibevoice_backend_module()
    payload = {"Start": 1.25, "End": 2.5, "Speaker": "2", "Content": "Hi"}

    segments = module._normalize_vibevoice_segments(payload)

    assert segments == [
        {
            "text": "Hi",
            "start": 1.25,
            "end": 2.5,
            "speaker": "SPEAKER_02",
        }
    ]


def test_extract_plaintext_from_jsonish_output_uses_content_field() -> None:
    module = _import_vibevoice_backend_module()

    text = '[{"Start":0,"End":1,"Speaker":0,"Content":"hello world"}'

    assert module._extract_plaintext_from_jsonish_output(text) == "hello world"


def test_extract_plaintext_from_jsonish_output_handles_partial_content_string() -> None:
    module = _import_vibevoice_backend_module()

    text = '[{"Start":0,"End":1,"Speaker":0,"Content":"hello partial'

    assert module._extract_plaintext_from_jsonish_output(text) == "hello partial"


def test_decode_generated_text_prefers_batch_decode() -> None:
    module = _import_vibevoice_backend_module()

    class _TokenIds:
        def detach(self):  # type: ignore[no-untyped-def]
            return self

        def cpu(self):  # type: ignore[no-untyped-def]
            return self

        def unsqueeze(self, dim: int):  # type: ignore[no-untyped-def]
            assert dim == 0
            return ["batched"]

    class _Processor:
        def batch_decode(self, ids, skip_special_tokens=True):  # type: ignore[no-untyped-def]
            assert ids == ["batched"]
            assert skip_special_tokens is True
            return ["decoded-via-batch"]

        def decode(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("decode() should not be called when batch_decode is available")

    assert module._decode_generated_text(_Processor(), _TokenIds()) == "decoded-via-batch"


def test_vibevoice_generate_uses_backend_specific_defaults_and_config_overrides(
    monkeypatch,
) -> None:
    module = _import_vibevoice_backend_module()
    backend = module.VibeVoiceASRBackend()
    backend._model = types.SimpleNamespace()
    backend._device = "cpu"
    backend._target_sample_rate = 24000
    backend._num_beams = 1
    backend._temperature = 0.0
    backend._max_new_tokens = 1234

    class _Tokenizer:
        eos_token_id = 42
        pad_token_id = 42

    class _Processor:
        tokenizer = _Tokenizer()

    backend._processor = _Processor()

    class _FakeTensor(module.torch.Tensor):  # type: ignore[misc]
        def __init__(self, data):  # type: ignore[no-untyped-def]
            self._data = np.asarray(data)

        @property
        def ndim(self):  # type: ignore[no-untyped-def]
            return self._data.ndim

        @property
        def shape(self):  # type: ignore[no-untyped-def]
            return self._data.shape

        def __getitem__(self, item):  # type: ignore[no-untyped-def]
            result = self._data[item]
            if isinstance(result, np.ndarray):
                return _FakeTensor(result)
            return result

    captured_kwargs: dict[str, object] = {}

    def fake_generate(**kwargs):  # type: ignore[no-untyped-def]
        captured_kwargs.update(kwargs)
        return _FakeTensor([[1, 2, 3]])

    backend._model.generate = fake_generate  # type: ignore[attr-defined]

    monkeypatch.setattr(module, "_resample_audio", lambda audio, **_kwargs: audio)
    monkeypatch.setattr(
        module,
        "_call_vibevoice_processor",
        lambda *_args, **_kwargs: ({"input_ids": _FakeTensor([[1, 2]])}, "raw-array"),
    )
    monkeypatch.setattr(module, "_move_inputs_to_device", lambda inputs, _device: inputs)
    monkeypatch.setattr(module, "_decode_generated_text", lambda *_args, **_kwargs: "[]")
    monkeypatch.setattr(
        module,
        "_parse_vibevoice_structured_output_detailed",
        lambda *_args, **_kwargs: (
            [{"text": "ok", "start": 0.0, "end": 1.0, "speaker": None}],
            "direct_json",
            {
                "has_json_start": True,
                "unbalanced": False,
                "in_string": False,
                "bracket_depth": 0,
                "brace_depth": 0,
            },
        ),
    )

    segments = backend._generate_segments(
        np.zeros(16, dtype=np.float32),
        audio_sample_rate=24000,
        language=None,
        beam_size=7,  # ignored in favor of VibeVoice-specific config
    )

    assert segments[0]["text"] == "ok"
    assert captured_kwargs["num_beams"] == 1
    assert captured_kwargs["temperature"] == 0.0
    assert captured_kwargs["max_new_tokens"] == 1234
    assert captured_kwargs["do_sample"] is False
