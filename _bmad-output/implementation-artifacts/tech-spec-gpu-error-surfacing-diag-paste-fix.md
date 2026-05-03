---
title: 'GPU Error Surfacing + Diagnostics + Paste-at-Cursor'
slug: 'gpu-error-surfacing-diag-paste-fix'
created: '2026-03-26'
status: 'implementation-complete'
stepsCompleted: [1, 2, 3, 4]
tech_stack: ['Python 3.13/FastAPI 0.135', 'React 19/TypeScript 5.9', 'Electron 40', 'PyTorch 2.8.0+cu129', 'Tailwind CSS 4', '@tanstack/react-query 5']
files_to_modify: ['server/backend/core/audio_utils.py', 'dashboard/src/hooks/useServerStatus.ts', 'dashboard/components/Sidebar.tsx', 'dashboard/components/views/SessionView.tsx', 'dashboard/electron/pasteAtCursor.ts', 'server/backend/tests/test_audio_utils.py', 'server/backend/tests/test_health_routes.py', 'dashboard/src/hooks/useServerStatus.test.ts', 'README.md']
code_patterns: ['structlog stdlib logging', 'FastAPI lifespan pattern', 'React custom hooks with @tanstack/react-query', 'Electron main process execFile chains', 'StatusLight component (active/inactive/warning/error/loading)', 'Sidebar status from Docker container state props']
test_patterns: ['pytest + pytest-asyncio (asyncio_mode=auto)', 'Vitest + @testing-library/react + jsdom', 'MagicMock + patch for subprocess/torch mocking', 'test_client_local fixture for FastAPI route tests']
---

# Tech-Spec: GPU Error Surfacing + Diagnostics + Paste-at-Cursor

**Created:** 2026-03-26

## Overview

### Problem Statement

Three independent issues degrade the user experience:

1. **Misleading dashboard status on GPU failure** — When the server is configured for GPU mode and CUDA initialization fails (error 999 from driver context poisoning), the server starts, passes health checks, and the dashboard shows full green status. No transcription model is loaded, so all transcription controls are non-functional. The user sees "everything connected, nothing works" with no indication of what's wrong or what to do.

2. **Undiagnosable CUDA failures** — CUDA failures don't log enough context (torch version, CUDA toolkit version, device nodes present) to diagnose the root cause without a manual investigation session. Separately, transient CUDA init failures (non-999 RuntimeErrors that self-resolve within ~200ms) cause false `no_cuda` status when a single retry would succeed.

3. **Paste-at-cursor wrong keystroke on Linux terminals** — The paste-at-cursor feature sends `Ctrl+V` regardless of the active window. Linux terminal emulators require `Shift+Ctrl+V`, so paste silently fails or sends a raw control character.

### Solution

- When GPU mode is selected and CUDA fails, surface a **red error state** in the dashboard with a persistent banner: *"GPU unavailable — restart your computer to reset the GPU driver, or switch to CPU mode in Settings > Server."* The StatusLight shows red; Start Recording stays greyed out. No automatic CPU fallback — users explicitly choose their compute mode.
- Add structured CUDA diagnostic logging at startup (single log line with torch version, CUDA version, device nodes, driver version) and a single 500ms retry for transient non-999 health check failures.
- Detect terminal emulator windows on Linux by window class and send `Shift+Ctrl+V` instead of `Ctrl+V`. Falls back to `Ctrl+V` on non-terminal windows and unsupported compositors.

### Scope

**In Scope:**
- P0: GPU failure → red error state in dashboard with persistent banner and actionable message. Fix is primarily in `useServerStatus.ts` — derive `'error'` when `gpu_error` present. StatusLight shows red, Start Recording greyed out.
- P0: Distinguish GPU-failure error from other no-model states (no model selected, model still loading)
- P1: Startup diagnostic logging — single structured log line before health check with torch/CUDA/driver/device info
- P1: Health check single retry for non-999 RuntimeErrors (500ms delay, inside `cuda_health_check()` before ModelManager init)
- P1: NVIDIA Persistence Mode documentation (README troubleshooting)
- P1: Paste-at-cursor terminal detection (Linux) — hardcoded terminal class blocklist, KDE Wayland D-Bus + X11 xdotool detection, correct keystroke per compositor. Implementable as separate PR.
- P2: "GPU stuck" troubleshooting entry in docs
- P2: Paste-at-cursor text field safety (file manager blocklist, skip paste for non-text targets)

**Out of Scope:**
- `cudaDeviceReset()` — rejected in prior spec as dangerous in multi-consumer GPU environments
- GPU reset/retry button in dashboard
- Automatic CPU model loading on GPU failure (users switch to CPU mode explicitly via server settings)
- WebSocket graceful rejection for no-model state
- Pinning torch CUDA version in requirements
- `/dev/nvidia-uvm` device node check (eliminated as root cause by investigation)
- Allowlist-based text field detection (too restrictive; Wayland security model prevents it)

## Context for Development

### Codebase Patterns

- **Logging**: `logger = logging.getLogger(__name__)` at module level; structlog wraps stdlib via `server.logging.setup`
- **CUDA state**: Module-level `_cuda_probe_failed` flag in `audio_utils.py:63` gates all downstream GPU checks via `check_cuda_available()` (line 104)
- **Status API**: `/api/status` (health.py:66-98) already surfaces `gpu_error` and `gpu_error_action` fields when `app.state.gpu_error` is set (lines 93-96). Always returns HTTP 200. No backend changes needed for error surfacing.
- **Frontend status hook**: `useServerStatus.ts` `deriveStatus()` (lines 25-73) has 4 branches: loading → inactive → active → warning. **Root bug:** checks `result.ready` (line 52) but never checks `result.status.gpu_error`. When GPU fails: server is reachable, `ready=false`, so it returns `'warning'` with "Models loading…" — misleading.
- **Sidebar status**: `Sidebar.tsx:107-121` derives status from Docker container state props (`containerRunning`, `containerHealth`), NOT from `useServerStatus`. Docker container is healthy even when GPU fails inside it, so sidebar shows green. Must incorporate GPU error state.
- **SessionView buttons**: Already disable when `!serverConnection.ready` (line 1312, 1751). Buttons ARE greyed out on GPU failure. Missing: error banner explaining why.
- **Paste-at-cursor**: `pasteAtCursor.ts` has per-platform fallback chains. `simulatePasteLinuxWayland()` (line 36) and `simulatePasteLinuxX11()` (line 77) both hardcode `ctrl+v`. Terminal detection must happen before keystroke simulation.

### Files to Modify

| File | Change | Lines |
| ---- | ------ | ----- |
| `server/backend/core/audio_utils.py` | Add diagnostic logging before health check; add retry for non-999 RuntimeErrors | 113-152 |
| `dashboard/src/hooks/useServerStatus.ts` | Check `gpu_error` in `deriveStatus()`, return `'error'` state with GPU failure message | 25-73 |
| `dashboard/components/Sidebar.tsx` | Incorporate GPU error into sidebar status derivation | 107-121 |
| `dashboard/components/views/SessionView.tsx` | Add error banner when GPU error present | ~1290 |
| `dashboard/electron/pasteAtCursor.ts` | Add `getActiveWindowClass()`, terminal blocklist, shifted paste variant | 36-91 |
| `server/backend/tests/test_audio_utils.py` | Add retry test for transient non-999 errors | new tests |
| `server/backend/tests/test_health_routes.py` | Add test for `gpu_error` in `/api/status` response | new tests |
| `dashboard/src/hooks/useServerStatus.test.ts` | New file: test `deriveStatus()` error state derivation | new file |
| `README.md` | Add Persistence Mode and "GPU stuck" troubleshooting entries | troubleshooting section |

### Files to Reference (read-only)

| File | Purpose |
| ---- | ------- |
| `server/backend/api/main.py:410-463` | Lifespan startup — health check → ModelManager → preload. Ordering constraint for retry. |
| `server/backend/api/routes/health.py:93-96` | `gpu_error` already in `/api/status` response — confirms no backend change needed |
| `dashboard/src/api/types.ts:27-28` | `ServerStatus.gpu_error` and `gpu_error_action` already typed |
| `dashboard/src/api/client.ts:186-267` | `checkConnection()` returns `{ reachable, ready, status, error }` — status contains full `ServerStatus` |
| `dashboard/components/ui/StatusLight.tsx` | Supports `'error'` state (red color) — no changes needed |
| `_bmad-output/implementation-artifacts/tech-spec-gpu-crash-resilience.md` | Prior spec — CUDA health probe, sentinel process |
| `_bmad-output/brainstorming/quick-spec-additions-2026-03-26.md` | CUDA RCA findings + paste-at-cursor additions |

### Technical Decisions

1. **No automatic CPU fallback** — If user selects GPU mode and CUDA fails, show an error. Users must explicitly switch to CPU mode in server settings. Rationale: silent CPU fallback masks the problem and delivers unexpectedly slow transcription without explanation.

2. **Health check retry limited to non-999 errors** — Error 999 (cudaErrorUnknown) indicates unrecoverable driver state. Non-999 RuntimeErrors can be transient (observed post-reboot: health check returned `no_cuda` but CUDA worked 175ms later). A single 500ms retry catches these without delaying startup significantly.

3. **Terminal detection via window class blocklist** — Detect known terminal emulators by window class name, not by attempting to introspect widget focus. Works on X11 (xdotool) and KDE Wayland (KWin D-Bus). Falls back to `Ctrl+V` on other Wayland compositors.

4. **Status API stays HTTP 200** — `/api/status` is a status report, not a health check. The GPU error is surfaced via the existing `gpu_error` response field. The fix is entirely in the frontend status derivation logic (`useServerStatus.ts`), which currently ignores `gpu_error`.

5. **GPU failure is distinct from other no-model states** — The error message and UX must distinguish: (a) GPU failed → "reboot or switch to CPU mode"; (b) no model selected → "select a model in Settings"; (c) model still loading → "please wait." These are different user actions.

6. **Paste-at-cursor implementable as separate PR** — Zero shared code with GPU error surfacing. Different files, different test strategies. The spec covers both but they should ship independently.

## Implementation Plan

### Tasks

Tasks are grouped by priority and ordered by dependency (lowest-level first).

#### P0 — GPU Error Surfacing

- [x] **Task 1: Update `deriveStatus()` to detect GPU error**
  - File: `dashboard/src/hooks/useServerStatus.ts`
  - Action: In `deriveStatus()` (lines 25-73), add a new branch after the `!result.reachable` check (line 40) and before the `result.ready` check (line 52). When the server is reachable AND `result.status?.gpu_error` is truthy, return `serverStatus: 'error'` with `serverLabel` set to the `gpu_error_action` value (or fallback: `'GPU unavailable — restart computer or switch to CPU mode in Settings > Server'`). Set `ready: false`. This must come before the `result.ready` check so GPU error takes priority over "models loading."
  - Also update `ServerConnectionInfo` interface: add `gpuError: string | null` field, populated from `result.status?.gpu_error ?? null`.

- [x] **Task2: Pass GPU error to Sidebar**
  - File: `dashboard/components/Sidebar.tsx`
  - Action: Add optional `gpuError?: string` prop to `SidebarProps` interface (line 20). In the status derivation block (lines 107-121), when `gpuError` is truthy, override both `sessionStatus` and `serverSidebarStatus` to `'error'` regardless of Docker container state. This makes the sidebar dots turn red when GPU fails.
  - File: `dashboard/App.tsx`
  - Action: In the `<Sidebar>` JSX (line 642), add prop: `gpuError={serverConnection.details?.gpu_error}`.

- [x] **Task3: Add GPU error banner in SessionView**
  - File: `dashboard/components/views/SessionView.tsx`
  - Action: Near the existing "Main model not selected" warning (line 1293), add a new conditional block: when `serverConnection.details?.gpu_error` is truthy AND `serverRunning` is true, render a red error banner with:
    - Red border/background (matching error styling: `border-red-500/20 bg-red-500/10 text-red-300`)
    - Icon: `AlertTriangle` from lucide-react (already imported)
    - Text: `serverConnection.details.gpu_error_action` or fallback message
    - This banner should appear BEFORE the "Main model not selected" amber warning (GPU error is higher priority)
  - Notes: The Start Recording button is already disabled via `!serverConnection.ready` (line 1312). No button logic changes needed.

#### P1 — CUDA Diagnostics

- [x] **Task4: Add startup diagnostic logging**
  - File: `server/backend/core/audio_utils.py`
  - Action: Add a new function `_log_cuda_diagnostics()` that logs a single structured line with:
    - `torch.__version__` (e.g. `"2.8.0+cu129"`)
    - `torch.version.cuda` (e.g. `"12.9"`)
    - Device nodes present: `glob.glob("/dev/nvidia*")` + `glob.glob("/dev/dri/*")`
    - Driver version: parse from `_capture_nvidia_smi()` output (first line contains driver version) or `"unavailable"`
  - Call this function at the top of `cuda_health_check()` (line 114, after the `no_torch` early return). Use `logger.info()` with structlog `extra={}` dict containing the fields.
  - Notes: Import `glob` at module level. The nvidia-smi call is already non-blocking with 5s timeout.

- [x] **Task5: Add health check retry for transient errors**
  - File: `server/backend/core/audio_utils.py`
  - Action: In `cuda_health_check()`, modify the non-999 error paths (lines 150-152). When a `RuntimeError` is caught that does NOT contain "unknown error" or "error 999", sleep 500ms (`time.sleep(0.5)`) and retry `torch.cuda.init()` + `torch.cuda.get_device_properties(0)` once. If retry succeeds, return `{"status": "healthy", ...}` with an additional `"retried": True` field. If retry also fails, return `{"status": "no_cuda", ...}` as before.
  - Also handle the `except Exception` path (line 151-152) the same way — retry once for non-999 errors.
  - Notes: Import `time` at module level. The retry happens inside `cuda_health_check()` which runs before `ModelManager` init in `main.py:427` — no ordering issue. Log the retry attempt at `logger.warning` level.

#### P1 — Paste-at-Cursor Terminal Detection

- [x] **Task6: Add active window class detection**
  - File: `dashboard/electron/pasteAtCursor.ts`
  - Action: Add a new async function `getActiveWindowClass(): Promise<string | null>` that detects the active window's class name:
    1. If `isWayland()`:
       - Try KDE Wayland: `gdbus call --session --dest org.kde.KWin --object-path /KWin --method org.kde.KWin.activeWindow`. Parse the returned variant dict for the `resourceClass` or `resourceName` field. Wrap in try/catch — fails on non-KDE compositors.
       - If KDE fails, return `null` (unsupported compositor — will fall back to Ctrl+V).
    2. If X11:
       - Run `xdotool getactivewindow getwindowclassname`. Returns the WM_CLASS (e.g. `"konsole"`, `"kitty"`).
       - Wrap in try/catch — return `null` on failure.
  - Notes: Uses existing `execFileAsync` and `hasCommand` helpers. Cache the compositor detection (KDE vs other) per session like `commandCache`.

- [x] **Task7: Add terminal blocklist and shifted paste**
  - File: `dashboard/electron/pasteAtCursor.ts`
  - Action:
    1. Add a constant `TERMINAL_WINDOW_CLASSES` — a `Set<string>` of known terminal window class names (case-insensitive matching). Include: `konsole`, `kitty`, `alacritty`, `foot`, `wezterm`, `gnome-terminal-server`, `xterm`, `tilix`, `terminator`, `xfce4-terminal`, `mate-terminal`, `sakura`, `st`, `urxvt`, `lxterminal`.
    2. Add a helper `isTerminalWindow(windowClass: string | null): boolean` — returns true if `windowClass?.toLowerCase()` is in `TERMINAL_WINDOW_CLASSES`.
    3. Modify `simulatePasteLinuxWayland()` and `simulatePasteLinuxX11()`: at the start, call `getActiveWindowClass()`. If `isTerminalWindow()` returns true, use shifted paste variants:
       - wtype: `wtype -M ctrl -M shift v -m shift -m ctrl`
       - dotool: `dotool key ctrl+shift+v`
       - ydotool: `ydotool key 29:1 42:1 47:1 47:0 42:0 29:0` (Ctrl+Shift+V raw keycodes)
       - xdotool: `xdotool key --clearmodifiers ctrl+shift+v`
    4. If `getActiveWindowClass()` returns `null`, fall back to normal `Ctrl+V` (current behavior).
  - Notes: Window class detection adds ~50ms latency (subprocess call). This is acceptable given the existing 50ms sleep before paste.

#### P2 — Paste-at-Cursor Text Field Safety

- [x] **Task8: Add file manager blocklist**
  - File: `dashboard/electron/pasteAtCursor.ts`
  - Action: Add a constant `PASTE_SKIP_WINDOW_CLASSES` — a `Set<string>` of window classes where paste should be skipped entirely: `org.kde.dolphin`, `org.kde.plasmashell`, `org.gnome.nautilus`, `pcmanfm`, `thunar`, `nemo`, `caja`.
  - In `simulatePasteLinuxWayland()` and `simulatePasteLinuxX11()`: after calling `getActiveWindowClass()`, if `isPasteSkipWindow()` returns true, throw an `Error('Paste skipped — active window does not accept text input. Text has been copied to clipboard.')` instead of simulating the keystroke.
  - Notes: The error message is caught by `pasteAtCursor()` and surfaced to the caller. Clipboard still contains the text for manual paste.

#### P1 — Documentation

- [x] **Task9: Add Persistence Mode troubleshooting**
  - File: `README.md`
  - Action: In the troubleshooting section, add an entry:
    - **Title:** "GPU errors persist across container restarts"
    - **Symptom:** CUDA error 999 in server logs while `nvidia-smi` shows healthy GPU
    - **Solution:** Enable NVIDIA Persistence Mode on the host: `sudo nvidia-smi -pm 1`. This prevents the driver from entering a degraded state on container stop/start cycles.
    - **Alternative:** Reboot the host to fully reset driver state.

- [x] **Task10: Add "GPU stuck" troubleshooting entry**
  - File: `README.md`
  - Action: In the troubleshooting section, add an entry:
    - **Title:** "Dashboard shows GPU error / red status"
    - **Symptom:** Dashboard shows red error state with "GPU unavailable" message
    - **Steps:** (1) Restart computer to reset GPU driver state. (2) If frequent, enable Persistence Mode (`sudo nvidia-smi -pm 1`). (3) If persists after reboot, check server logs for CUDA diagnostic line (torch version, CUDA version, device nodes). (4) Advanced: `nvidia-smi --gpu-reset` (warning: affects all GPU consumers on the host). (5) Workaround: switch to CPU mode in Settings > Server.

#### Tests

- [x] **Task11: Backend test — health check retry**
  - File: `server/backend/tests/test_audio_utils.py`
  - Action: Add tests to the existing `cuda_health_check` test class:
    1. `test_cuda_health_check_retries_transient_non_999_error`: Mock `torch.cuda.init()` to raise `RuntimeError("some transient error")` on first call, succeed on second. Assert return value has `status: "healthy"` and `retried: True`.
    2. `test_cuda_health_check_no_retry_on_error_999`: Mock `torch.cuda.init()` to raise `RuntimeError("unknown error (999)")`. Assert `_cuda_probe_failed` is set, no retry attempted (only one call to `torch.cuda.init`).
    3. `test_cuda_health_check_retry_also_fails`: Mock `torch.cuda.init()` to raise `RuntimeError("transient")` on both calls. Assert return value has `status: "no_cuda"`.
  - Notes: Use `unittest.mock.patch` on `torch.cuda.init` and `time.sleep`. Verify `time.sleep` called with `0.5` on retry path.

- [x] **Task12: Backend test — gpu_error in status response**
  - File: `server/backend/tests/test_health_routes.py`
  - Action: Add test `test_status_includes_gpu_error_when_set`:
    1. Set `test_client_local.app.state.gpu_error = {"error": "CUDA unknown error", "status": "unrecoverable"}`
    2. GET `/api/status`
    3. Assert response contains `gpu_error` field with the error string and `gpu_error_action` field with reboot instruction.
  - Also add `test_status_no_gpu_error_when_healthy`: Verify `gpu_error` is NOT in response when `app.state.gpu_error` is not set.

- [x] **Task13: Frontend test — deriveStatus with GPU error**
  - File: `dashboard/src/hooks/useServerStatus.test.ts` (new file)
  - Action: Create test file testing the `deriveStatus` function. To test it, either export `deriveStatus` or test via the hook using `renderHook` with a mocked `apiClient.checkConnection`.
  - Test cases:
    1. `returns error state when gpu_error present`: Mock `checkConnection` to return `{ reachable: true, ready: false, status: { gpu_error: "CUDA error", gpu_error_action: "Restart" }, error: null }`. Assert `serverStatus === 'error'`, `serverLabel` contains action text, `gpuError` is truthy.
    2. `returns warning when not ready and no gpu_error`: Mock `checkConnection` to return `{ reachable: true, ready: false, status: {}, error: null }`. Assert `serverStatus === 'warning'`.
    3. `returns active when ready even if gpu_error present` → actually this shouldn't happen (if GPU failed, model can't be ready). But test that `gpu_error` + `ready: true` still returns `'error'` (error takes priority).
    4. `returns inactive when not reachable`: Assert `serverStatus === 'inactive'`.
  - Notes: Follow existing test patterns in `dashboard/src/`. Use `vi.fn()` for mocking. May need to export `deriveStatus` as a named export for direct testing.

### Acceptance Criteria

#### P0 — GPU Error Surfacing

- [x] **AC1:** Given the server is configured for GPU mode and CUDA health check returns `"unrecoverable"`, when the dashboard polls `/api/status` and receives a response with `gpu_error` set, then `useServerStatus` derives `serverStatus: 'error'` (not `'warning'` or `'active'`).

- [x] **AC2:** Given the server has a GPU error, when the user views the Session tab, then a red error banner is visible with the text "GPU unavailable — restart your computer to reset the GPU driver, or switch to CPU mode in Settings > Server."

- [x] **AC3:** Given the server has a GPU error, when the user views the Sidebar, then the Session and Server status dots show red (error state), not green.

- [x] **AC4:** Given the server has no model selected (but no GPU error), when the dashboard polls, then `serverStatus` is `'warning'` with "Models loading…" label (not `'error'`). GPU-failure error is distinct from other no-model states.

- [x] **AC5:** Given the server is healthy with models loaded and no GPU error, when the dashboard polls, then `serverStatus` is `'active'` with "Server ready" label. No regression in the happy path.

#### P1 — CUDA Diagnostics

- [x] **AC6:** Given torch is installed, when `cuda_health_check()` runs, then a single structured log line is emitted BEFORE the CUDA init attempt containing: `torch.__version__`, `torch.version.cuda`, list of `/dev/nvidia*` device nodes, and driver version string.

- [x] **AC7:** Given `torch.cuda.init()` raises a non-999 `RuntimeError`, when `cuda_health_check()` handles the error, then it sleeps 500ms and retries once. If retry succeeds, returns `{"status": "healthy", "retried": true, ...}`.

- [x] **AC8:** Given `torch.cuda.init()` raises `RuntimeError` with "unknown error" or "error 999", when `cuda_health_check()` handles the error, then it does NOT retry — immediately sets `_cuda_probe_failed = True` and returns `{"status": "unrecoverable", ...}`.

#### P1 — Paste-at-Cursor

- [x] **AC9:** Given the user is focused on a terminal emulator (e.g. Konsole, Kitty, Alacritty) on Linux, when paste-at-cursor fires, then `Shift+Ctrl+V` is sent instead of `Ctrl+V`, and the transcribed text appears in the terminal.

- [x] **AC10:** Given the user is focused on a non-terminal application on Linux, when paste-at-cursor fires, then `Ctrl+V` is sent (unchanged behavior). No regression for normal paste.

- [x] **AC11:** Given the user is on macOS or Windows, when paste-at-cursor fires, then behavior is completely unchanged. Terminal detection is Linux-only.

- [x] **AC12:** Given the active window class cannot be determined (unsupported Wayland compositor, tool not installed), when paste-at-cursor fires, then it falls back to `Ctrl+V` (current behavior). No error thrown.

#### P2 — File Manager Safety

- [x] **AC13:** Given the user is focused on a file manager (Dolphin, Nautilus, Thunar), when paste-at-cursor fires, then the paste is skipped and an error is returned indicating text was copied to clipboard for manual paste.

#### Documentation

- [x] **AC14:** Given the README troubleshooting section, when a user searches for GPU/CUDA issues, then entries for "GPU errors persist across container restarts" and "Dashboard shows GPU error / red status" are present with step-by-step solutions.

## Additional Context

### Dependencies

- No new package dependencies required for backend or frontend
- Terminal detection uses existing system tools: `xdotool` (X11), `gdbus` (KDE Wayland D-Bus), `wtype`/`dotool`/`ydotool` (keystroke simulation)
- Python stdlib additions: `glob` (device node enumeration), `time` (retry sleep) — both already available
- `StatusLight` component already supports `'error'` state (red) — no component changes needed
- `ServerStatus` type already includes `gpu_error` and `gpu_error_action` fields — no type changes needed

### Testing Strategy

**Backend (pytest):**
- Health check retry: mock `torch.cuda.init()` side effects (fail-then-succeed, fail-fail, 999-no-retry)
- Diagnostic logging: mock torch version attributes and subprocess, verify log output
- Status endpoint: set `app.state.gpu_error` on test client, verify response fields
- All tests in existing files — no new conftest changes needed

**Frontend (Vitest):**
- New `useServerStatus.test.ts`: test `deriveStatus()` with various `checkConnection` return values
- Export `deriveStatus` as named export for direct unit testing (currently module-private)
- Mock `apiClient.checkConnection` via `vi.fn()`
- Test cases: gpu_error → error, no gpu_error + not ready → warning, ready → active, unreachable → inactive

**Manual testing:**
- Paste-at-cursor: test on Konsole, Kitty, Alacritty (terminal), Firefox/Chrome (non-terminal), Dolphin (file manager skip)
- GPU error: simulate by setting `app.state.gpu_error` via admin endpoint or by temporarily forcing `cuda_health_check()` to return unrecoverable

### Notes

- **Root cause confirmed**: CUDA error 999 was driver context poisoning from prior container crash. Reboot fixed it. Same venv, same torch, same Docker config. Full writeup in `_bmad-output/brainstorming/brainstorming-session-2026-03-26-cuda-rca.md`.
- **Prior spec reference**: `tech-spec-gpu-crash-resilience.md` implemented the CUDA health probe + crash-safe sentinel. This spec builds on that by fixing the incomplete error surfacing and adding diagnostics.
- **VRAM observation**: Boot 3 showed VRAM dropped to 1457 MiB with no processes, yet CUDA still failed — confirms structural driver issue, not memory exhaustion.
- **Separate PRs recommended**: GPU error surfacing (Tasks 1-3, 11-13) and paste-at-cursor (Tasks 6-8) share zero code. Ship as independent PRs for cleaner review.
- **`deriveStatus` export change**: Task 13 requires exporting `deriveStatus` from `useServerStatus.ts`. It's currently a module-private function. Exporting it is a minor API surface change but enables direct unit testing without `renderHook` overhead.
- **KDE Wayland D-Bus specifics**: The `org.kde.KWin.activeWindow` method returns a QVariantMap. The `resourceClass` key contains the window class (e.g. `"konsole"`). Parse it from the gdbus output string. On non-KDE Wayland compositors (sway, GNOME), this D-Bus call will fail — handle gracefully by returning `null`.
