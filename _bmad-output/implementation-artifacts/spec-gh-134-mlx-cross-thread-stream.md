---
title: 'GH #134 — MLX/Metal "no stream (gpu,0)" crash: pin all MLX GPU ops to one owning thread'
type: 'bugfix'
created: '2026-06-01'
status: 'done'
baseline_commit: '44d60e8adda7504eaf44af1d70e2b480761ba6bf'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/investigations/gh-134-investigation.md'
  - '{project-root}/server/backend/core/stt/backends/base.py'
  - '{project-root}/server/backend/core/stt/backends/mlx_parakeet_backend.py'
  - '{project-root}/server/backend/core/stt/backends/mlx_whisper_backend.py'
  - '{project-root}/server/backend/core/stt/backends/mlx_canary_backend.py'
  - '{project-root}/server/backend/core/stt/backends/mlx_vibevoice_backend.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** On Apple Silicon **Metal mode** (v1.3.5), *every* transcription — file import, import queue, and live microphone — fails with the MLX runtime error **"There is no stream (gpu,0) in current thread"** (GH #134). Root cause (confirmed in the investigation case file): MLX binds a GPU stream to the thread that *creates* it, but the server materializes the model on one thread and runs inference on another. The startup prewarm loads the model on the **asyncio event-loop thread** (`api/main.py:629`, a synchronous un-awaited call inside `async def lifespan`), while every transcribe runs on a different **`asyncio.to_thread` pool worker** (`transcription.py:480` → `engine.transcribe_file:753` → `backend.transcribe:913`). Live mode (dedicated `LiveModeThread`, `live_engine.py:297`) and parallel diarization (`parallel_diarize.py:222` `ThreadPoolExecutor`) add two more cross-thread dispatch sites. No MLX backend manages streams at all. It is **Metal-only** because CUDA/PyTorch contexts are process-wide, so the *identical* dispatch is safe in Docker mode — this is **not a 1.3.5 regression**; it surfaced only once the native Metal server actually started after #124's DMG fix.

**Approach:** Pin **all** MLX GPU operations for a backend instance to a single, long-lived dedicated thread. Add a small `MLXThreadAffinityMixin` (new module `mlx_thread_pin.py`) that owns **one** `ThreadPoolExecutor(max_workers=1)` per backend instance, plus a `@mlx_pinned` method decorator that marshals the wrapped method onto that thread — with a **reentrancy guard** so a pinned method that calls another pinned method runs inline instead of deadlocking the single worker. The four MLX backends inherit the mixin and decorate their GPU methods (`load`, `unload`, `warmup`, `transcribe`, plus vibevoice's `transcribe_with_diarization`). Because the marshaling happens **inside** the backend, one change fixes file import, import-queue, parallel-diarize, *and* live mode simultaneously, with **zero** changes to the dispatch layer; CUDA/NeMo/WhisperX backends are untouched.

## Boundaries & Constraints

**Always:**
- Every MLX GPU op for a given backend instance — `from_pretrained` / `mlx_stt_load` / `_load_canary_model`, `mx.eval`, model `.generate`/`.transcribe`, `mx.clear_cache`, `del self._model` — MUST run on **that instance's single owning thread**.
- The owning thread MUST be the **same** across `load → warmup → transcribe → unload` for the instance's lifetime (reuse the executor; never spin a fresh thread per call).
- The decorator MUST preserve the wrapped method's signature, return value, and exceptions **verbatim** (`functools.wraps`; `future.result()` re-raises the original exception, not a `concurrent.futures` wrapper).
- Reentrancy: if a pinned method is already executing on the owning thread, a nested pinned call MUST run **inline** (no re-submit) to avoid single-worker deadlock.
- Keep `is_loaded`, `supports_translation`, `preferred_input_sample_rate_hz`, `backend_name`, `configure_decode_options` **un-pinned** — no GPU work; called from arbitrary threads; must stay cheap and non-blocking.

**Ask First:**
- Switching from per-backend executors to a **single process-wide MLX worker thread** (would also let `mx.metal.set_cache_limit` at `model_manager.py:268/277` move onto it — larger surface).
- Moving the startup prewarm (`api/main.py:629`) to `await asyncio.to_thread(...)` (orthogonal correctness nit; the affinity fix makes it correct regardless).
- Adding thread pinning to any **non-MLX** backend.

**Never:**
- Do NOT change `asyncio.to_thread` dispatch in `transcription.py`/`live.py`, the `parallel_diarize` `ThreadPoolExecutor`, or the `LiveModeThread`/`recording_thread` model — the fix lives entirely in the backend layer.
- Do NOT alter transcription inputs/outputs, segment parsing, chunking, attention-model toggling, resampling, or any decode behavior — **threading fix only**.
- Do NOT touch CUDA/NeMo/WhisperX/faster-whisper/whisper.cpp backends or their dispatch.
- Do NOT add locking to `engine.transcription_lock` as a "fix" — it serializes but does not pin, and is irrelevant to this bug.
- Do NOT introduce a per-call thread (defeats affinity) or shut the executor down inside `unload` if the instance may be reused (orphans the owning-thread id).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior | Error Handling |
|----------|--------------|-------------------|----------------|
| File import (single) | MLX backend prewarmed on event-loop thread; transcribe via `to_thread` worker | `load` + `transcribe` bodies both run on the backend's owning MLX thread → succeeds | original exception propagates unchanged to the route |
| Import queue / parallel diarize | transcribe dispatched on a `parallel_diarize` pool thread | marshaled to owning MLX thread; succeeds. Diarization (torch/pyannote) stays on its own thread — does not touch MLX | as above |
| Live microphone | model loaded via `to_thread` (`live.py:400`); inference on `LiveModeThread` | both marshaled to the owning MLX thread → succeeds | as above |
| vibevoice diarization | `transcribe_with_diarization` (pinned) → `_run_generate` (inline) | runs on owning thread; no nested re-submit | reentrancy guard runs inner inline |
| Reentrancy | a pinned method calls another pinned method while on the owning thread | inner body runs inline (no submit) | no deadlock |
| Model swap / reload | `unload` then `load` (same instance) OR new instance (live swap) | same instance reuses its thread; new instance gets its own; affinity preserved within each | n/a |
| Exception in pinned body | `model.generate(...)` raises `RuntimeError` | identical `RuntimeError` (type + message + traceback) re-raised to caller | `future.result()` re-raises; no executor wrapping |
| Non-MLX backend (CUDA/NeMo) | transcribe via `to_thread` | unchanged — no mixin, no pinning | unchanged |

</frozen-after-approval>

## Code Map

- **NEW** `server/backend/core/stt/backends/mlx_thread_pin.py` — `MLXThreadAffinityMixin`: lazy per-instance `ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx-<backend_name>")`; `_run_on_mlx_thread(fn, *a, **k)` that captures the owning-thread id on first use and runs **inline** when `threading.get_ident()` already equals it, else `submit(...).result()`; plus the `mlx_pinned(method)` decorator (`functools.wraps`, delegates to `self._run_on_mlx_thread`, re-raises original exception).
- `server/backend/core/stt/backends/mlx_parakeet_backend.py` — `class MLXParakeetBackend(STTBackend)` **L104** → add mixin to bases; `@mlx_pinned` on `load` **L121**, `unload` **L145**, `warmup` **L160**, `transcribe` **L176**. (`_tokens_to_words` L46 is pure — no change.)
- `server/backend/core/stt/backends/mlx_whisper_backend.py` — class **L39**; decorate `load` **L54**, `unload` **L76**, `warmup` **L92**, `transcribe` **L101**.
- `server/backend/core/stt/backends/mlx_canary_backend.py` — class **L262**; decorate `load` **L279**, `unload` **L301**, `warmup` **L317**, `transcribe` **L333**. (`_load_canary_model` **L177** is a module fn called only from the pinned `load` → already runs on the owning thread; leave as-is — it holds the `mx.eval(model.parameters())` at L257.)
- `server/backend/core/stt/backends/mlx_vibevoice_backend.py` — class **L38**; decorate `load` **L47**, `unload` **L56**, `warmup` **L72**, `transcribe` **L82**, `transcribe_with_diarization` **L131**. (`_run_generate` **L206** is private, called only from pinned methods → runs inline on the owning thread; **leave un-decorated**.)
- `server/backend/core/stt/backends/base.py` — **reference only, no change**; `STTBackend` L56 abstract contract is unchanged (mixin is additive via multiple inheritance: `class MLXxBackend(MLXThreadAffinityMixin, STTBackend)`).
- **NEW** `server/backend/tests/test_mlx_thread_affinity.py` — affinity proofs using a fake backend subclass; **no MLX/Metal import required** (records `threading.get_ident()`).
- Reference: `_bmad-output/implementation-artifacts/investigations/gh-134-investigation.md` (full evidence chain).

## Tasks & Acceptance

**Execution:**
- [x] **NEW** `mlx_thread_pin.py` — implement `MLXThreadAffinityMixin` + `mlx_pinned` per Code Map. Lazy executor creation (guarded); capture owning-thread id by `submit(threading.get_ident).result()` at creation; reentrancy guard compares `threading.get_ident()` to the captured id; `future.result()` propagates the original exception. Module docstring cites GH #134 + the thread-affinity reason.
- [x] `mlx_parakeet_backend.py`, `mlx_whisper_backend.py`, `mlx_canary_backend.py`, `mlx_vibevoice_backend.py` — add `MLXThreadAffinityMixin` to bases and `@mlx_pinned` to the GPU methods per Code Map. **No method-body changes.**
- [x] **NEW** `test_mlx_thread_affinity.py` — cover the ACs below (fake backend; Linux-runnable).
- [x] (verify, not edit) confirm no MLX `warmup` calls a *pinned sibling* (`self.transcribe`) — all four call `self._model.*`/`self._run_generate` directly (confirmed at baseline); the guard covers it regardless.

**Acceptance Criteria:**
- Given a fake MLX backend (mixin + `@mlx_pinned` methods recording `threading.get_ident()`), when `load()` then `transcribe()` are invoked from **two different** caller threads, then both bodies execute on the **same** thread id, and that id **differs from both** callers'.
- Given a pinned method that internally calls another pinned method, when invoked, then the inner body runs on the owning thread **without deadlock** (completes within a short timeout) and returns correctly.
- Given a pinned method whose body raises `ValueError("x")`, when called, then the **same** `ValueError("x")` propagates to the caller (type + message preserved) — not a `concurrent.futures` wrapper.
- Given one backend instance, when `transcribe()` is called N times across N distinct caller threads, then all N bodies run on **one and the same** owning thread id.
- Given `cd server/backend && ../../build/.venv/bin/pytest tests/test_mlx_thread_affinity.py -v`, then all pass on **Linux** (no MLX/Metal dependency).
- Given the existing `tests/test_stt_backend_factory.py` and `tests/test_mlx_vibevoice_backend.py`, when run, then they still pass (mixin is additive; factory detection unchanged).

## Spec Change Log

**2026-06-01 — implemented (ready-for-dev → done).** Built exactly to the frozen intent; no renegotiation.
- New `server/backend/core/stt/backends/mlx_thread_pin.py` — `MLXThreadAffinityMixin` (lazy per-instance `ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx-<backend_name>")`; owning-thread id captured via `submit(threading.get_ident).result()`; reentrancy guard runs inline when already on the owning thread; `future.result()` re-raises the original exception; idempotent `shutdown_mlx_thread()`) + `mlx_pinned` decorator (`functools.wraps`).
- Decorated GPU methods on all four backends, **no body changes**: parakeet/whisper/canary `load`+`unload`+`warmup`+`transcribe` (4 each); vibevoice adds `transcribe_with_diarization` (5). `_run_generate` (vibevoice) deliberately left private/un-decorated — it runs inline inside an already-pinned public method.
- New `server/backend/tests/test_mlx_thread_affinity.py` — 6 tests, Linux-runnable, no MLX import (fake backend records `threading.get_ident()`).

**Verification results (Linux, build venv):**
- `test_mlx_thread_affinity.py` → 6/6 pass.
- `test_stt_backend_factory.py` + `test_mlx_vibevoice_backend.py` → 30/30 pass — the vibevoice cases exercise the real decorated `load`/`unload`/`transcribe`/`transcribe_with_diarization` paths with mocked models, confirming behavior is preserved through the marshal.
- Full backend suite → **1920 passed, 3 skipped, 0 failed** (no regressions; the 2 failures noted in older docs are already resolved on this baseline).
- `gitnexus_impact` (4 backend classes, upstream) → LOW. `gitnexus_detect_changes` → risk low, 28 expected symbols touched, **0 affected execution flows**.

**Out of scope / Ask-First (unchanged):** process-wide single MLX thread; moving the `api/main.py:629` prewarm to `await asyncio.to_thread`; any non-MLX backend. **Manual Apple-Silicon confirmation still required** (no Mac hardware here) — the predicted fix is code-verified, not device-verified.

## File List

- `server/backend/core/stt/backends/mlx_thread_pin.py` *(new)*
- `server/backend/core/stt/backends/mlx_parakeet_backend.py` *(modified)*
- `server/backend/core/stt/backends/mlx_whisper_backend.py` *(modified)*
- `server/backend/core/stt/backends/mlx_canary_backend.py` *(modified)*
- `server/backend/core/stt/backends/mlx_vibevoice_backend.py` *(modified)*
- `server/backend/tests/test_mlx_thread_affinity.py` *(new)*
- `_bmad-output/implementation-artifacts/spec-gh-134-mlx-cross-thread-stream.md` *(this spec)*
- `_bmad-output/implementation-artifacts/investigations/gh-134-investigation.md` *(investigation, pre-existing)*

## Design Notes

**Per-backend executor, not process-wide.** Only one transcription backend is active at a time (live swap unloads the main model, loads the live one), and MLX stream affinity is per-thread; a per-instance owning thread is sufficient and has a trivial lifecycle (it dies with the instance). A single process-wide MLX thread would *also* naturally own `mx.metal.set_cache_limit` (`model_manager.py:268/277`) and any future module-level `mx.*`, but it is a larger surface and a harder lifecycle — deferred to Ask-First. The per-backend choice still fixes the **shared-backend** live path: `live.py:280` detaches and reuses the main backend on `LiveModeThread`, but because marshaling is keyed to the **instance's** executor (not the caller), reuse still lands on that instance's owning thread.

**Decorator over body-rewrite.** Every backend's GPU work already lives in public methods that call `self._model.*` / `self._run_generate` — never a sibling *public* method — so `@mlx_pinned` needs **zero** body edits and introduces no deadlock path at baseline. The reentrancy guard is defensive: it future-proofs against a later nested pinned call (and makes vibevoice's `transcribe_with_diarization → _run_generate` safe even if `_run_generate` is ever promoted/decorated).

**`mx.clear_cache()` placement is now correct for free.** It sits inside `unload`/`transcribe`/`_run_generate`, so once those run on the owning thread, the cache clear is also on the owning thread — clearing the Metal cache from a foreign thread is itself a cross-thread MLX op and would be unsafe.

**Startup prewarm blocking is unchanged.** `api/main.py:629` already blocks the event loop synchronously (un-awaited `load_transcription_model()`); with the fix the *actual* MLX work hops to the owning thread while the event-loop thread blocks on `.result()` — same wall-clock blocking, now thread-correct. (Making the prewarm `await asyncio.to_thread(...)` is a separate, optional nicety — Ask-First.)

**Why Metal-only / not a regression.** CUDA contexts are process-wide; the identical `asyncio.to_thread` dispatch is safe in Docker. The bug appeared only when the native Metal server started post-#124. Full evidence: the investigation case file.

## Verification

**Commands** (from `server/backend/`, build venv per CLAUDE.md):
- `../../build/.venv/bin/pytest tests/test_mlx_thread_affinity.py -v --tb=short` — new affinity tests pass (Linux, no Metal).
- `../../build/.venv/bin/pytest tests/test_stt_backend_factory.py tests/test_mlx_vibevoice_backend.py -v` — no regressions.
- `../../build/.venv/bin/pytest tests/ -q` — full suite green (modulo the 2 known pre-existing failures recorded in `docs/TESTING.md`).

**Manual checks (Apple Silicon + Metal required — maintainer):**
- Install `-arm64-mac-metal.dmg`, start the Metal server, import one audio file → transcription succeeds with **no** "no stream (gpu,0)".
- Start a live microphone session → live transcription succeeds.
- Reporter confirmation on #134 with an MLX model selected (parakeet/whisper/canary/vibevoice).

## Suggested Review Order

**The core — start here**

- The mixin: lazy single-worker executor + owning-thread-id capture
  [`mlx_thread_pin.py:37`](../../server/backend/core/stt/backends/mlx_thread_pin.py#L37)
- `_run_on_mlx_thread` — the reentrancy guard (inline when already on the owning thread) + `future.result()` exception passthrough
  [`mlx_thread_pin.py:66`](../../server/backend/core/stt/backends/mlx_thread_pin.py#L66)
- The `@mlx_pinned` decorator — `functools.wraps` + delegation
  [`mlx_thread_pin.py:88`](../../server/backend/core/stt/backends/mlx_thread_pin.py#L88)

**Wiring (identical pattern ×4)**

- parakeet: mixin base + 4 decorators
  [`mlx_parakeet_backend.py:105`](../../server/backend/core/stt/backends/mlx_parakeet_backend.py#L105)
- whisper [`mlx_whisper_backend.py:40`](../../server/backend/core/stt/backends/mlx_whisper_backend.py#L40) · canary [`mlx_canary_backend.py:263`](../../server/backend/core/stt/backends/mlx_canary_backend.py#L263)
- vibevoice — the only 5-decorator file (adds `transcribe_with_diarization`); `_run_generate` left un-decorated
  [`mlx_vibevoice_backend.py:39`](../../server/backend/core/stt/backends/mlx_vibevoice_backend.py#L39)

**Tests — the affinity proofs (no Metal needed)**

- Fake backend + same-owning-thread / distinct-from-caller / reentrancy-no-deadlock / exception-passthrough / N-calls-one-thread
  [`test_mlx_thread_affinity.py:18`](../../server/backend/tests/test_mlx_thread_affinity.py#L18)
