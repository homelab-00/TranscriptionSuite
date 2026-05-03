---
title: 'M4: Server-compatibility guard for in-app Dashboard updates'
type: 'feature'
created: '2026-04-13'
status: 'done'
baseline_commit: '4dccea79a47b013df38ae7eb80e865d47ff219aa'
context:
  - '{project-root}/_bmad-output/brainstorming/brainstorming-session-2026-04-12-in-app-updates.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-m1-electron-updater.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-m3-safety-gate.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `updates:download` currently pulls any newer Dashboard binary without checking whether the installed Docker server can still talk to it. The brainstorming doc (D1) defines a per-release `manifest.json` asset carrying `compatibleServerRange` (semver) + `sha256`. Without M4 the Dashboard can replace a working binary with one whose API requirements the server does not meet. The server's running version is also not exposed over HTTP, so remote-server compat is undetectable.

**Approach:** Add `class CompatGuard` in a new file `dashboard/electron/compatGuard.ts`. It fetches `manifest.json` from GitHub's releases/latest asset list, probes the server version via a new `version` field on `/api/admin/status`, and evaluates the semver range via the `semver` package. `main.ts` wraps `updates:download` with a pre-flight `check()`: incompatible → `{ok:false, reason:'incompatible-server', detail}` without entering `UpdateInstaller`; compatible or any "unknown" → fall through to `updateInstaller.startDownload()` (fail-open). A new `updates:checkCompatibility` IPC surfaces the result for M5's modal. The parsed manifest is persisted in electron-store so M6 can later read `sha256`.

## Boundaries & Constraints

**Always:**
- New file `dashboard/electron/compatGuard.ts` exports `type Manifest`, `type CompatResult`, `class CompatGuard`. Constructor `{ store, logger?, fetchImpl? }` (test seams). Methods: `check(): Promise<CompatResult>`, `getLastManifest(): Manifest | null`, `destroy(): void`. No behavior growth in `updateInstaller.ts`, `updateManager.ts`, or `InstallGate`.
- `Manifest` shape (D1, inline-validated — no zod): `{ version:string, compatibleServerRange:string, sha256:Record<string,string>, releaseType:string }`.
- `CompatResult` = union: `{result:'compatible', manifest, serverVersion}` | `{result:'incompatible', manifest, serverVersion, compatibleRange, deployment:'local'|'remote'}` | `{result:'unknown', reason:'no-manifest'|'manifest-fetch-failed'|'manifest-parse-error'|'server-version-unavailable'|'invalid-range', detail?:string}`.
- Fetches: `GET https://api.github.com/repos/homelab-00/TranscriptionSuite/releases/latest` (Accept `application/vnd.github+json`, 15s timeout) → manifest asset's `browser_download_url` (15s). Server probe: `GET ${url}/api/admin/status` with `Authorization: Bearer ${token}` when present, 5s timeout. URL + token reuse `appState.ts` helpers (exported for this purpose — behavior unchanged).
- Semver eval: `semver.satisfies(serverVersion, compatibleServerRange, { includePrerelease: false })`. Add `semver` (`^7.7.1`) + `@types/semver`.
- Backend: `server/backend/api/routes/admin.py::get_admin_status` adds `"version": __version__` (import `from server import __version__`). No other server changes.
- main.ts: construct `compatGuard = new CompatGuard({ store })` after `installGate` (~line 500). Rewrite `ipcMain.handle('updates:download')` at line 1261 to run `compatGuard.check()` first and return the ok-false shape on `incompatible`, else delegate to `updateInstaller.startDownload()`. Add `ipcMain.handle('updates:checkCompatibility', () => compatGuard.check())`. Add `compatGuard.destroy()` to the cleanup block near `installGate.destroy()` (~line 1801).
- preload.ts + `src/types/electron.d.ts`: widen `updates.download()` return union with `{ok:false; reason:'incompatible-server'; detail:{serverVersion:string|null; compatibleRange:string; deployment:'local'|'remote'}}`. Add `updates.checkCompatibility(): Promise<CompatResult>`. Export `Manifest`, `CompatResult`.
- Persist `store.set('updates.lastManifest', manifest)` whenever `check()` successfully parses a manifest — even on `incompatible` (M6 needs `sha256` regardless). Do not persist on parse-error.
- `check()` is single-flight: concurrent callers await the same Promise. No cross-call caching.
- Fail-open: every `unknown` branch in `updates:download` delegates to `startDownload()`. Log via `console.warn('[CompatGuard]', ...)`.

**Ask First:**
- Any change to `manifest.json`'s shape beyond the four D1 fields.
- Any new server endpoint (M4 adds ONE field to an existing response — nothing else).
- Any UI work — those belong to M5.

**Never:**
- Do NOT touch `UpdateInstaller`'s state machine, `InstallerStatus`, or `StartDownloadResult` (frozen by M1). Do NOT gate install (M3). Do NOT remove `UpdateManager.checkServer()`'s GHCR poll.
- Do NOT create `/api/version`; do NOT hand-roll semver range parsing; do NOT verify the downloaded binary's SHA-256 here (M6).
- Do NOT fail-closed on unknown compat — it would brick auto-update for anyone on a pre-M4 server.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior |
|---|---|---|
| Compatible, local | range='>=1.0.0 <2.0.0', version='1.4.2', useRemote=false | `{result:'compatible', ...}`. `updates:download` → `startDownload()`. Manifest persisted. |
| Incompatible, local | range='>=99.0.0', version='1.4.2' | `{result:'incompatible', deployment:'local', ...}`. `updates:download` → `{ok:false, reason:'incompatible-server', detail}`. startDownload NOT called. Manifest persisted. |
| Incompatible, remote | same + useRemote=true | same with `deployment:'remote'`. |
| Manifest asset missing or fetch fails or parse error | HTTP !ok / timeout / malformed JSON / missing fields | `{result:'unknown', reason:'no-manifest'\|'manifest-fetch-failed'\|'manifest-parse-error'}`. Fall-through to startDownload. Persist only on successful parse. |
| admin/status unreachable, 401/403/5xx, or `.version` absent, or serverVersion not valid semver | any server-side failure | `{result:'unknown', reason:'server-version-unavailable', detail}`. Fall-through. Manifest may still persist if fetched cleanly. |
| `compatibleServerRange` invalid | e.g. 'garbage' | `{result:'unknown', reason:'invalid-range', detail}`. Fall-through. Persist manifest. |
| Concurrent `check()` calls | second call while first in flight | Second call awaits the same Promise; only ONE pair of network fetches occurs. |
| `destroy()` mid-fetch | gracefulShutdown | Destroyed flag set; in-flight result discarded; no persistence after destroy. |

</frozen-after-approval>

## Code Map

- `dashboard/package.json` — add `"semver": "^7.7.1"` + `"@types/semver": "^7.7.0"`.
- `dashboard/electron/appState.ts` — export `getServerUrl` + `getAuthToken` (no behavior change).
- `dashboard/electron/compatGuard.ts` — NEW. Types + class per Boundaries.
- `dashboard/electron/main.ts` — wire `compatGuard`; rewrite `updates:download`; add `updates:checkCompatibility`; destroy on cleanup.
- `dashboard/electron/preload.ts` — add `checkCompatibility`; widen `download()` return type; export new types.
- `dashboard/src/types/electron.d.ts` — mirror.
- `server/backend/api/routes/admin.py` — add `"version": __version__` to the response.
- `dashboard/electron/__tests__/compatGuard.test.ts` — NEW. Vitest cases covering every I/O matrix row; mocks `fetch` (releases/latest + manifest asset + admin/status) and fake electron-store.
- `server/backend/tests/test_admin_status_version.py` — NEW. Pytest asserting `/api/admin/status` JSON contains `"version" == server.__version__`, reusing `test_client_local` + `admin_token` fixtures.

Not changed (frozen by earlier milestones): `updateInstaller.ts`, `updateManager.ts` behavior, `InstallGate`, `InstallerStatus`, `UpdateBanner.tsx`.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/package.json` — added `semver ^7.7.4` + `@types/semver ^7.7.1`.
- [x] `dashboard/electron/appState.ts` — exported `getServerUrl` + `getAuthToken` for reuse by `compatGuard.ts`.
- [x] `dashboard/electron/compatGuard.ts` — NEW. `Manifest` + `CompatResult` + `CompatGuard` class with single-flight `check()`, destroy-safe persistence, fail-open on unknown.
- [x] `dashboard/electron/main.ts` — constructed `compatGuard` after `installGate`; rewrote `updates:download` to run compat pre-flight; added `updates:checkCompatibility`; added `compatGuard.destroy()` to cleanup.
- [x] `dashboard/electron/preload.ts` — widened `download()` return union; added `checkCompatibility`; local `Manifest` + `CompatResult` type declarations mirror the renderer ambient types.
- [x] `dashboard/src/types/electron.d.ts` — mirrored wider `download()` return-union, new `checkCompatibility`, `Manifest` + `CompatResult` ambient types.
- [x] `server/backend/api/routes/admin.py` — imported `__version__`; added `"version": __version__` to admin/status response.
- [x] `dashboard/electron/__tests__/compatGuard.test.ts` — 29 Vitest cases: 19 covering every I/O matrix row (compatible/incompatible local + remote, no-manifest, fetch failures at 3 endpoints, parse errors, version-field absent, non-semver version, invalid range, single-flight concurrent calls, auth header, destroy mid-fetch, `getLastManifest` variants) + 10 post-review hardening cases (sha256 hex-regex, empty/oversized sha256 sets, invalid manifest version, asset URL allow-list rejection, content-length > 1 MB abort, non-array `assets`, null admin body, post-destroy `check()` returns without fetch, `getLastManifest` tolerates throwing store).
- [x] `server/backend/tests/test_admin_status_version.py` — 2 pytest cases: version field present and equal to `server.__version__`; stable across successive calls.

**Acceptance Criteria:**
- Given `manifest.compatibleServerRange='>=99.0.0'` and `/api/admin/status.version='1.4.2'`, when the renderer invokes `window.electronAPI.updates.download()`, then it returns `{ok:false, reason:'incompatible-server', detail:{serverVersion:'1.4.2', compatibleRange:'>=99.0.0', deployment:'local'}}` and `UpdateInstaller.startDownload()` is NOT called.
- Given `manifest.compatibleServerRange='>=1.0.0 <2.0.0'` and the same server version, when `updates.download()` runs, then `startDownload()` is called and its `StartDownloadResult` is returned verbatim.
- Given the release lacks a `manifest.json` asset OR `/api/admin/status` returns 503 OR `.version` is absent, when `updates.download()` runs, then `[CompatGuard]` logs the specific unknown reason and `startDownload()` is still invoked (fail-open).
- Given a compatible `check()`, when it resolves, then `store.get('updates.lastManifest')` equals the parsed manifest (so M6 can read `sha256`).
- Given two concurrent `updates:checkCompatibility` calls, when both resolve, then only ONE pair of network fetches occurred.
- Given `cd dashboard && npm run typecheck && npm run test -- compatGuard` — zero errors, all new tests pass.
- Given `cd server/backend && ../../build/.venv/bin/pytest tests/test_admin_status_version.py -v` — passes.

## Design Notes

**Post-review defensive patches** (blind hunter + edge-case hunter findings classified `patch`, applied post-draft):
1. `isManifest` now requires `sha256` to have 1–32 entries, each value matching `/^[a-f0-9]{64}$/`; rejects keys named `__proto__` / `constructor` / `prototype`; requires `manifest.version` to pass `semver.valid()`. Defuses shape-based attacks on M6's future hash verifier.
2. Manifest asset download enforces a host allow-list (`github.com`, `api.github.com`, `objects.githubusercontent.com`) + HTTPS; a poisoned release payload cannot redirect the fetch to an attacker-controlled origin. Unfamiliar asset URL → `manifest-fetch-failed` with `detail: 'asset-url-rejected'`.
3. `Content-Length > 1 MB` on the manifest asset short-circuits to `manifest-fetch-failed` with `detail: 'oversized'` — DoS defense against a giant response body.
4. `releaseData.assets` is guarded with `Array.isArray` before `.find()`; a non-array shape (malformed API response, field renamed) now surfaces as `no-manifest` instead of throwing.
5. `fetchServerVersion` defends against `null` / non-object bodies from `/api/admin/status` — accessing `.version` on `null` no longer throws.
6. `getLastManifest()` wraps `store.get` in try/catch; a corrupt/locked electron-store returns `null` instead of propagating out of a read-side accessor.
7. `check()` guards against post-`destroy()` calls and short-circuits to `{result:'unknown', reason:'manifest-fetch-failed', detail:'destroyed'}` without any network I/O.
8. `updates:download` and `updates:checkCompatibility` IPC handlers wrap `compatGuard.check()` in try/catch. If the guard itself throws (library bug, store corruption), the download IPC falls through to `updateInstaller.startDownload()` (fail-open) and the checkCompatibility IPC returns a synthesized `unknown` — preserving the spec's fail-open principle even on internal compat-guard error.
9. `Accept: application/json` header added to the manifest asset fetch; a CDN returning an HTML error page with 200 status is routed to `manifest-parse-error` with clearer signal.

**Why fail-open on unknown:** Failing-closed would brick auto-update for every user on a pre-M4 server release (no `version` field) and for every transient GitHub/server outage. Downstream defenses are M6 (SHA-256 + watchdog rollback). M4 only guards against a specific mistake: shipping a Dashboard known to be incompatible.

**Why a live `updates:checkCompatibility` IPC and not just cached-manifest reads:** M5's pre-install modal needs a fresh compat verdict when the user opens it — the server may have been updated since the last `download` click. Reading stale cached values would be misleading.

**Manifest shape example:**
```json
{
  "version": "1.3.3",
  "compatibleServerRange": ">=1.4.0 <2.0.0",
  "sha256": { "TranscriptionSuite.AppImage": "abc..." },
  "releaseType": "stable"
}
```

## Verification

**Commands:**
- `cd dashboard && npm install` — resolves `semver` cleanly.
- `cd dashboard && npm run typecheck` — zero errors.
- `cd dashboard && npm run test -- compatGuard` — all new tests pass.
- `cd dashboard && npm run build:electron` — compiles.
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_admin_status_version.py -v` — passes.

**Manual gate (optional, Linux AppImage):** Edit a test release's `manifest.json` → `compatibleServerRange: '>=99.0.0'`. DevTools: `await window.electronAPI.updates.download()` → expect `{ok:false, reason:'incompatible-server', ...}` and `UpdateInstaller` state stays `idle`. Restore manifest → `download()` proceeds.

## Suggested Review Order

**Core primitive**

- Entry point — the `CompatGuard` class exposes `check()`, `getLastManifest()`, `destroy()` and owns the fail-open policy.
  [`compatGuard.ts:171`](../../dashboard/electron/compatGuard.ts#L171)

- `check()` single-flight + post-destroy short-circuit — callers after `destroy()` never re-enter the network path.
  [`compatGuard.ts:190`](../../dashboard/electron/compatGuard.ts#L190)

- `doCheck()` orchestrates manifest-fetch → destroy-gate → persist → server-version → semver eval → deployment branch.
  [`compatGuard.ts:228`](../../dashboard/electron/compatGuard.ts#L228)

**Manifest validation (hardening)**

- `isManifest()` is the tamper-resistant gate: semver-valid version, sha256 hex-regex, entry-count cap, `__proto__` guard.
  [`compatGuard.ts:123`](../../dashboard/electron/compatGuard.ts#L123)

- Host allow-list + HTTPS-only on the manifest asset URL; poisoned release payloads cannot redirect the fetch to an attacker origin.
  [`compatGuard.ts:153`](../../dashboard/electron/compatGuard.ts#L153)

- `Content-Length > 1 MB` short-circuits to `manifest-fetch-failed` with `detail: 'oversized'` — DoS defense.
  [`compatGuard.ts:162`](../../dashboard/electron/compatGuard.ts#L162)

**Network seams**

- `fetchManifest()` — two staged fetches (releases/latest, asset) with `Array.isArray` guard on `assets`, host allow-list, and Accept header on the asset pull.
  [`compatGuard.ts:304`](../../dashboard/electron/compatGuard.ts#L304)

- `fetchServerVersion()` — 5s probe of `/api/admin/status` with bearer token; tolerates null / non-object body and missing `.version`.
  [`compatGuard.ts:440`](../../dashboard/electron/compatGuard.ts#L440)

**Main-process wiring**

- `compatGuard` constructed right after `installGate` so IPC handlers can reference it.
  [`main.ts:510`](../../dashboard/electron/main.ts#L510)

- `updates:download` — pre-flight compat check with try/catch fail-open; short-circuits only on explicit `incompatible`.
  [`main.ts:1271`](../../dashboard/electron/main.ts#L1271)

- `updates:checkCompatibility` — the M5 modal's live verdict channel; also wrapped for fail-open.
  [`main.ts:1298`](../../dashboard/electron/main.ts#L1298)

- `compatGuard.destroy()` joins the cleanup block between `installGate.destroy()` and `updateInstaller.destroy()`.
  [`main.ts:1848`](../../dashboard/electron/main.ts#L1848)

**IPC surface**

- Preload bridge exposes `checkCompatibility`; widens `download()` return union with the new `incompatible-server` discriminant.
  [`preload.ts:551`](../../dashboard/electron/preload.ts#L551)

- Renderer ambient mirror adds `Manifest` + `CompatResult` types for type-safe consumers (M5 modal).
  [`electron.d.ts:189`](../../dashboard/src/types/electron.d.ts#L189)

**Shared helper export**

- `getServerUrl` + `getAuthToken` exported from `appState.ts` so `compatGuard.ts` shares the exact URL/token hierarchy with `isAppIdle`.
  [`appState.ts:7`](../../dashboard/electron/appState.ts#L7)

**Server change**

- `/api/admin/status` now carries `"version": __version__` — the authoritative server-version signal for both local Docker and remote-server deployments.
  [`admin.py:60`](../../server/backend/api/routes/admin.py#L60)

**Tests**

- 29 Vitest cases driving every I/O matrix row plus 10 post-review hardening cases (URL rejection, oversized content, null body, destroy race, throwing store, prototype-key guard).
  [`compatGuard.test.ts:1`](../../dashboard/electron/__tests__/compatGuard.test.ts#L1)

- 2 pytest cases confirming `/api/admin/status` includes `version == server.__version__` and is stable across calls.
  [`test_admin_status_version.py:1`](../../server/backend/tests/test_admin_status_version.py#L1)
