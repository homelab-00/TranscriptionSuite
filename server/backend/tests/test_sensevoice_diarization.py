"""Tests for SenseVoice diarization: engine resolver, route predicate,
CAM++ single-pass parsing, and the harmonized transcribe parser.
funasr is stubbed via sys.modules — no model download."""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

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


# --- shared funasr stub (spk-aware) ---------------------------------------


class _FakeAutoModel:
    def __init__(self, result: list[dict[str, Any]] | None = None):
        self._result = result if result is not None else [{"text": "<|en|>Hi."}]
        self.generate = MagicMock(side_effect=lambda **kw: self._result)


def _funasr_stub(model: _FakeAutoModel) -> dict[str, Any]:
    import re

    funasr_mod = types.ModuleType("funasr")
    funasr_mod.AutoModel = MagicMock(return_value=model)  # type: ignore[attr-defined]
    utils_mod = types.ModuleType("funasr.utils")
    postproc_mod = types.ModuleType("funasr.utils.postprocess_utils")
    postproc_mod.rich_transcription_postprocess = (  # type: ignore[attr-defined]
        lambda s: re.sub(r"<\|[^|]*\|>", "", s).strip()
    )
    return {
        "funasr": funasr_mod,
        "funasr.utils": utils_mod,
        "funasr.utils.postprocess_utils": postproc_mod,
    }


def _load(model: _FakeAutoModel, *, cam: bool = True):
    from server.core.stt.backends.sensevoice_backend import SenseVoiceBackend

    stubs = _funasr_stub(model)
    with patch.dict(sys.modules, stubs):
        backend = SenseVoiceBackend()
        backend.load("iic/SenseVoiceSmall", device="cpu", sensevoice_diarization=cam)
    return backend, stubs


class TestAlwaysLoadCamPP:
    def test_load_builds_with_spk_model_when_enabled(self) -> None:
        model = _FakeAutoModel()
        backend, stubs = _load(model, cam=True)
        kwargs = stubs["funasr"].AutoModel.call_args.kwargs
        assert kwargs["spk_model"] == "cam++"
        assert kwargs["spk_mode"] == "vad_segment"
        assert kwargs["vad_model"] == "fsmn-vad"
        assert backend._diarization_loaded is True

    def test_load_omits_spk_model_when_disabled(self) -> None:
        model = _FakeAutoModel()
        backend, stubs = _load(model, cam=False)
        kwargs = stubs["funasr"].AutoModel.call_args.kwargs
        assert "spk_model" not in kwargs
        assert backend._diarization_loaded is False

    def test_transcribe_reads_sentence_key(self) -> None:
        # With cam++ loaded, segments arrive under "sentence", not "text".
        model = _FakeAutoModel(
            [
                {
                    "text": "<|en|>full",
                    "sentence_info": [
                        {"sentence": "<|en|>Hello.", "start": 0, "end": 1000, "spk": 0},
                    ],
                }
            ]
        )
        backend, stubs = _load(model, cam=True)
        with patch.dict(sys.modules, stubs):
            segments, _ = backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert [s.text for s in segments] == ["Hello."]

    def test_transcribe_still_reads_text_key(self) -> None:
        # Back-compat: plain (no-spk) sentence_info using the legacy "text" key.
        model = _FakeAutoModel(
            [
                {
                    "text": "<|en|>full",
                    "sentence_info": [
                        {"text": "<|en|>Legacy.", "start": 0, "end": 1000},
                    ],
                }
            ]
        )
        backend, stubs = _load(model, cam=False)
        with patch.dict(sys.modules, stubs):
            segments, _ = backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert [s.text for s in segments] == ["Legacy."]

    def test_cam_build_fails_falls_back_to_transcriber_only(self) -> None:
        from server.core.stt.backends.sensevoice_backend import SenseVoiceBackend

        model = _FakeAutoModel()
        stubs = _funasr_stub(model)
        # First AutoModel(...) (with spk keys) raises; retry without spk keys succeeds.
        stubs["funasr"].AutoModel.side_effect = [RuntimeError("cam++ unavailable"), model]
        with patch.dict(sys.modules, stubs):
            backend = SenseVoiceBackend()
            backend.load("iic/SenseVoiceSmall", device="cpu", sensevoice_diarization=True)
        assert backend.is_loaded()
        assert backend._diarization_loaded is False
        second_call_kwargs = stubs["funasr"].AutoModel.call_args_list[1].kwargs
        assert "spk_model" not in second_call_kwargs
        assert "spk_mode" not in second_call_kwargs


class TestCamPPSinglePass:
    def test_parses_spk_into_speaker_labels(self) -> None:
        model = _FakeAutoModel(
            [
                {
                    "text": "<|en|>full",
                    "sentence_info": [
                        {"sentence": "<|en|>Hi there.", "start": 0, "end": 1500, "spk": 0},
                        {"sentence": "<|en|>Hello back.", "start": 1500, "end": 3000, "spk": 1},
                    ],
                }
            ]
        )
        backend, stubs = _load(model, cam=True)
        with patch.dict(sys.modules, stubs):
            res = backend.transcribe_with_diarization(np.zeros(48000, dtype=np.float32))
        assert res is not None
        assert [s["speaker"] for s in res.segments] == ["SPEAKER_00", "SPEAKER_01"]
        assert [s["text"] for s in res.segments] == ["Hi there.", "Hello back."]
        assert res.segments[0]["start"] == 0.0 and res.segments[0]["end"] == pytest.approx(1.5)
        assert res.words == []
        assert res.num_speakers == 2

    def test_single_speaker_all_spk0(self) -> None:
        model = _FakeAutoModel(
            [
                {
                    "text": "<|en|>full",
                    "sentence_info": [
                        {"sentence": "<|en|>One.", "start": 0, "end": 1000, "spk": 0},
                        {"sentence": "<|en|>Two.", "start": 1000, "end": 2000, "spk": 0},
                    ],
                }
            ]
        )
        backend, stubs = _load(model, cam=True)
        with patch.dict(sys.modules, stubs):
            res = backend.transcribe_with_diarization(np.zeros(32000, dtype=np.float32))
        assert {s["speaker"] for s in res.segments} == {"SPEAKER_00"}
        assert res.num_speakers == 1

    def test_empty_sentence_info_degrades_to_plain(self) -> None:
        model = _FakeAutoModel([{"text": "<|en|>Just merged text."}])  # no sentence_info
        backend, stubs = _load(model, cam=True)
        with patch.dict(sys.modules, stubs):
            res = backend.transcribe_with_diarization(np.zeros(16000, dtype=np.float32))
        assert res is not None
        assert len(res.segments) == 1
        assert res.segments[0]["text"] == "Just merged text."
        assert res.segments[0]["speaker"] == "UNKNOWN"
        assert res.num_speakers == 0

    def test_diarized_generate_error_degrades_to_plain(self) -> None:
        # The spk-path crash (distribute_spk TypeError) is specific to the
        # diarized call; a plain re-transcribe of the same audio still works.
        model = _FakeAutoModel()
        model.generate.side_effect = [
            TypeError("'>' not supported between 'float' and 'NoneType'"),
            [{"text": "<|en|>Fallback text."}],
        ]
        backend, stubs = _load(model, cam=True)
        with patch.dict(sys.modules, stubs):
            res = backend.transcribe_with_diarization(np.zeros(16000, dtype=np.float32))
        # Transcript preserved, no labels — never dropped.
        assert res is not None
        assert res.num_speakers == 0
        assert res.segments[0]["speaker"] == "UNKNOWN"
        assert res.segments[0]["text"] == "Fallback text."

    def test_none_timing_does_not_drop_transcript(self) -> None:
        # funasr can emit start/end=None on a VAD edge; must NOT raise (never drop).
        model = _FakeAutoModel(
            [
                {
                    "text": "<|en|>full",
                    "sentence_info": [
                        {"sentence": "<|en|>Hi.", "start": None, "end": None, "spk": 0},
                    ],
                }
            ]
        )
        backend, stubs = _load(model, cam=True)
        with patch.dict(sys.modules, stubs):
            res = backend.transcribe_with_diarization(np.zeros(16000, dtype=np.float32))
        assert res is not None
        assert res.segments[0]["text"] == "Hi."
        assert res.segments[0]["start"] == 0.0
        assert res.segments[0]["end"] == 0.0

    def test_raises_if_model_not_loaded(self) -> None:
        from server.core.stt.backends.sensevoice_backend import SenseVoiceBackend

        with pytest.raises(RuntimeError, match="not loaded"):
            SenseVoiceBackend().transcribe_with_diarization(np.zeros(16000, dtype=np.float32))


class TestFormatSpk:
    @pytest.mark.parametrize(
        ("val", "expected"),
        [
            (None, "UNKNOWN"),
            (0, "SPEAKER_00"),
            (2.0, "SPEAKER_02"),
            ("3", "SPEAKER_03"),
            ("", "UNKNOWN"),
        ],
    )
    def test_format_spk(self, val: object, expected: str) -> None:
        from server.core.stt.backends.sensevoice_backend import _format_spk

        assert _format_spk(val) == expected


class TestIntegratedDiarizationPredicate:
    def test_funasr_engine_uses_integrated_for_sensevoice(self) -> None:
        from server.core.stt.backends.base import use_integrated_diarization_for
        from server.core.stt.backends.sensevoice_backend import SenseVoiceBackend

        assert use_integrated_diarization_for(SenseVoiceBackend(), "funasr") is True

    def test_pyannote_engine_skips_integrated(self) -> None:
        from server.core.stt.backends.base import use_integrated_diarization_for
        from server.core.stt.backends.sensevoice_backend import SenseVoiceBackend

        assert use_integrated_diarization_for(SenseVoiceBackend(), "pyannote") is False

    def test_backend_without_override_is_false(self) -> None:
        from server.core.stt.backends.base import STTBackend, use_integrated_diarization_for

        class _Plain(STTBackend):  # minimal stub; does NOT override transcribe_with_diarization
            def load(self, *a, **k): ...
            def unload(self): ...
            def is_loaded(self):
                return True

            def warmup(self): ...
            def transcribe(self, *a, **k): ...
            def supports_translation(self):
                return False

            @property
            def backend_name(self):
                return "plain"

        assert use_integrated_diarization_for(_Plain(), "funasr") is False

    def test_none_backend_is_false(self) -> None:
        from server.core.stt.backends.base import use_integrated_diarization_for

        assert use_integrated_diarization_for(None, "funasr") is False

    def test_non_sensevoice_integrated_backend_keeps_single_pass(self) -> None:
        # WhisperX/VibeVoice override transcribe_with_diarization and must KEEP
        # their single-pass path; the SenseVoice engine resolver (which returns
        # "pyannote" for them) must NOT disable it.
        from server.core.stt.backends.base import (
            DiarizedTranscriptionResult,
            STTBackend,
            use_integrated_diarization_for,
        )

        class _IntegratedNonSenseVoice(STTBackend):
            def load(self, *a, **k): ...
            def unload(self): ...
            def is_loaded(self):
                return True

            def warmup(self): ...
            def transcribe(self, *a, **k): ...
            def supports_translation(self):
                return False

            def transcribe_with_diarization(self, *a, **k):  # overrides the base no-op
                return DiarizedTranscriptionResult(segments=[], words=[], num_speakers=0)

            @property
            def backend_name(self):
                return "whisperx"

        be = _IntegratedNonSenseVoice()
        # Realistic case: resolver returns "pyannote" for non-SenseVoice → still single-pass.
        assert use_integrated_diarization_for(be, "pyannote") is True
        assert use_integrated_diarization_for(be, "funasr") is True


class TestBootstrapWarmDownload:
    def _bootstrap(self):
        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "docker" / "bootstrap_runtime.py"
        spec = importlib.util.spec_from_file_location("bootstrap_warm_under_test", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_warm_download_is_non_fatal_on_failure(self) -> None:
        from pathlib import Path

        bootstrap = self._bootstrap()

        # A venv_python that fails the subprocess must NOT raise.
        result = bootstrap.warm_download_sensevoice_models(
            venv_python=Path("/nonexistent/python"),
            timeout_seconds=30,
        )
        assert result is False  # signalled failure, did not raise
