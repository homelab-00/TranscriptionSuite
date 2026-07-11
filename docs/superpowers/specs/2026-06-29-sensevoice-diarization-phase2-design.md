# SenseVoice Diarization — Phase 2 Design

> **Status:** Approved design, ready for implementation planning (→ writing-plans).
> **Date:** 2026-06-29
> **Branch:** `feature/sensevoice-diarization-phase2`
> **Predecessor:** [Phase 1 plan](../plans/2026-06-24-sensevoice-phase1-linux-nvidia.md) (transcriber-only SenseVoice, merged via PR #198). Issue [#129](https://github.com/homelab-00/TranscriptionSuite/issues/129).

## Goal

Give the SenseVoice (FunASR) STT backend first-class speaker diarization with **two selectable engines**:

1. **FunASR-native CAM++ single-pass** — the **default** for SenseVoice. Speakers come out of SenseVoice's own `AutoModel.generate()` call (one pass, no extra model server, ungated models, no HF token).
2. **pyannote two-pass** — the **override**. The suite's existing, mature, backend-agnostic diarizer, reached when the user picks it.

Plus a best-effort, **cuttable** enhancement (Wave 3): populate per-word timestamps for SenseVoice so the pyannote-override path can use the precise word-level merge instead of the segment-level fallback.

## Scope

**In scope (one combined PR):**
- Wave 1 — CAM++ single-pass backend + engine-selection plumbing (server/API).
- Wave 2 — Dashboard engine selector + capability-flag fixes (frontend).
- Wave 3 — Best-effort per-word timestamps for SenseVoice (**cuttable**: ship only if a GPU smoke test shows it beats segment-level).

**Out of scope:** changing pyannote/Sortformer behavior for any non-SenseVoice backend; live-mode diarization; emotion/audio-event tags as a product feature; Windows/macOS SenseVoice; `ct-punc` (1.1 GB, not needed — see §3.5).

**Platform:** Linux / NVIDIA (CUDA), matching SenseVoice Phase 1. CAM++ also runs on CPU but is validated on CUDA.

---

## Background — two diarization shapes already exist

The suite already encodes the exact two shapes this design needs (verified):

- **Two-pass (backend-agnostic):** `DiarizationEngine` (pyannote) / `sortformer_engine` runs independently on raw audio *after* STT, then `speaker_merge.py` stitches `SPEAKER_NN` labels onto STT segments by timestamp overlap. Orchestrated by `core/parallel_diarize.py` (`transcribe_then_diarize` / `transcribe_and_diarize`). Requires only `start`/`end`/`text` per segment; uses `words[]` for higher-fidelity word-level assignment when present, else falls back to proportional text splitting (`build_speaker_segments_nowords`). Persisted via `database.py::_insert_diarization_segments_with_words`. Triggered by the `/transcription` form flags `diarization`, `parallel_diarization`, `expected_speakers`.
- **Single-pass (integrated):** a backend overrides `STTBackend.transcribe_with_diarization()` (`core/stt/backends/base.py:182-204`) and returns a `DiarizedTranscriptionResult` (`base.py:75-82`) itself. WhisperX and VibeVoice-ASR already do this. The route auto-detects it (`api/routes/transcription.py:348-355`, duplicated at `:905-911`):

  ```python
  use_integrated_diarization = (
      diarization
      and backend is not None
      and type(backend).transcribe_with_diarization
      is not STTBackend.transcribe_with_diarization
  )
  ```

**SenseVoice today:** `SenseVoiceBackend` (`core/stt/backends/sensevoice_backend.py`) loads `AutoModel(model=…, vad_model="fsmn-vad", …)` with **no `spk_model`**, does **not** override `transcribe_with_diarization` (so it already falls through to the two-pass path), and returns segments with `words=[]` (per-sentence `sentence_info` timestamps, or a whole-clip fallback). So pyannote *already* diarizes SenseVoice at the backend level — this design makes that a deliberate, selectable behavior and adds the faster native default.

## Key verified facts (source: FunASR `v1.3.12` tag, HF API, PyPI, issues #2662/#2706/#2333/#2339, SenseVoice #215)

- **No new dependency.** CAM++ works on the `funasr>=1.3.12` already pinned in `pyproject.toml`. The historical `distribute_spk` `TypeError` crash is fixed at `v1.3.12` via an auto-fallback to `spk_mode="vad_segment"`. **No source install** (the SenseVoice README's "install from source" note is stale).
- **CAM++ config:** `AutoModel(model="iic/SenseVoiceSmall", vad_model="fsmn-vad", spk_model="cam++", spk_mode="vad_segment", hub="hf", device="cuda")`, then `generate(input=…, language=…, use_itn=True, merge_vad=True, merge_length_s=15, batch_size_s=300)`.
- **Output shape:** `result[0]["sentence_info"]` = list of `{"start": int_ms, "end": int_ms, "sentence": str, "timestamp": [], "spk": int}`. **The per-segment text key is `"sentence"`, not `"text"`** for SenseVoice — read `seg.get("sentence") or seg.get("text")`. `spk` is an integer index; single speaker ⇒ all `spk=0` (not an error).
- **Footprint:** cam++ = `funasr/campplus` (**28 MB**), fsmn-vad = `funasr/fsmn-vad` (1.7 MB, already loaded). **Incremental ≈ 30 MB.** All ungated/public (no HF token). `ct-punc` (1.1 GB) is **not required** and does not punctuate `sentence_info[i]["sentence"]` — **omit it**.
- **No attach API:** `spk_model` is built in `AutoModel.__init__`; it cannot be added to an already-constructed instance. ⇒ the diarizing model must be built with `spk_model` at load time (see load strategy, §1.3).
- **Sub-models download at `AutoModel(...)` construction**, not at `generate()`. First build needs network; subsequent runs hit the HF cache.

---

## Decisions (locked with the user)

| Decision | Choice |
|---|---|
| Engine selection UX | **Config default + dashboard override** |
| Default engine for SenseVoice | **CAM++** (pyannote is the override) |
| CAM++ availability | **SenseVoice-only**; never offered for other backends |
| Word timestamps (Wave 3) | **Keep as cuttable Wave 3** — implement last, ship only if a GPU smoke test shows it beats segment-level |
| Deliverable shape | **One spec, one combined PR** (Wave 3 excised pre-merge if it underperforms) |
| Bootstrap warm-download | **In scope** — pre-fetch cam++ + fsmn-vad when `INSTALL_FUNASR=true` (best-effort, non-fatal) |

---

## 1. Architecture

### 1.1 Two paths, one selector
- **CAM++ (default) → single-pass.** `SenseVoiceBackend.transcribe_with_diarization()` runs `generate()` on a `spk_model="cam++"` model and returns a `DiarizedTranscriptionResult`.
- **pyannote (override) → two-pass.** Existing `parallel_diarize` + `speaker_merge`, unchanged. Reached whenever the resolved engine is not `funasr`.

### 1.2 Route gate (the minimal change)
The single-pass switch becomes engine-aware at **both** sites (`transcription.py:350` and `:905`):

```python
use_integrated_diarization = (
    diarization
    and backend is not None
    and type(backend).transcribe_with_diarization is not STTBackend.transcribe_with_diarization
    and resolved_diar_engine == "funasr"          # NEW
)
```

When `resolved_diar_engine != "funasr"`, the condition is false and execution falls through to the existing two-pass path — so **pyannote-as-override needs no new code**, only the gate. `resolved_diar_engine` is computed once (§2) and is always non-`funasr` for non-SenseVoice models.

### 1.3 Load strategy — always-load CAM++ (chosen approach)
`SenseVoiceBackend.load()` builds the `AutoModel` **with `spk_model="cam++"` whenever the CAM++ feature is available** — *not* reload-on-toggle.

- **Rationale:** cam++ is 28 MB. A single always-diarizing instance avoids both (a) reload latency on every diarize toggle and (b) the dual-instance memory cost — important given the suite's 12 GB VibeVoice-OOM history. `transcribe()` ignores `spk`; `transcribe_with_diarization()` reads it.
- **Accepted cost:** non-diarization jobs compute speaker embeddings they discard (negligible at 28 MB). If profiling ever shows it matters, a reload/dual-instance optimization is a localized follow-up — the public contract (`load`/`transcribe`/`transcribe_with_diarization`) does not change.
- **Bonus:** `spk_mode="vad_segment"` reliably produces `sentence_info` (one entry per VAD segment), which (a) the CAM++ path reads for `spk` and (b) **mitigates the whole-clip-fallback degradation** for the pyannote-override path — SenseVoice gets dependable per-segment timestamps instead of occasionally collapsing to a single whole-clip segment.
- **Required consequence (parser harmonization):** with `spk_model` loaded, segments arrive under the key **`"sentence"`**, not **`"text"`**. The existing `transcribe()` parser (`_parse_result`, which currently reads `seg.get("text")`) **must** be updated to `seg.get("sentence") or seg.get("text")` so the non-diarization path keeps working. See §3.1.1.
- **Graceful load degrade:** if building with `spk_model` fails (e.g. cam++ undownloadable offline), fall back to building a **plain** SenseVoice model (no `spk_model`), mark the CAM++ engine unavailable, and let the dashboard offer pyannote. The transcription path is never blocked by a diarization-model problem.

---

## 2. Engine selection (config + request + resolution)

### 2.1 Config
Add to the `diarization:` block in `server/config.yaml` (after `parallel:`):

```yaml
    # Default speaker-diarization engine for the SenseVoice STT model ONLY.
    # "funasr"   - FunASR-native CAM++ single-pass (default; fast, no HF token)
    # "pyannote" - the standard two-pass pyannote diarizer (override)
    # Ignored for all non-SenseVoice models (they always use pyannote/sortformer).
    # Default: "funasr"
    sensevoice_engine: "funasr"
```

### 2.2 Request field
Add an optional form field to `/transcription` (and the file-import path): `diarization_engine: "auto" | "funasr" | "pyannote"` (default `"auto"`). `auto` ⇒ use the config default. The dashboard sends `"funasr"` or `"pyannote"` when the user overrides.

### 2.3 Resolution
A pure helper, placed **alongside `resolve_parallel_diarization_default`** (the existing diarization-config resolver invoked at `transcription.py:442-444`), so all diarization-config resolution lives in one module:

```python
def resolve_sensevoice_diarization_engine(
    model_name: str, request_value: str | None, config_default: str,
    *, funasr_diar_available: bool,
) -> str:
    """Return 'funasr' or 'pyannote'. 'funasr' only ever for SenseVoice when available."""
    if not is_sensevoice_model(model_name):
        return "pyannote"            # CAM++ never offered for other backends
    chosen = (request_value or "auto").lower()
    if chosen == "auto":
        chosen = (config_default or "funasr").lower()
    if chosen == "funasr" and not funasr_diar_available:
        return "pyannote"            # runtime fallback if CAM++ unavailable
    return "funasr" if chosen == "funasr" else "pyannote"
```

This is the single source of truth feeding the route gate (§1.2). It is unit-tested in isolation.

---

## 3. Wave 1 — CAM++ single-pass backend (server/API)

### 3.1 `SenseVoiceBackend.load()`
Build the `AutoModel` with `spk_model="cam++"`, `spk_mode="vad_segment"` (skips the punc-mode warning + forced fallback) when the CAM++ feature is available; else plain (see §1.3). Keep existing `vad_model`, `vad_kwargs`, `hub="hf"`, `disable_update=True`, device composition.

### 3.1.1 Harmonize the `transcribe()` parser (required by always-load)
Update `_parse_result` (the non-diarization path) to read each segment as `seg.get("sentence") or seg.get("text")`, because always-loading `spk_model` switches the `sentence_info` key from `"text"` to `"sentence"` (§1.3). Without this, plain transcription returns empty text. Add a regression test that `transcribe()` still yields correct text when the stub model is built with `spk_model` (see §3.7). This is a small, contained change but is **load-bearing** — it gates whether non-diarization SenseVoice transcription keeps working.

### 3.2 `SenseVoiceBackend.transcribe_with_diarization()` (new override)
- Write the float32 audio to a temp WAV (reuse the existing `_write_temp_wav` helper), call `generate(input=path, language=resolved_lang, use_itn=True, merge_vad=True, merge_length_s=15, batch_size_s=300)`.
- Parse `result[0]["sentence_info"]`: for each segment build `{"text": rich_transcription_postprocess(seg.get("sentence") or seg.get("text") or ""), "start": ms/1000, "end": ms/1000, "speaker": _format_spk(seg.get("spk")), "words": []}`.
- **Speaker label:** `_format_spk(0) -> "SPEAKER_00"` — mirror the `SPEAKER_{int:02d}` convention (`vibevoice_asr_backend.py:1172`) so CAM++ renders identically to pyannote in the UI. Missing/None `spk` ⇒ `"UNKNOWN"`.
- Compute `num_speakers` = count of distinct non-`UNKNOWN` labels.
- Return `DiarizedTranscriptionResult(segments=…, words=[], num_speakers=…, language=…, language_probability=0.0)`. Ignore the Whisper-shaped kwargs (`beam_size`, `initial_prompt`, `suppress_tokens`, `vad_filter`, `hf_token`, `num_speakers` hint) — same `del …` pattern as `transcribe()`.

### 3.3 Durability fallback (load-bearing — CAM++ is the default)
Wrap `generate()`/parsing. On **any** of these, degrade to the plain SenseVoice transcript (`result[0]["text"]`, single `UNKNOWN`-speaker segment) and return it — **never drop the result** (honors the "save first, deliver second" invariant):
- `TypeError` from `distribute_spk` (the function still has no `None`-guard upstream);
- missing/empty `sentence_info` (empty/whitespace audio);
- `KeyError`/parse errors;
- cam++ construction/download failure (handled at load, §1.3, but double-guard here).

Returning a non-`None` result with `UNKNOWN` speakers keeps the route on the integrated path; the transcript is always preserved.

### 3.4 Route changes
- Compute `resolved_diar_engine` (§2.3) and add the gate clause at `transcription.py:350` and `:905`.
- Thread the new `diarization_engine` form field through to the resolver.
- No change to the existing two-pass branch.

### 3.5 No `ct-punc`
Do **not** add `punc_model`. It costs 1.1 GB, is not required for `spk`, and (verified by source-read; smoke-confirm) does not punctuate `sentence_info[i]["sentence"]` for SenseVoice — only the merged top-level `text`, which the integrated path doesn't use per-segment.

### 3.6 Feature/install gating
- No new pip extra (`funasr>=1.3.12` already covers CAM++). cam++/fsmn-vad auto-download (ungated) at first load.
- CAM++ engine availability tracks the existing `sensevoice` feature status (`model_manager.get_sensevoice_feature_status`), with the runtime load-degrade (§1.3) as the safety net.
- **Bootstrap warm-download (in scope):** when `INSTALL_FUNASR=true`, after the existing funasr install step in `bootstrap_runtime.py`, **pre-fetch cam++ and fsmn-vad into the HF cache** so the first diarization run doesn't pay a download (sub-models download at `AutoModel(...)` construction, not lazily). Implement via `huggingface_hub.snapshot_download("funasr/campplus")` + `"funasr/fsmn-vad"` (both ungated, ~30 MB total), mirroring the existing model-prefetch pattern. **Best-effort and non-fatal:** a warm-download failure only logs a warning — the runtime load-degrade (§1.3) still covers it, so bootstrap never fails on this step. Reflect the outcome in the `sensevoice` feature status reason where practical.

### 3.7 Server tests (pytest, funasr stubbed via `sys.modules`)
- `transcribe_with_diarization` parses `sentence_info` → `SPEAKER_NN` segments; `spk` int → label mapping; `num_speakers` count; single-speaker (all `spk=0`).
- `"sentence"`-vs-`"text"` key handling; missing/empty `sentence_info` → plain-transcript fallback; `distribute_spk` `TypeError` → fallback; never returns `None` when audio is non-empty.
- `load()` builds with `spk_model="cam++"`/`spk_mode="vad_segment"` when available; degrades to plain on spk-build failure.
- **Regression:** plain `transcribe()` still returns correct text when the model is built with `spk_model` loaded (segments under the `"sentence"` key) — guards the §3.1.1 parser harmonization.
- `resolve_sensevoice_diarization_engine`: SenseVoice+auto→config default; SenseVoice+explicit override; non-SenseVoice always `pyannote`; funasr-unavailable→`pyannote`.
- Route: engine gate selects single-pass only when resolved engine is `funasr`; `pyannote` override reaches the two-pass branch.
- Bootstrap: warm-download is attempted when `INSTALL_FUNASR=true` and is **non-fatal** on failure (bootstrap still completes); skipped when `INSTALL_FUNASR` is unset.

---

## 4. Wave 2 — Dashboard engine selector + flag fixes (frontend)

### 4.1 Capability flags (fix the existing contradiction)
- `modelRegistry.ts`: set the SenseVoice entry's `capabilities.diarization: true` (it genuinely supports diarization now). This currently drives the Model Manager `CapBadge` (`ModelManagerTab.tsx:346`).
- `modelCapabilities.ts`: `supportsDiarization()` already returns `true` for SenseVoice (consistent). Add `supportsFunasrDiarization(model): boolean` — **true only for SenseVoice** — to drive the engine selector's visibility.

### 4.2 Engine selector UI
When SenseVoice is the active model **and** diarization is enabled, show a small engine control (default **CAM++**, alternative **pyannote**). For all other models, no selector (pyannote-only, unchanged). The chosen value is sent as the `diarization_engine` field by the transcription request hook(s) (`useTranscription.ts` and the file-import flow).

### 4.3 Frontend tests (Vitest)
- `supportsFunasrDiarization`: true for SenseVoice ids, false for whisper/parakeet/canary/vibevoice/whisper.cpp.
- Registry: SenseVoice `capabilities.diarization === true`.
- Selector renders only for SenseVoice+diarization; defaults to CAM++; emits the override value.

---

## 5. Wave 3 — Per-word timestamps for SenseVoice (best-effort, **cuttable**)

**Purpose:** populate `words[]` so the **pyannote-override** path uses the precise word-level merge (`assign_speakers_to_words` + `smooth_micro_turns`) instead of `build_speaker_segments_nowords`. It does **not** affect the CAM++ default (segment-level by construction).

**Mechanism (verified):** pass `output_timestamp=True` to `generate()`; read `result[0]["timestamp"] = [[token, start, end], …]` at SentencePiece sub-word granularity. Reconstruct English words by merging consecutive tokens, starting a new word on the `"▁"` (U+2581) word-start marker; CJK tokens are ~per-character.

**Hard caveats baked into the design:**
- **60 ms frame quantization** ⇒ per-boundary error can exceed the current ±40 ms merge padding. Use a **≥80–120 ms** tolerance for the SenseVoice word-level path (do not reuse the ±40 ms default).
- **VAD multi-segment offset** (issue #2339): per-segment timestamps are segment-relative — add the VAD segment offset back.
- **Unit ambiguity:** per-token timing math yields **seconds**, while `sentence_info` is **ms** — normalize and **confirm empirically** before merging.
- **Count desync** (SenseVoice #215): align timestamps against the **raw** token list, post-process display text separately.
- **Unconditional fallback:** empty/short/length-mismatched/crashing timestamp list ⇒ revert to segment-level (`words=[]`). Word-level is never a hard dependency.

**Cut criterion:** if the GPU smoke test shows word-level assignment does not measurably beat segment-level for SenseVoice (or crashes under our VAD pipeline), **excise Wave 3 from the PR before merge.** Waves 1+2 stand alone.

---

## 6. Data flow (CAM++ default, happy path)

```
POST /transcription (diarization=true, model=iic/SenseVoiceSmall, diarization_engine=auto)
  → resolve_sensevoice_diarization_engine(...) = "funasr"
  → use_integrated_diarization = True   (route gate, §1.2)
  → backend.transcribe_with_diarization(audio, ...)
        AutoModel(spk_model="cam++").generate(...)  →  sentence_info[{start,end,sentence,spk}]
        parse → segments[{text,start,end,speaker:"SPEAKER_NN",words:[]}], num_speakers
        (on failure → plain transcript, speaker=UNKNOWN — never drop)
  → DiarizedTranscriptionResult → TranscriptionResult.to_dict()
  → _persist_result(...) BEFORE delivery → mark_delivered → return
```

pyannote-override path: `resolved = "pyannote"` ⇒ gate false ⇒ existing `transcribe_then_diarize`/`transcribe_and_diarize` two-pass.

## 7. GPU smoke-test checklist (real hardware — only these can confirm)
- [ ] CAM++: on a known 2-speaker clip, `sentence_info` carries `{start,end,sentence,spk}`, no `TypeError`, distinct `SPEAKER_00/01` in the result.
- [ ] CAM++: single-speaker clip ⇒ all `SPEAKER_00`, no crash.
- [ ] CAM++: confirm `ct-punc` omission is correct (sentences still usable without it).
- [ ] Engine switch: same audio with `diarization_engine=pyannote` reaches the two-pass path and returns labels.
- [ ] Memory/latency: SenseVoice+vad+cam++ vs SenseVoice alone (watch the 12 GB budget).
- [ ] Wave 3 (if attempted): per-token timestamp unit (s vs ms), VAD-offset correctness, realized boundary error vs the 60 ms grid, crash rate under VAD multi-segment. → decide ship/cut.

## 8. References
- **Existing diarization:** `core/diarization_engine.py`, `core/sortformer_engine.py`, `core/parallel_diarize.py`, `core/speaker_merge.py`, `database.py::_insert_diarization_segments_with_words`, route `api/routes/transcription.py:348-510` & `:905-940`.
- **Single-pass seam:** `core/stt/backends/base.py:75-82` (`DiarizedTranscriptionResult`), `:182-204` (`transcribe_with_diarization`); `core/stt/backends/vibevoice_asr_backend.py:358-404` (mirror), `:1172` (`SPEAKER_NN` format).
- **SenseVoice backend:** `core/stt/backends/sensevoice_backend.py`; `factory.py` (`is_sensevoice_model`), `capabilities.py`, `bootstrap_runtime.py` (`INSTALL_FUNASR`), `model_manager.py` (`get_sensevoice_feature_status`).
- **Frontend:** `dashboard/src/services/modelRegistry.ts`, `modelCapabilities.ts` (`supportsDiarization:185-188`), `components/views/ModelManagerTab.tsx:346`.
- **Upstream (FunASR `v1.3.12`):** `funasr/auto/auto_model.py` (L198-275 construction, L808-908 spk branch), `funasr/models/campplus/utils.py` (L256-277 `distribute_spk`), `funasr/models/sense_voice/model.py` (CTC timestamp block). Issues [#2662](https://github.com/modelscope/FunASR/issues/2662), [#2706](https://github.com/modelscope/FunASR/issues/2706), [#2333](https://github.com/modelscope/FunASR/issues/2333), [#2339](https://github.com/modelscope/FunASR/issues/2339), [SenseVoice #215](https://github.com/FunAudioLLM/SenseVoice/issues/215). PyPI `funasr` release dates confirm `>=1.3.12` ships the fix.
