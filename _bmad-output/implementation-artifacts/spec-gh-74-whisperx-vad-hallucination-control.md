---
title: 'GH-74: Wire vad_filter and decode options through WhisperX backend'
type: 'bugfix'
created: '2026-04-12'
status: 'done'
baseline_commit: '3f47c9e'
context:
  - docs/project-context.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** WhisperXBackend.transcribe() accepts `vad_filter` but silently drops it — `_whisperx_transcribe()` never receives it, so faster-whisper's built-in VAD is never applied on the WhisperX code path. Additionally, `transcribe_with_diarization()` hardcodes `initial_prompt=None` and `suppress_tokens=None`, preventing operators from using prompt guidance or token suppression during diarized runs. There is also no config surface for advanced decode/anti-hallucination parameters (`no_speech_threshold`, `compression_ratio_threshold`, `hallucination_silence_threshold`, etc.).

**Approach:** Wire `vad_filter` through `_whisperx_transcribe()` using the existing `inspect.signature` + `dataclasses.replace(pipeline.options)` compat-patch pattern. Thread `initial_prompt`, `suppress_tokens`, and `vad_filter` into the diarization path. Add a `whisper_decode` config map that stores on backends as instance state and merges into transcribe kwargs, filtered by each backend's accepted parameters.

## Boundaries & Constraints

**Always:** Follow the existing inspect + compat-patch pattern in WhisperXBackend. Preserve backward compatibility — all defaults must match current behavior. NeMo/Parakeet/Canary/VibeVoice backends must be unmodified (zero blast radius).

**Ask First:** If the approach of storing decode_options as backend instance state (vs. adding to the abstract transcribe signature) creates issues.

**Never:** Don't add per-request decode overrides via REST/WebSocket API — config-level only. Don't validate `whisper_decode` keys at config-load time (signatures vary by library version). Don't change the abstract `transcribe()` method signature in base.py.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| vad_filter=true + silence audio | WhisperX backend, config vad_filter=true | vad_filter=True reaches faster-whisper transcribe call | N/A |
| whisper_decode with unsupported keys | e.g. key unknown to current faster-whisper | Key absent from inspect.signature, silently skipped | N/A |
| Diarization + initial_prompt set | WhisperX diarization, config has initial_prompt | Prompt forwarded to _whisperx_transcribe (not None) | N/A |
| NeMo backend + whisper_decode present | Parakeet with whisper_decode in config | Config ignored (no configure_decode_options override), transcription normal | N/A |

</frozen-after-approval>

## Code Map

- `server/backend/core/stt/backends/whisperx_backend.py` -- Primary fix: vad_filter wiring, diarization params, decode_options merging
- `server/backend/core/stt/backends/base.py` -- Add `configure_decode_options()` concrete method + `_decode_options` attribute
- `server/backend/core/stt/backends/faster_whisper_backend.py` -- Merge `_decode_options` into transcribe kwargs
- `server/backend/core/stt/backends/whisper_backend.py` -- Merge `_decode_options` into transcribe kwargs
- `server/backend/core/stt/engine.py` -- Read `whisper_decode` from config, call `configure_decode_options()` after load
- `server/config.yaml` -- Add commented `whisper_decode:` section under `main_transcriber`
- `server/backend/tests/test_whisperx_backend.py` -- Test vad_filter forwarding, decode_options merging, diarization param threading

## Tasks & Acceptance

**Execution:**
- [x] `base.py` -- Add `configure_decode_options(options)` concrete method storing `self._decode_options`; initialize `_decode_options = {}` as default
- [x] `whisperx_backend.py` -- Add `vad_filter` param to `_whisperx_transcribe()` with inspect+compat handling; pass it from `transcribe()`; merge `self._decode_options` into kwargs using the same inspect pattern; add `initial_prompt`, `suppress_tokens`, `vad_filter` params to `transcribe_with_diarization()` and forward them
- [x] `faster_whisper_backend.py` -- In `transcribe()`, merge compatible keys from `self._decode_options` into kwargs
- [x] `whisper_backend.py` -- In `transcribe()`, merge compatible keys from `self._decode_options` into kwargs
- [x] `engine.py` -- Read `main_transcriber.whisper_decode` config (default `{}`); store as `self.whisper_decode`; call `_backend.configure_decode_options()` after `_load_model()`
- [x] `config.yaml` -- Add commented `whisper_decode:` map with documented hallucination-relevant keys
- [x] `test_whisperx_backend.py` -- Add tests: vad_filter reaches model; decode_options keys reach model/options; diarization receives initial_prompt + suppress_tokens

**Acceptance Criteria:**
- Given WhisperX backend with faster_whisper_vad_filter=true, when transcribing, then vad_filter=True reaches the underlying transcribe call
- Given whisper_decode config with no_speech_threshold=0.3, when transcribing via WhisperX, then the value reaches the model call via kwargs or options patch
- Given WhisperX diarization with initial_prompt in config, when transcribe_with_diarization() is called, then initial_prompt is forwarded (not None)
- Given NeMo backend with whisper_decode config present, when transcribing, then config is silently ignored

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_whisperx_backend.py -v --tb=short` -- expected: all tests pass including new vad_filter/decode_options/diarization tests

## Suggested Review Order

**Core bug fix — vad_filter wiring**

- Entry point: vad_filter routed through inspect+compat pattern (matches beam_size handling)
  [`whisperx_backend.py:479`](../../server/backend/core/stt/backends/whisperx_backend.py#L479)

- transcribe() now forwards vad_filter to the inner method
  [`whisperx_backend.py:227`](../../server/backend/core/stt/backends/whisperx_backend.py#L227)

**Diarization path fix**

- Signature gains initial_prompt, suppress_tokens, vad_filter (were hardcoded None)
  [`whisperx_backend.py:280`](../../server/backend/core/stt/backends/whisperx_backend.py#L280)

- Inner call now forwards all three instead of hardcoding None
  [`whisperx_backend.py:311`](../../server/backend/core/stt/backends/whisperx_backend.py#L311)

- Route handler passes engine params to diarization (async path)
  [`transcription.py:220`](../../server/backend/api/routes/transcription.py#L220)

- Route handler passes engine params to diarization (sync file-import path)
  [`transcription.py:646`](../../server/backend/api/routes/transcription.py#L646)

**decode_options infrastructure**

- Base class: configure_decode_options() stores per-instance options dict
  [`base.py:61`](../../server/backend/core/stt/backends/base.py#L61)

- WhisperX: merges decode_options via inspect/compat with key-collision guard
  [`whisperx_backend.py:489`](../../server/backend/core/stt/backends/whisperx_backend.py#L489)

- FasterWhisper: merges decode_options with explicit-arg precedence guard
  [`faster_whisper_backend.py:116`](../../server/backend/core/stt/backends/faster_whisper_backend.py#L116)

- Whisper: merges decode_options with explicit-key exclusion set
  [`whisper_backend.py:117`](../../server/backend/core/stt/backends/whisper_backend.py#L117)

**Config and engine wiring**

- Engine reads whisper_decode from main_transcriber config
  [`engine.py:287`](../../server/backend/core/stt/engine.py#L287)

- Engine calls configure_decode_options after model load
  [`engine.py:415`](../../server/backend/core/stt/engine.py#L415)

- New documented whisper_decode section with hallucination-relevant keys
  [`config.yaml:81`](../../server/config.yaml#L81)

**Peripherals**

- VibeVoice backends: accept new params, immediately discard them
  [`vibevoice_asr_backend.py:366`](../../server/backend/core/stt/backends/vibevoice_asr_backend.py#L366)

- 9 new tests covering vad_filter, decode_options, diarization params, instance isolation
  [`test_whisperx_backend.py:314`](../../server/backend/tests/test_whisperx_backend.py#L314)
