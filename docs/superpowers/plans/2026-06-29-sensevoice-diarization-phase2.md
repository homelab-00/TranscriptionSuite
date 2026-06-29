# SenseVoice Diarization — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the SenseVoice STT backend speaker diarization with two selectable engines — FunASR-native CAM++ single-pass (the default) and the existing pyannote two-pass (the override) — plus a cuttable per-word-timestamp enhancement.

**Architecture:** CAM++ rides the existing single-pass seam (`SenseVoiceBackend.transcribe_with_diarization()` → `DiarizedTranscriptionResult`); a one-line engine gate on the route turns pyannote into the override for free. SenseVoice's `AutoModel` is always built with `spk_model="cam++"` when FunASR is available (28 MB, no reload), so the only behavioural ripple is harmonizing the transcribe parser to the `"sentence"` key. Engine choice is a config default + a per-job request field surfaced in the dashboard.

**Tech Stack:** Python 3.13, `funasr>=1.3.12` (already pinned), FastAPI; TypeScript/React (Electron dashboard); pytest (build venv) + Vitest (Node 22).

**Design spec:** [`docs/superpowers/specs/2026-06-29-sensevoice-diarization-phase2-design.md`](../specs/2026-06-29-sensevoice-diarization-phase2-design.md). Branch: `feature/sensevoice-diarization-phase2`.

**Deliverable:** one combined PR. **Wave 3 is cuttable** — excise it before merge if the GPU smoke test (§ Smoke Test) shows word-level does not beat segment-level.

---

## Conventions (read once)

- **Backend tests** run from `server/backend/` with the **build venv**:
  `cd server/backend && ../../build/.venv/bin/pytest tests/<file> -v --tb=short`
- **Lint** a backend file: `cd server/backend && ../../build/.venv/bin/ruff check <path>`
- **Frontend tests** run from `dashboard/` under **Node 22**: `cd dashboard && nvm use && npx vitest run <path>`
- The `server` import package maps to `server/backend/` (e.g. `server.config` → `server/backend/config.py`, `server.core.*` → `server/backend/core/*`).
- Verified FunASR facts this plan relies on: CAM++ works on `funasr>=1.3.12`; output is `result[0]["sentence_info"] = [{start:int_ms, end:int_ms, sentence:str, timestamp:[], spk:int}]` (**key is `"sentence"`, not `"text"`**); `spk` is an int; cam++=`funasr/campplus` (28 MB) + fsmn-vad (1.7 MB), both ungated; **omit `ct-punc`** (1.1 GB, not needed). Speaker labels render as `SPEAKER_NN`.

---

## File Structure

**New files:**
- `server/backend/tests/test_sensevoice_diarization.py` — unit tests for the CAM++ single-pass path + the harmonized parser + the engine resolver + the route predicate.

**Modified files:**
- `server/backend/config.py` — add `resolve_sensevoice_diarization_engine()` + `DEFAULT_SENSEVOICE_DIARIZATION_ENGINE`.
- `server/backend/core/stt/backends/sensevoice_backend.py` — always-load cam++ in `load()`; harmonize `_parse_result` to the `"sentence"` key; add `transcribe_with_diarization()` + `_format_spk()` + `_parse_diarized_result()`; (Wave 3) `_tokens_to_words()` + `output_timestamp` wiring.
- `server/backend/api/routes/transcription.py` — `diarization_engine` form field; `use_integrated_diarization_for()` predicate at both gate sites (`~350`, `~907`); thread the resolved engine.
- `server/backend/core/stt/backends/__init__.py` *(or wherever the predicate best lives)* — house `use_integrated_diarization_for()` (see Task 1.4 for exact placement).
- `server/docker/bootstrap_runtime.py` — `warm_download_sensevoice_models()` invoked after the funasr install block (`~2230`).
- `server/config.yaml` — document `diarization.sensevoice_engine`.
- `dashboard/src/services/modelCapabilities.ts` — `supportsFunasrDiarization()`.
- `dashboard/src/services/modelRegistry.ts` — SenseVoice `capabilities.diarization: true`.
- `dashboard/src/services/modelCapabilities.test.ts`, `dashboard/src/services/modelRegistry.test.ts` — coverage.
- `dashboard/src/api/client.ts` — send `diarization_engine` in the 3 FormData builders; extend the options types.
- `dashboard/components/views/SessionImportTab.tsx` — engine selector UI + state + options wiring.

---

# WAVE 1 — CAM++ single-pass backend + engine plumbing (server/API)

## Task 1.1: Engine resolver in `config.py`

**Files:**
- Modify: `server/backend/config.py` (add after `resolve_parallel_diarization_default`, ~line 556)
- Test: `server/backend/tests/test_sensevoice_diarization.py`

- [ ] **Step 1: Write the failing test**

Create `server/backend/tests/test_sensevoice_diarization.py`:
```python
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
    def _resolve(self, model_name, request_value, config_default, available):
        from server.config import resolve_sensevoice_diarization_engine

        return resolve_sensevoice_diarization_engine(
            model_name,
            request_value,
            config_default,
            funasr_diar_available=available,
        )

    def test_non_sensevoice_always_pyannote(self) -> None:
        assert self._resolve("Systran/faster-whisper-large-v3", "funasr", "funasr", True) == "pyannote"

    def test_sensevoice_auto_uses_config_default(self) -> None:
        assert self._resolve("iic/SenseVoiceSmall", "auto", "funasr", True) == "funasr"
        assert self._resolve("iic/SenseVoiceSmall", None, "pyannote", True) == "pyannote"

    def test_sensevoice_explicit_override(self) -> None:
        assert self._resolve("iic/SenseVoiceSmall", "pyannote", "funasr", True) == "pyannote"
        assert self._resolve("iic/SenseVoiceSmall", "funasr", "pyannote", True) == "funasr"

    def test_funasr_unavailable_falls_back_to_pyannote(self) -> None:
        assert self._resolve("iic/SenseVoiceSmall", "funasr", "funasr", False) == "pyannote"

    def test_unknown_value_falls_back_to_pyannote(self) -> None:
        assert self._resolve("iic/SenseVoiceSmall", "garbage", "funasr", True) == "pyannote"
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_diarization.py::TestResolveEngine -v --tb=short`
Expected: FAIL — `ImportError: cannot import name 'resolve_sensevoice_diarization_engine'`.

- [ ] **Step 3: Implement the resolver**

In `server/backend/config.py`, immediately after `resolve_parallel_diarization_default` (ends ~line 556), add:
```python
# Default diarization engine for the SenseVoice STT model only.
DEFAULT_SENSEVOICE_DIARIZATION_ENGINE = "funasr"


def resolve_sensevoice_diarization_engine(
    model_name: str | None,
    request_value: str | None,
    config_default: str | None,
    *,
    funasr_diar_available: bool,
) -> str:
    """Resolve the diarization engine for a transcription job.

    Returns "funasr" (CAM++ single-pass) or "pyannote" (two-pass). "funasr" is
    only ever returned for SenseVoice models, and only when CAM++ is available;
    every other model and every fallback resolves to "pyannote".
    """
    from server.core.stt.backends.factory import is_sensevoice_model

    if not is_sensevoice_model(model_name or ""):
        return "pyannote"
    chosen = (request_value or "auto").strip().lower()
    if chosen == "auto":
        chosen = (config_default or DEFAULT_SENSEVOICE_DIARIZATION_ENGINE).strip().lower()
    if chosen == "funasr" and funasr_diar_available:
        return "funasr"
    return "pyannote"
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_diarization.py::TestResolveEngine -v --tb=short`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add server/backend/config.py server/backend/tests/test_sensevoice_diarization.py
git commit -m "feat(stt): add SenseVoice diarization-engine resolver (funasr default, pyannote fallback)"
```

---

## Task 1.2: Always-load CAM++ + harmonize the transcribe parser

**Files:**
- Modify: `server/backend/core/stt/backends/sensevoice_backend.py` (`load` ~110-132; `_parse_result` ~222-254; add a module flag)
- Test: `server/backend/tests/test_sensevoice_diarization.py`

> **Why:** with `spk_model="cam++"` loaded, funasr emits each segment under the key `"sentence"`, not `"text"`. The existing `_parse_result` reads `"text"`, so plain transcription would return empty text unless harmonized. Always-loading cam++ (28 MB) also guarantees `sentence_info` is populated, avoiding the whole-clip fallback.

- [ ] **Step 1: Write the failing tests**

Append to `server/backend/tests/test_sensevoice_diarization.py`:
```python
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
        _, stubs = _load(model, cam=True)
        kwargs = stubs["funasr"].AutoModel.call_args.kwargs
        assert kwargs["spk_model"] == "cam++"
        assert kwargs["spk_mode"] == "vad_segment"
        assert kwargs["vad_model"] == "fsmn-vad"

    def test_load_omits_spk_model_when_disabled(self) -> None:
        model = _FakeAutoModel()
        _, stubs = _load(model, cam=False)
        kwargs = stubs["funasr"].AutoModel.call_args.kwargs
        assert "spk_model" not in kwargs

    def test_transcribe_reads_sentence_key(self) -> None:
        # With cam++ loaded, segments arrive under "sentence", not "text".
        model = _FakeAutoModel(
            [{"text": "<|en|>full", "sentence_info": [
                {"sentence": "<|en|>Hello.", "start": 0, "end": 1000, "spk": 0},
            ]}]
        )
        backend, stubs = _load(model, cam=True)
        with patch.dict(sys.modules, stubs):
            segments, _ = backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert [s.text for s in segments] == ["Hello."]

    def test_transcribe_still_reads_text_key(self) -> None:
        # Back-compat: plain (no-spk) sentence_info using the legacy "text" key.
        model = _FakeAutoModel(
            [{"text": "<|en|>full", "sentence_info": [
                {"text": "<|en|>Legacy.", "start": 0, "end": 1000},
            ]}]
        )
        backend, stubs = _load(model, cam=False)
        with patch.dict(sys.modules, stubs):
            segments, _ = backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert [s.text for s in segments] == ["Legacy."]
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_diarization.py::TestAlwaysLoadCamPP -v --tb=short`
Expected: FAIL — `load()` doesn't accept `sensevoice_diarization`/doesn't pass `spk_model`; `_parse_result` reads only `"text"`.

- [ ] **Step 3: Update `load()` to always-load cam++**

In `sensevoice_backend.py`, replace the `load` body's `AutoModel(...)` construction (lines ~122-129) with:
```python
        # CAM++ single-pass diarization is the default for SenseVoice. cam++ is
        # ~28 MB, so we build it into the model unconditionally (when requested)
        # rather than reloading on a per-job toggle. Disable via
        # sensevoice_diarization=False (e.g. cam++ unavailable offline).
        want_diarization = bool(kwargs.get("sensevoice_diarization", True))
        model_kwargs: dict[str, Any] = dict(
            model=hf_repo_id,
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": 30000},
            device=funasr_device,
            hub="hf",
            disable_update=True,
        )
        if want_diarization:
            # spk_mode="vad_segment" matches SenseVoice (no token timestamps) and
            # skips funasr's punc_segment warning + forced fallback.
            model_kwargs["spk_model"] = "cam++"
            model_kwargs["spk_mode"] = "vad_segment"
        try:
            self._model = AutoModel(**model_kwargs)
        except Exception:
            if want_diarization:
                logger.warning(
                    "SenseVoice: building with cam++ failed; retrying transcriber-only "
                    "(diarization will fall back to pyannote).",
                    exc_info=True,
                )
                model_kwargs.pop("spk_model", None)
                model_kwargs.pop("spk_mode", None)
                self._model = AutoModel(**model_kwargs)
                self._diarization_loaded = False
            else:
                raise
        else:
            self._diarization_loaded = want_diarization
```

Add `self._diarization_loaded: bool = False` to `__init__` (after `self._device = None`, line ~106), and reset it in `unload()` (after `self._device = None`, line ~137): `self._diarization_loaded = False`.

- [ ] **Step 4: Harmonize `_parse_result`**

In `_parse_result`, change the sentence-text read (line ~246) from:
```python
                text = rich_transcription_postprocess(str(sentence.get("text", "")))
```
to:
```python
                text = rich_transcription_postprocess(
                    str(sentence.get("sentence") or sentence.get("text") or "")
                )
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_diarization.py::TestAlwaysLoadCamPP -v --tb=short`
Expected: 4 passed.

- [ ] **Step 6: Run the existing SenseVoice suite (no regressions)**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_backend.py tests/test_sensevoice_routing.py -v --tb=short`
Expected: all still pass (the legacy stubs omit `sensevoice_diarization`, defaulting to True; their `AutoModel` is a `MagicMock` so `spk_model` kwargs are harmless, and `_parse_result` still reads `"text"`).

- [ ] **Step 7: Commit**

```bash
git add server/backend/core/stt/backends/sensevoice_backend.py server/backend/tests/test_sensevoice_diarization.py
git commit -m "feat(stt): always-load cam++ on SenseVoice + harmonize parser to the 'sentence' key"
```

---

## Task 1.3: `transcribe_with_diarization()` (CAM++ single-pass)

**Files:**
- Modify: `server/backend/core/stt/backends/sensevoice_backend.py` (imports; add `_format_spk`, `transcribe_with_diarization`, `_parse_diarized_result`)
- Test: `server/backend/tests/test_sensevoice_diarization.py`

- [ ] **Step 1: Write the failing tests**

Append to `server/backend/tests/test_sensevoice_diarization.py`:
```python
class TestCamPPSinglePass:
    def test_parses_spk_into_speaker_labels(self) -> None:
        model = _FakeAutoModel(
            [{"text": "<|en|>full", "sentence_info": [
                {"sentence": "<|en|>Hi there.", "start": 0, "end": 1500, "spk": 0},
                {"sentence": "<|en|>Hello back.", "start": 1500, "end": 3000, "spk": 1},
            ]}]
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
            [{"text": "<|en|>full", "sentence_info": [
                {"sentence": "<|en|>One.", "start": 0, "end": 1000, "spk": 0},
                {"sentence": "<|en|>Two.", "start": 1000, "end": 2000, "spk": 0},
            ]}]
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
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_diarization.py::TestCamPPSinglePass -v --tb=short`
Expected: FAIL — `transcribe_with_diarization` not overridden (returns `None`).

- [ ] **Step 3: Add the import**

In `sensevoice_backend.py`, extend the `base` import (lines 27-32) to include `DiarizedTranscriptionResult`:
```python
from server.core.stt.backends.base import (
    BackendDependencyError,
    BackendSegment,
    BackendTranscriptionInfo,
    DiarizedTranscriptionResult,
    STTBackend,
)
```

- [ ] **Step 4: Add the `_format_spk` module helper**

After `_extract_language` (ends line 69), add:
```python
def _format_spk(spk: Any) -> str:
    """Map a funasr integer ``spk`` index to the project's ``SPEAKER_NN`` label."""
    if spk is None:
        return "UNKNOWN"
    try:
        return f"SPEAKER_{int(spk):02d}"
    except (TypeError, ValueError):
        raw = str(spk).strip()
        return raw or "UNKNOWN"
```

- [ ] **Step 5: Add the override + parser**

In `SenseVoiceBackend`, after `transcribe` (ends line 200) and before `supports_translation`, add:
```python
    def transcribe_with_diarization(
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
        num_speakers: int | None = None,
        hf_token: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> DiarizedTranscriptionResult | None:
        # CAM++ single-pass: speakers come from funasr's own generate() call.
        # Whisper-shaped knobs do not apply.
        del task, beam_size, initial_prompt, suppress_tokens, vad_filter
        del num_speakers, hf_token, progress_callback

        if self._model is None:
            raise RuntimeError("SenseVoice model is not loaded")

        lang = self._resolve_language(language)
        wav_path = _write_temp_wav(audio, audio_sample_rate)
        duration_s = float(len(audio)) / float(audio_sample_rate) if audio_sample_rate else 0.0
        try:
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
            except Exception:
                # Known upstream failure modes (distribute_spk TypeError, etc.).
                # NEVER drop the result — degrade to a plain transcript.
                logger.warning(
                    "SenseVoice CAM++ diarization failed; returning plain transcript "
                    "without speaker labels.",
                    exc_info=True,
                )
                return self._plain_diarized_fallback(audio, audio_sample_rate, lang)
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

        return self._parse_diarized_result(result, duration_s, forced_language=lang)
```

After `_parse_result` (ends line 254), add:
```python
    def _parse_diarized_result(
        self,
        result: list[dict[str, Any]],
        duration_s: float,
        *,
        forced_language: str,
    ) -> DiarizedTranscriptionResult:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        if not result:
            return DiarizedTranscriptionResult(
                segments=[], words=[], num_speakers=0, language=None, language_probability=0.0
            )

        first = result[0]
        raw_text = str(first.get("text", ""))
        detected = _extract_language(raw_text)
        if detected is None and forced_language != "auto":
            detected = forced_language

        sentence_info = first.get("sentence_info")
        if isinstance(sentence_info, list) and sentence_info:
            segments: list[dict[str, Any]] = []
            speakers: set[str] = set()
            for sentence in sentence_info:
                text = rich_transcription_postprocess(
                    str(sentence.get("sentence") or sentence.get("text") or "")
                )
                speaker = _format_spk(sentence.get("spk"))
                if speaker != "UNKNOWN":
                    speakers.add(speaker)
                segments.append(
                    {
                        "text": text,
                        "start": float(sentence.get("start", 0.0)) / 1000.0,
                        "end": float(sentence.get("end", 0.0)) / 1000.0,
                        "speaker": speaker,
                        "words": [],
                    }
                )
            return DiarizedTranscriptionResult(
                segments=segments,
                words=[],
                num_speakers=len(speakers),
                language=detected,
                language_probability=0.0,
            )

        # No per-segment speaker info — degrade to one UNKNOWN-speaker segment.
        return DiarizedTranscriptionResult(
            segments=[
                {
                    "text": rich_transcription_postprocess(raw_text),
                    "start": 0.0,
                    "end": duration_s,
                    "speaker": "UNKNOWN",
                    "words": [],
                }
            ],
            words=[],
            num_speakers=0,
            language=detected,
            language_probability=0.0,
        )

    def _plain_diarized_fallback(
        self, audio: np.ndarray, audio_sample_rate: int, lang: str
    ) -> DiarizedTranscriptionResult:
        """Re-transcribe without speaker labels and wrap as UNKNOWN-speaker segments.

        Deliberately does NOT swallow a transcribe() failure: if the model is
        genuinely broken, the exception propagates so the route can fall through
        to standard (non-diarized) transcription / surface a real error — rather
        than silently delivering an empty transcript.
        """
        segments, info = self.transcribe(
            audio, audio_sample_rate=audio_sample_rate, language=lang
        )
        return DiarizedTranscriptionResult(
            segments=[
                {"text": s.text, "start": s.start, "end": s.end, "speaker": "UNKNOWN", "words": []}
                for s in segments
            ],
            words=[],
            num_speakers=0,
            language=info.language,
            language_probability=info.language_probability,
        )
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_diarization.py::TestCamPPSinglePass -v --tb=short`
Expected: 4 passed.

- [ ] **Step 7: Lint**

Run: `cd server/backend && ../../build/.venv/bin/ruff check core/stt/backends/sensevoice_backend.py tests/test_sensevoice_diarization.py`
Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add server/backend/core/stt/backends/sensevoice_backend.py server/backend/tests/test_sensevoice_diarization.py
git commit -m "feat(stt): add SenseVoice CAM++ single-pass diarization (transcribe_with_diarization)"
```

---

## Task 1.4: Route engine gate + `diarization_engine` form field

**Files:**
- Modify: `server/backend/core/stt/backends/base.py` (add `use_integrated_diarization_for` near `STTBackend`)
- Modify: `server/backend/api/routes/transcription.py` (form field ~94; both gate sites ~350 and ~907; thread the resolver)
- Test: `server/backend/tests/test_sensevoice_diarization.py`

> **Why a predicate:** the `type(backend).transcribe_with_diarization is not STTBackend.transcribe_with_diarization` check is duplicated at two route sites. Extract it once, add the engine clause, and unit-test it without standing up the route.

- [ ] **Step 1: Write the failing test**

Append to `server/backend/tests/test_sensevoice_diarization.py`:
```python
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
            def is_loaded(self): return True
            def warmup(self): ...
            def transcribe(self, *a, **k): ...
            def supports_translation(self): return False
            @property
            def backend_name(self): return "plain"

        assert use_integrated_diarization_for(_Plain(), "funasr") is False

    def test_none_backend_is_false(self) -> None:
        from server.core.stt.backends.base import use_integrated_diarization_for

        assert use_integrated_diarization_for(None, "funasr") is False
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_diarization.py::TestIntegratedDiarizationPredicate -v --tb=short`
Expected: FAIL — `use_integrated_diarization_for` does not exist.

- [ ] **Step 3: Add the predicate to `base.py`**

In `server/backend/core/stt/backends/base.py`, after the `STTBackend` class definition (end of file or after the class), add a module-level function:
```python
def use_integrated_diarization_for(backend: "STTBackend | None", resolved_engine: str) -> bool:
    """True when the route should use a backend's single-pass diarization.

    Requires (a) the backend overrides ``transcribe_with_diarization`` and
    (b) the resolved engine is ``"funasr"`` (CAM++). Any other engine routes to
    the two-pass pyannote pipeline.
    """
    if backend is None:
        return False
    if resolved_engine != "funasr":
        return False
    return (
        type(backend).transcribe_with_diarization
        is not STTBackend.transcribe_with_diarization
    )
```

- [ ] **Step 4: Run the predicate test and confirm it passes**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_diarization.py::TestIntegratedDiarizationPredicate -v --tb=short`
Expected: 4 passed.

- [ ] **Step 5: Add the `diarization_engine` form field (both handlers)**

In `transcribe_audio` (signature ~line 86), after the `parallel_diarization` form field (line ~96), add:
```python
    diarization_engine: str | None = Form(None),
```
In `import_and_transcribe` (signature ~line 1153), after its `enable_diarization` / `parallel_diarization` form fields (~line 1159), add the same line:
```python
    diarization_engine: str | None = Form(None),
```

- [ ] **Step 6: Resolve + gate the FIRST site — `transcribe_audio` (~348-355)**

This handler has `request`, `config`, and `engine = model_manager.transcription_engine` (line 296) in scope. Replace the `use_integrated_diarization = (...)` block (lines 348-355) with:
```python
        # Resolve the diarization engine (funasr CAM++ single-pass vs pyannote two-pass).
        from server.config import resolve_sensevoice_diarization_engine
        from server.core.stt.backends.base import use_integrated_diarization_for

        backend = engine._backend
        resolved_diar_engine = resolve_sensevoice_diarization_engine(
            getattr(engine, "model_name", None),  # set in Stt engine __init__ (engine.py:216)
            diarization_engine,
            request.app.state.config.get("diarization", "sensevoice_engine", default="funasr"),
            funasr_diar_available=getattr(backend, "_diarization_loaded", False),
        )
        use_integrated_diarization = diarization and use_integrated_diarization_for(
            backend, resolved_diar_engine
        )
```
(The local flag at this site is named `diarization`.)

- [ ] **Step 7a: Thread the engine into the file-import helper `_run_file_import` (signature ~824-836)**

The SECOND gate site lives in the internal helper `_run_file_import`, which has **no** `request`. Add two params to its signature, after `use_parallel_default: bool,` (line 832):
```python
    diarization_engine: str | None = None,
    sensevoice_engine_default: str = "funasr",
```

- [ ] **Step 7b: Pass them from `import_and_transcribe` (call ~1277-1294)**

In `import_and_transcribe` (where `config = request.app.state.config` exists at line 1270), in the `_run_file_import(...)` keyword call, after `use_parallel_default=use_parallel_default,` (line 1290), add:
```python
            diarization_engine=diarization_engine,
            sensevoice_engine_default=config.get(
                "diarization", "sensevoice_engine", default="funasr"
            ),
```

- [ ] **Step 7c: Gate the SECOND site inside `_run_file_import` (~905-912)**

The helper has `engine = model_manager.ensure_transcription_loaded()` (line 855) and `backend = engine._backend` (line 906). Replace the `use_integrated_diarization = (...)` block (lines 907-912) with:
```python
        from server.config import resolve_sensevoice_diarization_engine
        from server.core.stt.backends.base import use_integrated_diarization_for

        resolved_diar_engine = resolve_sensevoice_diarization_engine(
            getattr(engine, "model_name", None),
            diarization_engine,
            sensevoice_engine_default,
            funasr_diar_available=getattr(backend, "_diarization_loaded", False),
        )
        use_integrated_diarization = enable_diarization and use_integrated_diarization_for(
            backend, resolved_diar_engine
        )
```
(Keep the existing `backend = engine._backend` line above it; the local flag here is named `enable_diarization`.)

- [ ] **Step 8: Verify nothing regressed in the route module**

Run: `cd server/backend && ../../build/.venv/bin/python -c "import ast; ast.parse(open('api/routes/transcription.py').read()); print('OK')"`
Expected: `OK`

Run the existing transcription route tests:
`cd server/backend && ../../build/.venv/bin/pytest tests/test_transcription_durability_routes.py tests/test_sensevoice_diarization.py -v --tb=short`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add server/backend/core/stt/backends/base.py server/backend/api/routes/transcription.py server/backend/tests/test_sensevoice_diarization.py
git commit -m "feat(server): gate SenseVoice diarization engine (funasr CAM++ vs pyannote) on the route"
```

---

## Task 1.5: Bootstrap warm-download of cam++ + fsmn-vad

**Files:**
- Modify: `server/docker/bootstrap_runtime.py` (add `warm_download_sensevoice_models` after `check_funasr_import` ~1361; call it after the funasr install ~2230)
- Test: `server/backend/tests/test_sensevoice_diarization.py`

- [ ] **Step 1: Write the failing helper test**

Append to `server/backend/tests/test_sensevoice_diarization.py`:
```python
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
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_diarization.py::TestBootstrapWarmDownload -v --tb=short`
Expected: FAIL — `warm_download_sensevoice_models` does not exist.

- [ ] **Step 3: Add the warm-download helper**

In `bootstrap_runtime.py`, after `check_funasr_import` (ends line 1361), add:
```python
def warm_download_sensevoice_models(
    venv_python: Path,
    timeout_seconds: int,
) -> bool:
    """Best-effort pre-fetch of cam++ + fsmn-vad into the HF cache.

    Both repos are ungated (~30 MB total). Failure is non-fatal — the runtime
    load-degrade still covers a missing model — so this never raises.
    Returns True if the prefetch subprocess reported success.
    """
    prefetch = """
import json
try:
    from huggingface_hub import snapshot_download
    snapshot_download("funasr/campplus")
    snapshot_download("funasr/fsmn-vad")
    print(json.dumps({"ok": True}))
except Exception as exc:
    print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
"""
    try:
        result = subprocess.run(
            [str(venv_python), "-c", prefetch],
            text=True,
            capture_output=True,
            timeout=max(60, min(timeout_seconds, 600)),
            check=False,
        )
    except Exception as exc:
        log(f"SenseVoice CAM++ warm-download skipped (non-fatal): {type(exc).__name__}: {exc}")
        return False

    output = (result.stdout or "").strip().splitlines()
    try:
        payload = json.loads(output[-1]) if output else {"ok": False}
    except json.JSONDecodeError:
        payload = {"ok": False}
    if payload.get("ok"):
        log("SenseVoice CAM++ models warm-downloaded (cam++, fsmn-vad)")
        return True
    log(f"SenseVoice CAM++ warm-download did not complete (non-fatal): {payload.get('error', '')}")
    return False
```

- [ ] **Step 4: Call it after the funasr install**

In `bootstrap_runtime.py`, inside the `elif install_funasr:` branch, immediately after `log("FunASR installed")` (line ~2230), add:
```python
                    warm_download_sensevoice_models(
                        venv_python=venv_python,
                        timeout_seconds=timeout_seconds,
                    )
```

- [ ] **Step 5: Run the helper test + syntax check**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_diarization.py::TestBootstrapWarmDownload -v --tb=short`
Expected: 1 passed.
Run: `cd server && ../build/.venv/bin/python -c "import ast; ast.parse(open('docker/bootstrap_runtime.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add server/docker/bootstrap_runtime.py server/backend/tests/test_sensevoice_diarization.py
git commit -m "feat(server): warm-download cam++/fsmn-vad when INSTALL_FUNASR=true (non-fatal)"
```

---

## Task 1.6: Document the config key

**Files:**
- Modify: `server/config.yaml` (diarization block, after `parallel:` ~line 343)

- [ ] **Step 1: Add the documented key**

In `server/config.yaml`, after the `parallel: false` line in the `diarization:` block, add:
```yaml

    # Default speaker-diarization engine for the SenseVoice STT model ONLY.
    # "funasr"   - FunASR-native CAM++ single-pass (default; fast, ungated, no HF token)
    # "pyannote" - the standard two-pass pyannote diarizer (override)
    # Ignored for all non-SenseVoice models (they always use pyannote/sortformer).
    # The dashboard can override this per-transcription.
    # Default: "funasr"
    sensevoice_engine: "funasr"
```

- [ ] **Step 2: Validate YAML parses**

Run: `cd server && ../build/.venv/bin/python -c "import yaml; d=yaml.safe_load(open('config.yaml')); print(d['diarization']['sensevoice_engine'])"`
Expected: `funasr`

- [ ] **Step 3: Commit**

```bash
git add server/config.yaml
git commit -m "docs(config): document diarization.sensevoice_engine (funasr default)"
```

---

# WAVE 2 — Dashboard engine selector + flag fixes (frontend)

> Run all frontend tests under Node 22: `cd dashboard && nvm use` first.

## Task 2.1: Capability flags

**Files:**
- Modify: `dashboard/src/services/modelCapabilities.ts` (add `supportsFunasrDiarization` after `supportsDiarization` ~189)
- Modify: `dashboard/src/services/modelRegistry.ts` (SenseVoice entry, line 85)
- Test: `dashboard/src/services/modelCapabilities.test.ts`, `dashboard/src/services/modelRegistry.test.ts`

- [ ] **Step 1: Write the failing tests**

In `dashboard/src/services/modelCapabilities.test.ts`, add `supportsFunasrDiarization` to the imports (line ~15) and a new describe block (after the `supportsDiarization` block, ~line 430):
```typescript
describe('supportsFunasrDiarization', () => {
  it('returns true only for SenseVoice models', () => {
    expect(supportsFunasrDiarization('iic/SenseVoiceSmall')).toBe(true);
    expect(supportsFunasrDiarization('FunAudioLLM/SenseVoiceSmall')).toBe(true);
  });
  it('returns false for every other backend', () => {
    expect(supportsFunasrDiarization('Systran/faster-whisper-large-v3')).toBe(false);
    expect(supportsFunasrDiarization('nvidia/parakeet-tdt-0.6b-v3')).toBe(false);
    expect(supportsFunasrDiarization('microsoft/VibeVoice-ASR')).toBe(false);
    expect(supportsFunasrDiarization(null)).toBe(false);
  });
});
```

In `dashboard/src/services/modelRegistry.test.ts`, find the existing SenseVoice assertion (`m.capabilities.diarization` near line 89) and change the expectation to `true`:
```typescript
      expect(m.capabilities.diarization).toBe(true);
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd dashboard && nvm use && npx vitest run src/services/modelCapabilities.test.ts src/services/modelRegistry.test.ts`
Expected: FAIL — `supportsFunasrDiarization` is not exported; registry diarization is `false`.

- [ ] **Step 3: Add `supportsFunasrDiarization`**

In `dashboard/src/services/modelCapabilities.ts`, after `supportsDiarization` (ends line 189), add:
```typescript
/**
 * Returns true if the model supports FunASR-native CAM++ single-pass diarization.
 * SenseVoice-only — every other backend uses the pyannote two-pass path.
 */
export function supportsFunasrDiarization(modelName: string | null | undefined): boolean {
  return isSenseVoiceModel(modelName);
}
```

- [ ] **Step 4: Flip the registry flag**

In `dashboard/src/services/modelRegistry.ts`, line 85 (the SenseVoice entry), change `diarization: false` to `diarization: true`:
```typescript
    capabilities: { translation: false, liveMode: false, diarization: true, languageCount: 5 },
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `cd dashboard && nvm use && npx vitest run src/services/modelCapabilities.test.ts src/services/modelRegistry.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/services/modelCapabilities.ts dashboard/src/services/modelRegistry.ts dashboard/src/services/modelCapabilities.test.ts dashboard/src/services/modelRegistry.test.ts
git commit -m "feat(dashboard): add supportsFunasrDiarization + mark SenseVoice diarization-capable"
```

---

## Task 2.2: Send `diarization_engine` in the API client

**Files:**
- Modify: `dashboard/src/api/client.ts` (option types; the 3 FormData builders at ~522, ~764, ~840)

- [ ] **Step 1: Extend the option types**

Find the options interfaces used by `transcribeAudio` (`TranscriptionUploadOptions`) and the import builders. Add an optional field to each:
```typescript
  /** SenseVoice-only: which diarization engine to use ('funasr' CAM++ or 'pyannote'). */
  diarization_engine?: 'funasr' | 'pyannote';
```

- [ ] **Step 2: Append the field in all three builders**

In `client.ts`, in `transcribeAudio` after the `expected_speakers` append (line ~524), add:
```typescript
    if (options?.diarization_engine)
      fd.append('diarization_engine', options.diarization_engine);
```
Add the identical three lines after the `parallel_diarization` append in **both** import builders (after lines ~770 and ~846).

- [ ] **Step 3: Type-check**

Run: `cd dashboard && nvm use && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/api/client.ts
git commit -m "feat(dashboard): send diarization_engine in transcription requests"
```

---

## Task 2.3: Engine selector in `SessionImportTab`

**Files:**
- Modify: `dashboard/components/views/SessionImportTab.tsx` (import the helper ~36; state ~93; reset effect ~254; options ~336; render inside the `{diarization && (...)}` block ~781)

- [ ] **Step 1: Import the capability helper + add state**

At the imports (near line 36), add:
```typescript
import { supportsFunasrDiarization } from '../../src/services/modelCapabilities';
```
After `const [parallelDiarization, setParallelDiarization] = useState<boolean>(false);` (line 93), add:
```typescript
  // SenseVoice-only: CAM++ (funasr) is the default, pyannote is the override.
  const [diarizationEngine, setDiarizationEngine] = useState<'funasr' | 'pyannote'>('funasr');
  const showEngineSelector = supportsFunasrDiarization(activeModel);
```

- [ ] **Step 2: Reset the engine when the model loses CAM++ support**

After the existing word-timestamp reset effect (near line 254), add:
```typescript
  useEffect(() => {
    if (!showEngineSelector) setDiarizationEngine('funasr');
  }, [showEngineSelector]);
```

- [ ] **Step 3: Send the engine in the options**

In the options object built around line 336, after `parallel_diarization: ...`, add:
```typescript
        diarization_engine:
          showEngineSelector && diarization && !multitrack ? diarizationEngine : undefined,
```
Add `diarizationEngine` and `showEngineSelector` to that callback's dependency array (alongside `parallelDiarization` at line ~356).

- [ ] **Step 4: Render the selector**

Inside the `{diarization && ( ... )}` block (opens line 781), after the parallel-diarization `AppleSwitch` group (closes ~line 808), add the engine selector (only for SenseVoice):
```tsx
              {showEngineSelector && (
                <div className="flex items-center justify-between">
                  <label className="text-sm text-zinc-300">Diarization engine</label>
                  <select
                    className="rounded-md bg-zinc-800 px-2 py-1 text-sm text-zinc-100"
                    value={diarizationEngine}
                    onChange={(e) =>
                      setDiarizationEngine(e.target.value === 'pyannote' ? 'pyannote' : 'funasr')
                    }
                  >
                    <option value="funasr">CAM++ (fast, built-in)</option>
                    <option value="pyannote">pyannote (two-pass)</option>
                  </select>
                </div>
              )}
```

> Match the surrounding markup conventions (class names, the `AppleSwitch`/row layout) used by the adjacent parallel-diarization control — the snippet above is structurally correct but adjust classes to the file's existing style.

- [ ] **Step 5: Type-check + run any existing SessionImportTab tests**

Run: `cd dashboard && nvm use && npx tsc --noEmit`
Expected: no new errors.
Run: `cd dashboard && npx vitest run components/views` (if SessionImportTab has tests)
Expected: pass.

- [ ] **Step 6: UI contract (CSS classes touched)**

Per CLAUDE.md, after UI edits touching CSS classes, from `dashboard/`:
`npm run ui:contract:check`
If it flags changes, follow the full update sequence in `.claude/skills/ui-contract/SKILL.md` (extract → build → `--update-baseline` → check), bumping `meta.spec_version` first.

- [ ] **Step 7: Commit**

```bash
git add dashboard/components/views/SessionImportTab.tsx
git commit -m "feat(dashboard): add SenseVoice diarization-engine selector (CAM++ default, pyannote override)"
```

---

# WAVE 3 — Per-word timestamps (cuttable)

> **Cut criterion:** implement, then run the § Smoke Test word-timestamp checks. If word-level does not measurably beat segment-level for SenseVoice (or crashes under the VAD multi-segment pipeline), **revert these commits before merging** — Waves 1+2 stand alone. This wave only sharpens the **pyannote-override** path; CAM++ is segment-level by construction.

## Task 3.1: Token→word reconstruction helper

**Files:**
- Modify: `server/backend/core/stt/backends/sensevoice_backend.py` (add `_tokens_to_words`)
- Test: `server/backend/tests/test_sensevoice_diarization.py`

- [ ] **Step 1: Write the failing test**

Append to `server/backend/tests/test_sensevoice_diarization.py`:
```python
class TestTokensToWords:
    def test_merges_sentencepiece_subwords_on_marker(self) -> None:
        from server.core.stt.backends.sensevoice_backend import _tokens_to_words

        # SentencePiece: "▁" marks a word start; pieces in seconds.
        tokens = [
            ["▁Hello", 0.30, 0.54],
            ["▁wor", 0.54, 0.78],
            ["ld", 0.78, 0.96],
        ]
        words = _tokens_to_words(tokens, segment_offset_s=0.0)
        assert [w["word"] for w in words] == ["Hello", "world"]
        assert words[0]["start"] == pytest.approx(0.30)
        assert words[1]["start"] == pytest.approx(0.54)
        assert words[1]["end"] == pytest.approx(0.96)

    def test_applies_segment_offset(self) -> None:
        from server.core.stt.backends.sensevoice_backend import _tokens_to_words

        words = _tokens_to_words([["▁Hi", 0.0, 0.2]], segment_offset_s=10.0)
        assert words[0]["start"] == pytest.approx(10.0)
        assert words[0]["end"] == pytest.approx(10.2)

    def test_empty_or_malformed_returns_empty(self) -> None:
        from server.core.stt.backends.sensevoice_backend import _tokens_to_words

        assert _tokens_to_words([], 0.0) == []
        assert _tokens_to_words(None, 0.0) == []  # type: ignore[arg-type]
        assert _tokens_to_words([["bad"]], 0.0) == []
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_diarization.py::TestTokensToWords -v --tb=short`
Expected: FAIL — `_tokens_to_words` does not exist.

- [ ] **Step 3: Implement the helper**

In `sensevoice_backend.py`, after `_format_spk`, add:
```python
_WORD_START_MARKER = "▁"  # SentencePiece "▁"


def _tokens_to_words(
    tokens: list[list[Any]] | None, segment_offset_s: float
) -> list[dict[str, Any]]:
    """Merge CTC sub-word tokens ([piece, start_s, end_s]) into words.

    A new word starts on a piece beginning with the SentencePiece "▁" marker.
    Times are in seconds; ``segment_offset_s`` is added to make VAD-segment-relative
    timestamps absolute. Malformed input yields an empty list (caller falls back
    to segment-level).
    """
    if not tokens:
        return []
    words: list[dict[str, Any]] = []
    cur_text = ""
    cur_start: float | None = None
    cur_end: float | None = None
    try:
        for piece, start, end in (t for t in tokens):
            piece_s = str(piece)
            s = float(start) + segment_offset_s
            e = float(end) + segment_offset_s
            if piece_s == _WORD_START_MARKER:
                continue
            starts_word = piece_s.startswith(_WORD_START_MARKER)
            clean = piece_s[1:] if starts_word else piece_s
            if starts_word or cur_start is None:
                if cur_text:
                    words.append({"word": cur_text, "start": cur_start, "end": cur_end})
                cur_text, cur_start, cur_end = clean, s, e
            else:
                cur_text += clean
                cur_end = e
    except (TypeError, ValueError):
        return []
    if cur_text:
        words.append({"word": cur_text, "start": cur_start, "end": cur_end})
    return words
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_diarization.py::TestTokensToWords -v --tb=short`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add server/backend/core/stt/backends/sensevoice_backend.py server/backend/tests/test_sensevoice_diarization.py
git commit -m "feat(stt): add SenseVoice CTC token->word reconstruction helper (Wave 3)"
```

---

## Task 3.2: Populate `words[]` on the transcribe path (best-effort)

**Files:**
- Modify: `server/backend/core/stt/backends/sensevoice_backend.py` (`transcribe` generate-call + `_parse_result`)
- Test: `server/backend/tests/test_sensevoice_diarization.py`

- [ ] **Step 1: Write the failing test**

Append to `server/backend/tests/test_sensevoice_diarization.py`:
```python
class TestWordTimestamps:
    def test_words_populated_when_timestamps_present(self) -> None:
        model = _FakeAutoModel(
            [{"text": "<|en|>Hello world.", "sentence_info": [
                {"sentence": "<|en|>Hello world.", "start": 0, "end": 1000, "spk": 0},
            ], "timestamp": [
                ["▁Hello", 0.0, 0.4], ["▁world", 0.4, 0.9],
            ]}]
        )
        backend, stubs = _load(model, cam=True)
        with patch.dict(sys.modules, stubs):
            segments, _ = backend.transcribe(np.zeros(16000, dtype=np.float32))
        # output_timestamp must have been requested
        assert model.generate.call_args.kwargs.get("output_timestamp") is True
        all_words = [w for s in segments for w in s.words]
        assert [w["word"] for w in all_words] == ["Hello", "world"]

    def test_missing_timestamps_keeps_empty_words(self) -> None:
        model = _FakeAutoModel(
            [{"text": "<|en|>Hi.", "sentence_info": [
                {"sentence": "<|en|>Hi.", "start": 0, "end": 500, "spk": 0},
            ]}]  # no "timestamp" key
        )
        backend, stubs = _load(model, cam=True)
        with patch.dict(sys.modules, stubs):
            segments, _ = backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert all(s.words == [] for s in segments)
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_diarization.py::TestWordTimestamps -v --tb=short`
Expected: FAIL — `output_timestamp` not passed; `words` stays empty.

- [ ] **Step 3: Request timestamps in `transcribe`**

In `transcribe`'s `generate(...)` call (lines ~184-192), add `output_timestamp=True`:
```python
            result = self._model.generate(
                input=wav_path,
                cache={},
                language=lang,
                use_itn=True,
                batch_size_s=300,
                merge_vad=True,
                merge_length_s=15,
                output_timestamp=True,
            )
```

- [ ] **Step 4: Populate words in `_parse_result`**

In `_parse_result`, in the `sentence_info` branch, after computing `start`/`end` for each sentence, attach words sliced from the top-level `timestamp` list by time window. Replace the segment append (line ~249) with:
```python
                seg_words = _segment_words(first.get("timestamp"), start, end)
                segments.append(
                    BackendSegment(text=text, start=start, end=end, words=seg_words)
                )
```
And add a helper after `_tokens_to_words`:
```python
def _segment_words(
    timestamp: list[list[Any]] | None, seg_start_s: float, seg_end_s: float
) -> list[dict[str, Any]]:
    """Best-effort: return words whose midpoint falls within [seg_start, seg_end].

    The top-level CTC ``timestamp`` is whole-clip; slice it per sentence. Any
    parse problem yields [] (segment-level fallback — never a hard dependency).
    """
    words = _tokens_to_words(timestamp, segment_offset_s=0.0)
    out: list[dict[str, Any]] = []
    for w in words:
        try:
            mid = (float(w["start"]) + float(w["end"])) / 2.0
        except (TypeError, ValueError, KeyError):
            continue
        if seg_start_s <= mid <= seg_end_s:
            out.append(w)
    return out
```

> **Unit note (verify on hardware):** the CTC math yields **seconds**, while `sentence_info` start/end are **ms** (divided by 1000 in the parser, so both are seconds here). If the smoke test shows the units differ, normalize in `_segment_words` before comparing. See § Smoke Test.

- [ ] **Step 5: Run the test and confirm it passes**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_diarization.py::TestWordTimestamps -v --tb=short`
Expected: 2 passed.

- [ ] **Step 6: Run the full SenseVoice suite + lint**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_sensevoice_backend.py tests/test_sensevoice_routing.py tests/test_sensevoice_diarization.py -v --tb=short`
Expected: all pass (the existing `test_sentence_info_yields_per_sentence_segments` has no `timestamp` key → `words=[]`, unchanged).
Run: `cd server/backend && ../../build/.venv/bin/ruff check core/stt/backends/sensevoice_backend.py`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add server/backend/core/stt/backends/sensevoice_backend.py server/backend/tests/test_sensevoice_diarization.py
git commit -m "feat(stt): best-effort SenseVoice word timestamps via CTC alignment (Wave 3, cuttable)"
```

---

# Final: GPU Smoke Test (real hardware — gates ship/cut)

Run a real CUDA build with `INSTALL_FUNASR=true` and `iic/SenseVoiceSmall` selected.

- [ ] **W1 CAM++ default:** transcribe a known 2-speaker clip with diarization on (engine left at default). Confirm distinct `SPEAKER_00`/`SPEAKER_01` segments, no `TypeError`, transcription intact.
- [ ] **W1 single speaker:** a 1-speaker clip yields all `SPEAKER_00`, no crash.
- [ ] **W1 override:** repeat with `diarization_engine=pyannote` (dashboard selector) — confirm the two-pass pyannote path runs and labels appear.
- [ ] **W1 fallback:** simulate cam++ unavailable (offline first run with no warm cache) — transcription still completes; engine falls back to pyannote or plain transcript; result never dropped.
- [ ] **W1 memory/latency:** compare SenseVoice+vad+cam++ vs SenseVoice alone; confirm within the 12 GB budget (VibeVoice-OOM history).
- [ ] **W3 decision:** verify per-token timestamp **unit** (s vs ms) and VAD-offset correctness on multi-segment audio; measure realized boundary error vs the 60 ms grid; check crash rate (#2339/#2333). **If word-level doesn't beat segment-level → revert Wave 3 commits before merge.**

---

## Self-Review (run before opening the PR)

- [ ] **Spec coverage:** every spec section has a task — engine resolver (1.1), always-load + parser (1.2), CAM++ single-pass + durability (1.3), route gate + form field (1.4), warm-download (1.5), config doc (1.6), capability flags (2.1), client field (2.2), selector UI (2.3), word timestamps (3.1-3.2). ✔
- [ ] **Placeholder scan:** no `TODO`/`TBD`; every code step shows complete code.
- [ ] **Type consistency:** `resolve_sensevoice_diarization_engine` / `use_integrated_diarization_for` / `_format_spk` / `_tokens_to_words` / `_segment_words` / `supportsFunasrDiarization` / `diarization_engine` field names match across tasks.
- [ ] **Route anchors (pinned, re-verify line numbers):** `engine.model_name` (engine.py:216), first site in `transcribe_audio` (local flag `diarization`, `request`/`config` in scope), second site in `_run_file_import` (local flag `enable_diarization`, engine threaded via `diarization_engine` + `sensevoice_engine_default` from `import_and_transcribe`). Line numbers may have drifted — confirm before editing.
- [ ] **`gitnexus_detect_changes()`** before the final commit (code changes touch the symbol graph).
```
