---
title: 'Issue #105 — Auto-update suggests updating to the already-installed version'
type: 'bugfix'
created: '2026-04-26'
status: 'done'
baseline_commit: '9515c83da08bcf43992d690815535b2c54fba281'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** After the user upgrades the Dashboard (e.g. 1.3.2 → 1.3.3), the persisted `updates.lastStatus.app` written by the previous version still has `updateAvailable: true, latest: '1.3.3', current: '1.3.2'`. On the new launch, `UpdateManager.getStatus()` returns that record verbatim, so `UpdateBanner` paints the "1.3.3 available — Download" banner. Clicking Download opens the pre-install modal labelled `v1.3.3 → v1.3.3` (Issue #105 screenshot). The stale state survives until the next periodic check completes.

**Approach:** Re-derive `app.updateAvailable` and rewrite `app.current` against the running `app.getVersion()` at every `UpdateManager.getStatus()` call so persisted truth never beats runtime truth. Add a defensive guard in `UpdateInstaller.startDownload()` that respects electron-updater's `result.isUpdateAvailable` (which our seam currently ignores in favour of the always-populated `updateInfo`) so a Download click on an equal-version state cleanly returns `no-update-available`.

## Boundaries & Constraints

**Always:**
- `UpdateManager.getStatus()` stays synchronous (renderer polls it every 60 s; making it async would ripple).
- Re-derivation uses the same `parseSemVer` + `compareSemVer` helpers as `checkApp()` — no second comparison library.
- Persisted `lastStatus.app.error` and `releaseNotes` are passed through unchanged when re-deriving.
- The fix preserves the existing dedup of `updates.lastNotified.appLatest` / `serverLatest` — `maybeNotify` is unaffected because it operates on freshly-computed status from `check()`, not on `getStatus()`.

**Ask First:**
- Whether to extend the same re-derivation to `lastStatus.server` (Docker-image channel can have the same staleness if the user pulls a newer image manually). Default answer for this spec: no — keep server out of scope; the bug report and screenshot are dashboard-only and `current` for server is read fresh from `dockerManager.listImages()` at check time anyway.

**Never:**
- Do not reset/clear the persisted `lastStatus` on app launch — that would lose the last-known `latest` and force a network round-trip before the banner can ever appear.
- Do not change `checkApp()`'s comparison itself — it is correct; only the read-back path is broken.
- Do not call `app.getVersion()` from module top-level (Electron `app` may not be ready in test imports).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Upgrade race | persisted `app: { current: '1.3.2', latest: '1.3.3', updateAvailable: true }`, running `app.getVersion() === '1.3.3'` | `getStatus()` returns `app.current === '1.3.3'`, `app.updateAvailable === false`, `app.latest === '1.3.3'` (preserved) | N/A |
| Genuine update | persisted `app: { current: '1.3.3', latest: '1.4.0', updateAvailable: true }`, running `1.3.3` | `getStatus()` returns `app.updateAvailable === true`, `app.current === '1.3.3'` | N/A |
| Pre-release running | persisted `app: { current: '1.3.3', latest: '1.3.3', updateAvailable: false }`, running `app.getVersion() === '1.4.0-beta.1'` (unparsable by strict X.Y.Z) | `getStatus()` returns `app.updateAvailable === false`, `app.current === '1.4.0-beta.1'` | parse failure → `updateAvailable = false` |
| No persisted status | `store.get('updates.lastStatus')` returns `undefined` | `getStatus()` returns `null` (unchanged behaviour) | N/A |
| Installer race | electron-updater `checkForUpdates()` returns `{ isUpdateAvailable: false, updateInfo: { version: '1.3.3' } }` | `startDownload()` transitions installer to `idle`, returns `{ ok: false, reason: 'no-update-available' }` | no `downloading` state, no error toast |
| Older shape | persisted status from version before this fix has `app: { current: '1.3.2', updateAvailable: true }` | Same re-derivation applies; no schema migration needed | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/electron/updateManager.ts` -- root cause: `getStatus()` returns persisted `lastStatus` verbatim; `parseSemVer` + `compareSemVer` are private and need to be reused for the re-derivation.
- `dashboard/electron/updateInstaller.ts` -- defensive layer: `startDownload()` checks `!result.updateInfo` instead of `!result.isUpdateAvailable`; `AutoUpdaterLike` seam misses the `isUpdateAvailable` field.
- `dashboard/electron/__tests__/updateManager.test.ts` -- existing test style (vi.mock electron, `getVersion: () => '1.0.0'`); add `getStatus`-rederivation cases.
- `dashboard/electron/__tests__/updateInstaller.test.ts` -- existing fake `AutoUpdaterLike` setup; add a case where `isUpdateAvailable: false` but `updateInfo` is present.
- `dashboard/components/ui/UpdateBanner.tsx` -- consumer; reads `updateStatus.app.updateAvailable` for `deriveBannerState`. No change needed once `getStatus()` is fixed; verify via mental trace.
- `dashboard/components/ui/UpdateModal.tsx` -- consumer; renders `v{currentVersion} → v{targetVersion}` header. No change needed.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/updateManager.ts` -- in `getStatus()`, after loading the persisted record, build a fresh `app` object: set `current = app.getVersion()`, parse both `current` and `stored.app.latest`, recompute `updateAvailable = currentSv !== null && latestSv !== null && compareSemVer(latestSv, currentSv) > 0`, preserve `error` and `releaseNotes`. Server slice is passed through unchanged. -- root-cause fix.
- [x] `dashboard/electron/updateInstaller.ts` -- add `isUpdateAvailable?: boolean` to `AutoUpdaterLike.checkForUpdates`'s return shape; in `startDownload()`, after the existing `!result || !result.updateInfo` check, also bail with `{ state: 'idle' }` + `{ ok: false, reason: 'no-update-available' }` when `result.isUpdateAvailable === false`. -- defense-in-depth.
- [x] `dashboard/electron/__tests__/updateManager.test.ts` -- add `describe('getStatus re-derivation')` block covering the four `getStatus` rows of the I/O Matrix (upgrade race, genuine update, pre-release running, no persisted status). Use the existing `vi.mock('electron', { app: { getVersion: () => '...' } })` pattern; bump the mocked `getVersion` per test via `vi.mocked` or by re-mocking. -- regression coverage.
- [x] `dashboard/electron/__tests__/updateInstaller.test.ts` -- add a case asserting `startDownload()` returns `{ ok: false, reason: 'no-update-available' }` and the installer status is `idle` (not `downloading`) when the fake `checkForUpdates()` resolves with `{ isUpdateAvailable: false, updateInfo: { version: '1.3.3' } }`. -- defensive-layer coverage.

**Acceptance Criteria:**
- Given a user upgrades the Dashboard from 1.3.2 to 1.3.3 with `updateChecksEnabled: true`, when the Dashboard launches and the renderer polls `updates.getStatus()` before the new periodic check completes, then the returned `app.updateAvailable` is `false` and `app.current` equals `'1.3.3'`, and the UpdateBanner stays hidden.
- Given the persisted `updates.lastStatus.app.latest` is genuinely newer than `app.getVersion()`, when `getStatus()` is called, then `app.updateAvailable` is `true` and the banner appears as before — no regression of the real "update available" path.
- Given a Download click drives `UpdateInstaller.startDownload()` and electron-updater reports `isUpdateAvailable: false`, when `startDownload()` runs, then the installer status remains `idle` (no transient `downloading` state, no `error` toast) and the IPC return is `{ ok: false, reason: 'no-update-available' }`.
- `npm run typecheck` from `dashboard/` passes.
- The two new test blocks pass under `npx vitest run dashboard/electron/__tests__/updateManager.test.ts dashboard/electron/__tests__/updateInstaller.test.ts`.

## Design Notes

The re-derivation lives in the main process (UpdateManager) rather than the renderer (UpdateBanner) because the renderer doesn't ship `parseSemVer` and shouldn't grow a duplicate of the comparison code. Doing it once at the source keeps every consumer (banner, SettingsModal status block, modal header) consistent for free.

Renaming or exporting `parseSemVer` / `compareSemVer` is **not** required — they're module-private and `getStatus()` lives in the same file. Keep them private.

Sketch (illustrative — final code may differ):

```ts
getStatus(): UpdateStatus | null {
  const stored = (this.store.get('updates.lastStatus') as UpdateStatus) ?? null;
  if (!stored) return null;
  const currentVersion = app.getVersion();
  const currentSv = parseSemVer(currentVersion);
  const latestSv = stored.app.latest ? parseSemVer(stored.app.latest) : null;
  const updateAvailable =
    currentSv !== null && latestSv !== null && compareSemVer(latestSv, currentSv) > 0;
  return {
    ...stored,
    app: { ...stored.app, current: currentVersion, updateAvailable },
  };
}
```

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` -- expected: 0 errors.
- `cd dashboard && npx vitest run electron/__tests__/updateManager.test.ts electron/__tests__/updateInstaller.test.ts` -- expected: all green, including the four new cases.
- `cd dashboard && npx vitest run components/ui/__tests__/UpdateBanner.test.tsx components/ui/__tests__/UpdateModal.test.tsx` -- expected: still green (no consumer regressions).

**Manual checks:**
- Open `_bmad-output/implementation-artifacts/spec-gh-105-stale-update-banner.md` and confirm the I/O matrix scenarios match what the new tests assert.

## Suggested Review Order

**Root cause — runtime truth beats persisted truth**

- Re-derives `app.current` and `app.updateAvailable` at every read so a persisted record from the pre-upgrade run cannot lie.
  [`updateManager.ts:287`](../../dashboard/electron/updateManager.ts#L287)

**Defense layer — installer respects electron-updater's real signal**

- Strict `=== false` guard pinned with a comment so a future "simplify to `!isUpdateAvailable`" doesn't break older-updater pass-through.
  [`updateInstaller.ts:255`](../../dashboard/electron/updateInstaller.ts#L255)

- Seam expansion that lets the test fakes drive `isUpdateAvailable` per case.
  [`updateInstaller.ts:137`](../../dashboard/electron/updateInstaller.ts#L137)

**Tests — pin the I/O matrix and the bug repro**

- Upgrade-race repro: persisted `updateAvailable: true` from 1.3.2 turns into `false` once running on 1.3.3.
  [`updateManager.test.ts:336`](../../dashboard/electron/__tests__/updateManager.test.ts#L336)

- Installer never enters `downloading` when the fresh check reports `isUpdateAvailable: false`.
  [`updateInstaller.test.ts:138`](../../dashboard/electron/__tests__/updateInstaller.test.ts#L138)

- Backward-compat: `isUpdateAvailable` undefined still proceeds (legacy electron-updater path).
  [`updateInstaller.test.ts:164`](../../dashboard/electron/__tests__/updateInstaller.test.ts#L164)

**Test scaffolding — versionRef hoisting + describe-level reset**

- Hoisted mutable ref allows per-test `app.getVersion()` overrides without reset-modules ceremony.
  [`updateManager.test.ts:11`](../../dashboard/electron/__tests__/updateManager.test.ts#L11)

- Top-level `afterEach` defends against future describe blocks leaking version-ref mutations across tests.
  [`updateManager.test.ts:307`](../../dashboard/electron/__tests__/updateManager.test.ts#L307)

