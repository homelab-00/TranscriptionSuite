---
title: 'Reliable clipboard write on Wayland via verify-retry + wl-copy fallback'
type: 'bugfix'
created: '2026-04-08'
status: 'done'
baseline_commit: 'd984b1e'
context:
  - docs/project-context.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The "automatically copy transcription to clipboard" feature intermittently fails on Linux/KDE/Wayland. Electron's `clipboard.writeText()` silently drops writes when Chromium's Ozone Wayland backend lacks a valid input event serial (the focused-window requirement of `wl_data_device.set_selection`). No error is thrown — the write just doesn't happen.

**Approach:** Add a write-verify-retry loop in the Electron main process: after `clipboard.writeText()`, read back to confirm; on mismatch, retry once. If verification still fails, fall back to spawning `wl-copy` (which bypasses Chromium's serial requirement entirely). Keep the `wl-copy` child process alive to maintain Wayland clipboard ownership. Non-Wayland platforms use the existing path unchanged.

## Boundaries & Constraints

**Always:**
- Fix lives entirely in the Electron main process — no renderer changes
- Non-Wayland platforms (macOS, Windows, X11) keep current behavior, zero regression risk
- `wl-copy` process must be kept alive until the next clipboard write (Wayland ownership model)
- Previous `wl-copy` process must be killed before spawning a new one
- Log diagnostics at each stage (`console.info` for fallback activation, `console.warn` for failures)

**Ask First:**
- Whether to add `wl-clipboard` to the documented system dependencies / installation instructions
- Whether to surface a user-visible notification when clipboard write falls back to wl-copy

**Never:**
- Don't steal window focus (`BrowserWindow.focus()`) to generate a serial
- Don't change the renderer-side effect hook (`SessionView.tsx`) or `useClipboard.ts`
- Don't touch `pasteAtCursor.ts` paste-simulation logic (separate concern)
- Don't add npm dependencies — `wl-copy` is a system tool invoked via `child_process`

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path (Electron write succeeds) | `writeText("hello")` on Wayland, serial valid | Clipboard contains "hello", no fallback triggered | N/A |
| Verify fails, retry succeeds | First write drops silently, retry succeeds | Clipboard contains text after retry, log: "Clipboard retry succeeded" | N/A |
| Verify fails, wl-copy fallback | Both Electron writes fail verification | wl-copy spawned, text piped to stdin, process kept alive | Log: "Falling back to wl-copy" |
| wl-copy not installed | Fallback triggered but `which wl-copy` fails | Clipboard write fails, log warning with install hint | `console.warn` with actionable message |
| Rapid successive writes | Two transcriptions complete quickly | Previous wl-copy child killed before new one spawns | Kill previous via stored ChildProcess ref |
| Non-Wayland platform | Any clipboard write on macOS/Windows/X11 | Existing `clipboard.writeText()` used directly, no verify | N/A |
| pasteAtCursor path | `pasteAtCursor()` calls `clipboard.writeText()` internally | `pasteAtCursor.ts` uses new reliable write for its own clipboard.writeText() call | Falls through existing catch |

</frozen-after-approval>

## Code Map

- `dashboard/electron/clipboardWayland.ts` -- NEW: reliable clipboard write module with verify-retry + wl-copy fallback
- `dashboard/electron/main.ts:1195` -- IPC handler `clipboard:writeText` — update to use reliable write on Wayland
- `dashboard/electron/pasteAtCursor.ts:328` -- `clipboard.writeText(text)` call — update to use reliable write
- `dashboard/electron/shortcutManager.ts:25` -- existing `isWayland()` helper (reused, not modified)

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/clipboardWayland.ts` -- Create module exporting `reliableWriteText(text: string): Promise<void>` with verify-retry-fallback logic and `wl-copy` child process lifecycle management
- [x] `dashboard/electron/main.ts` -- Update `clipboard:writeText` IPC handler to call `reliableWriteText()` on Wayland, pass through to `clipboard.writeText()` on other platforms
- [x] `dashboard/electron/pasteAtCursor.ts` -- Replace `clipboard.writeText(text)` (line 328) with `await reliableWriteText(text)` so paste-at-cursor also gets reliable writes
- [x] `dashboard/electron/__tests__/clipboardWayland.test.ts` -- Unit tests: verify-pass, verify-fail-retry-pass, verify-fail-wl-copy-fallback, wl-copy-missing, rapid-successive-writes, non-Wayland-passthrough

**Acceptance Criteria:**
- Given Wayland session and autoCopy enabled, when transcription completes and Electron clipboard write succeeds verification, then text is in clipboard with no fallback logged
- Given Wayland session and Electron clipboard write silently fails, when readback detects mismatch, then retry is attempted and if still fails, wl-copy fallback is used
- Given wl-copy is not installed, when fallback is triggered, then a descriptive warning is logged and no crash occurs
- Given two clipboard writes in rapid succession, when second write starts, then previous wl-copy child process (if any) is killed before spawning new one
- Given non-Wayland platform, when clipboard write occurs, then existing direct path is used with no verify overhead

## Design Notes

The `wl-copy` fallback follows the pattern proven by espanso (PR #2654): the child process must remain alive because Wayland clipboard ownership requires the source process to serve paste requests. Store the `ChildProcess` reference in module state; kill it on next write or on app quit. Pipe text to `wl-copy` via stdin (not CLI arg) to handle arbitrarily long transcriptions. Close stdin after writing to signal EOF, but do not kill the process.

The verify step uses `clipboard.readText()` which is synchronous in Electron's main process. On Wayland this can occasionally block briefly if a clipboard manager is unresponsive — wrap in a 500ms timeout via `Promise.race` with a setTimeout rejection to prevent hangs.

## Verification

**Commands:**
- `cd dashboard && npx vitest run electron/__tests__/clipboardWayland.test.ts` -- expected: all tests pass
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors

## Suggested Review Order

**Core: verify-retry-fallback logic**

- Entry point — the full write→verify→retry→wl-copy fallback chain
  [`clipboardWayland.ts:103`](../../dashboard/electron/clipboardWayland.ts#L103)

- wl-copy child process lifecycle with error guards and ownership tracking
  [`clipboardWayland.ts:78`](../../dashboard/electron/clipboardWayland.ts#L78)

- Synchronous readback helper with try/catch for Ozone backend exceptions
  [`clipboardWayland.ts:40`](../../dashboard/electron/clipboardWayland.ts#L40)

**Integration: IPC and paste-at-cursor**

- IPC handler now async, routes through reliableWriteText
  [`main.ts:1197`](../../dashboard/electron/main.ts#L1197)

- will-quit cleanup kills lingering wl-copy child
  [`main.ts:1193`](../../dashboard/electron/main.ts#L1193)

- pasteAtCursor uses reliable write for text, direct write for restore
  [`pasteAtCursor.ts:329`](../../dashboard/electron/pasteAtCursor.ts#L329)

**Tests**

- 7 scenarios: happy path, retry, wl-copy fallback, missing tool, rapid writes, non-Wayland
  [`clipboardWayland.test.ts:81`](../../dashboard/electron/__tests__/clipboardWayland.test.ts#L81)

- Existing pasteAtCursor tests mock clipboardWayland.js to preserve isolation
  [`pasteAtCursor.test.ts:44`](../../dashboard/electron/__tests__/pasteAtCursor.test.ts#L44)
