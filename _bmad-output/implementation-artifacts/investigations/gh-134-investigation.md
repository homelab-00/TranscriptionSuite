# Investigation: GH #134 — MLX/Metal "There is no stream (gpu,0) in current thread"

## Hand-off Brief

1. **What happened.** On Apple-Silicon Metal mode (v1.3.5), every transcription (file import *and* microphone) fails with the MLX runtime error *"There is no stream (gpu,0) in current thread"* — **Deduced** root cause: MLX GPU work is dispatched across interchangeable worker threads via `asyncio.to_thread` / separate `ThreadPoolExecutor` / dedicated live threads, but MLX binds a GPU stream to the thread that created it.
2. **Where the case stands.** Root cause **Confirmed** from code structure with full `path:line` citations: the startup prewarm materializes the model on the event-loop thread (`main.py:629`) while every `transcribe()` runs on a `to_thread` pool worker — a *deterministic* (not racy) mismatch; no MLX backend manages streams at all. Only the live Mac raising-frame capture is blocked by lack of hardware.
3. **What's needed next.** Decide the fix shape — pin **all** MLX operations (load, `mx.eval`, transcribe, `clear_cache`, unload) for a backend to a single long-lived dedicated thread — then implement via `bmad-quick-dev` or a tracked story.

## Case Info

| Field            | Value                                                                                         |
| ---------------- | --------------------------------------------------------------------------------------------- |
| Ticket           | GH #134 (links to #124; upstream mlx#2133, mlx-lm#1181, vllm-mlx#496)                          |
| Date opened      | 2026-06-01                                                                                    |
| Status           | Concluded — root cause Confirmed; fix implemented (see Follow-up 2026-06-01)                    |
| System           | Apple Silicon (M4 Max), macOS 15 Sequoia, TranscriptionSuite v1.3.5, **Metal mode** (native MLX) |
| Evidence sources | GitHub issue #134 + #124 thread, source code, upstream MLX issues. **No Mac hardware for repro.** |

## Problem Statement

Reporter (odnodn), after fixing the Metal-server start problem from #124 (installed the correct `-arm64-mac-metal.dmg`):

> transcription from local file and microphone is not working.
> 1. Session → start recording (recording starts) and 2. Session → import → drag audio file → Import queue
> - **Transcription failed: There is no stream (gpu,0) in current thread.**

Reporter's own hypothesis (with links): MLX dispatches work to a different thread than the one that created the GPU stream; MLX `Stream`/`wired_limit` are not thread-safe (mlx#2133).

## Evidence Inventory

| Source                              | Status    | Notes                                                                                          |
| ----------------------------------- | --------- | ---------------------------------------------------------------------------------------------- |
| GitHub issue #134 body + screenshot | Available | Error string + repro steps; screenshot shows the toast (full Python traceback not transcribed) |
| GitHub issue #124 follow-up comment | Available | Same error first surfaced here; also lists 3 smaller side issues (see Side Findings)            |
| Source code (MLX backends, routes)  | Available | `server/backend/core/stt/backends/mlx_*.py`, `api/routes/transcription.py`, `live.py`, engine  |
| Upstream MLX issues                 | Partial   | mlx#2133 documents thread-affinity of streams; confirms the constraint exists                  |
| Mac runtime / stack trace           | Missing   | No Apple-Silicon hardware available — cannot capture the exact raising frame or reproduce       |

## Investigation Backlog

| # | Path to Explore                                                                 | Priority | Status | Notes                                                                             |
| - | ------------------------------------------------------------------------------- | -------- | ------ | --------------------------------------------------------------------------------- |
| 1 | Confirm load thread materializes MLX model vs transcribe thread does GPU ops    | High     | Done   | Confirmed: load `from_pretrained`/`mlx_stt_load`/`mx.eval`; transcribe forward+`clear_cache` |
| 2 | Map full call chain route → engine → backend.transcribe for non-live + live     | High     | Done   | Confirmed chain (Source Code Trace)                                               |
| 3 | Check whether model is preloaded at startup (which thread) — guarantees mismatch | High     | Done   | Confirmed: `main.py:629` sync prewarm on event-loop thread → deterministic mismatch |
| 4 | Verify CUDA path uses same dispatch (explains Metal-only)                        | Medium   | Done   | Confirmed backend-agnostic dispatch (`factory.py`, `engine.py:443`)               |
| 5 | Survey all `mx.*` call sites for any existing stream/device pinning             | Medium   | Done   | Confirmed: none in backends; only `mx.metal.set_cache_limit` in `model_manager.py:268/277` |

## Timeline of Events

| Time             | Event                                                                       | Source            | Confidence |
| ---------------- | --------------------------------------------------------------------------- | ----------------- | ---------- |
| 2026-05-20       | #124 opened: Metal server won't start (wrong DMG)                           | issue #124        | Confirmed  |
| 2026-05-31       | PR #132 merged — Metal-start diagnostics; reporter installs correct DMG     | PR #132           | Confirmed  |
| 2026-05-31/06-01 | After server starts, transcription fails with "no stream (gpu,0)"           | issue #124 / #134 | Confirmed  |
| 2026-06-01       | #134 opened with the error + upstream thread-affinity links                 | issue #134        | Confirmed  |

## Confirmed Findings

### Finding 1: Transcription dispatches model-load and inference through separate `asyncio.to_thread` calls

**Evidence:** `server/backend/api/routes/transcription.py:132` (`await asyncio.to_thread(model_manager.ensure_transcription_loaded)`) and `:268`, `:337`, `:422`, `:480`, `:653`, `:1240`, `:1463` (`await asyncio.to_thread(... transcribe ...)`).

**Detail:** `asyncio.to_thread` schedules onto the event loop's default `ThreadPoolExecutor`, whose worker threads are interchangeable. Load and transcribe are *separate* awaits → no guarantee they run on the same OS thread.

### Finding 2: No MLX thread-pinning / dedicated single-thread executor exists

**Evidence:** Repo-wide grep for `ThreadPoolExecutor|max_workers|run_in_executor|set_default_executor|dedicated.*thread` in `server/backend/core/` returns only `parallel_diarize.py` (max_workers=2), live-engine threads, NeMo-import thread, and warmup threads — **none MLX-stream-aware**.

**Detail:** Nothing marshals MLX ops back to a single owning thread.

### Finding 3: Parallel diarization runs transcription on a fresh ThreadPoolExecutor

**Evidence:** `server/backend/core/parallel_diarize.py:222` — `with ThreadPoolExecutor(max_workers=2, thread_name_prefix="parallel_diarize") as pool:` runs transcription + diarization concurrently on separate threads.

**Detail:** A second, independent cross-thread dispatch site for MLX inference.

### Finding 4: Live mode transcribes on dedicated threads distinct from the load thread

**Evidence:** Model loaded via `server/backend/api/routes/live.py:400` (`await asyncio.to_thread(model_manager.load_transcription_model)`); the live engine spins its own worker threads at `server/backend/core/live_engine.py:297` (`_loop_thread`) / `:303` (`_feeder_thread`) and `server/backend/core/stt/engine.py:410` (`recording_thread = threading.Thread(target=self._recording_worker, ...)`).

**Detail:** Load happens on a pool thread; live inference happens on long-lived dedicated threads → guaranteed mismatch. Explains the microphone failure.

### Finding 5: MLX model weights are materialized at load time (on the load thread)

**Evidence:** `server/backend/core/stt/backends/mlx_canary_backend.py:257` — `mx.eval(model.parameters())` during model construction; `mx.clear_cache()` appears in load/unload paths of all four MLX backends (`mlx_whisper_backend.py:85,159`, `mlx_vibevoice_backend.py:65,216`, `mlx_canary_backend.py:310,429`, `mlx_parakeet_backend.py:153,300`).

**Detail:** GPU stream state is established on whichever thread runs `load()`; subsequent `transcribe()` on a different thread cannot see it. Confirmed transcribe-thread GPU ops: parakeet `self._model.transcribe(...)` `mlx_parakeet_backend.py:293` + `mx.clear_cache()` `:300`; whisper `self._model.generate(...)` `mlx_whisper_backend.py:147` + `mx.clear_cache()` `:159`. Confirmed load-thread materialization: `from_pretrained(...)` `mlx_parakeet_backend.py:138`, `mlx_stt_load(...)` `mlx_whisper_backend.py:65`, `mx.eval(model.parameters())` `mlx_canary_backend.py:257`.

### Finding 6: Startup prewarm materializes the model on the event-loop thread — deterministic mismatch

**Evidence:** `server/backend/api/main.py:629` — `manager.load_transcription_model()` is called **synchronously and un-awaited** inside `async def lifespan` (`api/main.py:377`), so it executes on the asyncio event-loop (main) thread. Per-request transcription runs on a `to_thread` worker (`transcription.py:480`).

**Detail:** This removes any "maybe same thread" luck: the model's GPU stream is created on the main thread at boot, and the first (and every) `transcribe()` runs on a different worker thread → guaranteed failure, matching the reporter's "transcription is not working" (not "sometimes fails").

### Finding 7: The engine's lock serializes but does not pin to a thread

**Evidence:** `server/backend/core/stt/engine.py:370` (`self.transcription_lock = threading.Lock()`), acquired at `:674`/`:875`.

**Detail:** The lock prevents concurrent transcriptions but does nothing to ensure they run on the GPU-stream-owning thread — so it neither causes nor mitigates the bug. (A wrong fix would add more locking here; that would not help.)

## Deduced Conclusions

### Deduction 1: Cross-thread GPU dispatch triggers the MLX "no stream" error

**Based on:** Findings 1–5 + upstream mlx#2133 (a stream allocated on one thread cannot be used/synchronized from another).

**Reasoning:** `load()` materializes MLX arrays / establishes the GPU stream on thread A. `transcribe()` issues MLX ops on thread B (different `to_thread` worker, parallel-diarize pool thread, or live worker thread). MLX looks up stream `(gpu,0)` in thread B's context, finds none → raises.

**Conclusion:** The defect is the **threading model**, not model selection, model files, or the build. It affects every MLX backend and every transcription entry point.

### Deduction 2: The defect is Metal-only because CUDA contexts are process-wide

**Based on:** PyTorch/CUDA context is shared across threads in a process; the same `to_thread` dispatch is used for CUDA backends in Docker mode without error.

**Reasoning:** The identical route code runs on CUDA without issue, so the bug surfaces only where the GPU runtime is thread-affine (MLX). Matches the `apple-silicon-mlx` label and the "works in Docker" expectation.

**Conclusion:** Not a regression in 1.3.5 code; an architectural mismatch exposed once the native Metal server actually starts and runs MLX.

## Hypothesized Paths

### Hypothesis 1: (Reporter's) MLX work dispatched to a thread other than the GPU-stream owner

**Status:** Confirmed (architecturally, from code structure).

**Theory:** Handler dispatches MLX GPU work to a different thread than the one that created the stream.

**Supporting indicators:** Findings 1–5; upstream mlx#2133.

**Would confirm:** A Mac stack trace showing the raise inside an MLX op invoked from a `to_thread`/pool/live worker frame.

**Would refute:** Evidence that MLX work is already pinned to one thread, or that the error originates elsewhere (e.g., model file corruption). None found.

**Resolution:** Code structure confirms the cross-thread dispatch; only the live capture of the exact frame is outstanding (blocked on hardware).

## Missing Evidence

| Gap                                   | Impact                                                    | How to Obtain                                                       |
| ------------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------- |
| Mac runtime + full Python stack trace | Would upgrade Deduction 1 from Deduced→Confirmed at frame | Reporter runs with full server logs, or maintainer on Apple Silicon |
| Which MLX model the reporter used     | None to root cause (all MLX backends share the pattern)   | Reporter's model selection                                          |

## Source Code Trace

| Element       | Detail                                                                                                       |
| ------------- | ------------------------------------------------------------------------------------------------------------ |
| Error origin  | MLX C++ core (raised inside an `mx.*` op / model forward / `mx.eval`) — not a literal string in this repo       |
| Trigger       | Any transcription on Metal mode: file import, import queue, or live microphone                                |
| Condition     | The thread issuing the MLX op ≠ the thread that loaded/materialized the model (created stream `(gpu,0)`)       |
| Non-live chain | `transcription.py:132` load (`to_thread`) / `:480` transcribe (`to_thread`) → `engine.transcribe_file` `engine.py:753` → `transcribe_audio` `:839` → `backend.transcribe` `:913` |
| Live chain     | load via `to_thread` `live.py:400`; worker `LiveModeThread` `live_engine.py:297-300` → `recorder.text()` `:209` → `engine.py:629` → `_perform_transcription` `:661` → `backend.transcribe` `:700`. Shared backend detached at `live.py:280` after being materialized on the main thread (`main.py:629`). |
| Diarize chain  | `parallel_diarize.py:222` `ThreadPoolExecutor(max_workers=2)` runs the transcribe half on a pool thread        |
| Related files | `api/main.py:629`, `api/routes/transcription.py`, `api/routes/live.py`, `core/live_engine.py`, `core/stt/engine.py`, `core/parallel_diarize.py`, `core/stt/backends/mlx_*.py`, `core/model_manager.py` |

## Conclusion

**Confidence:** High (root cause Confirmed from code structure across three independent dispatch sites; only the live raising-frame capture is blocked on Mac hardware).

The error is caused by MLX's thread-affine GPU streams colliding with the server's multi-threaded dispatch. MLX requires that every GPU operation for a given context run on the thread that created the stream; the server loads the model on one thread and runs inference on others (`asyncio.to_thread` pool threads for file import, a separate `ThreadPoolExecutor` for parallel diarization, dedicated worker threads for live mode). It is Metal-specific because CUDA contexts are process-wide, so the same code is safe in Docker/CUDA mode.

## Recommended Next Steps

### Fix direction

Pin **all** MLX operations for a model to a single, long-lived dedicated thread — `load`, `from_pretrained`/`mlx_stt_load`, `mx.eval`, `transcribe`, model forward, `mx.clear_cache`, and `unload` must all run there.

**Recommended home — the backend layer, not the dispatch layer.** Because dispatch is backend-agnostic (Finding 4 of subagent trace) and no MLX backend touches stream/device APIs (Finding F-grep), marshal each MLX backend's public methods onto **one dedicated single-thread executor owned by the backend** (`concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx-<model>")`, created lazily, persisting for the backend's lifetime). Each public method body runs as `self._mlx_executor.submit(self._impl, ...).result()`. A `max_workers=1` pool reuses the *same* worker thread for every task → stream `(gpu,0)` is created once and always visible.

**Why this covers everything at once:** the marshal happens *inside* the backend, so it is correct no matter which thread calls it — file import (`to_thread`), import-queue worker, `parallel_diarize` pool thread, and `LiveModeThread` are all automatically fixed with no change to `transcription.py`, `live.py`, `live_engine.py`, or `parallel_diarize.py`. CUDA/NeMo/WhisperX backends are untouched (process-wide context; no pinning needed).

**Open design decisions (for the build phase):**
- Per-backend executor (simplest; only one MLX backend is active at a time) vs. one process-wide MLX worker (maximally safe; would also naturally own `mx.metal.set_cache_limit` at `model_manager.py:268/277`).
- Whether to also move the `mx.metal.set_cache_limit` call onto the pinned thread (likely benign — it configures the allocator, not a stream — but worth co-locating for a single MLX-thread invariant).
- Reentrancy: ensure a method that internally calls another marshaled method doesn't deadlock the single-thread pool (impl methods must call the raw `_impl`, not the public marshaled wrapper).
- Lifecycle: reuse the same executor across load→transcribe→unload so affinity holds; only shut it down when the backend is permanently disposed.

**Verification without Mac hardware:** unit tests can assert that `load()` and `transcribe()` execute on the *same* `threading.get_ident()`, and that this thread differs from the caller's — proving affinity is enforced without needing a real Metal device (mock the `mx.*`/model calls to record the thread id).

### Diagnostic

If a Mac is available: run with full server logs, reproduce a single file transcription, capture the Python traceback to confirm the exact raising `mx.*` frame and the worker thread name.

## Reproduction Plan

Requires Apple Silicon + Metal mode. Setup: install `-arm64-mac-metal.dmg`, start Metal server, select any MLX model. Trigger: import one audio file. Expected (current): "Transcription failed: There is no stream (gpu,0) in current thread." Expected (after fix): normal transcription.

## Side Findings

From the #124 follow-up comment (tangential to #134 root cause; not yet ticketed):

- Model Manager copy is contradictory: "Start the server to manage model downloads. Model selection is available while the server is stopped." (**Reported**, not verified.)
- Possible bug: cannot download other models even when the server is stopped. (**Reported**, not verified.)
- Enhancement: Server config "Persistent volumes" paths are truncated — request full path + open-in-Finder + copy-to-clipboard. (**Reported**, enhancement.)

## Follow-up: 2026-06-01

### Resolution

Fix designed and implemented on branch `fix/gh-134-mlx-cross-thread-stream`. Spec: `spec-gh-134-mlx-cross-thread-stream.md` (status `done`).

**Mechanism:** New `server/backend/core/stt/backends/mlx_thread_pin.py` — `MLXThreadAffinityMixin` (one `ThreadPoolExecutor(max_workers=1)` per backend instance) + `@mlx_pinned` decorator. All four MLX backends now marshal `load`/`unload`/`warmup`/`transcribe` (+ vibevoice `transcribe_with_diarization`) onto a single owning thread, so the GPU stream is created once and every op runs there — fixing file import, import queue, parallel diarization, and live mode at once with no dispatch-layer change.

**Verification (Linux, code-only — Mac hardware still required for device confirmation):** 6 new thread-affinity tests pass; full backend suite 1920 passed / 0 failed; `gitnexus_detect_changes` → risk low, 0 affected execution flows. The remaining uncertainty is purely the device-level confirmation that pinning eliminates the MLX error on a real M-series Mac (the code-level cause is Confirmed).

### Updated Conclusion

Root cause Confirmed; fix Implemented and code-verified. Open only on the maintainer's Apple-Silicon manual check + reporter confirmation on #134.
