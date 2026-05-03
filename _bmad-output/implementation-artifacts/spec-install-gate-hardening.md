---
title: 'Install-gate hardening: socket rearm + sync throw-safety + bootstrap diagnostic'
type: 'bugfix'
created: '2026-04-14'
status: 'done'
baseline_commit: '31080a1'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Three cousin bugs orbit `APIClient.syncFromConfig()` and its bootstrap/resync call chain:
(1) `TranscriptionSocket.doReconnect()` dead-ends on `!isBaseUrlConfigured()` — sets state=error + fires `onError`, then never retries. If the user fixes Settings mid-session, the socket stays dead.
(2) `syncFromConfig()` calls `getServerBaseUrl()` → `getConfig()` → preload bridge with no try/catch. An IPC rejection at any of its four call sites (`App.tsx:239`, `SessionView.tsx:507,534`, `SettingsModal.tsx:456`) propagates as an unhandled rejection and leaves `synced=false` permanently.
(3) With `useRemote=true` + blank host already persisted from a prior session, nothing at bootstrap tells the operator the config is unusable; the user sees an opaque "offline" state without a diagnostic.

**Approach:** Make `APIClient` a minimal event source with a `config-changed` event. Wrap `syncFromConfig()` internally in try/catch; on success or failure, always emit `config-changed` so subscribers re-check gate state. `useTranscription` and `useLiveMode` subscribe and, when their socket is in `error` state, call `socket.connect()` to rearm. `initApiClient()` emits a single bootstrap diagnostic when post-sync `!isBaseUrlConfigured()`.

## Boundaries & Constraints

**Always:** `syncFromConfig()` must not throw to callers under any config-read failure. `synced` stays `false` on throw so existing `isBaseUrlConfigured()` gating stays closed. The `config-changed` event fires on both success and failure paths so consumers re-evaluate, not just on success.

**Ask First:** Whether to expose a `rearm()` public method on `TranscriptionSocket` as an alternative to hook-side subscription. (Current plan: hook-side only — simpler, per-session scope.)

**Never:** Introduce a blocking first-run dialog. Don't make `getServerBaseUrl` throw on blank-remote — the `http://:<port>` loud-fail shape is already correct and consumed correctly by `isBaseUrlConfigured()`. Don't convert `apiClient` from singleton to per-session. Don't retry in the socket layer on its own — rearm is externally triggered by the config event.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy sync | valid host, IPC OK | `synced=true`, `config-changed` fires once, subscribers notified | N/A |
| IPC rejection mid-sync | preload throws | `synced=false`, console.warn with narrowed err, `config-changed` still fires | caught internally |
| Blank-remote persisted on launch | `useRemote=true`, blank host | baseUrl=`http://:<port>`, `synced=true`, `isBaseUrlConfigured()=false`, one bootstrap diagnostic logged | N/A (expected state) |
| WS in error state, user fixes Settings | socket state=`error`, new config saved | `config-changed` event → hook calls `socket.connect()` → new connect attempt | if connect fails again, normal scheduleReconnect resumes |
| WS in `connected` state, config re-sync fires | socket OK, syncFromConfig called | event fires but hook's error-only guard skips rearm | no-op |

</frozen-after-approval>

## Code Map

- `dashboard/src/api/client.ts` -- `APIClient`: add EventTarget-compatible emitter (`addEventListener` / `removeEventListener` / private `emit`), wrap `syncFromConfig()` in try/catch, emit `'config-changed'` on both paths
- `dashboard/src/api/client.ts` -- `initApiClient()`: after `syncFromConfig()`, log one bootstrap diagnostic when `!apiClient.isBaseUrlConfigured()` AND `useRemote=true`
- `dashboard/src/services/websocket.ts` -- no changes; existing `connect()` / `getState()` / `error` state is the rearm entry point
- `dashboard/src/hooks/useTranscription.ts` -- subscribe to `'config-changed'` in the session-lifecycle `useEffect`; on event, if `socketRef.current?.getState() === 'error'`, call `socketRef.current.connect()`
- `dashboard/src/hooks/useLiveMode.ts` -- same subscription pattern as `useTranscription`
- `dashboard/src/api/client.test.ts` -- tests: (a) event fires on sync success, (b) event fires on sync throw, (c) `syncFromConfig()` does not throw when underlying `getServerBaseUrl` rejects, (d) bootstrap diagnostic logs exactly once for blank-remote persisted state
- `dashboard/src/hooks/useTranscription.test.ts` or a new `useTranscription.rearm.test.ts` -- if existing test file shape permits, else create minimal behavioral test that the socket's `connect()` is called on `config-changed` when state is error
- `dashboard/src/hooks/useLiveMode.test.ts` -- same rearm coverage

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/services/websocket.ts` -- add public `getState(): ConnectionState` (minor addition not anticipated at plan time; required because the rearm listener reads socket state from outside the class).
- [x] `dashboard/src/api/client.ts` -- extend `APIClient` with `onConfigChanged(listener)` returning an unsubscribe function; private `emitConfigChanged()` iterates listeners with per-call try/catch so one throwing listener doesn't skip siblings.
- [x] `dashboard/src/api/client.ts` -- wrap `syncFromConfig()` body in try/catch. On throw: narrowed console.warn, `synced` stays false. `emitConfigChanged()` fires on both paths.
- [x] `dashboard/src/api/client.ts` -- `initApiClient()` now logs the bootstrap diagnostic when post-sync `!isBaseUrlConfigured()`. `getAuthToken()` call was also wrapped (uses same IPC bridge; discovered via test).
- [x] `dashboard/src/hooks/useTranscription.ts` -- dedicated `useEffect` subscribes via `apiClient.onConfigChanged`; handler calls `socket.connect()` only when `socket.getState() === 'error'`.
- [x] `dashboard/src/hooks/useLiveMode.ts` -- same pattern.
- [x] `dashboard/src/api/client.test.ts` -- added 8 new tests across two describe blocks (throw-safety, event semantics, bootstrap diagnostic).
- [x] Hook rearm tests -- 3 new tests in each of `useTranscription.test.ts` and `useLiveMode.test.ts` covering error-only rearm, healthy-state no-op, and unsubscribe/null-socket edges.

**Acceptance Criteria:**
- Given `useRemote=true` + blank host on launch, when `initApiClient()` runs, then exactly one `[APIClient] bootstrap:` diagnostic appears in the console and `isBaseUrlConfigured()` returns false.
- Given `getConfig` rejects inside `syncFromConfig`, when the promise settles, then `syncFromConfig()` resolves (does not throw), `synced` is false, and one `config-changed` event fired.
- Given a `TranscriptionSocket` in `error` state from a previous `doReconnect` dead-end, when the user saves a valid remote host in Settings, then the hook's `config-changed` listener fires and `socket.connect()` is invoked.
- Given a `TranscriptionSocket` in `connected` state, when `config-changed` fires, then `socket.connect()` is NOT called (no churn).

## Spec Change Log

### 2026-04-14 — Review patches (specLoopIteration=1, no loopback)

**Findings triggering patch:**
- Blind hunter MEDIUM: rearm called `socket.connect()` on `state === 'error'` without re-checking `isBaseUrlConfigured()`. On IPC-throw (synced=false), this triggered a redundant connect that immediately re-entered `error` via the `getWsUrl()` null-guard.
- Edge-case hunter EC-6 MEDIUM: `emitConfigChanged` iterated the live `Set`; a listener that unsubscribes a not-yet-visited sibling silently dropped that sibling for the current emit cycle.
- Blind hunter LOW: `expect(true).toBe(true)` vacuous assertion in the null-socketRef test.

**Amended (outside frozen-after-approval):**
- Hooks: rearm condition is now `socket.getState() === 'error' && apiClient.isBaseUrlConfigured()` in both `useTranscription` and `useLiveMode`.
- `client.ts::emitConfigChanged()`: iterate over `[...this.configChangedListeners]` snapshot.
- `useLiveMode.test.ts`: replaced vacuous assertion with `result.current.status === 'idle'`; added new test "does NOT rearm when the gate is still closed".
- `useTranscription.test.ts`: extended `apiClient` mock with `isBaseUrlConfigured` controlled by a `mockGateConfigured` flag; added new test "does NOT rearm when the gate is still closed".

**Known-bad state avoided:** Without the gate re-check, every IPC-bridge failure that fires `config-changed` would produce a redundant `connect()` → immediate re-error → log churn cycle.

**KEEP:** The "emit on both success AND failure paths" semantic must survive — subscribers re-evaluate predicate state, not trust the event means success. The rearm-only-on-`error` discipline (no `disconnected` rearm) prevents reconnect churn in healthy sessions.

**Findings deferred (not this story's problem):** EC-2 (config-change during `ready` silently retargets future reconnects) and EC-3 (up to 30s rearm blind spot during reconnect backoff) — both appended to deferred-work.md with concrete defense shapes.

## Design Notes

**Why EventTarget (or equivalent) over a callback prop:** Two independent hooks subscribe; a prop-based callback would force one hook to know about the other. Event bus keeps them decoupled. `addEventListener` is the standard DOM API already available in the renderer; zero new dependencies.

**Why emit on both success AND failure paths:** A sync that resolved to a blank-remote URL (`http://:<port>`) is semantically "config-changed" even though it's not "config-valid." Subscribers must re-check predicate state, not trust the event means success.

**Why the rearm guard is `state === 'error'`:** Avoids reconnect churn in healthy sessions. If the socket is already connecting, connected, or disconnecting, a fresh `connect()` would at best be wasted effort, at worst break mid-flight state. `error` is the only state where the socket has voluntarily stopped retrying.

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` -- expected: exit 0
- `cd dashboard && npx vitest run src/api/client.test.ts src/hooks/useTranscription.test.ts src/hooks/useLiveMode.test.ts` -- expected: all green, new tests present
- `cd dashboard && npm run ui:contract:check` -- expected: no contract drift (no className changes)

**Manual checks:**
- Launch app with `useRemote=true` + blank `remoteHost` persisted in config. Confirm one bootstrap diagnostic logs. Confirm offline banner shows. Save a valid host. Confirm no stale blank-host probe fires; REST calls unblock.
- Start a live session against an unreachable host until socket enters `error` state. Change host in Settings. Confirm the socket reconnects without needing a session restart.
