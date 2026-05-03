---
title: 'Auto Watch Folder forgets enabled state on app restart'
type: 'bugfix'
created: '2026-04-26'
status: 'done'
baseline_commit: '5f03650e765d9ec93a46254ca3e982a62340cbb9'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** When a user enables Auto Watch on a Sessions or Notebook folder and quits, the toggle is silently OFF on next launch — the path is restored from `folderWatch.sessionPath` / `folderWatch.notebookPath`, but `sessionWatchActive` / `notebookWatchActive` are intentionally ephemeral (`useSessionWatcher.ts:27`). Reported on Issue #100 (macOS 15.7.3, v1.3.3); reproducible on every platform. Half the state persists, half does not — users perceive this as the app forgetting their setting.

**Approach:** Persist the active flag for each watcher (`folderWatch.sessionWatchActive`, `folderWatch.notebookWatchActive`) using the existing `getConfig`/`setConfig` pair. Wrap the raw zustand setter inside each watcher hook (mirror of the existing `setWatchPath` callback at `useSessionWatcher.ts:86`) so every state change — UI toggle, auto-disable on start failure, auto-disable on path change — also writes to disk. Extend the on-mount load `useEffect` to read both keys via `Promise.all` and re-arm only when both are truthy. **This deliberately overrides the original Folder Watch tech spec and Issue #93's "toggles remain ephemeral" boundary, but only for the active flag — not for the four import toggles from #93.**

## Boundaries & Constraints

**Always:**
- Two new electron-store keys: `folderWatch.sessionWatchActive`, `folderWatch.notebookWatchActive` (booleans). Mirror the existing `*.Path` keys exactly.
- Auto-disable paths (start-failure on line 46, path-change on line 89) MUST also persist `false` — otherwise a broken folder re-arm-loops every launch.
- Hydrate via `Promise.all` so the start-effect (`:35-54`) sees both path and active flag together — never path-only or active-only.
- Re-arm only when BOTH the saved path AND saved active flag are truthy; first-launch users still see OFF.
- Existing accessibility-poll guard (`:57-83`) still gates the watcher when the saved path is now inaccessible.

**Ask First:**
- If a confirmation prompt on startup ("Resume Auto Watch on /path?") is preferred over silent re-arm, surface the alternative — do not implement both.
- If electron-store has a typed schema rejecting unknown keys, surface the schema-update requirement before adding the new keys.

**Never:**
- Do not introduce a new IPC channel, preload contract, or main-process state — the existing electron-store renderer bridge is sufficient.
- Do not change `watcherManager` (main process) or `useWatcherFilesBridge` (Issue #94 singleton).
- Do not persist any of the four import toggles introduced by Issue #93 (`enableDiarization`, `enableWordTimestamps`, `parallelDiarization`, `multitrack`) — that boundary is unchanged; this fix is scoped to the active flag only.
- Do not change the per-tab toggle defaults in `importQueueStore.ts` (`sessionWatchActive: false`, `notebookWatchActive: false`).

</frozen-after-approval>

## Code Map

- `dashboard/src/hooks/useSessionWatcher.ts` — wrap `setSessionWatchActive` with persistence (mirror of `setWatchPath`); extend the on-mount `useEffect` (`:28-32`) to `Promise.all` both reads.
- `dashboard/src/hooks/useNotebookWatcher.ts` — symmetric change for the notebook side (`:28-32`, wrap `setNotebookWatchActive`).
- `dashboard/components/views/SessionImportTab.tsx` and `dashboard/components/views/NotebookView.tsx` — verify the `<AppleSwitch>` consumer pulls the wrapped setter from the hook return, not the raw zustand action from the store.
- `dashboard/src/hooks/__tests__/useSessionWatcher.test.tsx` _(new)_ — hydration, toggle-persistence, start-failure auto-disable.
- `dashboard/src/hooks/__tests__/useNotebookWatcher.test.tsx` _(new)_ — symmetric tests.
- `dashboard/src/config/store.ts` — reference only; existing API covers the new keys.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/hooks/useSessionWatcher.ts` — Replace the on-mount `useEffect` with a `Promise.all([getConfig<string>('folderWatch.sessionPath'), getConfig<boolean>('folderWatch.sessionWatchActive')])` that sets both pieces of state, gating active=true on both being truthy. Add a `useCallback` that wraps the raw zustand `setSessionWatchActive`: invokes the raw setter then `await setConfig('folderWatch.sessionWatchActive', active)`. Replace internal call sites (line 46 in the start-failure `.catch`, line 89 in `setWatchPath`) with the wrapped version. Return the wrapped setter under the same `setSessionWatchActive` key. Update the file-top docstring: replace "toggle is ALWAYS false on mount (ephemeral state)" with "toggle restored from persisted state on mount (Issue #100)".
- [x] `dashboard/src/hooks/useNotebookWatcher.ts` — Symmetric change against `folderWatch.notebookWatchActive`. Same docstring update.
- [x] `dashboard/src/hooks/__tests__/useSessionWatcher.test.tsx` _(new)_ — Use `renderHook` from `@testing-library/react`. `vi.mock` `../../config/store`. Cases: (a) both keys present → state becomes active=true after mount, `electronAPI.watcher.startSession` called once; (b) path present, active absent → state stays false, no start call; (c) toggle ON via wrapped setter → `setConfig('folderWatch.sessionWatchActive', true)` called once; (d) `startSession` rejects → wrapped setter called with `false` AND `setConfig` called with `false`; (e) `electronAPI` undefined → no crash, no calls.
- [x] `dashboard/src/hooks/__tests__/useNotebookWatcher.test.tsx` _(new)_ — Same five cases against `folderWatch.notebookWatchActive` and `electronAPI.watcher.startNotebook`.
- [x] `dashboard/components/views/SessionImportTab.tsx`, `dashboard/components/views/NotebookView.tsx` — Audit: any consumer using the raw store action instead of the hook-returned wrapper bypasses persistence. Switch them to the hook return.
- [x] `dashboard/electron/main.ts` — Add `'folderWatch.sessionWatchActive': false` and `'folderWatch.notebookWatchActive': false` to electron-store defaults so the new keys have explicit schema entries (parallel to the existing `*.Path` defaults at lines 462-463).

**Acceptance Criteria:**
- Given Sessions Auto Watch is ON for `/some/folder`, when the user quits and relaunches, then the toggle is ON, the path field shows `/some/folder`, and a new file dropped in appears as a `session-auto` job within ~2s without user input.
- Given Notebook Auto Watch is ON for a different folder, when the user relaunches, then notebook re-arms independently of session state.
- Given Auto Watch was OFF when quit, when relaunched, then it stays OFF and no watcher starts.
- Given Auto Watch was ON but the folder was deleted before relaunch, when the app re-arms and `startSession` rejects, then the wrapped setter writes `false` to disk so the next launch starts OFF — no infinite re-arm loop.
- Given the user changes the watch path while active, when the path changes, then the toggle goes OFF in both UI and persisted state — preserves the existing "path change resets active" behavior.
- Given a fresh install, when the app launches, then both toggles default OFF and no watcher starts.

## Spec Change Log

## Design Notes

**Design override — record for future reviewers.** The original Folder Watch tech spec and Issue #93's spec both stated "toggles remain ephemeral … prevents surprise auto-processing after restart." Issue #100 reverses that decision *for the active flag only* (not the four import toggles, which stay ephemeral). Half-persistence (path saved, flag not saved) was the actual root cause of user confusion — the app remembered what to watch but not whether to watch. The existing safety nets (accessibility polling, start-failure auto-disable, path-change reset) remain intact.

The wrap lives inside the hook, not the zustand store, because the hook already owns `setWatchPath` (path-change-and-persist). Splitting the persistence pattern (path in hook, active in store) would fragment the contract documented in the file-top docstring.

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` — passes (no new type errors).
- `cd dashboard && npm test -- useSessionWatcher useNotebookWatcher` — new tests pass; no regression on `useWatcherFilesBridge`.
- `cd dashboard && npm run ui:contract:check` — clean (no className changes).

**Manual checks:**
- Toggle Sessions Auto Watch ON, set folder, quit (Cmd+Q / Alt+F4 / KDE close), relaunch — verify toggle ON without user input. Drop an audio file → `session-auto` job appears.
- Repeat for Notebook tab independently.
- Toggle OFF, quit, relaunch — toggle stays OFF.
- Enable, quit, delete watched folder, relaunch — toggle auto-disables with the existing inline warning; the *next* launch starts OFF (no re-arm-fail loop).

## Suggested Review Order

**Persistence write path — the design entry point**

- The single sync wrapper that turns every active-flag transition into a paired in-memory + disk write. Errors logged, never propagated, so onChange / .catch consumers stay simple.
  [`useSessionWatcher.ts:30`](../../dashboard/src/hooks/useSessionWatcher.ts#L30)

- Symmetric mirror for the notebook side; intentional duplication so divergence (the cause of #93/#94) is visible at a glance.
  [`useNotebookWatcher.ts:32`](../../dashboard/src/hooks/useNotebookWatcher.ts#L32)

**Hydration read path — re-arming on launch**

- `Promise.all` reads both keys together; the start-effect (line 59-78 of the same file) sees them update in the same batch. Strict `=== true` check rejects `undefined`/`false`/`null` from the store.
  [`useSessionWatcher.ts:43`](../../dashboard/src/hooks/useSessionWatcher.ts#L43)

- Mirror for the notebook side.
  [`useNotebookWatcher.ts:45`](../../dashboard/src/hooks/useNotebookWatcher.ts#L45)

**Path-change ordering — closes a quit-mid-flow race (post-review patch)**

- `setWatchPath` now uses the raw zustand setter and persists active=false BEFORE the new path. Quit between writes never leaves disk in `{ active: true, path: <newPath> }`.
  [`useSessionWatcher.ts:110`](../../dashboard/src/hooks/useSessionWatcher.ts#L110)

- Mirror for the notebook side.
  [`useNotebookWatcher.ts:112`](../../dashboard/src/hooks/useNotebookWatcher.ts#L112)

**Defaults schema**

- Two new electron-store defaults, parallel to the existing `*.Path` defaults. New keys are explicit `false` so first-launch users get OFF, not `undefined`.
  [`main.ts:464`](../../dashboard/electron/main.ts#L464)

**Regression coverage**

- Six test cases cover: hydration with both keys, hydration with path-only, toggle persists, start-failure auto-disable persists `false`, path-change-while-active persists active=false BEFORE path (the post-review patch), and `electronAPI` undefined is a no-op.
  [`useSessionWatcher.test.tsx:48`](../../dashboard/src/hooks/__tests__/useSessionWatcher.test.tsx#L48)

- Symmetric six cases for the notebook side.
  [`useNotebookWatcher.test.tsx:47`](../../dashboard/src/hooks/__tests__/useNotebookWatcher.test.tsx#L47)
