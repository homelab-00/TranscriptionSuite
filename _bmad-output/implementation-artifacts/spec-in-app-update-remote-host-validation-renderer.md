---
title: 'In-App Update — Remote-Host Validation (Renderer-Side Mirror)'
type: 'bugfix'
created: '2026-04-14'
status: 'done'
baseline_commit: '6afb8ed37b9bc94609e6852cbc8691c5ab80d33d'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-remote-host-validation.md'
  - '{project-root}/dashboard/electron/appState.ts'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The renderer has the same silent-localhost deadlock the main-process install-gate just closed in `486aea0`. When `useRemote=true` with a `.trim()`-empty Tailscale/LAN host is already persisted (prior session, manual electron-store edit, config import, pre-Save race), `dashboard/src/config/store.ts:188-192` coerces `remoteHost || DEFAULT_CONFIG.connection.localHost`, so `apiClient.baseUrl` and the WebSocket service silently point at `localhost:9786` on a pure-remote user's machine. Symptom is stuck API calls and a misleading `serverUnreachable` banner with no actionable remedy — the exact misleading path the main-process fix exists to close.

**Approach:** Mirror the main-process `isServerUrlConfigured` predicate to the renderer as an exported async helper in `store.ts`, remove the silent-localhost coercion in `getServerBaseUrl` (parity with the `getServerUrl` regression lock on the main side), and gate `apiClient.checkConnection` on the predicate so it returns a stable `'remote-host-not-configured'` error synchronously without issuing a probe. WebSocket inherits the fix via `apiClient.getBaseUrl()`.

## Boundaries & Constraints

**Always:**
- Renderer `isServerUrlConfigured` truth-table matches main-process `appState.ts::isServerUrlConfigured` exactly: local mode → true; `useRemote=true` + active-profile host `.trim()`-empty → false; otherwise true. Active profile is Tailscale→`remoteHost`, LAN→`lanHost`.
- `getServerBaseUrl` returns `http://:<port>` (no host) for blank-remote rather than coercing to `localhost` — misuses fail loud, mirroring the main-process `getServerUrl` regression lock.
- `apiClient.checkConnection` short-circuits on `!isServerUrlConfigured()` and returns `{ reachable: false, ready: false, status: null, error: 'remote-host-not-configured' }` **before** any `electronAPI.server.probeConnection` or `fetch` is dispatched.
- Fallback behavior for local mode and configured remote is unchanged — no regression in the happy paths.

**Ask First:**
- Adding a renderer UI surface for the new `'remote-host-not-configured'` state (dedicated banner, first-run modal). The current spec wires the stable error string through `checkConnection`'s return shape; a dedicated banner with "Open Settings → Connection" CTA is adjacent UX work and out of scope. Callers display the error verbatim today.
- Gating `SessionView.handleStartClientRemote` on the predicate with a diagnostic log event. The save-time LAN/Tailscale validator in `SettingsModal.handleSave` already blocks blank-host persistence, but a toggle from a pre-populated corrupt store can still reach `handleStartClientRemote` without passing through Save.

**Never:**
- Do not modify `dashboard/electron/appState.ts` or `dashboard/electron/main.ts` — main-process fix already landed in 486aea0. Renderer is the second, independent half.
- Do not tighten `.trim()` to reject NBSP (`\u00A0`), ZWSP (`\u200B`), or other unicode whitespace — separate deferred item that requires symmetric fix across LAN validator, Tailscale validator, save-time predicate, and both renderer + main-process predicates simultaneously.
- Do not add host-syntax validation (`host:port` collision, URL-invalid characters, length bounds) — separate deferred item.
- Do not refactor the non-transactional `api.config.set` loop in `SettingsModal.handleSave` — pre-existing.
- Do not batch-add the symmetric boolean-coercion hardening (`connection.useRemote === true` strict check, `remoteProfile` whitelist) — separate deferred item.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Local mode | `useRemote=false`, any host fields | `isServerUrlConfigured()` → true; `getServerBaseUrl()` → configured localHost URL; `checkConnection` probes normally | N/A |
| Pure remote + Tailscale configured | `useRemote=true`, `remoteProfile='tailscale'`, `remoteHost='foo.ts.net'` | predicate → true; URL → `https?://foo.ts.net:9786`; probe normally | N/A |
| Pure remote + blank Tailscale | `useRemote=true`, `remoteProfile='tailscale'`, `remoteHost=''` (or whitespace) | predicate → false; `getServerBaseUrl()` → `http://:9786` (no coercion); `checkConnection` returns `{reachable:false, ready:false, status:null, error:'remote-host-not-configured'}` with NO probe dispatched | Fail-fast; no `electronAPI.server.probeConnection`, no `fetch` |
| Pure remote + blank LAN | `useRemote=true`, `remoteProfile='lan'`, `lanHost=''` | predicate → false; same as above | Same fail-fast |
| Active-profile mismatch | `useRemote=true`, `remoteProfile='tailscale'`, `remoteHost=''`, `lanHost='10.0.0.5'` | predicate reads ACTIVE profile (Tailscale) → false; lanHost irrelevant | Fail-fast |
| Blank-remote regression lock | After fix, `getServerBaseUrl()` for blank-remote useRemote | Result MUST be `http://:9786`, NOT `http://localhost:9786` | Test asserts exact string |

</frozen-after-approval>

## Code Map

- `dashboard/src/config/store.ts` -- add exported async `isServerUrlConfigured()` mirroring main-process shape; remove `|| DEFAULT_CONFIG.connection.localHost` coercion in `getServerBaseUrl` Tailscale branch (line 191).
- `dashboard/src/api/client.ts` -- `checkConnection()` (line 186+): call `isServerUrlConfigured()` first; return stable error-object immediately if false, before the `electronAPI.server.probeConnection` / `fetch` paths.
- `dashboard/electron/appState.ts` -- REFERENCE ONLY; do not modify. Source of truth for predicate behavior.
- `dashboard/src/config/store.test.ts` -- NEW; unit tests for `isServerUrlConfigured` truth table and `getServerBaseUrl` non-coercion regression lock.
- `dashboard/src/api/client.test.ts` -- NEW; unit test for `checkConnection` fail-fast path (mocks `isServerUrlConfigured`, asserts no probe dispatched, asserts returned shape).

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/config/store.ts` -- add `export async function isServerUrlConfigured(): Promise<boolean>` reading `connection.useRemote`, `connection.remoteProfile`, `connection.remoteHost`, `connection.lanHost` via `getConfig`, with `.trim()` parity.
- [x] `dashboard/src/config/store.ts` -- remove `|| DEFAULT_CONFIG.connection.localHost` from the Tailscale branch at line 191; the ternary reads `remoteProfile === 'lan' ? lanHost : remoteHost` with NO fallback. Add an inline comment referencing the parity invariant with `electron/appState.ts::getServerUrl`.
- [x] `dashboard/src/api/client.ts` -- import `isServerUrlConfigured` from `../config/store`; in `checkConnection`, call it first; on false, return `{reachable:false, ready:false, status:null, error:'remote-host-not-configured'}` before any probe. Add short JSDoc explaining the short-circuit parity with `appState.isAppIdle`.
- [x] `dashboard/src/config/store.test.ts` -- NEW; cover predicate truth table (local mode, Tailscale configured, Tailscale blank, Tailscale whitespace, LAN blank, active-profile-mismatch) and `getServerBaseUrl` regression lock (`http://:9786` not `http://localhost:9786`).
- [x] `dashboard/src/api/client.test.ts` -- NEW; cover `checkConnection` short-circuit: mock `isServerUrlConfigured` to return false, assert `electronAPI.server.probeConnection` is never called and return shape matches spec.

**Acceptance Criteria:**
- Given `useRemote=true`, `remoteProfile='tailscale'`, and `remoteHost=''`, when `apiClient.checkConnection()` is called, then the result is `{reachable:false, ready:false, status:null, error:'remote-host-not-configured'}` AND no network probe is issued (verified by mock-not-called assertion).
- Given `useRemote=true` and blank active-profile host, when `getServerBaseUrl()` is called, then the return value is `http://:9786` (or `https://:9786` when `useHttps=true`) — never `http://localhost:9786`.
- Given local mode, when `isServerUrlConfigured()` is called, then the return value is `true` regardless of remote-host fields.
- Existing `dashboard/components/__tests__/ServerView.test.tsx` and `SessionView.test.tsx` continue to pass (their `checkConnection` mocks short-circuit their paths — regression lock for happy-path invocation).
- `npm run ui:contract:check` from `dashboard/` stays green (no UI class changes).

## Spec Change Log

### Review iteration 1 (2026-04-14)

No intent_gap or bad_spec findings. Acceptance auditor PASS. Three in-review PATCH-class findings applied (B3, B5, E7) and seven DEFER-class findings appended to `deferred-work.md` under the `## From Renderer Install-Gate Mirror Review (2026-04-14)` section. No code re-derivation required; no loopback.

Applied patches:
- **B3** (client.test.ts): local-mode + configured-Tailscale tests now assert `result.error === null` in addition to the existing `probeConnection.toHaveBeenCalledTimes(1)` check — closes a regression-coverage gap for the happy path.
- **B5** (store.ts, client.ts): code comments referencing the spec filename now keep the filename on a single line instead of wrapping mid-slug (grep-hostile).
- **E7** (client.test.ts): added `afterEach` that calls `vi.unstubAllGlobals()`, `vi.restoreAllMocks()`, and `delete (window as any).electronAPI` — prevents the singleton `apiClient`, fetch stub, and config-bridge stub from leaking into unrelated test files.

KEEP (preserved from initial implementation): checkConnection short-circuit placement at the very top of the method before any `electronAPI.server.probeConnection` / `fetch` path (acceptance auditor explicitly verified line-level conformance); `DEFAULT_CONFIG.connection.remoteProfile` reference for the profile default (semantically equivalent to inline `'tailscale'` literal in the golden example, with the advantage of single-source-of-truth).

## Design Notes

The main-process fix in commit `486aea0` deliberately split the install-gate concern from the compat-guard concern: `isAppIdle` short-circuits via `isServerUrlConfigured` before constructing a URL (loud fail), while `compatGuard.fetchServerVersion` deliberately does NOT short-circuit per M4's fail-open design (malformed `http://:9786` TypeError maps to `server-version-unavailable`, same as any probe failure). The renderer mirror adopts the same philosophy: `checkConnection` is the moral equivalent of `isAppIdle` and gets the short-circuit; anything that calls `apiClient.getBaseUrl()` directly (e.g. WebSocket) inherits the non-coerced `http://:<port>` and fails loud at connect-time — the desirable semantics.

Golden example of the predicate shape (≤10 lines):

```typescript
export async function isServerUrlConfigured(): Promise<boolean> {
  const useRemote = (await getConfig<boolean>('connection.useRemote')) ?? false;
  if (!useRemote) return true;
  const profile =
    (await getConfig<'tailscale' | 'lan'>('connection.remoteProfile')) ?? 'tailscale';
  const host = (
    profile === 'lan'
      ? ((await getConfig<string>('connection.lanHost')) ?? '')
      : ((await getConfig<string>('connection.remoteHost')) ?? '')
  ).trim();
  return host.length > 0;
}
```

## Verification

**Commands:**
- `cd dashboard && npm test -- src/config/store.test.ts src/api/client.test.ts` -- expected: all new tests pass.
- `cd dashboard && npm run typecheck` -- expected: no new TS errors.
- `cd dashboard && npm test` -- expected: existing test suites unchanged (ServerView, SessionView, SettingsModal, UpdateBanner, etc.).
- `cd dashboard && npm run ui:contract:check` -- expected: pass (no UI class changes).

## Suggested Review Order

**Design intent — the renderer-side predicate**

- Start here: the new async predicate mirrors `electron/appState.ts::isServerUrlConfigured` byte-for-byte.
  [`store.ts:218`](../../dashboard/src/config/store.ts#L218)

- Non-coercion: Tailscale branch no longer falls back to localhost — `http://:9786` is the loud-fail shape.
  [`store.ts:195`](../../dashboard/src/config/store.ts#L195)

**Gate application — checkConnection as moral isAppIdle**

- Short-circuit sits before any `electronAPI.server.probeConnection` or `fetch` dispatch.
  [`client.ts:204`](../../dashboard/src/api/client.ts#L204)

- Import pulling `isServerUrlConfigured` into the API client singleton.
  [`client.ts:6`](../../dashboard/src/api/client.ts#L6)

**Behavioral contracts — tests**

- Headline: blank Tailscale → stable error, zero probes dispatched.
  [`client.test.ts:42`](../../dashboard/src/api/client.test.ts#L42)

- Regression lock: `http://:9786` (NOT `http://localhost:9786`) for blank-remote.
  [`store.test.ts:123`](../../dashboard/src/config/store.test.ts#L123)

- Active-profile subtlety: Tailscale blank + LAN configured → false when Tailscale is active.
  [`store.test.ts:80`](../../dashboard/src/config/store.test.ts#L80)

- Test-isolation hygiene: `afterEach` prevents singleton state leakage across files.
  [`client.test.ts:33`](../../dashboard/src/api/client.test.ts#L33)
