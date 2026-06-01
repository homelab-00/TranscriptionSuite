---
title: 'GH #122 — WhisperX file-import diarization reliability'
type: 'bugfix'
created: '2026-06-01'
status: 'done'
baseline_commit: '1c2f65c'
context:
  - '{project-root}/CLAUDE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** File-import transcription with diarization on the default WhisperX backend produces inconsistent output (GH #122): out of ~40 files only ~5 got proper `[Speaker N]` SRTs, the rest came back with no speaker attribution. Logs reveal **two stacked causes** firing on every reported run: (1) `WhisperXBackend.transcribe_with_diarization()` raises `TypeError: unexpected keyword argument 'progress_callback'` because its override signature drifted from the base — this kills the fast single-pass path 100% of the time and forces a fallback; (2) the fallback (`transcribe_then_diarize`) unloads STT and loads a fresh pyannote pipeline, which intermittently raises `CUDA driver error: device not ready` on the WSL2 GPU, returning a transcript with no speakers. The intermittency (and the rare successes) is pure luck on the CUDA cold-start race.

**Approach:** (1) Restore `progress_callback` to the WhisperX override so the single-pass path works and reports coarse phase progress; this also keeps the GPU warm (no STT-unload→pyannote-load swap), removing the main trigger for cause #2. (2) Add a bounded retry on **transient** CUDA errors around the pyannote inference call in `diarize_audio`, mirroring the existing `cuda_health_check` backoff pattern, so an occasional "device not ready" self-heals instead of silently dropping speakers.

## Boundaries & Constraints

**Always:**
- Keep `WhisperXBackend.transcribe_with_diarization` signature a superset of `STTBackend.transcribe_with_diarization` (base contract is the source of truth).
- Diarization retry must only fire on transient CUDA errors (e.g. "device not ready", "unknown error"/999, generic "cuda driver error"); all other exceptions re-raise immediately.
- Preserve graceful degradation: if diarization ultimately fails, the transcript MUST still be returned (no data loss — see CLAUDE.md durability invariant).
- Between retries, sync + empty the CUDA cache before re-attempting.

**Ask First:**
- Changing retry count/backoff beyond 3 attempts at 1s/2s/4s (matching the established `cuda_health_check` pattern).
- Any change to the live-mode integrated call site or to `parallel_diarize` orchestration order.

**Never:**
- Do not modify the route's branch logic (`use_integrated_diarization` gating) or `parallel_diarize` model swap order.
- Do not touch the NVIDIA driver, Docker entrypoint, or WSL2 host config.
- Do not change the VibeVoice/MLX overrides (they already match the base contract).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Single-pass diarization, file import | `enable_diarization=True`, backend=WhisperX, `progress_callback` passed | Runs transcribe→align→diarize in one pass; emits coarse progress; returns `DiarizedTranscriptionResult` with speakers | N/A |
| Transient CUDA error, recovers | pyannote pipeline raises `RuntimeError("CUDA driver error: device not ready")` on attempt 1, succeeds after | sync+empty_cache, backoff, retry; diarization succeeds | retry ≤3× (1s/2s/4s); warn per attempt |
| Persistent transient CUDA error | pipeline raises transient error on every attempt | retries exhausted → exception re-raised; caller returns transcript **without** speakers | caller logs warning, no crash, transcript preserved |
| Non-transient diarization error | pipeline raises `ValueError`/unrelated error | re-raised immediately, **no** retry | propagate to caller |

</frozen-after-approval>

## Code Map

- `server/backend/core/stt/backends/whisperx_backend.py` — `transcribe_with_diarization` (L272) is missing `progress_callback`; `transcribe` (L199) and base (base.py:142) already have it. Fix site for cause #1.
- `server/backend/core/stt/backends/base.py` — `STTBackend.transcribe_with_diarization` (L142) defines the canonical signature including `progress_callback`.
- `server/backend/api/routes/transcription.py` — file-import path calls `transcribe_with_diarization(..., progress_callback=on_progress)` (L904-915); `on_progress` → `update_progress(current,total)` (L816). The `except Exception` at L948 swallows the TypeError as "integrated backend diarization failed". No change here.
- `server/backend/core/diarization_engine.py` — `diarize_audio` (L244) calls `self._pipeline(...)` (L293) with no retry; raises on CUDA error. Fix site for cause #2.
- `server/backend/core/parallel_diarize.py` — `transcribe_then_diarize` (L32) is the fallback that catches the diarization failure and returns `(result, None)` (L93-98). Unchanged; degradation already correct.
- `server/backend/core/audio_utils.py` — `cuda_health_check` (L256) is the backoff/retry precedent to mirror; `clear_gpu_cache` (L205) syncs+empties cache.

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/core/stt/backends/whisperx_backend.py` -- Add `progress_callback: Callable[[int, int], None] | None = None` to `transcribe_with_diarization` (keyword-only, after `hf_token`). Emit coarse phase progress when non-None: after transcribe `(60,100)`, after align `(80,100)`, after diarize+assign `(100,100)`. Guard each call with `if progress_callback is not None`.
- [x] `server/backend/core/diarization_engine.py` -- Add module-level `_is_transient_cuda_error(exc)` helper and `_CUDA_RETRY_DELAYS = (1, 2, 4)`. Wrap the `self._pipeline(...)` call in `diarize_audio` in a bounded retry loop: on transient CUDA error, log warning, `clear_gpu_cache()` (synchronize + empty_cache), sleep(delay), retry; non-transient → re-raise immediately; exhausted → re-raise last.
- [x] `server/backend/tests/test_stt_backend_diarization_signature.py` -- New regression test: for every concrete `STTBackend` subclass, assert its `transcribe_with_diarization` accepts every keyword-only param the base declares (would have caught cause #1).
- [x] `server/backend/tests/test_diarization_retry.py` -- New test: stub a pipeline that raises "device not ready" once then succeeds → asserts retry + success; raises a `ValueError` → asserts no retry and immediate propagation; raises transient error every time → asserts ≤3 retries then re-raise; OOM → no retry.

**Acceptance Criteria:**
- Given the WhisperX backend and a diarization file-import request, when the route calls `transcribe_with_diarization(progress_callback=...)`, then it no longer raises `TypeError` and the single-pass path completes with speaker labels.
- Given a transient CUDA "device not ready" on the first diarization attempt, when `diarize_audio` runs, then it retries with backoff and returns a populated `DiarizationResult`.
- Given diarization fails permanently, when the job completes, then the transcript is still returned (degraded, no speakers) and no exception escapes to the client.
- Given the full backend test suite, when run from the build venv, then all new and existing tests pass.

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_stt_backend_diarization_signature.py tests/test_diarization_retry.py -v --tb=short` -- expected: all pass.
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -q` -- expected: no new failures vs. baseline (2 known pre-existing failures only).
- `cd server/backend && ../../build/.venv/bin/ruff check core/stt/backends/whisperx_backend.py core/diarization_engine.py` -- expected: clean.

## Suggested Review Order

**Cause #1 — the actual GH #122 crash (signature drift)**

- Entry point: the dropped param restored, matching the base contract the route relies on.
  [`whisperx_backend.py:285`](../../server/backend/core/stt/backends/whisperx_backend.py#L285)

- Coarse phase progress emitted at transcribe / align / diarize boundaries.
  [`whisperx_backend.py:333`](../../server/backend/core/stt/backends/whisperx_backend.py#L333)

**Data-loss safety (review patch)**

- Progress emission isolated so a throwing callback can never discard a completed transcription.
  [`whisperx_backend.py:311`](../../server/backend/core/stt/backends/whisperx_backend.py#L311)

**Cause #2 — intermittent CUDA "device not ready"**

- Transient-vs-fatal classifier; OOM deliberately excluded.
  [`diarization_engine.py:53`](../../server/backend/core/diarization_engine.py#L53)

- Bounded retry (3× @ 1s/2s/4s) wrapping the pyannote call; non-transient re-raises immediately.
  [`diarization_engine.py:318`](../../server/backend/core/diarization_engine.py#L318)

**Tests**

- Signature-conformance guard that would have caught the original drift at CI time.
  [`test_stt_backend_diarization_signature.py:80`](../../server/backend/tests/test_stt_backend_diarization_signature.py#L80)

- Retry behavior: recover / no-retry-on-non-transient / exhaust / OOM-excluded.
  [`test_diarization_retry.py:84`](../../server/backend/tests/test_diarization_retry.py#L84)

- Data-loss guard: a throwing progress_callback must not lose the result.
  [`test_whisperx_backend.py:508`](../../server/backend/tests/test_whisperx_backend.py#L508)
