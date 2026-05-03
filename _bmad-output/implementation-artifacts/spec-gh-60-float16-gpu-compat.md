---
title: 'Fix container crash on GPUs with CUDA capability < sm_70'
type: 'bugfix'
created: '2026-04-07'
status: 'done'
baseline_commit: '0ea8a0c'
context:
  - 'docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** The server container crash-loops on GPUs with CUDA compute capability < 7.0 (e.g. GTX 1080 / sm_61) because `compute_type="default"` resolves to the model's stored precision (float16 for `Systran/faster-whisper-large-v3`), and CTranslate2 cannot run float16 kernels on pre-Volta hardware. GitHub Issue #60.

**Approach:** Add a GPU compute-capability check in `audio_utils.py` and use it in `engine.py` to auto-correct `compute_type="default"` to `"auto"` on GPUs < sm_70. Also fix the hardcoded `float16` in `database.py` and add a startup log warning so users know their compute type was adjusted.

## Boundaries & Constraints

**Always:**
- Preserve user's explicit compute_type choice (only override `"default"`, never override explicit types like `"int8"` or `"float32"`)
- The fix must be transparent -- log when auto-correction happens so users understand why performance differs
- All existing Volta+ (sm_70+) GPUs must see zero behavior change

**Ask First:**
- Changing the shipped default in config.yaml from `"default"` to `"auto"`

**Never:**
- Don't add a UI for compute capability display (out of scope)
- Don't change VibeVoice-ASR's existing bf16/fp16 auto-detection (it already handles this correctly)
- Don't add compute_type to NeMo backends (Parakeet/Canary don't use CTranslate2)

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Pascal GPU + default | GTX 1080 (sm_61), compute_type="default" | Auto-corrected to "auto", model loads successfully | Log warning about auto-correction |
| Volta+ GPU + default | RTX 3080 (sm_86), compute_type="default" | No change, loads with float16 as before | N/A |
| Any GPU + explicit type | compute_type="int8" | Passed through unchanged | N/A |
| CPU device | device="cpu" | No GPU check performed, "default" passed through | N/A |
| No CUDA available | torch.cuda not available | No GPU check performed, "default" passed through | N/A |
| database.py word timestamps | Pascal GPU, word timestamp extraction path | Uses "auto" instead of hardcoded "float16" | N/A |

</frozen-after-approval>

## Code Map

- `server/backend/core/audio_utils.py` -- Add `get_cuda_compute_capability()` helper alongside existing `cuda_health_check()`
- `server/backend/core/stt/engine.py:193` -- Auto-correct compute_type="default" using capability check
- `server/backend/database/database.py:1757` -- Replace hardcoded `compute_type="float16"` with `"auto"`
- `server/backend/core/stt/backends/whisper_backend.py` -- No change needed (receives corrected value)
- `server/backend/core/stt/backends/faster_whisper_backend.py` -- No change needed
- `server/backend/core/stt/backends/whisperx_backend.py` -- No change needed

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/core/audio_utils.py` -- Add `get_cuda_compute_capability() -> tuple[int, int] | None` that returns `(major, minor)` or `None` if unavailable. Cache the result (GPU capability doesn't change at runtime).
- [x] `server/backend/core/stt/engine.py` -- In `__init__` after line 193 where `self.compute_type` is set, add logic: if device is "cuda" and compute_type is "default" and capability < (7, 0), override to "auto" and log a warning.
- [x] `server/backend/database/database.py` -- Replace hardcoded `compute_type="float16"` at line 1757 with `compute_type="auto"`.
- [x] `server/backend/tests/` -- Add unit tests for `get_cuda_compute_capability()` and the auto-correction logic in engine.py.

**Acceptance Criteria:**
- Given a GPU with compute capability < 7.0 and compute_type="default", when the STT engine initializes, then compute_type is auto-corrected to "auto" and a warning is logged.
- Given a GPU with compute capability >= 7.0 and compute_type="default", when the STT engine initializes, then compute_type remains "default" (no behavior change).
- Given any GPU and an explicit compute_type (e.g. "int8"), when the STT engine initializes, then the explicit value is preserved unchanged.
- Given database word timestamp extraction on any GPU, when the function loads a model, then it uses compute_type="auto" instead of the hardcoded "float16".

## Spec Change Log

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_audio_utils.py tests/test_stt_engine_helpers.py -v --tb=short` -- expected: all tests pass including new capability tests
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` -- expected: no regressions in existing test suite

## Suggested Review Order

**GPU capability detection & auto-correction**

- Entry point: auto-correct `compute_type` when GPU lacks float16 support
  [`engine.py:297`](../../server/backend/core/stt/engine.py#L297)

- New cached helper probes device 0 compute capability
  [`audio_utils.py:150`](../../server/backend/core/audio_utils.py#L150)

**Secondary fix**

- Replace hardcoded `float16` with `auto` in word timestamp path
  [`database.py:1757`](../../server/backend/database/database.py#L1757)

**Tests**

- Boundary-value tests for the auto-correction logic + log assertion
  [`test_stt_engine_helpers.py:378`](../../server/backend/tests/test_stt_engine_helpers.py#L378)

- Tests for `get_cuda_compute_capability()` caching and GPU scenarios
  [`test_audio_utils.py:306`](../../server/backend/tests/test_audio_utils.py#L306)
