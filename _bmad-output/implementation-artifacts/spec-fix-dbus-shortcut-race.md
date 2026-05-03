---
title: 'Fix D-Bus shortcut registration race causing ERR_STREAM_WRITE_AFTER_END crash'
type: 'bugfix'
created: '2026-04-02'
status: 'done'
baseline_commit: 'babd500'
context:
  - docs/README_DEV.md
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** Clicking "Save Changes" in the Settings modal crashes the Electron main process with an uncaught `ERR_STREAM_WRITE_AFTER_END`. The `handleSave` function sends both `shortcuts.startRecording` and `shortcuts.stopTranscribe` via `Promise.all`, and each triggers a fire-and-forget `registerShortcuts()` call. The second call's `initWaylandShortcuts()` disconnects the first call's still-connecting D-Bus bus, so when the first socket's `connect` event fires the auth handshake writes to an ended stream.

**Approach:** Serialize shortcut registration so concurrent calls coalesce into a single D-Bus session, and add a bus-level error handler so `@particle/dbus-next` socket errors are caught instead of crashing the process.

## Boundaries & Constraints

**Always:**
- The fix must be backward-compatible with X11 and non-Linux platforms (shortcut registration must still work everywhere).
- Existing Wayland portal functionality (Activated/ShortcutsChanged signals, ListShortcuts, rebindShortcuts) must keep working.
- The `bus` module-level variable must never be disconnected by a concurrent caller while a connection is in progress.

**Ask First:**
- Adding a `process.on('uncaughtException')` handler to `main.ts` as defense-in-depth (could mask unrelated bugs).

**Never:**
- Do not change the `@particle/dbus-next` library itself.
- Do not remove Wayland portal support or degrade it to a globalShortcut-only fallback.
- Do not change the `handleSave` `Promise.all` pattern in `SettingsModal.tsx` (it correctly batches unrelated config writes; the bug is in the receiver).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Normal save on Wayland | User clicks Save Changes (both shortcut keys written) | Shortcuts re-registered once; no crash | N/A |
| Rapid repeated saves | User clicks Save twice quickly | Second registration waits for first to finish or replaces it cleanly | No crash; last-write-wins |
| D-Bus session bus unavailable | Socket file missing or daemon not running | `initWaylandShortcuts` returns false; falls back to globalShortcut | Error logged, no crash dialog |
| D-Bus socket connects then immediately closes | Socket file exists but daemon resets connection | Bus error handler catches the write error; init returns false | Error logged, fallback to globalShortcut |
| Save on X11 / macOS / Windows | `isWayland()` returns false | D-Bus code never runs; globalShortcut path used | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/electron/main.ts:617-628` -- `config:set` IPC handler; fires `registerShortcuts` without await on `shortcuts.*` keys
- `dashboard/electron/shortcutManager.ts:46-105` -- `registerShortcuts()`; calls `unregisterShortcuts()` then `initWaylandShortcuts()`
- `dashboard/electron/waylandShortcuts.ts:137` -- shared `bus` module variable; root of the race
- `dashboard/electron/waylandShortcuts.ts:166-264` -- `initWaylandShortcuts()`; disconnects existing `bus` then creates new one
- `dashboard/components/views/SettingsModal.tsx:365-368` -- saves both `shortcuts.*` keys via `Promise.all`

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/shortcutManager.ts` -- Add a serialization guard to `registerShortcuts()`: if a registration is already in-flight, store the latest args and re-run once the current call completes (last-write-wins debounce). This ensures only one `initWaylandShortcuts` runs at a time.
- [x] `dashboard/electron/waylandShortcuts.ts` -- In `initWaylandShortcuts()`, immediately after `bus = dbus.sessionBus()`, attach `bus.on('error', handler)` to catch socket-level errors (including `ERR_STREAM_WRITE_AFTER_END`) and route them into the existing try/catch rejection path instead of letting them become uncaught exceptions.
- [x] `dashboard/electron/main.ts` -- In the `config:set` handler, debounce the `registerShortcuts` trigger: instead of calling it synchronously for each `shortcuts.*` key, schedule it with a short `setTimeout(0)` / microtask so multiple rapid `shortcuts.*` writes in the same tick coalesce into one call. This is a belt-and-suspenders complement to the serialization guard.

**Acceptance Criteria:**
- Given a Wayland session with a working D-Bus portal, when the user clicks Save Changes in Settings, then shortcuts are re-registered exactly once and no error dialog appears.
- Given a Wayland session where the D-Bus session bus is unavailable or resets, when `initWaylandShortcuts` is called, then the function returns `false` and logs a warning instead of crashing the process.
- Given an X11 or non-Linux environment, when the user clicks Save Changes, then D-Bus code is never invoked and shortcuts register via globalShortcut as before.

## Verification

**Commands:**
- `cd dashboard && npx tsc -p electron/tsconfig.json --noEmit` -- expected: no type errors
- `cd dashboard && npm run build:electron` -- expected: clean build

**Manual checks (if no CLI):**
- On a Wayland session, open Settings, change any setting, click Save Changes -- no crash dialog, shortcuts still work.
- On a machine without D-Bus (or with `DBUS_SESSION_BUS_ADDRESS` unset), launch the app -- falls back to globalShortcut, no crash.

## Suggested Review Order

**Serialization guard (primary fix)**

- Last-write-wins guard ensures only one D-Bus session runs at a time
  [`shortcutManager.ts:39`](../../dashboard/electron/shortcutManager.ts#L39)

- Inner implementation extracted to keep concurrency concern separate
  [`shortcutManager.ts:87`](../../dashboard/electron/shortcutManager.ts#L87)

**Bus resilience**

- Error handler catches socket-level crashes (ERR_STREAM_WRITE_AFTER_END)
  [`waylandShortcuts.ts:188`](../../dashboard/electron/waylandShortcuts.ts#L188)

- Null guard on bus in waitForResponse cleanup (review finding fix)
  [`waylandShortcuts.ts:324`](../../dashboard/electron/waylandShortcuts.ts#L324)

- Null guard on bus in AddMatch rejection handler (review finding fix)
  [`waylandShortcuts.ts:381`](../../dashboard/electron/waylandShortcuts.ts#L381)

**Call-site coalescing (belt-and-suspenders)**

- Microtask batching for rapid config:set IPC events
  [`main.ts:607`](../../dashboard/electron/main.ts#L607)
