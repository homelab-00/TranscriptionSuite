---
title: 'GPU Crash Resilience and Recovery'
slug: 'gpu-crash-resilience'
created: '2026-03-26'
status: 'completed'
stepsCompleted: [1, 2, 3, 4]
tech_stack: ['Python 3.13', 'FastAPI 0.135.1', 'PyTorch 2.8.0 (CUDA 12.9)', 'Electron 40.8.0', 'TypeScript 5.9.3', 'Docker (compose overlays)']
files_to_modify: ['server/backend/core/audio_utils.py', 'server/backend/core/model_manager.py', 'server/backend/api/main.py', 'dashboard/electron/main.ts', 'dashboard/electron/dockerManager.ts', 'server/backend/tests/test_audio_utils.py', 'server/backend/tests/test_model_manager_init.py']
code_patterns: ['lazy torch imports (patch at call site)', 'gracefulShutdown lifecycle (SIGINT/SIGTERM/SIGHUP)', 'ModelManager.__init__ GPU probing via audio_utils', 'lifespan() startup sequence (prewarm→join→ModelManager)', 'CONTAINER_NAME constant for docker stop', 'spawn + detached + unref for child_process']
test_patterns: ['pytest + pytest-asyncio (asyncio_mode=auto)', 'patch.object(au, "torch", mock) + patch.object(au, "HAS_TORCH", True)', '_build_manager() helper with GPU stubs', 'mock subprocess for ffprobe/ffmpeg patterns', 'Vitest + testing-library (jsdom)']
---

# Tech-Spec: GPU Crash Resilience and Recovery

**Created:** 2026-03-26

## Overview

### Problem Statement

When the NVIDIA driver enters a dirty state (from Electron SIGBUS, orphaned CUDA contexts, or concurrent GPU consumer contention), the server fails to start with `cudaErrorUnknown` and offers no recovery path. Meanwhile, a hard Electron crash (SIGBUS) bypasses `gracefulShutdown()`, leaving the Docker container orphaned — which itself causes the dirty driver state on the next startup.

### Solution

Three-pronged hardening: (1) CUDA health probe at server startup — attempt `torch.cuda.init()`, detect failure, surface a clear "reboot required" message (no `cudaDeviceReset()` — too dangerous in multi-consumer GPU environments); (2) crash-resilient container cleanup via a sentinel process in Electron that survives SIGBUS/SIGKILL using `setsid` semantics; (3) diagnostic `nvidia-smi` capture (with timeout) on CUDA failure to aid future debugging.

### Scope

**In Scope:**
- CUDA health probe before model load (attempt `torch.cuda.init()`, detect `cudaErrorUnknown`, report status)
- Clear user-facing error when GPU is unrecoverable ("restart your computer")
- Electron sentinel process for crash-resilient container teardown (new session via `setsid`, survives SIGBUS/SIGKILL)
- Diagnostic `nvidia-smi` capture on CUDA failure (non-blocking, 5s timeout)
- Tests for all new server-side paths

**Out of Scope:**
- Actually running transcription on CPU (future work)
- VA-API probe suppression in Electron (separate effort)
- AppImage/FUSE resilience (separate effort)
- Host-side watchdog (systemd, Docker restart policies)
- Multi-GPU support

## Context for Development

### Codebase Patterns

- **Lazy torch imports**: `audio_utils.py` imports `torch` at module level with `try/except` (sets `HAS_TORCH` flag). `model_manager.py` lazily imports `check_cuda_available` and `get_gpu_memory_info` from `audio_utils` inside `__init__`. When mocking, patch `server.core.audio_utils.check_cuda_available` (not `server.core.model_manager.*`).
- **GPU probing at startup**: `ModelManager.__init__` (line 228) calls `check_cuda_available()` → sets `self.gpu_available`. If True, calls `get_gpu_memory_info()` → logs VRAM. The `get_gpu_memory_info()` function (audio_utils:87) catches ALL exceptions and returns `{"available": True, "error": str(e)}` — it never raises, never retries, never attempts recovery.
- **Lifespan startup sequence** (api/main.py:349): `prewarm_thread.join()` → `get_model_manager(config)` → `manager.load_transcription_model()`. The health check must go **between** prewarm join and `get_model_manager()`.
- **Graceful shutdown in Electron** (main.ts:1531): `gracefulShutdown()` calls `dockerManager.forceStopContainer(10)` with a `STOP_SERVER_ON_QUIT_TIMEOUT_MS` race. Handles SIGINT/SIGTERM/SIGHUP (line 1578). Does NOT survive SIGBUS/SIGKILL.
- **Docker container identity**: `CONTAINER_NAME = 'transcriptionsuite-container'` (dockerManager.ts:44). `forceStopContainer(timeout)` runs `docker stop --time {timeout} transcriptionsuite-container`. The sentinel needs this name, not a dynamic container ID.
- **GPU status in API**: `/api/status` endpoint returns `gpu_available` boolean. Frontend `types.ts` has `gpu_available?: boolean` and `gpu_memory?: string`. The "reboot required" error should surface through this existing status mechanism.
- **Existing test patterns**: `test_audio_utils.py` uses `patch.object(au, "torch", mock_torch)` + `patch.object(au, "HAS_TORCH", True)` for CUDA mocking. `test_model_manager_init.py` uses `_build_manager()` helper that patches `audio_utils.check_cuda_available` and `audio_utils.get_gpu_memory_info`. New health check tests should follow these patterns.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `server/backend/core/audio_utils.py` | `get_gpu_memory_info()` (line 87), `check_cuda_available()` (line 80), `clear_gpu_cache()` (line 62) — all CUDA interaction. New `cuda_health_check()` goes here. |
| `server/backend/core/model_manager.py` | `ModelManager.__init__` (line 199) probes GPU via `audio_utils`. No changes needed — `check_cuda_available()` short-circuits via `_cuda_probe_failed` flag. |
| `server/backend/api/main.py` | `lifespan()` (line 349) — startup sequence. Health check inserts between prewarm join (line 408) and `get_model_manager()` (line 411). |
| `server/backend/api/routes/health.py` | `/api/status` endpoint — surfaces `gpu_available` to frontend. Needs `gpu_error` field. |
| `dashboard/electron/main.ts` | `gracefulShutdown()` (line 1531), signal handlers (line 1578). Sentinel spawns at app startup. |
| `dashboard/electron/dockerManager.ts` | `CONTAINER_NAME` (line 44), `forceStopContainer()` (line 1247), `stopContainer()` (line 1225). Sentinel uses same container name. |
| `server/backend/tests/test_audio_utils.py` | Existing CUDA mock patterns — extend with `TestCudaHealthCheck` class. |
| `server/backend/tests/test_model_manager_init.py` | `_build_manager()` helper — extend with health check integration tests. |
| `dashboard/src/api/types.ts` | `gpu_available?: boolean` — add `gpu_error?: string` field. |

### Technical Decisions

- **No `cudaDeviceReset()` — too dangerous**: In a multi-consumer GPU environment (CUDA in Docker + VA-API in Electron + KMS in compositor), `cudaDeviceReset()` destroys all allocations on the device and could destabilize other consumers. Instead: attempt `torch.cuda.init()`, catch the error, log diagnostics, and tell the user to reboot.
- **Reboot message, not CPU fallback**: When CUDA is unrecoverable, show a clear user-facing error ("GPU in failed state — please restart your computer") rather than silently falling back to CPU. CPU transcription is a separate feature for future work.
- **Module-level `_cuda_probe_failed` flag**: `cuda_health_check()` sets `_cuda_probe_failed = True` in `audio_utils.py` when CUDA is unrecoverable. `check_cuda_available()` respects this flag and short-circuits to `False`. This makes `check_cuda_available()` the single source of truth for "can we use CUDA?" — ModelManager, STT engine, diarization engine, and live engine all call it. Set the flag once, everything downstream just works. **No ModelManager changes needed.**
- **Sentinel process with `setsid` semantics (Linux only)**: On app startup, spawn a tiny detached script in a **new session** (`setsid`) that watches for the Electron PID (passed explicitly, not `$PPID`) to vanish, then runs `docker stop`. A merely `detached: true` child may not survive SIGBUS if the kernel tears down the process group — `setsid` ensures the sentinel is in its own session and survives. **Platform scope: Linux only.** Windows/macOS sentinel is future work (Windows has no `setsid` equivalent; macOS could use `launchd` but is out of scope).
- **Sentinel cleanup on graceful shutdown**: In `gracefulShutdown()`, kill the sentinel PID with `SIGTERM` *before* calling `forceStopContainer()`. This prevents both the sentinel and gracefulShutdown from racing to stop the container. Docker stop is idempotent, but racing creates noisy logs.
- **`nvidia-smi` with timeout**: On CUDA failure, shell out to `nvidia-smi` with a 5-second subprocess timeout. If the driver is truly hosed, `nvidia-smi` itself can hang — the timeout prevents the server startup from blocking indefinitely. Captures driver version, GPU state, and running processes for bug reports.
- **Health check in lifespan, not ModelManager**: Run the CUDA health check in FastAPI's `lifespan()` startup, before ModelManager initializes. This catches the problem at the earliest possible point.

## Implementation Plan

### Prong 1: CUDA Health Probe (Server)

**New function** `cuda_health_check()` in `audio_utils.py`:
1. If `HAS_TORCH` is False → return `{"status": "no_torch"}` (not an error — torch may not be installed)
2. Try `torch.cuda.init()` explicitly
3. If succeeds → try `torch.cuda.get_device_properties(0)` to verify device is responsive → return `{"status": "healthy", "device": props_summary}`
4. If raises RuntimeError with "unknown error" or error code 999 → **set module-level `_cuda_probe_failed = True`** → capture `nvidia-smi` output (5s timeout via `subprocess.run(..., timeout=5)`) → return `{"status": "unrecoverable", "error": str(e), "nvidia_smi": smi_output}`
5. If `nvidia-smi` itself times out or fails → include that in the diagnostic
6. Log full diagnostic at ERROR level with structlog

**Update `check_cuda_available()`** to respect the flag:
```python
_cuda_probe_failed: bool = False

def check_cuda_available() -> bool:
    if _cuda_probe_failed:
        return False
    if not HAS_TORCH or torch is None:
        return False
    return torch.cuda.is_available()
```
This makes `check_cuda_available()` the single source of truth. ModelManager, all STT backends, diarization engine, and live engine call it — no changes needed in any of them.

**Integration in `lifespan()`** (api/main.py):
- Call `cuda_health_check()` after prewarm join, before `get_model_manager()`
- If status is `"unrecoverable"` → log the full diagnostic, set `app.state.gpu_error = result`, skip model preload, let server start (so `/api/status` is reachable)
- Do NOT crash the server — the dashboard needs the status endpoint to show the error

**Surface in `/api/status`**:
- Add `gpu_error` field to status response when health check detected failure
- Frontend reads `gpu_error` and shows user-facing "GPU in failed state — please restart your computer" banner

### Prong 2: Sentinel Process (Electron)

**Sentinel implementation** — inline shell via `setsid` (Linux only, ~3 lines):

```typescript
const pid = process.pid;
const sentinel = spawn('setsid', [
  'sh', '-c',
  `while kill -0 ${pid} 2>/dev/null; do sleep 2; done; docker stop --time 10 transcriptionsuite-container 2>/dev/null`
], { detached: true, stdio: 'ignore' });
sentinel.unref();
```

**Key details:**
- Pass `process.pid` explicitly — `$PPID` inside `setsid` would be the `setsid` process, not Electron
- Use `CONTAINER_NAME` ('transcriptionsuite-container') hardcoded, not a dynamic ID — sentinel doesn't need dockerManager
- **Linux only** — `setsid` binary doesn't exist on macOS/Windows. Guard with `process.platform === 'linux'`.

**Spawn in `main.ts`** — in `app.whenReady()`, after container start is initiated:
1. Spawn sentinel (Linux only)
2. Store `sentinel.pid` in module-level `sentinelPid` variable
3. In `gracefulShutdown()`: kill sentinel with `process.kill(sentinelPid, 'SIGTERM')` **before** calling `forceStopContainer()` — prevents both racing to stop the container

### Prong 3: Diagnostic Logging (Server)

Integrated into `cuda_health_check()` above:
- `subprocess.run(['nvidia-smi'], capture_output=True, text=True, timeout=5)`
- On timeout: log "nvidia-smi timed out (driver may be unresponsive)"
- On FileNotFoundError: log "nvidia-smi not found in PATH"
- Structured log output includes: error message, nvidia-smi stdout, driver version (parsed from smi output if available)

### Tasks

#### Phase 1: CUDA Health Probe (Server — no dependencies)

- [x] Task 1: Add `_capture_nvidia_smi()` helper to `audio_utils.py`
  - File: `server/backend/core/audio_utils.py`
  - Action: Add a new function `_capture_nvidia_smi() -> str` after the existing imports block. Uses `subprocess.run(['nvidia-smi'], capture_output=True, text=True, timeout=5)`. Returns stdout on success, descriptive error string on `TimeoutExpired`, `FileNotFoundError`, or any other exception.
  - Notes: Private function (underscore prefix). Timeout is 5 seconds. Never raises — always returns a string.

- [x] Task 2: Add `_cuda_probe_failed` flag and update `check_cuda_available()`
  - File: `server/backend/core/audio_utils.py`
  - Action: Add module-level `_cuda_probe_failed: bool = False` after the `HAS_SILERO_VAD` block (around line 59). Modify `check_cuda_available()` to check `_cuda_probe_failed` first — if `True`, return `False` immediately, before checking `HAS_TORCH` or `torch.cuda.is_available()`.
  - Notes: This makes `check_cuda_available()` the single source of truth. All downstream consumers (ModelManager, STT backends, diarization, live engine) call it — zero changes needed in any of them.

- [x] Task 3: Add `cuda_health_check()` function to `audio_utils.py`
  - File: `server/backend/core/audio_utils.py`
  - Action: Add new public function `cuda_health_check() -> dict` after `check_cuda_available()`. Logic:
    1. If `not HAS_TORCH or torch is None` → return `{"status": "no_torch"}`
    2. Try `torch.cuda.init()` then `torch.cuda.get_device_properties(0)`
    3. On success → return `{"status": "healthy", "device_name": props.name, "total_memory_gb": round(props.total_mem / 1024**3, 2)}`
    4. On `RuntimeError` → check error string case-insensitively: `err_lower = str(e).lower()`. If `"unknown error" in err_lower or "error 999" in err_lower` → set `global _cuda_probe_failed; _cuda_probe_failed = True` → call `_capture_nvidia_smi()` → log at ERROR level → return `{"status": "unrecoverable", "error": str(e), "nvidia_smi": smi_output}`
    5. On any other CUDA error (e.g., "no CUDA-capable device") → return `{"status": "no_cuda", "error": str(e)}` (not unrecoverable, just no GPU)
  - Notes: Uses `global _cuda_probe_failed` to set the flag. Logger is the existing module-level `logger`. The function never raises. Error matching is case-insensitive to cover PyTorch variants ("CUDA unknown error", "CUDA error: unknown error", etc.).

- [x] Task 4: Add `TestCaptureNvidiaSmi` tests
  - File: `server/backend/tests/test_audio_utils.py`
  - Action: Add new test class `TestCaptureNvidiaSmi` with tests:
    - `test_returns_stdout_on_success` — mock `subprocess.run` returning normal nvidia-smi output
    - `test_returns_timeout_message` — mock `subprocess.run` raising `subprocess.TimeoutExpired`
    - `test_returns_not_found_message` — mock `subprocess.run` raising `FileNotFoundError`
    - `test_returns_error_message_on_other_exception` — mock raising generic `OSError`
  - Notes: Follow existing `TestConvertToWav` pattern for subprocess mocking.

- [x] Task 5a: Add `TestCudaHealthCheck` tests
  - File: `server/backend/tests/test_audio_utils.py`
  - Action: Add new test class `TestCudaHealthCheck` with an `autouse` fixture that resets `au._cuda_probe_failed = False` after each test. Tests:
    - `test_no_torch_returns_no_torch` — `patch.object(au, "HAS_TORCH", False)` → assert status is `"no_torch"`
    - `test_healthy_gpu_returns_healthy` — mock `torch.cuda.init()` succeeds, `torch.cuda.get_device_properties(0)` returns mock with `.name` and `.total_mem` → assert status is `"healthy"`
    - `test_unknown_error_returns_unrecoverable` — mock `torch.cuda.init()` raising `RuntimeError("CUDA unknown error")` → assert status is `"unrecoverable"`, assert `au._cuda_probe_failed` is `True`, assert `nvidia_smi` key present
    - `test_no_cuda_device_returns_no_cuda` — mock `torch.cuda.init()` raising `RuntimeError("no CUDA-capable device")` → assert status is `"no_cuda"`, assert `au._cuda_probe_failed` is `False`
  - Notes: Follow existing `patch.object(au, "torch", mock_torch)` pattern. The autouse fixture prevents cross-test contamination:
    ```python
    @pytest.fixture(autouse=True)
    def _reset_cuda_probe_flag(self):
        yield
        au._cuda_probe_failed = False
    ```

- [x] Task 5b: Add `TestCheckCudaAvailableWithProbeFlag` tests
  - File: `server/backend/tests/test_audio_utils.py`
  - Action: Add new test class `TestCheckCudaAvailableWithProbeFlag` with the same autouse fixture for flag reset. Tests:
    - `test_returns_false_when_probe_failed` — set `au._cuda_probe_failed = True`, mock `torch.cuda.is_available()` returning `True` → assert `check_cuda_available()` returns `False`
    - `test_returns_true_when_probe_not_failed` — set `au._cuda_probe_failed = False`, mock `torch.cuda.is_available()` returning `True` → assert `check_cuda_available()` returns `True`
  - Notes: This is separate from `TestCudaHealthCheck` because it tests `check_cuda_available()` behavior, not the health check itself. Same autouse fixture pattern.

#### Phase 2: Lifespan Integration + Status Surface (depends on Phase 1)

- [x] Task 6: Integrate `cuda_health_check()` into `lifespan()`
  - File: `server/backend/api/main.py`
  - Action: After the prewarm join block (line 408) and before `get_model_manager()` (line 411), add:
    1. `from server.core.audio_utils import cuda_health_check`
    2. `gpu_health = cuda_health_check()`
    3. `_log_time(f"CUDA health check: {gpu_health['status']}")`
    4. If `gpu_health["status"] == "unrecoverable"`:
       - `logger.error("CUDA health check failed — GPU transcription disabled for this session", error=gpu_health["error"], nvidia_smi=gpu_health.get("nvidia_smi", "N/A"))`
       - `app.state.gpu_error = gpu_health`
    5. Add a warning log **before** `get_model_manager()` when health check failed: `logger.warning("CUDA health check failed — GPU transcription disabled for this session. %s", gpu_health["error"])` — this ensures the log chain is clear: health check failed → GPU disabled → ModelManager sees no GPU → model preload skipped.
    6. Wrap the existing model preload block: skip `manager.load_transcription_model()` if `gpu_health["status"] == "unrecoverable"` (log a warning instead)
  - Notes: Server must NOT crash — it needs `/api/status` reachable so the dashboard can show the error. The `get_model_manager()` call still executes (ModelManager handles `gpu_available=False` gracefully via the `_cuda_probe_failed` flag). The warning log before ModelManager init completes the causal chain in server logs.

- [x] Task 7: Surface `gpu_error` in `/api/status`
  - File: `server/backend/api/routes/health.py`
  - Action: In the `get_status()` route handler, read `request.app.state.gpu_error` (if it exists, default `None`). Add `"gpu_error"` key to the response dict with the error message string (or `None` if healthy). If `gpu_error` is set, include `"gpu_error_action": "Please restart your computer to reset the GPU driver."`.
  - Notes: Only add the field when it exists — don't break existing clients expecting the current shape.

- [x] Task 8: Add `gpu_error` to frontend types
  - File: `dashboard/src/api/types.ts`
  - Action: Add `gpu_error?: string` and `gpu_error_action?: string` to the `ServerStatus` type (or whichever interface contains `gpu_available`).
  - Notes: Optional fields only — no frontend UI changes in this spec (dashboard banner is a follow-up).

#### Phase 3: Sentinel Process (Electron — independent of Phase 1/2)

- [x] Task 9: Add sentinel spawn function to `main.ts`
  - File: `dashboard/electron/main.ts`
  - Action:
    1. Add module-level `let sentinelPid: number | null = null;` near other module-level state
    2. Add function `spawnContainerSentinel(): void` that:
       - Guards with `if (process.platform !== 'linux') return;`
       - Gets `const pid = process.pid;`
       - Spawns: `spawn('setsid', ['sh', '-c', \`while kill -0 ${pid} 2>/dev/null; do sleep 2; done; docker stop --time 10 transcriptionsuite-container 2>/dev/null\`], { detached: true, stdio: 'ignore' })`
       - Calls `.unref()` on the child
       - Stores `sentinelPid = child.pid ?? null`
       - Logs: `shutdownLog(\`[Sentinel] Spawned container sentinel (PID: ${sentinelPid})\`)`
    3. Call `spawnContainerSentinel()` inside `app.whenReady()`, after the Docker container start is initiated (after `dockerManager.startContainer()` or equivalent)
  - Notes: `spawn` is already imported from `child_process` in this file. The sentinel uses the hardcoded container name, not dockerManager.

- [x] Task 10: Add sentinel cleanup to `gracefulShutdown()`
  - File: `dashboard/electron/main.ts`
  - Action: At the top of the `gracefulShutdown()` async block (line 1535, after `flushMainProcessLogRemainders()`), add:
    1. If `sentinelPid !== null` → `try { process.kill(sentinelPid, 'SIGTERM'); } catch { /* already dead */ }`
    2. Set `sentinelPid = null`
    3. Log: `shutdownLog('[Sentinel] Killed container sentinel.');`
  - Notes: Must come **before** `forceStopContainer()` to avoid both racing. The `try/catch` handles the case where the sentinel already exited.

### Acceptance Criteria

#### Phase 1: CUDA Health Probe

- [x] AC 1: Given torch is not installed (`HAS_TORCH=False`), when `cuda_health_check()` is called, then it returns `{"status": "no_torch"}` and `_cuda_probe_failed` remains `False`.
- [x] AC 2: Given CUDA is healthy, when `cuda_health_check()` is called, then it returns `{"status": "healthy"}` with device name and memory, and `_cuda_probe_failed` remains `False`.
- [x] AC 3: Given CUDA returns "unknown error" (error 999), when `cuda_health_check()` is called, then it returns `{"status": "unrecoverable"}` with the error message and `nvidia-smi` output, and `_cuda_probe_failed` is set to `True`.
- [x] AC 4: Given `_cuda_probe_failed` is `True`, when `check_cuda_available()` is called, then it returns `False` regardless of what `torch.cuda.is_available()` would return.
- [x] AC 5: Given no CUDA-capable device is present (but driver is healthy), when `cuda_health_check()` is called, then it returns `{"status": "no_cuda"}` and `_cuda_probe_failed` remains `False`.
- [x] AC 6: Given `nvidia-smi` hangs for >5 seconds, when `_capture_nvidia_smi()` is called, then it returns a timeout message within ~5 seconds and does not block indefinitely.
- [x] AC 7: Given `nvidia-smi` is not in PATH, when `_capture_nvidia_smi()` is called, then it returns a "not found" message and does not raise.

#### Phase 2: Lifespan Integration + Status Surface

- [x] AC 8: Given CUDA health check returns `"unrecoverable"`, when the server starts via `lifespan()`, then the server reaches "Application startup complete" (does not crash), `app.state.gpu_error` is set, and model preload is skipped.
- [x] AC 9: Given `app.state.gpu_error` is set, when `/api/status` is called, then the response includes `"gpu_error"` with the error message and `"gpu_error_action"` with reboot instructions.
- [x] AC 10: Given CUDA is healthy, when `/api/status` is called, then the response does not include `"gpu_error"` (field is absent or null).

#### Phase 3: Sentinel Process

- [x] AC 11: Given the app is running on Linux, when `spawnContainerSentinel()` is called, then a child process is spawned with `setsid`, `detached: true`, `stdio: 'ignore'`, and `sentinelPid` is set to a valid PID.
- [x] AC 12: Given the app is running on macOS or Windows, when `spawnContainerSentinel()` is called, then no child process is spawned and `sentinelPid` remains `null`.
- [x] AC 13: Given a sentinel is running, when `gracefulShutdown()` is called, then the sentinel is killed with `SIGTERM` before `forceStopContainer()` is called.
- [x] AC 14: Given Electron crashes with SIGBUS (hard crash, no signal handlers run), when the sentinel detects the parent PID is gone, then it runs `docker stop --time 10 transcriptionsuite-container` within ~4 seconds (2 second poll interval × 2 polls).

## Additional Context

### Dependencies

- **No new Python packages** — `torch.cuda`, `subprocess` (for `nvidia-smi`), and existing `logging` are sufficient. All used modules are already available in the container.
- **No new npm packages** — Node.js `child_process` (already imported in `main.ts`) for the sentinel process. `setsid` is a standard Linux utility (`util-linux` package, present on all Linux distributions).
- **No new Docker compose changes** — sentinel uses the existing `docker` CLI binary available on the host.

### Testing Strategy

#### Backend (pytest)

- **`TestCaptureNvidiaSmi`** (4 tests): Mock `subprocess.run` for success, timeout, not-found, other-error paths. Follow `TestConvertToWav` subprocess mock pattern.
- **`TestCudaHealthCheck`** (5 tests): Mock `torch.cuda.init()` and `torch.cuda.get_device_properties()` for healthy, unknown-error, no-device, no-torch paths. Verify `_cuda_probe_failed` flag state. Reset flag in teardown.
- **`TestCheckCudaAvailableWithProbeFlag`** (2 tests): Verify `check_cuda_available()` returns `False` when `_cuda_probe_failed=True`, returns `True` when flag is `False` and CUDA is available.
- **Lifespan integration**: Extend existing test infrastructure (if lifespan tests exist) or add a focused test that mocks `cuda_health_check()` returning unrecoverable → verify server starts and `app.state.gpu_error` is set.

#### Frontend (Vitest — optional)

- **Sentinel spawn**: Mock `child_process.spawn`, verify correct args (`setsid`, detached, unref). Verify platform guard skips on non-Linux.
- **Sentinel cleanup**: Verify `process.kill` called with sentinel PID before `forceStopContainer`.

#### Manual Testing

- **SIGBUS reproduction** (Linux only): Fork a test process, send SIGBUS to parent, verify sentinel runs `docker stop`. Document as manual test procedure — CI-hostile.
- **Dirty GPU state** (requires real GPU): If reproducible, verify health check detects `cudaErrorUnknown` and returns unrecoverable. Requires `nvidia-smi -r` or reboot to reset between tests.

### Notes

- **Brainstorming session**: `_bmad-output/brainstorming/brainstorming-session-2026-03-26-current.md`
- **Related bugs**: Bug 1 (Electron SIGBUS), Bug 2 (CUDA unknown error) — see `bug1.txt`, `bug2.txt`
- **GitHub Issue**: Linked to brainstorming session findings
- **Bill has no AMD hardware** — this spec targets NVIDIA CUDA recovery only
- **Recipe F** from the brainstorming session describes the full causal chain these fixes target
- **Future work**: CPU fallback mode, VA-API suppression, AppImage/FUSE resilience, Windows/macOS sentinel, dashboard GPU error banner UI
- **Risk**: The `setsid` sentinel has a 2-second poll interval. In the worst case, the container runs for ~4 extra seconds after Electron dies. This is acceptable — the goal is preventing orphaned containers across restarts, not sub-second cleanup.
- **Risk**: `torch.cuda.init()` may behave differently across PyTorch versions. The error string matching ("unknown error") should be tested against PyTorch 2.8.0 specifically. Consider also matching on CUDA error code 999 if PyTorch exposes it.

## Review Notes

- Adversarial review completed
- Findings: 10 total, 6 fixed, 4 skipped (noise/undecided)
- Resolution approach: auto-fix
- Fixed: F1 (duplicate log), F3 (container name from constant), F4 (sentinel respects user settings), F8 (nvidia-smi stderr), F9 (sentinel spawn failure log), F10 (type annotation)
- Skipped: F2 (already handled by except Exception), F5 (pytest yield teardown is safe), F6 (exception-driven no-GPU path acceptable), F7 (pre-existing stdlib logger pattern)
