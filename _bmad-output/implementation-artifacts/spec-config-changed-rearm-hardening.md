---
title: 'Harden config-changed socket rearm (EC-2 + EC-3)'
type: 'bugfix'
created: '2026-04-18'
status: 'done'
baseline_commit: '5b82e6b19bb3f3507551b23a39a2c41857fdea65'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/dashboard/src/services/websocket.ts'
  - '{project-root}/_bmad-output/implementation-artifacts/deferred-work.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The `config-changed` rearm listener in `useTranscription` / `useLiveMode` only reacts when the socket is in `error`. Two adjacent states are left silently broken: (EC-3) `disconnected` with a pending reconnect backoff timer causes up to 30 s of unexplained delay before the reconnect finally fires against the new host; (EC-2) an active socket in `connecting`/`authenticating`/`ready` continues talking to the OLD host while `apiClient.baseUrl` has mutated to the NEW one, so any future natural reconnect (server bounce, network blip) silently retargets with no log breadcrumb.

**Approach:** Add a single public method `TranscriptionSocket.handleConfigChanged(configured)` that branches on state: `error` → existing `connect()` rearm; `disconnected` with pending reconnect timer → cancel backoff and fire `doReconnect()` immediately; any active state with a URL mismatch → emit a `warning`-level `logClientEvent` breadcrumb. Both hooks replace their inline rearm with a single call to that method.

## Boundaries & Constraints

**Always:**
- Existing rearm contract is preserved: `error` + configured gate → `connect()` (unchanged).
- Warn-only path does NOT drop the active socket or force a reconnect — dropping a `ready` socket mid-session would lose in-flight transcription audio.
- Warn is emitted exactly once per `config-changed` event with a URL mismatch; dedup is not required (events only fire on explicit `syncFromConfig`, which is a user action).
- `intentionalDisconnect` still suppresses all rearm/reconnect branches.

**Ask First:**
- If tracking `connectedUrl` requires touching more than the two construction sites (`connect()` + `doReconnect()`) and `disconnect()`, HALT and describe the scope creep.

**Never:**
- Do NOT add a UI toast, modal, or banner for the host-mismatch warning — diagnostic log only.
- Do NOT change the `apiClient.onConfigChanged` contract, the `syncFromConfig` throw-safety, or the `isBaseUrlConfigured()` double-gate behavior.
- Do NOT retarget the active `ready` socket to the new host — that is a separate "drain + reconnect" story and is out of scope.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Error rearm (unchanged) | `state=error`, gate configured, config-changed fires | `connect()` called exactly once | N/A |
| Error rearm, gate closed | `state=error`, gate closed | No `connect()` call (double-gate holds) | N/A |
| Pending backoff rearm (EC-3) | `state=disconnected`, `reconnectTimer !== null`, gate configured | Timer cancelled; `doReconnect()` fires within the same tick against the new URL | N/A |
| Pending backoff, gate closed | `state=disconnected`, pending timer, gate closed | No-op; existing backoff timer is left to fire on its own schedule | N/A |
| Active session host change (EC-2) | `state ∈ {connecting, authenticating, ready}`, `connectedUrl !== getWsUrl()` | One `warning`-level log entry via `logClientEvent` including both the old and new `ws(s)://…` URLs | N/A |
| Active session, no host change | Same state, `connectedUrl === getWsUrl()` | Silent no-op | N/A |
| Intentional disconnect in flight | `intentionalDisconnect = true` | All branches no-op (no rearm, no warn) | N/A |
| Idle socket, never connected | `state=disconnected`, `reconnectTimer === null`, `connectedUrl === null` | Silent no-op | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/src/services/websocket.ts` -- `TranscriptionSocket`: add `connectedUrl` field, set in `connect()` + `doReconnect()` post-`new WebSocket`, clear in `disconnect()`; add public `handleConfigChanged(configured: boolean)` that dispatches the three branches.
- `dashboard/src/hooks/useTranscription.ts` -- replace inline `if (getState()==='error' && ...)` rearm with `socketRef.current?.handleConfigChanged(apiClient.isBaseUrlConfigured())`.
- `dashboard/src/hooks/useLiveMode.ts` -- same replacement as above.
- `dashboard/src/services/websocket.test.ts` -- add tests for each matrix row touching the new method.
- `dashboard/src/hooks/useTranscription.test.ts` -- update existing mock's `getState` no longer used directly; add `handleConfigChanged` vi.fn() to `lastSocket`; verify the hook calls it on config-changed with the gate boolean.
- `dashboard/src/hooks/useLiveMode.test.ts` -- same mock + hook-level test updates.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/services/websocket.ts` -- Add `private connectedUrl: string | null = null`. Set it to `url` immediately after `this.ws = new WebSocket(url)` in both `connect()` and `doReconnect()`. Null it at the end of `disconnect()`. Rationale: gives the warn branch a reliable snapshot of the URL the current live socket was opened against.
- [x] `dashboard/src/services/websocket.ts` -- Add `handleConfigChanged(configured: boolean): void` implementing the three matrix branches. Use the existing `this.log(..., 'warning')` helper for the breadcrumb; include both old and new URLs in the message.
- [x] `dashboard/src/hooks/useTranscription.ts` -- Replace the `if (socketRef.current?.getState() === 'error' && apiClient.isBaseUrlConfigured()) socketRef.current.connect()` body with `socketRef.current?.handleConfigChanged(apiClient.isBaseUrlConfigured())`. Update the block comment to reflect that the socket class now owns the branching.
- [x] `dashboard/src/hooks/useLiveMode.ts` -- Same single-line replacement + comment update.
- [x] `dashboard/src/services/websocket.test.ts` -- Add a `describe('TranscriptionSocket.handleConfigChanged')` block covering every I/O matrix row; assert WebSocket construction count, `connectedUrl` tracking (via internal cast), and `logClientEvent` calls (mock the module).
- [x] `dashboard/src/hooks/useTranscription.test.ts` + `useLiveMode.test.ts` -- Extend the `lastSocket` mock with `handleConfigChanged: vi.fn()`. Replace the existing rearm tests with calls that assert `handleConfigChanged` is invoked with the correct gate boolean on each emitted event (configured true/false).

**Acceptance Criteria:**
- Given a live `ready` socket and a `syncFromConfig` that mutates `apiClient.baseUrl`, when `config-changed` emits, then exactly one `warning`-level client-debug log entry appears naming both the old and new `ws(s)://…` URLs, and the socket remains `ready` against the old URL.
- Given a socket in `disconnected` state with a pending reconnect timer and the install gate configured, when `config-changed` emits, then the pending timer is cleared and `doReconnect()` fires within the same tick against the new URL — no new WebSocket opens against the stale URL during the remaining backoff window.
- Given a socket in `error` state and a configured gate, when `config-changed` emits, then a single `connect()` occurs (existing behavior, regression-guarded).
- Given `intentionalDisconnect = true`, when `config-changed` emits, then no reconnect action and no warn log is emitted.

## Spec Change Log

### 2026-04-18 — Review iteration 1 (patches applied, no loopback)

- **BH-1 (HIGH)** — EC-3 branch would cancel a healthy backoff and fire `doReconnect()` even if `getWsUrl()` returned null at that instant (configured/gate race). **Patched:** added `this.getWsUrl() !== null` guard before `cancelReconnect()` + `doReconnect()` in branch 2.
- **EC-1 / EC-4 (MEDIUM)** — Branch 2's `doReconnect()` inherited the previous host's `reconnectAttempt` counter, capping the new URL's first retry at `maxDelayMs`. User perceived "I fixed the URL but reconnect is still glacial." **Patched:** reset `this.reconnectAttempt = 0` in branch 2 before `doReconnect()` (user intent = fresh start). Branch 1 already resets inside `connect()`, so the two rearm paths are now symmetric.
- **EC-7 (LOW)** — JSDoc on `connectedUrl` overstated the clearing lifecycle ("cleared on intentional disconnect()"), implying the field clears on any close. **Patched:** rewrote the doc to state explicitly that unintentional `onclose` / `onerror` leaves the field set, and that `handleConfigChanged()` relies on state gating (not field nullness alone) to avoid stale reads.
- **EC-3 (HIGH)** — Blind Hunter and Edge-Case Hunter both flagged branch 1 (`error` + configured → `connect()`) as nearly-dead in practice, since real transport errors follow `onerror → onclose` and land the socket in `disconnected` within a tick, not `error`. Branch 1 is intentional: it recovers the install-gate dead-end (null-URL short-circuit in `connect()`/`doReconnect()` leaves state persistently in `error` with no `onclose` follow-up). **Patched:** documentation-only — expanded the `handleConfigChanged` JSDoc to spell this out so future maintainers don't prune it.
- **BH-7 (MEDIUM)** — `useLiveMode` "configured=false" test asserted `toHaveBeenCalledWith(false)` but not `toHaveBeenCalledTimes(1)`, leaving a regression that double-fires invisible. **Patched:** added the call-count assertion.

**KEEP (preserve across any future re-derivation):**

- The `handleConfigChanged(configured)` signature — branching logic lives on the socket class, not the hooks.
- The warn-only (not drop-and-reconnect) behavior for the active-session branch — spec's `Never` boundary.
- The `connectedUrl` lifecycle: set in `connect()`/`doReconnect()` after `new WebSocket()`, cleared only in intentional `disconnect()`. Active-state detection relies on state gating.
- Test pattern that mutates private `state` via `as unknown as { state: string }` to isolate branch coverage from the full state machine — acknowledged in the spec's task list.

**DEFER (EC-6, not this sprint):** active live-mode session silently streams audio to OLD host after a URL change. Branch 3 warns but keeps the socket alive to avoid cancelling in-flight transcription. A future "drain + retarget" story can replace the warn with a controlled teardown + reconnect. Tracked in `deferred-work.md`.

## Design Notes

Branching lives inside `TranscriptionSocket` so `reconnectTimer` and `connectedUrl` stay private and the three behaviors are testable without React state.

Warn-only (not drop-and-reconnect) for the active-session case: tearing down a `ready` WebSocket mid-session would cancel in-flight transcription. A future "drain + retarget" story can promote the warn into an actual reconnect if needed.

Example log line (no tokens, no identifiers):
`Base URL changed during active session; current: ws://old:9786/ws → next reconnect: wss://new:9786/ws`

## Verification

**Commands:**
- `cd dashboard && npm test -- src/services/websocket.test.ts` -- expected: all new and existing tests pass.
- `cd dashboard && npm test -- src/hooks/useTranscription.test.ts src/hooks/useLiveMode.test.ts` -- expected: all pass with mocks extended for `handleConfigChanged`.
- `cd dashboard && npm run typecheck` -- expected: no new TS errors (new public method has explicit parameter + return types).

**Manual checks (if no CLI):**
- Run dashboard against a local server, start a live-mode session, open Settings, change host to a different reachable address, save. Confirm client debug log shows one `warning` entry with old/new URL shape. Session continues on the old host. Stop/restart the session — it now connects to the new host. No toast.

## Suggested Review Order

**Entry point — the new dispatch method**

- Single method owns all three branches; read first to grasp the design.
  [`websocket.ts:422`](../../dashboard/src/services/websocket.ts#L422)

**Lifecycle of the new `connectedUrl` field**

- Field declaration + JSDoc explaining the persist-through-unintentional-close lifecycle.
  [`websocket.ts:134`](../../dashboard/src/services/websocket.ts#L134)

- Set after `new WebSocket()` in `connect()` — covers `connecting`/`authenticating`/`ready` from first tick.
  [`websocket.ts:189`](../../dashboard/src/services/websocket.ts#L189)

- Same set in `doReconnect()` — keeps the field in sync across reconnect cycles.
  [`websocket.ts:343`](../../dashboard/src/services/websocket.ts#L343)

- Only cleared on intentional `disconnect()` — by design.
  [`websocket.ts:246`](../../dashboard/src/services/websocket.ts#L246)

**Hook call-site parity**

- `useTranscription` listener now delegates to the socket class.
  [`useTranscription.ts:122`](../../dashboard/src/hooks/useTranscription.ts#L122)

- `useLiveMode` listener — identical shape.
  [`useLiveMode.ts:88`](../../dashboard/src/hooks/useLiveMode.ts#L88)

**Matrix coverage tests**

- New describe block covering all I/O matrix rows.
  [`websocket.test.ts:127`](../../dashboard/src/services/websocket.test.ts#L127)

- EC-3 test — proves timer cancellation + immediate new-host reconnect.
  [`websocket.test.ts:182`](../../dashboard/src/services/websocket.test.ts#L182)

- EC-2 test — proves single `warning` breadcrumb naming both URLs, live socket preserved.
  [`websocket.test.ts:257`](../../dashboard/src/services/websocket.test.ts#L257)

**Hook-level forwarding tests**

- `useTranscription` forwards the gate boolean on config-changed.
  [`useTranscription.test.ts:431`](../../dashboard/src/hooks/useTranscription.test.ts#L431)

- `useLiveMode` same forwarding pattern (real `apiClient.syncFromConfig` drives the event).
  [`useLiveMode.test.ts:488`](../../dashboard/src/hooks/useLiveMode.test.ts#L488)
