---
title: 'Fix Vulkan /dev/dri pre-flight and whisper.cpp sidecar reachability (GH-58 follow-up)'
type: 'bugfix'
created: '2026-04-10'
status: 'done'
baseline_commit: '24838335d3655b289a0d53f437ba9a467109fa48'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Two container-start failures remain after the v1.3.1 GH-58 fix: (1) Vulkan profile unconditionally mounts `/dev/dri` but the device may not exist (WSL2, missing DRI drivers), causing `error gathering device information while adding custom device "/dev/dri": no such file or directory`; (2) selecting a GGML model in CPU mode routes to the whisper.cpp backend which tries to reach the non-running sidecar at `http://whisper-server:8080`, producing `[Errno -5] No address associated with hostname`.

**Approach:** Add a Vulkan pre-flight check in `startContainer()` (mirroring the existing GPU guard), harden `checkGpu()` to verify `/dev/dri` directory existence, and add a clear connection-failure error in `WhisperCppBackend` that tells the user the sidecar is unreachable and suggests switching to Vulkan mode.

## Boundaries & Constraints

**Always:**
- Preserve existing Vulkan users' workflow — only block when `/dev/dri` is genuinely missing.
- CPU profile must always start successfully regardless of model selection.
- Error messages must be actionable (tell the user what to do, not just what failed).

**Ask First:**
- Whether to also add a dashboard-side UI warning when a GGML model is selected but profile is not Vulkan (vs. relying on server-side error only).

**Never:**
- Modify Docker compose overlay file structure or device syntax.
- Auto-switch the runtime profile without user consent (beyond the existing one-time auto-detection).
- Remove the whisper.cpp backend's ability to work when the sidecar is actually running.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Vulkan profile, `/dev/dri` exists | `runtimeProfile='vulkan'`, `/dev/dri` present | Container starts normally with Vulkan overlay | N/A |
| Vulkan profile, `/dev/dri` missing | `runtimeProfile='vulkan'`, no `/dev/dri` | Pre-flight blocks start, error dialog shown | Suggests switching to CPU |
| Vulkan auto-detection, `/dev/dri` missing | `gpuAutoDetectDone=false`, no `/dev/dri` | Auto-detection selects `'cpu'` (not `'vulkan'`) | N/A |
| Vulkan auto-detection, `/dev/dri` + renderD128 present | `gpuAutoDetectDone=false`, both exist | Auto-detection selects `'vulkan'` | N/A |
| GGML model in CPU mode, sidecar not running | Model=`ggml-large-v3-turbo.bin`, profile=`'cpu'` | Transcription fails with clear message about sidecar | "whisper.cpp sidecar is not reachable — switch to Vulkan profile" |
| GGML model in Vulkan mode, sidecar running | Model=`ggml-large-v3-turbo.bin`, profile=`'vulkan'` | Transcription succeeds normally | N/A |
| Non-Linux Vulkan (macOS/Windows) | `runtimeProfile='vulkan'`, non-Linux platform | No `/dev/dri` check (irrelevant on these platforms) | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/electron/dockerManager.ts:1243-1261` -- Existing GPU pre-flight guard in `startContainer()` (add Vulkan equivalent after it)
- `dashboard/electron/dockerManager.ts:2205-2219` -- `checkGpu()` Vulkan detection (needs `/dev/dri` directory check)
- `server/backend/core/stt/backends/whispercpp_backend.py:22-43` -- Default sidecar URL and resolution logic
- `server/backend/core/stt/backends/whispercpp_backend.py:80-84` -- `_ensure_client()` HTTP client creation
- `server/backend/core/stt/backends/whispercpp_backend.py:100-106` -- `load()` method (first sidecar contact)
- `server/docker/docker-compose.vulkan.yml:22` -- `/dev/dri:/dev/dri` device mount

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/dockerManager.ts` -- Add Vulkan pre-flight guard in `startContainer()` after the existing GPU guard: when `runtimeProfile === 'vulkan'` and `process.platform === 'linux'`, check `/dev/dri` exists; if not, throw descriptive error suggesting CPU mode -- prevents cryptic Docker device mount errors
- [x] `dashboard/electron/dockerManager.ts` -- Harden `checkGpu()` Vulkan detection to require both `/dev/dri` (directory) and `/dev/dri/renderD128` (render node) -- prevents auto-detection from selecting Vulkan when the device directory is missing
- [x] `server/backend/core/stt/backends/whispercpp_backend.py` -- Wrap HTTP calls in `load()` and `transcribe()` with a try/except for `httpx.ConnectError` (and OSError for DNS) that re-raises with a clear message: "whisper.cpp sidecar not reachable at {url}. Ensure the Vulkan runtime profile is selected and the container is running." -- replaces cryptic `[Errno -5]` with actionable guidance

**Acceptance Criteria:**
- Given `runtimeProfile='vulkan'` on a Linux system without `/dev/dri`, when user clicks Start, then an error dialog is shown before Docker attempts to start — no cryptic device error.
- Given `gpuAutoDetectDone=false` on a system with `/dev/dri/renderD128` but no `/dev/dri` directory, when auto-detection runs, then profile is set to `'cpu'` (not `'vulkan'`).
- Given a GGML model selected in CPU mode with no sidecar running, when transcription is attempted, then the error message mentions the sidecar and Vulkan profile — not `[Errno -5]`.

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors from changed files
- `cd dashboard && npx vitest run` -- expected: existing tests pass
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` -- expected: existing tests pass

## Suggested Review Order

**Vulkan pre-flight and auto-detection hardening**

- Pre-flight blocks Vulkan start when `/dev/dri` or render node is missing
  [`dockerManager.ts:1263`](../../dashboard/electron/dockerManager.ts#L1263)

- Auto-detection now requires both `/dev/dri` dir and renderD128 for Vulkan flag
  [`dockerManager.ts:2228`](../../dashboard/electron/dockerManager.ts#L2228)

**whisper.cpp sidecar connection error handling**

- Shared error message constant — actionable guidance replaces raw DNS errors
  [`whispercpp_backend.py:27`](../../server/backend/core/stt/backends/whispercpp_backend.py#L27)

- `load()` catches ConnectError/OSError before the generic fallback
  [`whispercpp_backend.py:116`](../../server/backend/core/stt/backends/whispercpp_backend.py#L116)

- `transcribe()` wraps inference POST with same connection guard
  [`whispercpp_backend.py:190`](../../server/backend/core/stt/backends/whispercpp_backend.py#L190)

**Tests**

- 4 new tests: ConnectError and OSError paths for both load() and transcribe()
  [`test_whispercpp_backend.py:112`](../../server/backend/tests/test_whispercpp_backend.py#L112)
