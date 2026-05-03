---
title: 'In-App Update — Renderer Network-Path Install-Gate Coverage'
type: 'bugfix'
created: '2026-04-14'
status: 'done'
baseline_commit: 'bd9ca60d177111a4b8f784be04f23337d56ec6eb'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-remote-host-validation-renderer.md'
  - '{project-root}/dashboard/electron/appState.ts'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The renderer install-gate landed in `bd9ca60` only covers `APIClient.checkConnection`. Six REST helpers (`get`/`post`/`patch`/`put`/`del`/`postFormData`), three SSE generators (`llmProcessStream`, `summarizeRecordingStream`, `chat`), the `loadModelsStream` WebSocket opener, two derived-URL methods (`getAudioUrl`, `getExportUrl`), and `TranscriptionSocket.getWsUrl` all consume `apiClient.baseUrl` unchecked. When `useRemote=true` with blank active-profile host is already persisted, (a) pre-`syncFromConfig` callers hit the constructor default `http://localhost:9786` — **stealth localhost probe on a pure-remote user's machine**; (b) post-sync callers hit the malformed `http://:9786` — `fetch()` throws a generic TypeError, `new WebSocket('ws://:9786/...')` has implementation-defined behavior, and `<audio src>` / download URLs point at a broken resource. Symptom is obscure stack traces instead of the actionable `'remote-host-not-configured'` state.

**Approach:** Add a synchronous `APIClient.isBaseUrlConfigured()` predicate that returns true iff `syncFromConfig` has run at least once AND `new URL(baseUrl)` parses with a non-empty hostname. Gate all six REST helpers + three SSE generators + `loadModelsStream` via a shared `ensureConfigured(path)` that throws `new APIError(0, 'remote-host-not-configured', path)`. Change `getAudioUrl`/`getExportUrl` return type to `string | null`; thread the null through `NotebookView` + `useRecording`. `TranscriptionSocket.getWsUrl()` returns `null` when unconfigured; `connect()`/`doReconnect()` fire `onError('remote-host-not-configured')`, transition to `'error'` state, and skip `new WebSocket`.

## Boundaries & Constraints

**Always:**
- `isBaseUrlConfigured()` is sync (no IPC per call). Based on: (a) `synced` flag set to true inside `syncFromConfig`, (b) `new URL(this.baseUrl)` does not throw, (c) `url.hostname.length > 0`.
- `ensureConfigured(path)` throws `new APIError(0, 'remote-host-not-configured', path)` — callers see a failure shape they already handle.
- REST + SSE method changes are internal; public signatures preserved. Callers now get a stable `APIError` rejection instead of a silent wrong-host probe.
- `getAudioUrl` / `getExportUrl` public signature change: `string` → `string | null`. Callers must guard on null.
- WS `getWsUrl` returns `string | null`; `connect()` and `doReconnect()` guard on null, call `onError('remote-host-not-configured')`, set state to `'error'`, and skip WebSocket construction.
- `checkConnection` short-circuit at `client.ts:204` is unchanged — it reads fresh config via `isServerUrlConfigured()`.

**Ask First:**
- Replacing the `synced` boolean with a richer "connection-state machine" (idle/syncing/configured/blank). Current flag is sufficient; a state machine is adjacent UX work.
- Surfacing a renderer UI banner for `'remote-host-not-configured'`. Existing callers display the error string verbatim; dedicated banner is UX polish.

**Never:**
- Do not make `isBaseUrlConfigured()` async — would add 3+ IPC round-trips to every REST call; regresses 30-60s poll cadence perf.
- Do not change `APIClient` constructor default — would break local-mode dev builds that rely on the default before `syncFromConfig` runs. The `synced` flag is the gate.
- Do not gate `getBaseUrl()` itself — used by `SessionView` log lines 511/540 for diagnostic display of what URL was configured; a malformed display is informative.
- Do not extract a shared `ConnectionErrorReason` union (deferred item E7 on the ledger — requires main+renderer symmetric landing).
- Do not touch `electron/appState.ts` or `electron/main.ts` — main-process gate already landed.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Pre-sync REST call | Fresh `apiClient` (no `syncFromConfig` yet), any REST or SSE method invoked | `ensureConfigured` throws `APIError(0, 'remote-host-not-configured', path)` before `fetch` | Caller sees `APIError` rejection |
| Local mode, synced | `useRemote=false`, sync done, `baseUrl=http://localhost:9786` | All paths proceed normally | N/A |
| Blank remote, synced | `useRemote=true`, blank active-profile host, `baseUrl=http://:9786` | All REST + SSE throw `APIError('remote-host-not-configured')`; no `fetch` | Stable error |
| `getAudioUrl` / `getExportUrl` blank | Same | Return `null` instead of malformed URL | Callers guard |
| WS `connect()` blank | Same | `getWsUrl()` returns `null`; `connect()` fires `onError('remote-host-not-configured')`, `setState('error')`, no `new WebSocket` | No connection attempt |
| Configured remote, synced | `useRemote=true`, `remoteHost='foo.ts.net'` | All paths proceed normally | N/A |
| Pre-sync derived URL | Fresh `apiClient`, `getAudioUrl(5)` called | Returns `null` (synced=false) | Caller guards |

</frozen-after-approval>

## Code Map

- `dashboard/src/api/client.ts` — add `private synced = false` + `isBaseUrlConfigured(): boolean` + `ensureConfigured(path): void`; gate all 6 REST helpers + `llmProcessStream` + `summarizeRecordingStream` + `chat` + `loadModelsStream`; change `getAudioUrl` / `getExportUrl` return type to `string | null`; set `synced = true` inside `syncFromConfig`.
- `dashboard/src/services/websocket.ts` — change `getWsUrl()` return type to `string | null`; guard null in `connect()` + `doReconnect()`; fire `onError` + `setState('error')` + skip construction.
- `dashboard/components/views/NotebookView.tsx` — guard `getExportUrl` null at line 268 (skip export + log); guard `getAudioUrl` null at line 680 (skip Audio playback + log).
- `dashboard/src/hooks/useRecording.ts` — line 54 adapt to `string | null` return (current code already handles null via ternary — just pass-through).
- `dashboard/src/api/client.test.ts` — ADD tests: pre-sync REST gate (throws before fetch); blank-remote gate (REST + SSE); `getAudioUrl`/`getExportUrl` null return; configured path preserved.
- `dashboard/src/services/websocket.test.ts` — NEW file: `connect()` + `doReconnect()` short-circuit when `apiClient` unconfigured.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/api/client.ts` — add `private synced: boolean = false`; `isBaseUrlConfigured(): boolean` that returns `synced && <url-parse-succeeds> && <hostname-non-empty>`; `ensureConfigured(path: string): void` that throws `new APIError(0, 'remote-host-not-configured', path)` when predicate is false. Set `synced = true` inside `syncFromConfig`. Insert `this.ensureConfigured(path)` as the first line of `get`/`post`/`patch`/`put`/`del`/`postFormData` + the 3 SSE generators + `loadModelsStream`. Change `getAudioUrl` / `getExportUrl` signature to return `string | null`; return `null` when `!isBaseUrlConfigured()`.
- [x] `dashboard/src/services/websocket.ts` — change `getWsUrl(): string | null`; return `null` when `!apiClient.isBaseUrlConfigured()`. In `connect()` and `doReconnect()`, if `getWsUrl()` returns null, log, call `this.callbacks.onError?.('remote-host-not-configured')`, `setState('error')`, return early without `new WebSocket`.
- [x] `dashboard/components/views/NotebookView.tsx` — guard null return of `getExportUrl` (early-return + clientEvent log) and `getAudioUrl` (early-return + clientEvent log) at their two callsites.
- [x] `dashboard/src/hooks/useRecording.ts` — update `audioUrl` derivation to accept new signature; existing null-handling extends.
- [x] `dashboard/src/api/client.test.ts` — add tests: pre-sync REST throws APIError; blank-remote REST throws; blank-remote SSE generator throws on first `next()`; `getAudioUrl`/`getExportUrl` null when unconfigured; configured path invokes real fetch with expected URL.
- [x] `dashboard/src/services/websocket.test.ts` — NEW; assert `connect()` with unconfigured apiClient calls `onError('remote-host-not-configured')` + transitions to `'error'` + never constructs a WebSocket.

**Acceptance Criteria:**
- Given a fresh `apiClient` with no prior `syncFromConfig` call, when any REST or SSE method is invoked, then it rejects with `APIError` whose `body === 'remote-host-not-configured'` AND no `fetch` is dispatched (asserted via `vi.spyOn(global, 'fetch')` + `not.toHaveBeenCalled()`).
- Given `useRemote=true` with blank active-profile host and `syncFromConfig` has run, when REST helpers / SSE generators / `loadModelsStream` are invoked, then all throw the stable `'remote-host-not-configured'` shape.
- Given blank-remote state, when `getAudioUrl` or `getExportUrl` is called, then result is `null`.
- Given blank-remote state, when `TranscriptionSocket.connect()` is called, then `onError('remote-host-not-configured')` fires, `connectionState === 'error'`, and no `WebSocket` instance is constructed (spied via module-level `vi.spyOn`).
- Existing `src/api/client.test.ts`, `components/__tests__/NotebookView.test.tsx`, `ServerView.test.tsx`, `SessionView.test.tsx` suites continue to pass.
- `cd dashboard && npm run ui:contract:check` stays green (no className changes).

## Spec Change Log

### Review iteration 1 (2026-04-14)

Acceptance auditor PASS. No intent_gap or bad_spec findings — no loopback. Six PATCH-class findings applied in-review; five DEFER-class findings appended to `deferred-work.md` under `## From Renderer Network-Path Install-Gate Review (2026-04-14)`.

Applied patches:
- **B5** (client.test.ts per-verb test): assertions tightened from `instanceof APIError` to full-shape `toMatchObject({status:0, body:'remote-host-not-configured', path:<expected>})` for each of the 6 verbs — closes regression-coverage gap where a different APIError would have passed silently.
- **B6** (client.test.ts loadModelsStream test): added `vi.stubGlobal('WebSocket', wsConstructor)` + `expect(wsConstructor).not.toHaveBeenCalled()` — proves the gate sits before WebSocket construction, not just that `onError` fires.
- **B4** (client.test.ts new transition test): added `good→blank sync transition` — proves both clauses of the predicate (synced AND hostname) matter, not just `synced`.
- **B7** (NotebookView.tsx audio preview): added `toast.error('Remote host not configured...')` matching the export handler's UX pattern — consistent messaging across both derived-URL callsites.
- **B9** (websocket.test.ts): added a `doReconnect` short-circuit test via fake timers + simulated onclose — previously only `connect()` was covered.
- **E2** (NotebookView.test.tsx mock drift): replaced `mockReturnValue('')` with a real URL string — makes the mock match production `string | null` shape.

KEEP (preserved from initial implementation): `isBaseUrlConfigured()` remains sync with no IPC round-trip (perf-critical for 30-60s poll loops); three-clause predicate (synced AND URL-parseable AND hostname-non-empty) — each clause has a distinct regression guard; `TranscriptionSocket` tests use `vi.spyOn(apiClient, 'isBaseUrlConfigured')` for test isolation.

## Design Notes

Constructor-default regression vector: if we naively gate only on URL parse, `new APIClient()` → `baseUrl = 'http://localhost:9786'` parses successfully → predicate returns true → pre-sync callers sail through. The `synced` flag is the explicit defense: even a parseable URL is not "configured" until the renderer has read config at least once. This matches the main-process pattern where `getServerUrl` is only called from handlers that run after app-ready.

Golden predicate shape (≤10 lines):

```typescript
isBaseUrlConfigured(): boolean {
  if (!this.synced) return false;
  try {
    const u = new URL(this.baseUrl);
    return u.hostname.length > 0;
  } catch {
    return false;
  }
}

private ensureConfigured(path: string): void {
  if (!this.isBaseUrlConfigured()) {
    throw new APIError(0, 'remote-host-not-configured', path);
  }
}
```

WS short-circuit shape inside `connect()`:

```typescript
const url = this.getWsUrl();
if (url === null) {
  this.log('Skipping connect: remote-host-not-configured', 'error');
  this.callbacks.onError?.('remote-host-not-configured');
  this.setState('error');
  return;
}
this.ws = new WebSocket(url);
```

## Verification

**Commands:**
- `cd dashboard && npm test -- src/api/client.test.ts src/services/websocket.test.ts` — expected: all new tests pass.
- `cd dashboard && npm run typecheck` — expected: no new TS errors (signature changes propagate cleanly).
- `cd dashboard && npm test` — expected: existing suites unchanged.
- `cd dashboard && npm run ui:contract:check` — expected: green.

## Suggested Review Order

**Design intent — the sync predicate**

- Three-clause gate: `synced` AND URL-parses AND hostname-non-empty — each clause catches a distinct regression.
  [`client.ts:101`](../../dashboard/src/api/client.ts#L101)

- The `synced` flag flips true inside `syncFromConfig` — pre-sync stealth-localhost defense.
  [`client.ts:54`](../../dashboard/src/api/client.ts#L54)

- `ensureConfigured` throws the stable error shape before any `fetch`.
  [`client.ts:113`](../../dashboard/src/api/client.ts#L113)

**Gate application — REST + SSE + WebSocket**

- Six REST helpers gated at their first line (repeating pattern at lines 132, 141, 152, 163, 174, 184).
  [`client.ts:132`](../../dashboard/src/api/client.ts#L132)

- `loadModelsStream` short-circuits with `onError` + no-op cleanup, no WebSocket constructed.
  [`client.ts:662`](../../dashboard/src/api/client.ts#L662)

- Derived URLs return `null` when unconfigured — callers must guard.
  [`client.ts:500`](../../dashboard/src/api/client.ts#L500)

- WS `connect()` short-circuit: fires `onError`, sets state=`error`, skips `new WebSocket`.
  [`websocket.ts:171`](../../dashboard/src/services/websocket.ts#L171)

- WS `doReconnect()` mirror of the connect-path gate — reconnect loop dies loudly rather than constructing a broken socket.
  [`websocket.ts:324`](../../dashboard/src/services/websocket.ts#L324)

**Consumer adaptation**

- NotebookView export-URL null guard with user-visible toast.
  [`NotebookView.tsx:269`](../../dashboard/components/views/NotebookView.tsx#L269)

- NotebookView audio-preview null guard — same toast pattern for UX consistency (B7 patch).
  [`NotebookView.tsx:686`](../../dashboard/components/views/NotebookView.tsx#L686)

**Behavioral contracts — tests**

- Headline: pre-sync REST gate throws APIError + no fetch dispatched.
  [`client.test.ts:127`](../../dashboard/src/api/client.test.ts#L127)

- Full-shape per-verb regression lock (B5 patch).
  [`client.test.ts:139`](../../dashboard/src/api/client.test.ts#L139)

- Good→blank sync transition — proves both predicate clauses matter (B4 patch).
  [`client.test.ts:205`](../../dashboard/src/api/client.test.ts#L205)

- `loadModelsStream` WebSocket-not-called regression lock (B6 patch).
  [`client.test.ts:186`](../../dashboard/src/api/client.test.ts#L186)

- Derived-URL null return across pre-sync / blank-remote / configured paths.
  [`client.test.ts:275`](../../dashboard/src/api/client.test.ts#L275)

- WS `connect()` short-circuit — module-level `vi.spyOn(apiClient, 'isBaseUrlConfigured')`.
  [`websocket.test.ts:49`](../../dashboard/src/services/websocket.test.ts#L49)

- WS `doReconnect()` short-circuit via fake timers + simulated onclose (B9 patch).
  [`websocket.test.ts:78`](../../dashboard/src/services/websocket.test.ts#L78)
