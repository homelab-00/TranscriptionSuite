---
title: 'In-app Update — M6 Safety Hardening (sha256 ambiguity, watchdog IPC heartbeat, manifest staleness)'
type: 'bugfix'
created: '2026-04-13'
status: 'done'
baseline_commit: '486aea0f84a8c4c5ca1aee96663bb8a833c16422'
context:
  - '{project-root}/CLAUDE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Three latent M6 safety defects surfaced by the M6 safety-errors review and carried on deferred-work.md:
1. `resolveExpectedSha256` falls back to the FIRST manifest entry that shares the downloaded file's extension. For v1 with one `.AppImage`/`.exe`/`.dmg` per platform this is safe; once a multi-arch manifest lists two `.AppImage` entries (x64 + arm64), the fallback cross-validates an arm64 binary against an x64 hash.
2. The launch-watchdog stability signal fires `confirmLaunchStable()` 10 s past the window's `ready-to-show` event. A renderer that crashes AFTER that point (e.g. JS exception at T=30 s during initial data load) still resets the per-version counter to 0, masking reproducible runtime crashes from the 3-strikes rollback.
3. `updates.lastManifest` is persisted indefinitely with no `fetchedAt` or TTL. A stale manifest that never refreshes (user disables update checks, long offline window, CI pause) fails-open every future verify even though the guard at `main.ts:493` catches the version-mismatch case.

**Approach:** Three surgical, cohesive hardening changes in the M6 subsystem: (1) reject same-extension fallback matches that are ambiguous (`>1` key shares the downloaded file's extension → fail-closed null, verifier logs + skips per the existing fail-open posture); (2) replace the `ready-to-show + 10 s` timer with an explicit renderer-side IPC heartbeat (`updates:rendererReady`) fired after React's initial mount — a truly-broken renderer never emits, so the counter stays incremented; (3) add a `fetchedAt: number` timestamp to the persisted manifest and enforce a 14-day TTL in `getLastManifest()` so stale manifests are treated as "no manifest available" (same verifier path).

## Boundaries & Constraints

**Always:**
- Ambiguity (`>1` matches) in the sha256 fallback MUST cause a null return and a `logger.warn`; the verifier's existing "no expected hash → skip with warn" path then runs, consistent with M6's fail-open stance.
- Renderer-side IPC heartbeat MUST be idempotent on the main side — repeated emits after the first are no-ops (second window open, dev-mode reload, StrictMode double-mount).
- `getLastManifest()` MUST treat a stale manifest (`now - fetchedAt > MANIFEST_TTL_MS`) exactly the same as a missing one: return null and log-warn. CompatGuard's `check()` refreshes `fetchedAt` on every successful persist.
- The 14-day TTL is defended only by the store read — no background sweep, no file unlink. On stale-read the verifier log must carry both timestamps so operators can distinguish "stale → refresh failing" from "never set".
- The `ready-to-show + 10 s` timer is REMOVED, not weakened. A broken renderer must accumulate launch attempts; reinstating a timer fallback would re-enable the masking defect.

**Ask First:**
- Whether to emit `updates:rendererReady` from a top-level `<App>` `useEffect` or from a lower component (e.g. `<SessionView>`) that signals a MORE-complete mount. v1 stance: top-level `<App>` — simplest, closes the race, further refinement is a later ticket.

**Never:**
- No background sweep/unlink of stale manifest entries — persistence is read-side only.
- No preload surface expansion for the heartbeat beyond one method (`app.reportRendererReady()`).
- No manifest schema change (`artifacts` block, per-arch keys) — the sha256-ambiguity fix lives entirely inside `resolveExpectedSha256` + verifier.
- No change to the `manifest.version === version` guard at `main.ts:493` — it stays as the primary wrong-version filter; staleness TTL is an additional layer.

## I/O & Edge-Case Matrix

| Scenario | State | Expected Behavior |
|---|---|---|
| sha256: exact basename match (current v1) | manifest has `TranscriptionSuite-1.3.3.AppImage` matching downloaded file | Return hash; verify proceeds (unchanged). |
| sha256: one `.AppImage` entry, basename mismatch | manifest has canonical `TranscriptionSuite.AppImage`; downloaded `TranscriptionSuite-1.3.3.AppImage` | Fallback returns the single match; verify proceeds (unchanged). |
| sha256: `>1` `.AppImage` entries (future multi-arch) | manifest has `TranscriptionSuite-x64.AppImage` + `TranscriptionSuite-arm64.AppImage`; downloaded file `TranscriptionSuite-1.3.3.AppImage` | Fallback detects ambiguity → null + warn; verifier skips per existing "no hash available" path. |
| Watchdog: normal launch | renderer mounts within first 30 s | `updates:rendererReady` fires once; main calls `confirmLaunchStable()`; counter reset to 0. |
| Watchdog: renderer crashes pre-mount | JS bundle crash during initial paint | No `updates:rendererReady`; counter stays at N; next launch increments; 3rd attempt triggers rollback dialog. |
| Watchdog: renderer crashes post-mount (runtime defect) | mount completes (IPC fires, counter → 0), crash at T=30 s | Counter reset happened but subsequent crashes re-increment on next launch. Single runtime crash does NOT trigger rollback in one session — same contract as M6 (watchdog is boot-crash focused). Documented, not regressed. |
| Manifest: fresh persist | CompatGuard check succeeds | `fetchedAt: Date.now()` stored; `getLastManifest()` returns it. |
| Manifest: stale read | `now - fetchedAt > 14 * 24h` | `getLastManifest()` returns null + warn; verifier skips. |
| Manifest: missing `fetchedAt` key (legacy stored shape) | upgrade from pre-TTL build | `getLastManifest()` treats missing `fetchedAt` as stale (null); next CompatGuard check re-persists with fresh timestamp. |

</frozen-after-approval>

## Code Map

- `dashboard/electron/main.ts` (resolveExpectedSha256 ~L598-614, mainWindow ready-to-show ~L802-814) — tighten fallback ambiguity; remove timer; add `ipcMain.on('updates:rendererReady')` handler.
- `dashboard/electron/launchWatchdog.ts` — no code change; `confirmLaunchStable()` becomes IPC-driven only.
- `dashboard/electron/compatGuard.ts` (Manifest type ~L70-82, persist path writing `updates.lastManifest`, getLastManifest ~L208-220) — extend `Manifest` type with optional `fetchedAt: number`; `check()` stamps before persist; `getLastManifest()` filters on TTL.
- `dashboard/electron/preload.ts` — add `app.reportRendererReady()` method.
- `dashboard/src/types/electron.d.ts` — add the new preload method signature.
- `dashboard/App.tsx` — new `useEffect` (empty deps) that calls `window.electronAPI.app.reportRendererReady()` once on mount.
- `dashboard/electron/__tests__/compatGuard.test.ts` — new staleness tests.
- `dashboard/electron/__tests__/main-resolveSha256.test.ts` (new file, OR extract helper + test) — ambiguity tests. If `resolveExpectedSha256` stays a non-exported helper in main.ts, extract it to a new small module `dashboard/electron/sha256Lookup.ts` so it's unit-testable. This is a necessary extraction, not a scope-creep refactor.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/sha256Lookup.ts` (NEW) — Extract `resolveExpectedSha256` verbatim from main.ts. Tighten fallback: instead of returning the first `endsWith(ext)` match, collect all matches; if exactly 1, return it; if 0, return null (unchanged); if `>1`, return null AND take a `logger?: { warn }` parameter so the caller can log `"sha256 ambiguous: N matches share extension <ext>"`. Export `resolveExpectedSha256` and a const `AMBIGUOUS_SENTINEL` (just for test readability). Re-import into main.ts; pass `console` as the logger.
- [x] `dashboard/electron/compatGuard.ts` — Extend `Manifest` interface with optional `fetchedAt?: number`. Add `MANIFEST_TTL_MS = 14 * 24 * 60 * 60 * 1000`. In `check()`'s success-persist path, stamp `fetchedAt: Date.now()` immediately before `store.set(MANIFEST_STORE_KEY, manifest)`. In `getLastManifest()`, after the existing shape validation, if `fetchedAt` is missing or `Date.now() - fetchedAt > MANIFEST_TTL_MS` → `logger.warn('getLastManifest: manifest is stale', { fetchedAt, ageMs })` → return null. No other path change.
- [x] `dashboard/electron/main.ts` — Delete the `ready-to-show + STABLE_LAUNCH_CONFIRM_MS` timer block (~L798-814) including `stableLaunchTimer` declaration (~L658), the on-closed cleanup (~L818-821), and `STABLE_LAUNCH_CONFIRM_MS` const. Add `ipcMain.on('updates:rendererReady', () => { try { launchWatchdog.confirmLaunchStable(); } catch (err) { console.warn('[LaunchWatchdog] IPC confirmLaunchStable failed:', err); } });` near other ipcMain handlers. Because `confirmLaunchStable` is itself idempotent (no-op if no record), repeat emits are safe.
- [x] `dashboard/electron/preload.ts` — Add `reportRendererReady: () => ipcRenderer.send('updates:rendererReady')` under the existing `app` namespace in `contextBridge.exposeInMainWorld`.
- [x] `dashboard/src/types/electron.d.ts` — Add `reportRendererReady: () => void` to the `app` interface.
- [x] `dashboard/App.tsx` — Add a `useEffect(() => { try { window.electronAPI?.app?.reportRendererReady?.(); } catch {} }, [])` near the top of the component body so it runs exactly once per mount. The optional chain guards non-Electron runtimes (browser dev mode); the try/catch guards preload mismatch.
- [x] `dashboard/electron/__tests__/sha256Lookup.test.ts` (NEW) — Cover: exact-match hit; 0-match miss; 1-match fallback hit (existing behavior); `>1`-match ambiguity → null + logger.warn called with expected substring; no logger passed → still null (no throw).
- [x] `dashboard/electron/__tests__/compatGuard.test.ts` — Add: fresh `check()` stamps `fetchedAt`; `getLastManifest()` with fresh timestamp returns manifest; with `fetchedAt` older than TTL returns null + warn; with missing `fetchedAt` (legacy shape) returns null. Update existing `setSpy.toHaveBeenCalledWith(MANIFEST_STORE_KEY, STABLE_MANIFEST)` assertions that will now see a timestamped object — use `expect.objectContaining({ version, fetchedAt: expect.any(Number) })`.

**Acceptance Criteria:**
- Given a manifest with two `.AppImage` entries and a download matching neither exact basename, when the verifier resolves expected hash, then null is returned, a warn is logged, and the verifier proceeds with its existing "no expected hash → skip" behavior (install proceeds, unverified, same as missing-manifest path).
- Given a launch where the renderer mounts successfully, when the App `useEffect` fires `reportRendererReady`, then main receives `updates:rendererReady` exactly once and the launch-attempt counter for the current version is reset to 0.
- Given a launch where the renderer never mounts (bundle crash, preload failure), when the app is force-quit, then the launch-attempt counter stays at its incremented value; after the 3rd such failed launch, the rollback dialog is offered (existing `recordLaunchAttempt` behavior unchanged).
- Given a persisted manifest with `fetchedAt` older than 14 days, when any consumer calls `getLastManifest()`, then it returns null and the verifier falls through to its "no manifest persisted" warn-and-skip path.
- Given a manifest persisted before this change (no `fetchedAt` field), when `getLastManifest()` reads it, then it returns null; the next `check()` re-persists with a fresh timestamp.
- Given the app running in browser/dev mode (no `electronAPI`), when `<App>` mounts, then the `reportRendererReady` optional-chain no-ops and no error is thrown.

## Design Notes

**Why remove the `ready-to-show + 10 s` timer rather than shorten it:** the defect is that the timer's stability signal is decoupled from actual renderer health. Any timer-based signal is vulnerable to the same mask — the renderer can crash after the timer fires. The only signal that can't be masked is one emitted BY the renderer when it's demonstrably alive. Keeping the timer as a "safety net" would reintroduce the exact masking seam we're closing.

**Why 14-day TTL rather than 24 h:** the default update-check cadence is 24 h. A TTL of 24 h would mark the manifest stale at the exact moment the next check would refresh it — thrashing. 14 days covers: users who pause checks for a week, laptops offline over long weekends, CI manifest outages. The cost of a stale read is one fail-open install (matching missing-manifest behavior); the cost of too-short TTL is churn + warn-spam.

**Why sha256Lookup extraction isn't scope creep:** `resolveExpectedSha256` is currently a non-exported helper embedded in main.ts. Testing it requires either a full IPC integration test or an ad-hoc re-export. Pulling it into a dedicated 20-line module with its own test file is the minimum change that makes the ambiguity-detection testable at the unit level — which is what the acceptance criteria require. Matches the precedent set by `dashboard/electron/releaseUrl.ts` (extracted from main.ts for the same reason).

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` — expected: clean.
- `cd dashboard && npx vitest run electron/__tests__/sha256Lookup.test.ts electron/__tests__/compatGuard.test.ts` — expected: all existing + new pass.
- `cd dashboard && npx vitest run` — full suite; no regressions elsewhere (App.tsx useEffect, preload surface).
- `cd dashboard && npm run ui:contract:check` — clean.

**Manual checks:**
- Launch Dashboard → observe `[LaunchWatchdog]` log (or add one-liner debug) showing `confirmLaunchStable` triggered by IPC, not by the now-removed timer.
- Simulate renderer crash (introduce temporary `throw` in `<App>`) → relaunch 3× → rollback dialog appears (Linux AppImage with cached installer present).
- Edit `electron-store`'s `updates.lastManifest.fetchedAt` to 20 days ago → trigger update → verifier logs "manifest is stale" and skips verification.

## Spec Change Log

_2026-04-14 (step-04 patches applied in-review):_
- Narrowed `getLastManifest()` return type to `(Manifest & { fetchedAt: number }) | null` — the Manifest interface keeps `fetchedAt?: number` for the network-payload shape, but the read-side accessor now guarantees non-optional after TTL validation. Avoids callers pattern-matching on `fetchedAt === undefined` on a validated manifest.
- Added negative-`ageMs` clock-skew defense — a future-stamped or backward-clock-corrected manifest would otherwise pass `> MANIFEST_TTL_MS` indefinitely. Logger reason now distinguishes `'clock-skew-negative-age'` from `'ttl-exceeded'`.
- Tightened sha256Lookup ambiguity test to pin the second (structured-context) warn argument shape — catches refactors that drop the `{ downloaded, candidates }` object without altering the message string.
- compatGuard test now imports `MANIFEST_TTL_MS` instead of inlining the 14-day literal — one source of truth.
- IPC handler `updates:rendererReady` gates on `event.sender === mainWindow.webContents` — defends against future secondary BrowserWindow mounts resetting the counter from an untrusted source.

## Suggested Review Order

**Core design — sha256 ambiguity fails-closed**

- Entry point: the new predicate refuses to guess when `>1` manifest entries share the downloaded file's extension. Pre-multi-arch spoofing seam closed.
  [`sha256Lookup.ts:26`](../../dashboard/electron/sha256Lookup.ts#L26)

- Call site: verifier now passes `console` as logger so ambiguity warnings flow into the main-process log.
  [`main.ts:503`](../../dashboard/electron/main.ts#L503)

**Launch watchdog — timer → IPC heartbeat**

- Removed the `ready-to-show + 10 s` timer block; the only signal that can't be masked is one emitted by the renderer when it's demonstrably alive.
  [`main.ts:631`](../../dashboard/electron/main.ts#L631)

- IPC handler calls `confirmLaunchStable` on renderer-ready; sender-gated to `mainWindow` to prevent secondary BrowserWindow bypass.
  [`main.ts:1486`](../../dashboard/electron/main.ts#L1486)

- Preload exposes one new fire-and-forget method under the existing `app` namespace — no new IPC surface expansion.
  [`preload.ts:410`](../../dashboard/electron/preload.ts#L410)

- Renderer emits after initial React mount; optional-chain + try/catch guards non-Electron runtimes and preload/main version mismatch.
  [`App.tsx:91`](../../dashboard/App.tsx#L91)

**Manifest staleness — TTL on read + fetchedAt on write**

- `Manifest.fetchedAt?` added (optional on network payload; required after read-side TTL validation via narrowed return type).
  [`compatGuard.ts:91`](../../dashboard/electron/compatGuard.ts#L91)

- `MANIFEST_TTL_MS = 14 days` — covers long-weekend offline windows without thrashing the 24 h poll cadence.
  [`compatGuard.ts:102`](../../dashboard/electron/compatGuard.ts#L102)

- `getLastManifest()` with narrowed return + clock-skew defense + legacy-shape fail-closed.
  [`compatGuard.ts:228`](../../dashboard/electron/compatGuard.ts#L228)

- Stamp site: `fetchedAt: Date.now()` inserted immediately before the persist call so the TTL clock starts exactly at write time.
  [`compatGuard.ts:297`](../../dashboard/electron/compatGuard.ts#L297)

**Test coverage**

- sha256 ambiguity — truth table with structured-context shape assertions.
  [`sha256Lookup.test.ts:1`](../../dashboard/electron/__tests__/sha256Lookup.test.ts#L1)

- Manifest staleness — fresh stamp + fresh read + stale TTL + missing-fetchedAt legacy + NaN corruption + clock-skew negative age.
  [`compatGuard.test.ts:430`](../../dashboard/electron/__tests__/compatGuard.test.ts#L430)
