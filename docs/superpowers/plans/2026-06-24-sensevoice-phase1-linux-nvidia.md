# SenseVoice (FunASR) STT Backend — Phase 1 (Linux / NVIDIA, transcriber-only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Alibaba FunAudioLLM's **SenseVoice** model as a new STT backend (`iic/SenseVoiceSmall`) that transcribes on Linux/NVIDIA via the `funasr` PyTorch pipeline, selectable like any other model, with **no** new diarization code (existing pyannote two-pass remains available).

**Architecture:** SenseVoice plugs into the existing backend-factory pattern. A new `SenseVoiceBackend(STTBackend)` wraps `funasr.AutoModel` (SenseVoiceSmall + `fsmn-vad`), returns normalised `BackendSegment`s, and is reached when the model name matches `^<org>/sensevoice…`. Install is gated behind a new `INSTALL_FUNASR` env var mirroring `INSTALL_NEMO`. The dashboard learns the model's capabilities (5 languages, no translation). This is a vertical slice: backend + routing + capability flags + install gate + feature status + UI registry + smoke test.

**Tech Stack:** Python 3.13, `funasr>=1.3.12`, PyTorch (already present for pyannote), FastAPI; TypeScript/React dashboard; pytest (build venv) + Vitest (Node 22).

**Explicitly OUT of scope for Phase 1** (deferred to later phases): FunASR's own CAM++ diarization (`transcribe_with_diarization`), word-level timestamps, emotion/audio-event tags as a product feature, sherpa-onnx / SenseVoice.cpp runtimes, Windows / macOS / Apple-Silicon, ModelScope (CN) download path. SenseVoice **cannot transcribe Greek** — it is a specialist (zh/en/yue/ja/ko), not a Whisper replacement.

---

## Scope Check

This is a single subsystem (one new STT backend on one platform). It produces working, testable software on its own and does not need to be split further.

## File Structure

**New files:**
- `server/backend/core/stt/backends/sensevoice_backend.py` — the `SenseVoiceBackend` class (funasr wrapper). One responsibility: SenseVoice transcription behind the `STTBackend` interface.
- `server/backend/tests/test_sensevoice_backend.py` — unit tests (funasr stubbed via `sys.modules`).
- `server/backend/tests/test_sensevoice_routing.py` — factory + capability + bootstrap-helper routing tests.

**Modified files:**
- `server/backend/core/stt/backends/factory.py` — pattern + `detect_backend_type` branch + `create_backend` branch + `is_sensevoice_model` helper.
- `server/backend/core/stt/capabilities.py` — pattern + `supports_english_translation` returns `False`.
- `server/backend/pyproject.toml` — `sensevoice` optional-dependency extra.
- `server/docker/bootstrap_runtime.py` — `is_sensevoice_model_name`, exclude from `is_whisper_model_name`, `check_funasr_import`, `INSTALL_FUNASR` install block, `sensevoice` in features dict + cache-reuse list.
- `server/backend/core/model_manager.py` — `_initialize_sensevoice_feature_status` + `get_sensevoice_feature_status`.
- `server/config.yaml` — document SenseVoice model id + `INSTALL_FUNASR`.
- `dashboard/src/services/modelCapabilities.ts` — `SENSEVOICE_PATTERN`, `isSenseVoiceModel`, language filter, translation flag, exclude from `isWhisperModel`.
- `dashboard/src/services/modelCapabilities.test.ts` — Vitest coverage.
- `dashboard/src/services/modelRegistry.ts` — `'sensevoice'` family + registry entry.
- `docs/project-context.md`, `README_DEV.md` — note the new backend.

---

## Task 0: Feature branch

- [ ] **Step 1: Create the branch**

Run:
```bash
cd /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite
git checkout -b feature/sensevoice-asr-phase1
```
Expected: `Switched to a new branch 'feature/sensevoice-asr-phase1'`

---

## Task 1: Capability flags (`capabilities.py`)

**Files:**
- Modify: `server/backend/core/stt/capabilities.py:9-13` (patterns), `:64-66` region (translation guard)
- Test: `server/backend/tests/test_sensevoice_routing.py`

- [ ] **Step 1: Write the failing test**

Create `server/backend/tests/test_sensevoice_routing.py`:
```python
"""Routing + capability tests for the SenseVoice (FunASR) backend."""

from __future__ import annotations

import pytest


# --- capabilities.py -------------------------------------------------------

class TestSenseVoiceCapabilities:
    def test_sensevoice_has_no_translation(self) -> None:
        from server.core.stt.capabilities import supports_english_translation

        assert supports_english_translation("iic/SenseVoiceSmall") is False
        assert supports_english_translation("FunAudioLLM/SenseVoiceSmall") is False

    def test_sensevoice_supports_auto_detect(self) -> None:
        from server.core.stt.capabilities import supports_auto_detect

        assert supports_auto_detect("iic/SenseVoiceSmall") is True

    def test_sensevoice_translate_request_rejected(self) -> None:
        from server.core.stt.capabilities import validate_translation_request

        with pytest.raises(ValueError, match="does not support translation"):
            validate_translation_request(
                model_name="iic/SenseVoiceSmall",
                task="translate",
                translation_target_language="en",
            )
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_routing.py::TestSenseVoiceCapabilities -v --tb=short`
Expected: FAIL — `supports_english_translation("iic/SenseVoiceSmall")` currently returns `True` (unknown model default).

- [ ] **Step 3: Add the pattern**

In `server/backend/core/stt/capabilities.py`, after line 13 (`_MLX_CANARY_PATTERN = …`), add:
```python
# SenseVoice (FunAudioLLM) — any "<org>/sensevoice…" repo id.
_SENSEVOICE_PATTERN = re.compile(r"^[^/]+/sensevoice", re.IGNORECASE)
```

- [ ] **Step 4: Return False for translation**

In `supports_english_translation`, immediately after the VibeVoice block (after line 66, the `return False` for `_VIBEVOICE_ASR_PATTERN`), add:
```python
    # SenseVoice (FunASR) is ASR-only in Phase 1 — no translate task.
    if _SENSEVOICE_PATTERN.match(name):
        return False
```

- [ ] **Step 5: Run the test and confirm it passes**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_routing.py::TestSenseVoiceCapabilities -v --tb=short`
Expected: 3 passed. (`validate_translation_request` already raises because it calls `supports_english_translation`.)

- [ ] **Step 6: Commit**

```bash
git add server/backend/core/stt/capabilities.py server/backend/tests/test_sensevoice_routing.py
git commit -m "feat(stt): mark SenseVoice as ASR-only (no translation) in capabilities"
```

---

## Task 2: Factory routing (`factory.py`)

**Files:**
- Modify: `server/backend/core/stt/backends/factory.py` (pattern @ ~26, detect branch @ ~59, helper @ ~93, create branch @ ~136)
- Test: `server/backend/tests/test_sensevoice_routing.py`

- [ ] **Step 1: Write the failing test**

Append to `server/backend/tests/test_sensevoice_routing.py`:
```python
# --- factory.py ------------------------------------------------------------

class TestSenseVoiceFactory:
    @pytest.mark.parametrize(
        "model_name",
        [
            "iic/SenseVoiceSmall",
            "FunAudioLLM/SenseVoiceSmall",
            "iic/SenseVoice-extra",
            "IIC/SENSEVOICESMALL",  # case-insensitive
        ],
    )
    def test_sensevoice_models_detected(self, model_name: str) -> None:
        from server.core.stt.backends.factory import detect_backend_type, is_sensevoice_model

        assert detect_backend_type(model_name) == "sensevoice"
        assert is_sensevoice_model(model_name) is True

    def test_non_sensevoice_unaffected(self) -> None:
        from server.core.stt.backends.factory import detect_backend_type

        assert detect_backend_type("Systran/faster-whisper-large-v3") == "whisper"
        assert detect_backend_type("nvidia/parakeet-tdt-0.6b-v3") == "parakeet"
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_routing.py::TestSenseVoiceFactory -v --tb=short`
Expected: FAIL — `iic/SenseVoiceSmall` currently resolves to `"whisper"` (default branch); `is_sensevoice_model` does not exist.

- [ ] **Step 3: Add the pattern**

In `factory.py`, after line 26 (`_MLX_PATTERN = …`), add:
```python
# SenseVoice (FunAudioLLM) via FunASR — any "<org>/sensevoice…" repo id.
_SENSEVOICE_PATTERN = re.compile(r"^[^/]+/sensevoice", re.IGNORECASE)
```

- [ ] **Step 4: Add the detection branch**

In `detect_backend_type`, immediately before `if _looks_like_whispercpp(name):` (line 60), add:
```python
    if _SENSEVOICE_PATTERN.match(name):
        return "sensevoice"
```

- [ ] **Step 5: Add the `is_sensevoice_model` helper**

After the `is_vibevoice_asr_model` function (line 88-89), add:
```python
def is_sensevoice_model(model_name: str) -> bool:
    """Return True if *model_name* selects the SenseVoice (FunASR) backend."""
    return detect_backend_type(model_name) == "sensevoice"
```

- [ ] **Step 6: Add the instantiation branch**

In `create_backend`, immediately after the `vibevoice_asr` block (after line 136), add:
```python
    if backend_type == "sensevoice":
        from server.core.stt.backends.sensevoice_backend import SenseVoiceBackend

        return SenseVoiceBackend()
```

- [ ] **Step 7: Run the test and confirm it passes**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_routing.py::TestSenseVoiceFactory -v --tb=short`
Expected: 5 passed. (The `create_backend` import target is created in Task 3; detection tests pass now.)

- [ ] **Step 8: Commit**

```bash
git add server/backend/core/stt/backends/factory.py server/backend/tests/test_sensevoice_routing.py
git commit -m "feat(stt): route iic/SenseVoice* model ids to a sensevoice backend"
```

---

## Task 3: `SenseVoiceBackend` implementation

**Files:**
- Create: `server/backend/core/stt/backends/sensevoice_backend.py`
- Test: `server/backend/tests/test_sensevoice_backend.py`

### 3a — Lifecycle (load / unload / is_loaded / metadata)

- [ ] **Step 1: Write the failing test (lifecycle + metadata)**

Create `server/backend/tests/test_sensevoice_backend.py`:
```python
"""Unit tests for SenseVoiceBackend (funasr stubbed — no model download)."""

from __future__ import annotations

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
        self._result = result if result is not None else [{"key": "x", "text": "<|en|><|NEUTRAL|><|Speech|>Hello world."}]
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
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_backend.py::TestLifecycle -v --tb=short`
Expected: FAIL — module `sensevoice_backend` does not exist.

- [ ] **Step 3: Create the backend (full file)**

Create `server/backend/core/stt/backends/sensevoice_backend.py`:
```python
"""SenseVoice (FunAudioLLM) STT backend.

Adapted from FunAudioLLM/SenseVoice (https://github.com/FunAudioLLM/SenseVoice)
and modelscope/FunASR (https://github.com/modelscope/FunASR) — wraps the
``funasr.AutoModel`` pipeline (SenseVoiceSmall + fsmn-vad) behind the project's
STTBackend interface.

Phase 1 scope: transcriber-only, CUDA/Linux. SenseVoice is non-autoregressive
and produces NO word-level timestamps; segments carry empty ``words`` lists and,
when funasr returns no per-sentence info, a single segment spanning the clip.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from server.core.audio_utils import clear_gpu_cache
from server.core.stt.backends.base import (
    BackendSegment,
    BackendTranscriptionInfo,
    STTBackend,
)

SAMPLE_RATE = 16000

# SenseVoiceSmall's first-class language codes (the only values its API accepts).
_SENSEVOICE_LANGUAGES = frozenset({"zh", "en", "yue", "ja", "ko"})
_LANG_TOKEN_RE = re.compile(r"<\|(zh|en|yue|ja|ko)\|>", re.IGNORECASE)

logger = logging.getLogger(__name__)


def _compose_device(device: str, gpu_device_index: int) -> str:
    """Map the engine's ("cuda", index) convention to funasr's "cuda:N" string."""
    if device == "cuda":
        return f"cuda:{int(gpu_device_index)}"
    return device


def _extract_language(raw_text: str) -> str | None:
    """Return the SenseVoice language code embedded in *raw_text*, if any."""
    match = _LANG_TOKEN_RE.search(raw_text or "")
    return match.group(1).lower() if match else None


def _write_temp_wav(audio: np.ndarray, sample_rate: int) -> str:
    """Write float32 mono audio to a temp 16-bit WAV and return its path."""
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="sensevoice_")
    os.close(fd)
    sf.write(path, audio, sample_rate, subtype="PCM_16")
    return path


class SenseVoiceBackend(STTBackend):
    """FunASR-backed SenseVoice transcription backend (Phase 1, CUDA/Linux)."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._model_name: str | None = None
        self._device: str | None = None

    # -- lifecycle ----------------------------------------------------------

    def load(self, model_name: str, device: str, **kwargs: Any) -> None:
        from funasr import AutoModel

        gpu_device_index = kwargs.get("gpu_device_index", 0)
        funasr_device = _compose_device(device, gpu_device_index)

        logger.info(f"Loading SenseVoice model: {model_name} on {funasr_device}")
        # hub="hf": pull weights from HuggingFace, not the CN-hosted ModelScope.
        # disable_update=True: skip the ModelScope version ping (offline-friendly).
        self._model = AutoModel(
            model=model_name,
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": 30000},
            device=funasr_device,
            hub="hf",
            disable_update=True,
        )
        self._model_name = model_name
        self._device = funasr_device
        logger.info("SenseVoice model loaded")

    def unload(self) -> None:
        self._model = None
        self._model_name = None
        self._device = None
        clear_gpu_cache()

    def is_loaded(self) -> bool:
        return self._model is not None

    def warmup(self) -> None:
        if self._model is None:
            return
        try:
            warmup_path = Path(__file__).parent.parent / "warmup_audio.wav"
            if warmup_path.exists():
                self._model.generate(
                    input=str(warmup_path), cache={}, language="en", use_itn=True
                )
            logger.debug("SenseVoice warmup complete")
        except Exception as e:  # noqa: BLE001 — warmup is best-effort
            logger.warning(f"SenseVoice warmup failed (non-critical): {e}")

    # -- transcription ------------------------------------------------------

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        audio_sample_rate: int = SAMPLE_RATE,
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = 5,
        initial_prompt: str | None = None,
        suppress_tokens: list[int] | None = None,
        vad_filter: bool = True,
        word_timestamps: bool = True,
        translation_target_language: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        # SenseVoice has no translate task and no word timestamps — ignore the
        # Whisper-shaped knobs the engine passes through.
        del task, beam_size, initial_prompt, suppress_tokens
        del vad_filter, word_timestamps, translation_target_language, progress_callback

        if self._model is None:
            raise RuntimeError("SenseVoice model is not loaded")

        lang = self._resolve_language(language)
        wav_path = _write_temp_wav(audio, audio_sample_rate)
        try:
            result = self._model.generate(
                input=wav_path,
                cache={},
                language=lang,
                use_itn=True,
                batch_size_s=300,
                merge_vad=True,
                merge_length_s=15,
            )
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

        duration_s = float(len(audio)) / float(audio_sample_rate) if audio_sample_rate else 0.0
        return self._parse_result(result, duration_s, forced_language=lang)

    def supports_translation(self) -> bool:
        return False

    @property
    def backend_name(self) -> str:
        return "sensevoice"

    # -- helpers ------------------------------------------------------------

    def _resolve_language(self, language: str | None) -> str:
        if not language:
            return "auto"
        code = language.strip().lower()
        if code in _SENSEVOICE_LANGUAGES:
            return code
        logger.warning(
            f"SenseVoice does not support language '{language}'; falling back to auto-detect"
        )
        return "auto"

    def _parse_result(
        self,
        result: list[dict[str, Any]],
        duration_s: float,
        *,
        forced_language: str,
    ) -> tuple[list[BackendSegment], BackendTranscriptionInfo]:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        if not result:
            return [], BackendTranscriptionInfo(language=None, language_probability=0.0)

        first = result[0]
        raw_text = str(first.get("text", ""))
        detected = _extract_language(raw_text)
        if detected is None and forced_language != "auto":
            detected = forced_language
        info = BackendTranscriptionInfo(language=detected, language_probability=0.0)

        # Preferred shape: per-sentence segments (VAD-chunk boundaries in ms).
        sentence_info = first.get("sentence_info")
        if isinstance(sentence_info, list) and sentence_info:
            segments: list[BackendSegment] = []
            for sentence in sentence_info:
                text = rich_transcription_postprocess(str(sentence.get("text", "")))
                start = float(sentence.get("start", 0.0)) / 1000.0
                end = float(sentence.get("end", 0.0)) / 1000.0
                segments.append(BackendSegment(text=text, start=start, end=end, words=[]))
            return segments, info

        # Fallback: one segment spanning the whole clip (no timestamps available).
        text = rich_transcription_postprocess(raw_text)
        return [BackendSegment(text=text, start=0.0, end=duration_s, words=[])], info
```

- [ ] **Step 4: Run the lifecycle tests and confirm they pass**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_backend.py::TestLifecycle -v --tb=short`
Expected: 4 passed.

### 3b — Transcribe & output parsing

- [ ] **Step 5: Write the failing transcribe tests**

Append to `server/backend/tests/test_sensevoice_backend.py`:
```python
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
        fake = _FakeAutoModel([
            {
                "text": "<|zh|>whatever",
                "sentence_info": [
                    {"text": "<|en|>First.", "start": 0, "end": 1000},
                    {"text": "<|en|>Second.", "start": 1000, "end": 2500},
                ],
            }
        ])
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
```

- [ ] **Step 6: Run them — confirm pass (no impl change needed if 3a is correct)**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_backend.py -v --tb=short`
Expected: all `TestLifecycle` + `TestTranscribe` pass. If `test_unsupported_language_falls_back_to_auto` fails, verify `_resolve_language` clamps non-member codes to `"auto"`.

- [ ] **Step 7: Run the routing test that imports the backend (Task 2 Step 7 dependency)**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_routing.py tests/test_sensevoice_backend.py -v --tb=short`
Expected: all green. The `create_backend("iic/SenseVoiceSmall")` import target now exists.

- [ ] **Step 8: Lint the new module**

Run: `cd server/backend && ../../build/.venv/bin/ruff check core/stt/backends/sensevoice_backend.py tests/test_sensevoice_backend.py`
Expected: `All checks passed!` (fix any reported issue, e.g. unused import).

- [ ] **Step 9: Commit**

```bash
git add server/backend/core/stt/backends/sensevoice_backend.py server/backend/tests/test_sensevoice_backend.py
git commit -m "feat(stt): add SenseVoiceBackend (funasr AutoModel wrapper, transcriber-only)"
```

---

## Task 4: Install gate in bootstrap (`bootstrap_runtime.py`)

**Files:**
- Modify: `server/docker/bootstrap_runtime.py` — patterns (~line 110), `is_sensevoice_model_name` (~145), `is_whisper_model_name` (153-158), `check_funasr_import` (after 1300), selection vars (~1751), install block (after 1928), features dict (2139-2144), cache-reuse list (1040)
- Test: `server/backend/tests/test_sensevoice_routing.py`

> **Why this is needed:** today `is_whisper_model_name` returns `True` for *any* non-NeMo/non-VibeVoice id, so `iic/SenseVoiceSmall` would be misclassified as "whisper selected" and never trigger a funasr install. The pure model-name helpers are unit-tested; the install orchestration is verified by the Task 11 smoke test.

- [ ] **Step 1: Write the failing helper test**

Append to `server/backend/tests/test_sensevoice_routing.py`:
```python
# --- bootstrap model-name helpers -----------------------------------------

class TestBootstrapSelection:
    def _bootstrap(self):
        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "docker" / "bootstrap_runtime.py"
        spec = importlib.util.spec_from_file_location("bootstrap_runtime_under_test", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_sensevoice_recognised_and_not_whisper(self) -> None:
        bootstrap = self._bootstrap()
        assert bootstrap.is_sensevoice_model_name("iic/SenseVoiceSmall") is True
        # Must NOT be misclassified as a whisper model (else funasr never installs).
        assert bootstrap.is_whisper_model_name("iic/SenseVoiceSmall") is False
        # Real whisper ids still classify as whisper.
        assert bootstrap.is_whisper_model_name("Systran/faster-whisper-large-v3") is True
        assert bootstrap.is_sensevoice_model_name("nvidia/parakeet-tdt-0.6b-v3") is False
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_routing.py::TestBootstrapSelection -v --tb=short`
Expected: FAIL — `is_sensevoice_model_name` does not exist; `is_whisper_model_name("iic/SenseVoiceSmall")` returns `True`.

- [ ] **Step 3: Add the pattern + helper, and exclude from whisper**

In `server/docker/bootstrap_runtime.py`, near the other `_*_MODEL_PATTERN` definitions (search for `_VIBEVOICE_ASR_MODEL_PATTERN =`), add:
```python
_SENSEVOICE_MODEL_PATTERN = re.compile(r"^[^/]+/sensevoice", re.IGNORECASE)
```
After `is_nemo_model_name` (line 150), add:
```python
def is_sensevoice_model_name(model_name: str | None) -> bool:
    """Return True when *model_name* selects the SenseVoice (FunASR) backend."""
    name = normalize_selected_model_name(model_name)
    return bool(_SENSEVOICE_MODEL_PATTERN.match(name))
```
Then change `is_whisper_model_name` (lines 153-158) to exclude SenseVoice:
```python
def is_whisper_model_name(model_name: str | None) -> bool:
    """Return True when *model_name* belongs to the faster-whisper family."""
    name = normalize_selected_model_name(model_name)
    if not name:
        return False
    return (
        not is_nemo_model_name(name)
        and not is_vibevoice_asr_model_name(name)
        and not is_sensevoice_model_name(name)
    )
```

- [ ] **Step 4: Run the helper test and confirm it passes**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_routing.py::TestBootstrapSelection -v --tb=short`
Expected: 1 passed.

- [ ] **Step 5: Add the `check_funasr_import` probe**

In `bootstrap_runtime.py`, immediately after `check_nemo_asr_import` (ends line 1300), add a sibling that probes `funasr`:
```python
def check_funasr_import(
    venv_python: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    checker = """
import importlib.util
import json

try:
    spec = importlib.util.find_spec("funasr")
    if spec is None:
        print(json.dumps({"available": False, "reason": "import_failed", "error": "funasr: not found"}))
    else:
        print(json.dumps({"available": True, "reason": "ready"}))
except Exception as exc:
    print(json.dumps({"available": False, "reason": "import_failed", "error": f"{type(exc).__name__}: {exc}"}))
"""
    try:
        result = subprocess.run(
            [str(venv_python), "-c", checker],
            text=True,
            capture_output=True,
            timeout=max(30, min(timeout_seconds, 300)),
            check=False,
        )
    except Exception as exc:
        return {"available": False, "reason": "import_failed", "error": f"{type(exc).__name__}: {exc}"}

    output = (result.stdout or "").strip().splitlines()
    if not output:
        return {"available": False, "reason": "import_failed"}
    try:
        payload = json.loads(output[-1])
    except json.JSONDecodeError:
        return {"available": False, "reason": "import_failed"}

    result_payload = {
        "available": bool(payload.get("available", False)),
        "reason": str(payload.get("reason", "import_failed") or "import_failed"),
    }
    error = payload.get("error")
    if error:
        result_payload["error"] = str(error)
    return result_payload
```

- [ ] **Step 6: Add the selection var + install block**

After the line `vibevoice_selected = is_vibevoice_asr_model_name(...)` (~1753), add:
```python
    sensevoice_selected = is_sensevoice_model_name(main_model) or is_sensevoice_model_name(live_model)
```
After the VibeVoice feature-check block ends and **before** the `"features": {` status dict is written (i.e. just before line ~2139), add the SenseVoice block (mirrors NeMo at 1856-1928):
```python
    # ── SenseVoice (optional, FunASR pipeline) ──────────────────────────────
    sensevoice_start = time.perf_counter()
    install_funasr = parse_bool_env("INSTALL_FUNASR", False)
    sensevoice_status: dict[str, Any]

    if not sensevoice_selected and not install_funasr:
        sensevoice_status = {"available": False, "reason": "not_selected"}
        log("SenseVoice not selected by configured models, skipping feature check")
    elif _reuse_feature_cache and not install_funasr:
        sensevoice_status = previous_status_payload["features"]["sensevoice"]
        log(f"SenseVoice feature check: reusing cached result (available={sensevoice_status.get('available')})")
    else:
        existing_sensevoice_status = check_funasr_import(
            venv_python=venv_python,
            timeout_seconds=timeout_seconds,
        )
        if existing_sensevoice_status.get("available"):
            sensevoice_status = existing_sensevoice_status
            log("FunASR already available, skipping optional install")
        elif install_funasr:
            log("Installing FunASR for SenseVoice support...")
            try:
                run_command(
                    ["uv", "pip", "install", "--python", str(venv_python), "funasr>=1.3.12"],
                    timeout_seconds=timeout_seconds,
                    env=build_uv_sync_env(venv_dir=venv_dir, cache_dir=cache_dir),
                )
                sensevoice_status = check_funasr_import(
                    venv_python=venv_python,
                    timeout_seconds=timeout_seconds,
                )
                if sensevoice_status.get("available"):
                    log("FunASR installed")
                else:
                    failure_error = str(sensevoice_status.get("error", "")).strip()
                    log(
                        "FunASR installation completed but import check failed "
                        f"({sensevoice_status.get('reason', 'import_failed')}"
                        + (f": {failure_error}" if failure_error else "")
                        + ")"
                    )
            except Exception as exc:
                sensevoice_status = {"available": False, "reason": "install_failed", "error": str(exc)}
                log(f"FunASR installation failed: {exc}")
        else:
            sensevoice_status = {"available": False, "reason": "selected_but_not_requested"}
            log("SenseVoice model selected but INSTALL_FUNASR is not enabled, skipping optional install")
    log_timing("SenseVoice feature check complete", sensevoice_start)
    if sensevoice_selected and not sensevoice_status.get("available"):
        emit_event(
            "warn-sensevoice",
            "warning",
            f"SenseVoice unavailable — {sensevoice_status.get('reason', 'unavailable')}",
            persistent=True,
        )
```

- [ ] **Step 7: Register it in the features dict + cache-reuse list**

In the status payload `"features"` dict (lines 2139-2144), add the key:
```python
                "vibevoice_asr": vibevoice_asr_status,
                "sensevoice": sensevoice_status,
```
In the cache-reuse loop (line 1040), extend the tuple:
```python
    for key in ("whisper", "nemo", "vibevoice_asr", "sensevoice"):
```

- [ ] **Step 8: Syntax-check the edited bootstrap**

Run: `cd server && ../build/.venv/bin/python -c "import ast; ast.parse(open('docker/bootstrap_runtime.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 9: Re-run all routing tests**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_routing.py -v --tb=short`
Expected: all classes pass.

- [ ] **Step 10: Commit**

```bash
git add server/docker/bootstrap_runtime.py server/backend/tests/test_sensevoice_routing.py
git commit -m "feat(server): gate FunASR/SenseVoice install behind INSTALL_FUNASR (bootstrap)"
```

---

## Task 5: Optional-dependency extra (`pyproject.toml`)

**Files:**
- Modify: `server/backend/pyproject.toml:63-77` (`[project.optional-dependencies]`)

- [ ] **Step 1: Add the `sensevoice` extra**

In `server/backend/pyproject.toml`, after the `vibevoice_asr = [...]` block (line 73), add:
```toml
sensevoice = [
    "funasr>=1.3.12",
]
```

- [ ] **Step 2: Validate the TOML parses**

Run: `cd server/backend && ../../build/.venv/bin/python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print(d['project']['optional-dependencies']['sensevoice'])"`
Expected: `['funasr>=1.3.12']`

- [ ] **Step 3: Commit**

```bash
git add server/backend/pyproject.toml
git commit -m "build(deps): add optional 'sensevoice' extra (funasr)"
```

---

## Task 6: Feature status in `model_manager.py`

**Files:**
- Modify: `server/backend/core/model_manager.py` — init fields (~224), init call (~244), method (after 343), getter (after 533)
- Test: `server/backend/tests/test_sensevoice_routing.py`

- [ ] **Step 1: Write the failing test**

Append to `server/backend/tests/test_sensevoice_routing.py`:
```python
# --- model_manager feature status -----------------------------------------

class TestSenseVoiceFeatureStatus:
    def test_reads_sensevoice_from_bootstrap_status(self, tmp_path, monkeypatch) -> None:
        import json

        status = {"features": {"sensevoice": {"available": True, "reason": "ready"}}}
        status_file = tmp_path / "bootstrap-status.json"
        status_file.write_text(json.dumps(status), encoding="utf-8")
        monkeypatch.setenv("BOOTSTRAP_STATUS_FILE", str(status_file))

        from server.core.model_manager import ModelManager

        mgr = object.__new__(ModelManager)
        mgr._sensevoice_feature_available = False
        mgr._sensevoice_feature_reason = "not_requested"
        mgr._initialize_sensevoice_feature_status()

        assert mgr.get_sensevoice_feature_status() == {"available": True, "reason": "ready"}
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_routing.py::TestSenseVoiceFeatureStatus -v --tb=short`
Expected: FAIL — methods/fields do not exist.

- [ ] **Step 3: Add init fields**

In `model_manager.py`, after line 225 (`self._vibevoice_asr_feature_reason = "not_requested"`), add:
```python
        self._sensevoice_feature_available: bool = False
        self._sensevoice_feature_reason: str = "not_requested"
```

- [ ] **Step 4: Call the initializer**

After line 244 (`self._initialize_vibevoice_asr_feature_status()`), add:
```python
        self._initialize_sensevoice_feature_status()
```

- [ ] **Step 5: Add the initializer method**

After `_initialize_nemo_feature_status` (ends line 342), add a sibling (identical shape, `sensevoice` key):
```python
    def _initialize_sensevoice_feature_status(self) -> None:
        """Initialize SenseVoice (FunASR) feature availability from bootstrap state."""
        status_file = os.environ.get("BOOTSTRAP_STATUS_FILE", "/runtime/bootstrap-status.json")
        try:
            import json
            from pathlib import Path

            path = Path(status_file)
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                sensevoice = payload.get("features", {}).get("sensevoice", {})
                available = bool(sensevoice.get("available", False))
                reason = str(sensevoice.get("reason", "not_requested") or "not_requested")
                self._sensevoice_feature_available = available
                self._sensevoice_feature_reason = reason
                logger.info(
                    "Loaded SenseVoice feature status from bootstrap: "
                    f"available={available}, reason={reason}"
                )
                return
        except Exception as e:
            logger.debug(f"Could not load SenseVoice feature status from bootstrap: {e}")

        self._sensevoice_feature_available = False
        self._sensevoice_feature_reason = "not_requested"
```

- [ ] **Step 6: Add the getter**

After `get_vibevoice_asr_feature_status` (ends line 533), add:
```python
    def get_sensevoice_feature_status(self) -> dict[str, Any]:
        """Return SenseVoice (FunASR) feature availability for the dashboard."""
        return {
            "available": self._sensevoice_feature_available,
            "reason": self._sensevoice_feature_reason,
        }
```

- [ ] **Step 7: Run the test and confirm it passes**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_routing.py::TestSenseVoiceFeatureStatus -v --tb=short`
Expected: 1 passed.

- [ ] **Step 8: Commit**

```bash
git add server/backend/core/model_manager.py server/backend/tests/test_sensevoice_routing.py
git commit -m "feat(server): expose SenseVoice feature status from ModelManager"
```

---

## Task 7: Document the model in `config.yaml`

**Files:**
- Modify: `server/config.yaml:51-56` (main_transcriber comments)

- [ ] **Step 1: Extend the model comment block**

In `server/config.yaml`, in the `main_transcriber:` comment block (after the VibeVoice-ASR examples line, ~line 54), add:
```yaml
    # SenseVoice example: "iic/SenseVoiceSmall" (zh/en/yue/ja/ko only, fast NAR; requires INSTALL_FUNASR=true)
```
And update the backend-autodetect comment (line 55) to:
```yaml
    # Backend is auto-detected from the model name (nvidia/* → NeMo, */VibeVoice-ASR* → VibeVoice-ASR, */SenseVoice* → SenseVoice, else → Whisper).
```

- [ ] **Step 2: Validate YAML parses**

Run: `cd server && ../build/.venv/bin/python -c "import yaml; yaml.safe_load(open('config.yaml')); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add server/config.yaml
git commit -m "docs(config): document iic/SenseVoiceSmall + INSTALL_FUNASR"
```

---

## Task 8: Dashboard capabilities (`modelCapabilities.ts`)

**Files:**
- Modify: `dashboard/src/services/modelCapabilities.ts` (patterns ~14, language set, `isSenseVoiceModel`, `isWhisperModel`, `filterLanguagesForModel`, `supportsTranslation`)
- Test: `dashboard/src/services/modelCapabilities.test.ts`

> Run frontend commands under **Node 22**: `cd dashboard && nvm use` first (see project memory — Vitest needs Node 22).

- [ ] **Step 1: Write the failing Vitest cases**

Append to `dashboard/src/services/modelCapabilities.test.ts` (match the file's existing `import { … } from './modelCapabilities'` style — add the new symbols to that import):
```typescript
describe('SenseVoice capabilities', () => {
  it('detects SenseVoice model ids', () => {
    expect(isSenseVoiceModel('iic/SenseVoiceSmall')).toBe(true);
    expect(isSenseVoiceModel('FunAudioLLM/SenseVoiceSmall')).toBe(true);
    expect(isSenseVoiceModel('Systran/faster-whisper-large-v3')).toBe(false);
  });

  it('is not treated as a Whisper model', () => {
    expect(isWhisperModel('iic/SenseVoiceSmall')).toBe(false);
  });

  it('does not support translation', () => {
    expect(supportsTranslation('iic/SenseVoiceSmall')).toBe(false);
  });

  it('restricts languages to the 5 SenseVoice languages + Auto Detect', () => {
    const all = ['Auto Detect', 'English', 'Chinese', 'Greek', 'Japanese', 'Korean', 'Cantonese'];
    const filtered = filterLanguagesForModel(all, 'iic/SenseVoiceSmall');
    expect(filtered).toEqual(['Auto Detect', 'English', 'Chinese', 'Japanese', 'Korean', 'Cantonese']);
    expect(filtered).not.toContain('Greek');
  });
});
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd dashboard && npx vitest run src/services/modelCapabilities.test.ts`
Expected: FAIL — `isSenseVoiceModel` is not exported; SenseVoice currently behaves like Whisper (all languages, translation true).

- [ ] **Step 3: Add the pattern + language set**

In `dashboard/src/services/modelCapabilities.ts`, after line 14 (`const MLX_PATTERN = …`), add:
```typescript
const SENSEVOICE_PATTERN = /^[^/]+\/sensevoice/i;
```
After the `NEMO_LANGUAGES` set (line 46), add:
```typescript
/**
 * The 5 first-class languages SenseVoiceSmall actually supports
 * (despite the model's "50+ languages" marketing). No Greek.
 */
export const SENSEVOICE_LANGUAGES: ReadonlySet<string> = new Set([
  'English',
  'Chinese',
  'Japanese',
  'Korean',
  'Cantonese',
]);
```

- [ ] **Step 4: Add `isSenseVoiceModel` + exclude from `isWhisperModel`**

After `isVibeVoiceASRModel` (line 148), add:
```typescript
/**
 * Returns true if the model is a SenseVoice (FunASR) backend variant.
 */
export function isSenseVoiceModel(modelName: string | null | undefined): boolean {
  const name = (modelName ?? '').trim();
  return SENSEVOICE_PATTERN.test(name);
}
```
Update `isWhisperModel` (lines 133-140) to add the exclusion:
```typescript
export function isWhisperModel(modelName: string | null | undefined): boolean {
  return (
    !isNemoModel(modelName) &&
    !isVibeVoiceASRModel(modelName) &&
    !isWhisperCppModel(modelName) &&
    !isMLXModel(modelName) &&
    !isSenseVoiceModel(modelName)
  );
}
```

- [ ] **Step 5: Filter languages + reject translation**

In `filterLanguagesForModel`, before the `if (isVibeVoiceASRModel(modelName))` branch (line 218), add:
```typescript
  if (isSenseVoiceModel(modelName)) {
    // SenseVoiceSmall: zh/en/yue/ja/ko only, plus Auto Detect.
    return languages.filter(
      (l) => l === 'Auto Detect' || SENSEVOICE_LANGUAGES.has(l),
    );
  }
```
In `supportsTranslation`, after the `if (!name) return true;` line (line 246), add:
```typescript
  if (isSenseVoiceModel(name)) return false;
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `cd dashboard && npx vitest run src/services/modelCapabilities.test.ts`
Expected: all pass (including the new `SenseVoice capabilities` block).

- [ ] **Step 7: Typecheck**

Run: `cd dashboard && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add dashboard/src/services/modelCapabilities.ts dashboard/src/services/modelCapabilities.test.ts
git commit -m "feat(dashboard): SenseVoice capabilities — 5 languages, no translation"
```

---

## Task 9: Dashboard model registry (`modelRegistry.ts`)

**Files:**
- Modify: `dashboard/src/services/modelRegistry.ts` (`ModelFamily` type ~20, import ~10, registry entry after the NeMo block ~70)

- [ ] **Step 1: Add the `'sensevoice'` family + import**

In `dashboard/src/services/modelRegistry.ts`, add `'sensevoice'` to the `ModelFamily` union (line 20 region):
```typescript
export type ModelFamily =
  | 'whisper'
  | 'nemo'
  | 'sensevoice'
  | 'vibevoice'
  | 'whispercpp'
  | 'mlx'
  | 'diarization'
  | 'custom'
  | 'none';
```
Add `isSenseVoiceModel` to the import from `./modelCapabilities` (lines 9-17) so later UI code can use it consistently:
```typescript
  isMLXParakeetModel,
  isSenseVoiceModel,
```

- [ ] **Step 2: Add the registry entry**

In `MODEL_REGISTRY`, immediately after the NeMo block (after the `nvidia/canary-1b-v2` entry, ~line 72), add:
```typescript
  // ── SenseVoice (FunASR) ──────────────────────────────────────────────────
  {
    id: 'iic/SenseVoiceSmall',
    displayName: 'SenseVoice Small',
    family: 'sensevoice',
    description:
      'Alibaba FunAudioLLM non-autoregressive ASR. Very fast, CPU-capable. 5 languages (zh/en/yue/ja/ko) — no Greek, no translation. Linux/NVIDIA, requires INSTALL_FUNASR=true.',
    parameterCount: '234M',
    huggingfaceUrl: 'https://huggingface.co/FunAudioLLM/SenseVoiceSmall',
    capabilities: { translation: false, liveMode: true, diarization: false, languageCount: 5 },
    roles: ['main'],
    requiresRuntime: 'cuda',
  },
```

- [ ] **Step 3: Typecheck (this surfaces any exhaustive `ModelFamily` switch that needs a `sensevoice` label)**

Run: `cd dashboard && npx tsc --noEmit`
Expected: no errors. If `tsc` flags a non-exhaustive `switch (family)` in `ModelManagerView.tsx` or `modelRegistry.ts` (family→label/heading map), add a `sensevoice: 'SenseVoice'` case at the reported location, then re-run.

- [ ] **Step 4: Run registry tests**

Run: `cd dashboard && npx vitest run src/services/modelRegistry.test.ts`
Expected: pass. If a test asserts the registry length or family coverage, update it to include the SenseVoice entry.

- [ ] **Step 5: Build to confirm no UI-contract / CSS impact**

Run: `cd dashboard && npm run build`
Expected: build succeeds. (These edits touch service/registry logic, not CSS classes, so `ui:contract` is not triggered. If you edited `ModelManagerView.tsx` and added a new `className`, run `npm run ui:contract:check` per the ui-contract skill.)

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/services/modelRegistry.ts dashboard/src/services/modelRegistry.test.ts
git commit -m "feat(dashboard): register iic/SenseVoiceSmall in the model registry"
```

---

## Task 10: Full backend + frontend test sweep

- [ ] **Step 1: Backend suite (build venv)**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/ -q --tb=short`
Expected: all SenseVoice tests pass; no regressions beyond the 2 known pre-existing failures (db migration version, swr_linear resample — see project memory).

- [ ] **Step 2: Backend lint**

Run: `cd server/backend && ../../build/.venv/bin/ruff check core/ tests/test_sensevoice_backend.py tests/test_sensevoice_routing.py`
Expected: `All checks passed!`

- [ ] **Step 3: Frontend tests + typecheck (Node 22)**

Run: `cd dashboard && nvm use && npx vitest run src/services/ && npx tsc --noEmit`
Expected: green.

- [ ] **Step 4: Commit (only if any test fixups were needed)**

```bash
git add -A && git commit -m "test: stabilize suite after SenseVoice integration"
```

---

## Task 11: Real-hardware smoke test (Linux / NVIDIA) — MANUAL

> This is the **only** step that exercises the real funasr API + GPU. It verifies the assumptions the unit tests mock: that `iic/SenseVoiceSmall` resolves on HuggingFace, that `AutoModel(...).generate(input=<wav>)` returns the shape `_parse_result` expects, and that VRAM/throughput are acceptable. The Phase-1 backend was written defensively (handles both `sentence_info` and merged-text shapes) precisely so this step reconciles reality without code churn.

- [ ] **Step 1: Configure the model + enable install**

Edit your local `~/.config/TranscriptionSuite/config.yaml` (or the dev `server/config.yaml`):
```yaml
main_transcriber:
    model: "iic/SenseVoiceSmall"
    device: "cuda"
    gpu_device_index: 0
```
Export the install gate before starting the server/bootstrap:
```bash
export INSTALL_FUNASR=true
```

- [ ] **Step 2: Start the server and watch bootstrap**

Start the server as you normally do for dev. Confirm in the bootstrap log:
- `Installing FunASR for SenseVoice support...` then `FunASR installed`
- No `SenseVoice unavailable` warning event.
- `/runtime/bootstrap-status.json` contains `features.sensevoice.available == true`.

If `uv pip install funasr>=1.3.12` fails to resolve against the existing torch, note the conflict and pin a compatible funasr version (Phase-1 risk checkpoint) before continuing.

- [ ] **Step 3: Transcribe a short multilingual clip**

Transcribe a ~30–60s English (and, if available, Mandarin/Japanese) audio file via the dashboard or the `/api/transcribe/audio` endpoint. Confirm:
- Returned text is correct and **free of `<|…|>` tokens** (post-processing works).
- `info.language` is populated (e.g. `"en"`).
- Segments render; note whether you got **per-sentence** segments (funasr produced `sentence_info`) or **one** segment (merged-text fallback). Either is acceptable for Phase 1 — just record which.

- [ ] **Step 4: Transcribe a >30s clip (VAD chunking)**

Transcribe a 2–5 minute file. Confirm it does NOT error at the 30s SenseVoice cap (i.e. `fsmn-vad` chunking is active) and the full transcript returns.

- [ ] **Step 5: Verify durability + record VRAM**

Confirm the completed transcription is persisted (per the project's data-loss invariant) before delivery, and note peak VRAM (`nvidia-smi`) so we can document the footprint.

- [ ] **Step 6: Capture the real `generate()` shape for the record**

In a Python shell in the build venv, run a 5–10s clip directly and paste the raw `res[0].keys()` into the PR description:
```bash
cd server/backend && ../../build/.venv/bin/python - <<'PY'
from funasr import AutoModel
m = AutoModel(model="iic/SenseVoiceSmall", vad_model="fsmn-vad", device="cuda:0", hub="hf", disable_update=True)
res = m.generate(input="warmup_audio_or_short.wav", cache={}, language="auto", use_itn=True)
print(type(res), len(res))
print(sorted(res[0].keys()))
print(repr(res[0].get("text"))[:200])
print("sentence_info?" , "sentence_info" in res[0])
PY
```
If the real keys differ from what `_parse_result` handles, adjust `_parse_result` (and a matching unit test) — this is the one place reality may diverge from the mocks.

---

## Task 12: Documentation

**Files:**
- Modify: `docs/project-context.md`, `README_DEV.md`

- [ ] **Step 1: Note the new backend**

Add a short subsection to `README_DEV.md` (backend/model list) and a rule/line to `docs/project-context.md`:
> SenseVoice (`iic/SenseVoiceSmall`) — FunASR PyTorch backend, Linux/NVIDIA only (Phase 1), transcriber-only, `INSTALL_FUNASR=true`. Languages: zh/en/yue/ja/ko (no Greek). No translation, no word timestamps (diarization falls back to segment-level). Backend: `server/backend/core/stt/backends/sensevoice_backend.py`.

- [ ] **Step 2: Commit**

```bash
git add docs/project-context.md README_DEV.md
git commit -m "docs: document SenseVoice Phase 1 (Linux/NVIDIA, transcriber-only)"
```

---

## Task 13: Open the PR

- [ ] **Step 1: Push + PR**

Run:
```bash
git push -u origin feature/sensevoice-asr-phase1
gh pr create --title "feat(stt): SenseVoice (FunASR) backend — Phase 1 (Linux/NVIDIA, transcriber-only)" --body "$(cat <<'EOF'
## Summary
Adds Alibaba FunAudioLLM **SenseVoice** (`iic/SenseVoiceSmall`) as an STT backend via the `funasr` PyTorch pipeline. Phase 1: Linux/NVIDIA, transcriber-only (no new diarization code). Closes the SenseVoice request in #129 (and the duplicate #144) for Phase 1 scope.

## What's included
- `SenseVoiceBackend` (funasr AutoModel + fsmn-vad), reached via factory routing for `*/sensevoice*` ids
- Capability flags: no translation; 5 languages (zh/en/yue/ja/ko — **no Greek**)
- `INSTALL_FUNASR` bootstrap gate + feature status surfaced to the dashboard
- Dashboard registry + capability wiring
- Unit tests (funasr mocked); smoke-tested on real Linux/NVIDIA hardware

## Out of scope (later phases)
FunASR CAM++ diarization, word timestamps, emotion/event tags, sherpa-onnx / SenseVoice.cpp, Windows/macOS/Apple-Silicon, ModelScope download.

## Test plan
- [ ] `pytest tests/` green (backend)
- [ ] `vitest run src/services/` + `tsc --noEmit` green (dashboard)
- [ ] Smoke test: short + >30s clips transcribe on CUDA; tokens stripped; durability verified; VRAM recorded
EOF
)"
```

---

## Self-Review

**1. Spec coverage** (against the Phase-1 scope agreed in conversation):
- New transcriber backend → Task 3 ✅
- Factory routing → Task 2 ✅
- Capability flags (no translation, 5 langs) → Task 1 (backend) + Task 8 (dashboard) ✅
- Install gating like INSTALL_NEMO → Task 4 + Task 5 ✅
- Feature status → dashboard surfacing → Task 6 (+ bootstrap features dict Task 4) ✅
- Config documentation → Task 7 ✅
- Model selectable in UI → Task 9 ✅
- ModelScope→HF download avoidance → backend `hub="hf"` (Task 3) ✅
- Live mode → works automatically via shared backend; explicitly validated in smoke test (Task 11), no code change needed ✅
- Diarization left on the existing pyannote two-pass (degrades to segment-level for no-word backends — already handled by `build_speaker_segments_nowords`) — **no Phase-1 code**, documented Task 12 ✅
- Greek-unsupported reality → encoded in language filter (Task 8) + docs (Task 12) ✅

**2. Placeholder scan:** No `TBD`/`TODO`/"handle edge cases"; every code step shows complete code; commands have expected output. Task 11 is explicitly MANUAL (real hardware) — not a placeholder, a required human verification with exact commands.

**3. Type consistency:** `SenseVoiceBackend` implements every abstract member of `STTBackend` from `base.py` (`load`, `unload`, `is_loaded`, `warmup`, `transcribe`, `supports_translation`, `backend_name`) with matching signatures. `detect_backend_type` returns `"sensevoice"`; `create_backend` imports `SenseVoiceBackend` from the file Task 3 creates. Bootstrap key, model_manager key, and features-dict key are all the literal string `"sensevoice"` consistently. Dashboard `isSenseVoiceModel` / `SENSEVOICE_LANGUAGES` / `SENSEVOICE_PATTERN` names are used identically across `modelCapabilities.ts` and `modelRegistry.ts`.

**Known reality-divergence risk (called out, not hidden):** the exact `funasr.generate()` return shape (`sentence_info` vs merged `text`) is reconciled in Task 11 Step 6; `_parse_result` already handles both, so divergence costs at most a small parser tweak + one test.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-24-sensevoice-phase1-linux-nvidia.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session with checkpoints for review.

Which approach?
