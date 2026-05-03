---
title: 'Folder Watch imports each file twice once both tabs are visited'
type: 'bugfix'
created: '2026-04-26'
status: 'done'
baseline_commit: 'f64e471'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Folder Watch enqueues each newly-detected audio file twice in the Notebook (and Sessions) import queue once both tabs have been visited in the same session. Reported on Issue #94 (macOS 15.7.5, v1.3.3) as "Newly added items in the folder are imported twice (tested in Notebook)". Root cause: `electronAPI.watcher.onFilesDetected(handleFilesDetected)` is called from BOTH `useSessionWatcher` (mounted inside `SessionImportTab`) AND `useNotebookWatcher` (mounted inside `NotebookView`). The preload's `onFilesDetected` registers a fresh `ipcRenderer.on('watcher:filesDetected', …)` per call, and `SessionView` is intentionally never unmounted (`App.tsx:760-763` "stays mounted to preserve WebSocket/audio state"), so once the user opens Sessions → Import then switches to Notebook, two listeners coexist on the same channel and the store's `handleFilesDetected` runs twice per IPC dispatch — `addFiles(...)` enqueues the file twice.

**Approach:** Move the `watcher:filesDetected` IPC subscription into a single app-level hook `useWatcherFilesBridge` that registers exactly one listener on mount. Call it once from `App.tsx` near the existing app-singleton hooks (`useAuthTokenSync`, `useBootstrapDownloads`). Remove the now-redundant subscription `useEffect` from both `useSessionWatcher` and `useNotebookWatcher`; those hooks remain responsible only for path persistence, start/stop control, and accessibility polling — not for the IPC bridge.

## Boundaries & Constraints

**Always:**
- Preserve `handleFilesDetected`'s existing behavior, including the `payload.type` routing, the `watcherServerConnected` offline guard, and the per-tab config sourcing introduced for Issue #93. The bridge wires the IPC event into the same store action — no signature or behavior changes.
- Continue using the existing `electronAPI.watcher.onFilesDetected` preload contract; the cleanup function it returns must still be invoked on unmount.
- Maintain the existing `watcher:filesDetected` IPC channel name and payload shape — no preload, main-process, or renderer-API contract changes.

**Ask First:**
- If the bridge cannot be mounted in `AppInner` for some structural reason (e.g., it must mount before `electronAPI` is exposed), surface the constraint instead of inventing a different singleton mechanism (e.g., subscribing inside the zustand store's create callback).

**Never:**
- Do not add idempotency/dedupe logic inside `handleFilesDetected` (e.g., file-path TTL set) as a workaround. The fix targets the actual cause: duplicate listener registration.
- Do not unmount or alter `SessionView`'s always-mounted strategy — that exists for unrelated WebSocket/audio reasons.
- Do not change the watcher manager's chokidar/ledger/fingerprint logic — those layers already dedupe correctly; the duplicate is purely a renderer-side fan-out.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Notebook watch active, user previously visited Sessions/Import | One file dropped into notebook watch folder | Exactly one `addFiles([path], 'notebook-auto', …)` call → exactly one queued job | N/A |
| Session watch active, user is on Sessions/Import (no Notebook visit yet) | One file dropped into session watch folder | Exactly one `addFiles([path], 'session-auto', …)` call → exactly one queued job | N/A |
| User has never opened the Notebook tab; only Sessions/Import is mounted | Session watch fires | Bridge is mounted at app root → listener exists → exactly one job | N/A |
| User has never opened the Sessions/Import tab; only Notebook is mounted | Notebook watch fires | Bridge is mounted at app root → listener exists → exactly one job | N/A |
| App reloads (HMR or full reload) while bridge is mounted | Old bridge unmounts, new bridge mounts | `removeListener` invoked on old handler, single `on` call for new handler | N/A |
| `electronAPI.watcher` undefined (browser dev mode) | Bridge mounts in non-Electron runtime | Hook returns early; no listener; no crash | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/src/hooks/useWatcherFilesBridge.ts` _(new)_ — singleton hook that subscribes to `electronAPI.watcher.onFilesDetected` and forwards events to `useImportQueueStore.handleFilesDetected`.
- `dashboard/App.tsx` — call `useWatcherFilesBridge()` once in `AppInner`, alongside `useAuthTokenSync` / `useBootstrapDownloads`.
- `dashboard/src/hooks/useSessionWatcher.ts` — delete the listener-registration `useEffect` (`lines 33-38`); keep path persistence, start/stop, and accessibility polling.
- `dashboard/src/hooks/useNotebookWatcher.ts` — delete the listener-registration `useEffect` (`lines 34-39`); keep path persistence, start/stop, and accessibility polling.
- `dashboard/src/hooks/__tests__/useWatcherFilesBridge.test.tsx` _(new)_ — verifies one mount = one IPC subscription, cleanup removes the listener, missing `electronAPI` is a no-op, and dispatched events reach `handleFilesDetected` exactly once.
- `dashboard/src/stores/importQueueStore.ts` — reference only; no changes expected.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/hooks/useWatcherFilesBridge.ts` — Create the new hook. Subscribe via `electronAPI.watcher.onFilesDetected(handleFilesDetected)` in a single `useEffect` keyed on the (stable) zustand action reference. Return the cleanup function. Guard the missing-`electronAPI` case so non-Electron runtimes (Vite preview, jsdom tests) do not crash. Rationale: app-level singleton is the only place that survives `SessionView`'s always-mounted strategy without doubling up.
- [x] `dashboard/App.tsx` — Import `useWatcherFilesBridge` and call it once inside `AppInner`, near `useAuthTokenSync(...)` and `useBootstrapDownloads()` (around line 108-110). Rationale: app-singleton concern belongs with other app-singleton concerns.
- [x] `dashboard/src/hooks/useSessionWatcher.ts` — Remove the `useEffect` that registers `electronAPI.watcher.onFilesDetected` (lines 33-38) and delete the now-unused `handleFilesDetected` selector. Keep all other behavior. Rationale: per-tab hook should not own a global IPC subscription.
- [x] `dashboard/src/hooks/useNotebookWatcher.ts` — Same removal as the session hook (lines 34-39 and the unused `handleFilesDetected` selector). Rationale: same reason; eliminates the second listener.
- [x] `dashboard/src/hooks/__tests__/useWatcherFilesBridge.test.tsx` — New unit tests using `@testing-library/react`'s `renderHook`: (a) mount → exactly one `ipcRenderer.on`-equivalent registration; (b) unmount → cleanup invoked; (c) `window.electronAPI` undefined → no crash, no registration; (d) dispatched payload reaches `handleFilesDetected` exactly once even when the hook is mounted alongside `useSessionWatcher` and `useNotebookWatcher` simulated as parallel renders. Use `vi.fn()` to stub `electronAPI.watcher.onFilesDetected` and assert call counts.

**Acceptance Criteria:**
- Given a user has visited Sessions → Import then switched to Notebook, when a single audio file is detected by the notebook watcher, then `useImportQueueStore.getState().jobs` gains exactly one `notebook-auto` job (not two).
- Given a session watch is active and the user has never visited the Notebook tab, when a single audio file is detected, then exactly one `session-auto` job is queued.
- Given the app starts in a non-Electron runtime where `window.electronAPI` is undefined, when components render, then `useWatcherFilesBridge` does not throw and registers no listener.
- Given the bridge unmounts (e.g., HMR), when it remounts, then the prior listener is removed and exactly one new listener is registered.

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` — expected: passes (no new type errors).
- `cd dashboard && npm test -- useWatcherFilesBridge importQueueStore` — expected: new bridge tests pass; existing `handleFilesDetected` tests still pass.
- `cd dashboard && npm run ui:contract:check` — expected: no UI-contract drift (this fix touches no className).

**Manual checks:**
- With server running, set a Notebook watch path, enable the toggle, drop an audio file → exactly one row appears in the notebook calendar (not two), and the import queue panel shows exactly one job.
- Repeat the above after first opening Sessions → Import then switching to Notebook (the original repro path) → still exactly one job.
- With Sessions → Import open and a Sessions watch enabled, drop an audio file → exactly one `.srt`/`.ass` is written to the output directory (not two).

## Suggested Review Order

**The fix — singleton IPC subscription**

- Bug-fix entry point. The new app-singleton hook owning the `watcher:filesDetected` subscription, replacing two redundant per-tab subscriptions.
  [`useWatcherFilesBridge.ts:26`](../../dashboard/src/hooks/useWatcherFilesBridge.ts#L26)

- App-root mount alongside other singletons (`useAuthTokenSync`, `useBootstrapDownloads`) so the listener cannot be doubled by tab-level lifecycle.
  [`App.tsx:115`](../../dashboard/App.tsx#L115)

**Removal of the duplicate listener**

- `useSessionWatcher` no longer touches `watcher:filesDetected`; only owns path persistence, start/stop, and accessibility polling.
  [`useSessionWatcher.ts:18`](../../dashboard/src/hooks/useSessionWatcher.ts#L18)

- Same simplification for the Notebook side.
  [`useNotebookWatcher.ts:18`](../../dashboard/src/hooks/useNotebookWatcher.ts#L18)

**Tests**

- Regression coverage for the singleton invariant: one mount = one IPC registration, cleanup on unmount, and exactly-one forwarding to the store action.
  [`useWatcherFilesBridge.test.tsx:53`](../../dashboard/src/hooks/__tests__/useWatcherFilesBridge.test.tsx#L53)
