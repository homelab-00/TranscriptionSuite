---
title: 'M6: Safety & error handling for in-app Dashboard updates'
type: 'feature'
created: '2026-04-13'
status: 'done'
baseline_commit: '14600e902264f71ce082e8544d88ab3db1eefd4c'
context:
  - '{project-root}/_bmad-output/brainstorming/brainstorming-session-2026-04-12-in-app-updates.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-m1-electron-updater.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-m4-compat-guard.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** M1–M5 wire the happy path but leave three gaps: (1) `UpdateInstaller` doesn't cross-check the SHA-256 that M4 persists to `updates.lastManifest` — a corrupted asset reaches install; (2) a new version that crashes on launch bricks the user (no rollback); (3) download/install failures reach the renderer as silent `console.error` (M2's deferred item) so the banner freezes with no feedback.

**Approach:** Verify SHA-256 between `update-downloaded` and the `downloaded` state via a new streaming verifier. Cache the running AppImage to `userData/previous-installer/` just before `quitAndInstall()`. A launch-attempt counter keyed on `app.getVersion()` offers a native restore dialog once count ≥ 3. `UpdateBanner` toasts installer `error` with `[Retry]`. `UpdateManager.check()` arms a single-shot 1 h retry on failure.

## Boundaries & Constraints

**Always:**
- New `dashboard/electron/checksumVerifier.ts` exports `verifyChecksum(filePath, expectedHex): Promise<{ ok: boolean; actual?: string }>`. Stream-hashed via `crypto.createHash('sha256')`; lowercase-hex compare; never loads the full file.
- New `dashboard/electron/installerCache.ts` exports `cachePreviousInstaller({ sourcePath, version, userDataDir })`, `getCachedInstaller(userDataDir)`, `restoreCachedInstaller({ cachedPath, targetPath })`. Cache dir `userDataDir/previous-installer/`; keep exactly one file (unlink older before write). Non-Linux callers return `{ ok:false, reason:'platform-not-supported' }` without side effects.
- New `dashboard/electron/launchWatchdog.ts` exports class `LaunchWatchdog` with `recordLaunchAttempt(currentVersion): { count; shouldPromptRestore }`, `confirmLaunchStable(): void`, `destroy()`. Persists `updates.launchAttempts = { version, count }`. `shouldPromptRestore` is true iff `count >= 3` AND `getCachedInstaller()` returns a different version. Version change resets store to `{ version: current, count: 1 }`.
- `updateInstaller.ts` constructor gains two optional deps: `verifier(filePath, version) => Promise<{ ok; reason? }>` and `cacheHook(ctx) => Promise<void>`. Widen `InstallerStatus` with `| { state:'verifying'; version: string }`. `update-downloaded` goes `verifying` → (verifier) → `downloaded` OR `error { message:'checksum-mismatch' }` (unlink file on mismatch). Undefined verifier = no verifying state (preserves test behavior). `install()` awaits `cacheHook` BEFORE `quitAndInstall()`; hook rejection is logged, install still proceeds. Mirror `verifying` in `preload.ts` and `src/types/electron.d.ts`.
- `main.ts` wires: verifier reads `compatGuard.getLastManifest()`, looks up expected hash via new `resolveExpectedSha256(manifest, filename)` helper (exact-key first, then same-extension fallback). Cache hook uses `process.env.APPIMAGE` on Linux, no-ops elsewhere. `LaunchWatchdog` instantiated at startup; `recordLaunchAttempt(app.getVersion())` runs before window creation; `dialog.showMessageBox` with `[Restore previous version]` / `[Continue]` when `shouldPromptRestore`. `[Restore]` → `shell.openPath(previous-installer dir)` + info dialog instructing manual swap. `confirmLaunchStable()` fires 10 s after `mainWindow.on('ready-to-show')`. Watchdog added to the `gracefulShutdown()` teardown.
- `updateManager.ts` — on `checkApp()`/`checkServer()` catch paths OR when either component `error` is non-null, arm single-shot `failureRetryTimer = setTimeout(check, 3_600_000)`. Clear on next successful full check AND in `destroy()`. Existing `setInterval` untouched.
- `UpdateBanner.tsx` subscribes to installer transitions; on `state === 'error'` with a message not already shown (dedup by message), calls `toast.error('Update failed: ' + msg, { action: { label:'Retry', onClick: api.download } })`. `checksum-mismatch` gets copy `"Downloaded update failed integrity check. Retry to download again."`.
- Missing or unknown-asset manifests: log warn, skip verification, flip to `downloaded` (fail-open consistent with M4). Mismatches still fail closed.
- Tests: new `checksumVerifier.test.ts` (match/mismatch/missing-file), `installerCache.test.ts` (fresh/overwrite/non-linux), `launchWatchdog.test.ts` (version-reset/increment/stable-reset/prompt-threshold/no-cache-suppresses-prompt). Extend `updateInstaller.test.ts` (verifier pass/fail/no-verifier, cache-hook pass/throw). Extend `updateManager.test.ts` (retry armed/cleared/destroy). Extend `UpdateBanner.test.tsx` (one toast per unique message, retry dispatches download). No existing tests regress.

**Ask First:**
- Any change to `manifest.json` shape or `Manifest` type (frozen by M4).
- Rollback beyond "open cache folder + instruct manual swap" (e.g. helper-process overwrite).
- Surfacing network-failure to the user (brainstorming keeps it silent).
- Windows/macOS cache + watchdog — deferred to M7.

**Never:**
- Do NOT read the binary whole-file to hash — stream only.
- Do NOT cache or watchdog-rollback on Win/Mac in M6.
- Do NOT auto-execute the cached installer — Linux can't overwrite a running AppImage.
- Do NOT fail a download when the manifest is absent or lacks the expected asset key — fail-open warning; mismatch only fails closed.
- Do NOT touch `gracefulShutdown`'s idle wait (owned by M3) or invalidate `updates.lastManifest` (owned by M4).
- Do NOT widen the watchdog counter to non-update crashes — keyed by `app.getVersion()` only.
- Do NOT add telemetry; all failure signals stay local.

## I/O & Edge-Case Matrix

| Scenario | Expected Behavior |
|---|---|
| Checksum matches | `verifying` → `downloaded`; no toast. |
| Checksum mismatches | `verifying` → `error{checksum-mismatch}`; file unlinked; banner toast with integrity copy + [Retry]. |
| Manifest null or asset key absent | warn-log; skip verify; flip to `downloaded`. |
| Download error from electron-updater | existing `error` state; new toast "Update failed: <msg>" + [Retry]. |
| `install()` on Linux with APPIMAGE set | cache hook copies binary to `userData/previous-installer/<version>.AppImage`; older cache unlinked; `quitAndInstall` fires once. |
| `install()` on Win/Mac (no APPIMAGE) | cache hook no-ops; install proceeds. |
| Cache-hook throws (ENOSPC etc.) | error logged; `quitAndInstall` still fires. |
| First launch of new version | store → `{version:current, count:1}`; no dialog. |
| Third failed launch + cache exists for different version | dialog shown; `[Restore]` opens folder + instructs; `[Continue]` dismisses. |
| Third failed launch + cache absent/same-version | no dialog; count stays. |
| Stable launch (ready-to-show + 10 s) | counter → 0. |
| `check()` throws | `failureRetryTimer` armed for 1 h. |
| `check()` succeeds (both components error-null) | retry timer cleared. |
| `destroy()` during retry / download / watchdog lifetime | all timers cleared; no late callbacks. |
| Repeated installer `error` with same message | single toast per unique message string. |

</frozen-after-approval>

## Code Map

- `dashboard/electron/checksumVerifier.ts` — NEW, streaming sha256 compare.
- `dashboard/electron/installerCache.ts` — NEW, Linux AppImage cache manager.
- `dashboard/electron/launchWatchdog.ts` — NEW, per-version counter + prompt gate.
- `dashboard/electron/updateInstaller.ts` — add `verifier`/`cacheHook` deps, `verifying` state, mismatch unlink.
- `dashboard/electron/updateManager.ts` — 1 h failure-retry timer; widen `InstallerStatus`.
- `dashboard/electron/preload.ts`, `dashboard/src/types/electron.d.ts` — mirror `verifying`.
- `dashboard/electron/main.ts` — wire all three modules + `resolveExpectedSha256` helper; watchdog dialog + stable reset; extend `gracefulShutdown` teardown.
- `dashboard/components/ui/UpdateBanner.tsx` — error-state toast subscriber with retry + dedup.
- Tests (new): `checksumVerifier.test.ts`, `installerCache.test.ts`, `launchWatchdog.test.ts`.
- Tests (extend): `updateInstaller.test.ts`, `updateManager.test.ts`, `UpdateBanner.test.tsx`.

Not changed: `compatGuard.ts`, `installGate.ts`, `appState.ts`, `UpdateModal.tsx`, `dockerManager.ts`.

## Spec Change Log

- **2026-04-13 — post-draft hardening (patches applied in-review):**
  - `install()` changed from sync to `async` and now `await`s `cacheHook` BEFORE `quitAndInstall()`. Previous fire-and-forget raced Electron shutdown and could truncate the cache file on slow disks. `InstallGate.doInstall` signature already expected `Promise<{ ok; reason? }>`, so no caller change.
  - `install()` rejects with `reason: 'no-version'` when `currentVersion` is null — prevents writing a bogus `unknown.AppImage` cache entry that would permanently trigger the watchdog's restore dialog.
  - `main.ts` verifier now fails-open when `manifest.version !== version`. Prior behavior would fail every download after an upgrade because `compatGuard.getLastManifest()` could still hold the older version's sha256 table. Fail-open is consistent with M4 and with the spec's "unknown asset filename in manifest → skip verification" row.
  - `runVerification` re-checks `this.status.state === 'verifying'` AFTER the `fsp.unlink` await before calling `setStatus({state:'error'})`. Without this guard a cancellation that lands during the unlink would have been silently overwritten by the error state.
  - `UpdateManager` gained a `destroyed` flag. `check()` short-circuits with stub errors when destroyed (no store write); `scheduleFailureRetry` refuses to arm post-destroy and the timer callback re-checks the flag before dispatching. Prevents a late in-flight `check()` awaiting fetch across a `gracefulShutdown` teardown from re-scheduling a timer on a dead manager.
  - `LaunchWatchdog.recordLaunchAttempt` now rejects `count` values that aren't finite non-negative integers below 1000. `Infinity`, `-1`, `NaN`, and overflow scenarios previously either suppressed the rollback prompt forever or triggered it bogusly.
  - Three new test cases cover the above: `LaunchWatchdog` pathological-count suppression, `UpdateManager` post-destroy short-circuit, and `UpdateInstaller` `install()` no-version rejection. Existing cacheHook test now asserts the strict `['cached:1.3.3', 'quitAndInstall']` ordering rather than the previous loose "cached was first" assertion.

## Tasks & Acceptance

**Execution:**
- [x] `checksumVerifier.ts` — streaming sha256 match helper (`verifyChecksum`).
- [x] `installerCache.ts` — `cachePreviousInstaller` / `getCachedInstaller` / `restoreCachedInstaller`, Linux-only gate, 1-file slot.
- [x] `launchWatchdog.ts` — `LaunchWatchdog` class; per-version counter; `shouldPromptRestore` predicate; `confirmLaunchStable` resets to 0.
- [x] `updateInstaller.ts` — 3rd constructor arg (`verifier`, `cacheHook`); `verifying` transitional state; on mismatch unlinks downloaded file + flips to `error{checksum-mismatch}`; `cancelDownload` now accepts `verifying`; `install()` fires `cacheHook` before `quitAndInstall`.
- [x] `updateManager.ts` — `failureRetryTimer` single-shot at `FAILURE_RETRY_MS` (1 h); armed when either component errors; cleared on clean check and in `destroy()`; widened `InstallerStatus` with `verifying`.
- [x] `preload.ts` + `src/types/electron.d.ts` — mirrored `verifying`.
- [x] `main.ts` — verifier reads `compatGuard.getLastManifest()` via new `resolveExpectedSha256` (exact-match then same-extension fallback); cacheHook uses `process.env.APPIMAGE`; `LaunchWatchdog` instantiated + invoked in `app.whenReady()` before `createWindow`; rollback dialog with `[Show cached installer]` / `[Continue]` via `shell.openPath`; `confirmLaunchStable()` fires 10 s after `ready-to-show`; watchdog + timer added to `gracefulShutdown` teardown.
- [x] `UpdateBanner.tsx` — sonner `toast.error` subscriber with `[Retry]` action; `lastErrorMessageRef` dedup on message string; tailored copy for `checksum-mismatch`; dedup ref clears on successful `downloading`/`downloaded` transitions.
- [x] Six test files: `checksumVerifier.test.ts`, `installerCache.test.ts`, `launchWatchdog.test.ts`, extended `updateInstaller.test.ts`, extended `updateManager.test.ts`, extended `UpdateBanner.test.tsx`.

**Acceptance Criteria:**
- Given matching sha256, when download completes, then state transitions `verifying`→`downloaded` and no error toast renders.
- Given mismatching sha256, when download completes, then state is `error{checksum-mismatch}`, the file is unlinked, and the banner toasts the integrity copy with [Retry].
- Given `process.env.APPIMAGE` is set and the cache hook succeeds, when `install()` is called, then the current binary is at `userData/previous-installer/<version>.AppImage` and `quitAndInstall` is invoked exactly once.
- Given the cache hook throws, when `install()` is called, then the error is logged and `quitAndInstall` still fires.
- Given `launchAttempts.count === 2` for the running version AND a cached installer for a different version, when the app starts, then count increments to 3 and the restore dialog appears.
- Given the restore dialog is dismissed via `[Continue]`, when the main window stays alive 10 s past ready-to-show, then the counter is reset to 0.
- Given `check()` rejects, when the promise settles, then a 1 h timer is armed; given the next `check()` resolves with no component errors, then the timer is cleared.
- `cd dashboard && npm run typecheck && npm run test && npm run build:electron` — all green.

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` — zero errors.
- `cd dashboard && npm run test -- checksumVerifier installerCache launchWatchdog updateInstaller updateManager UpdateBanner` — all green.
- `cd dashboard && npm run build:electron` — compiles.

**Manual gate (optional, Linux AppImage):**
- Publish a test release with an intentionally-wrong sha256 → expect integrity-failure toast, no install button.
- Matching manifest → [Download] → [Install Dashboard] → [Quit & Install]; verify `~/.config/TranscriptionSuite/previous-installer/<old_version>.AppImage` exists after relaunch.
- Edit electron-store `updates.launchAttempts` to `{version: currentVersion, count: 3}`, relaunch → expect restore dialog.

## Suggested Review Order

**Design intent — start here**

- New `verifying` transitional state + mismatch → unlink + error path is M6's center of gravity.
  [`updateInstaller.ts:385`](../../dashboard/electron/updateInstaller.ts#L385)

**SHA-256 integrity verification**

- `async install()` awaits the cache hook BEFORE `quitAndInstall` so cache can't be truncated by shutdown.
  [`updateInstaller.ts:222`](../../dashboard/electron/updateInstaller.ts#L222)

- Streaming sha256 — never reads the binary whole-file into memory.
  [`checksumVerifier.ts:20`](../../dashboard/electron/checksumVerifier.ts#L20)

- Verifier closure: matches manifest version, then `resolveExpectedSha256`, fail-open on missing key.
  [`main.ts:483`](../../dashboard/electron/main.ts#L483)

- Lookup helper — exact-basename first, same-extension fallback second.
  [`main.ts:546`](../../dashboard/electron/main.ts#L546)

**Previous-installer cache (Linux AppImage only)**

- Single-slot cache: unlinks older entries before copying the new one.
  [`installerCache.ts:61`](../../dashboard/electron/installerCache.ts#L61)

- Cache hook reads `process.env.APPIMAGE`; no-op on Win/Mac per D6 scope.
  [`main.ts:523`](../../dashboard/electron/main.ts#L523)

**Launch watchdog + rollback prompt**

- Counter class with pathological-value rejection (Infinity / negative / non-integer).
  [`launchWatchdog.ts:53`](../../dashboard/electron/launchWatchdog.ts#L53)

- Prompt fires BEFORE `createWindow()` so a crashing renderer can't starve the dialog.
  [`main.ts:2039`](../../dashboard/electron/main.ts#L2039)

- Stable-launch reset: `ready-to-show + 10 s` → `confirmLaunchStable()`.
  [`main.ts:750`](../../dashboard/electron/main.ts#L750)

**Error surfacing + retry**

- Error-state toast with tailored `checksum-mismatch` copy + Retry action + message dedup.
  [`UpdateBanner.tsx:179`](../../dashboard/components/ui/UpdateBanner.tsx#L179)

- 1 h failure-retry arm/clear, with `destroyed` flag to block post-teardown check().
  [`updateManager.ts:300`](../../dashboard/electron/updateManager.ts#L300)

**Type mirroring**

- `verifying` variant added to the preload-exported union.
  [`preload.ts:43`](../../dashboard/electron/preload.ts#L43)

- Same mirrored on the ambient renderer type.
  [`electron.d.ts:258`](../../dashboard/src/types/electron.d.ts#L258)

**Tests — parity check**

- Streaming hash, mismatch, missing file, 10 MB large input.
  [`checksumVerifier.test.ts:15`](../../dashboard/electron/__tests__/checksumVerifier.test.ts#L15)

- Cache / get / restore + Linux-only gate + filename sanitization.
  [`installerCache.test.ts:20`](../../dashboard/electron/__tests__/installerCache.test.ts#L20)

- Version reset, increment, threshold, cache-absent suppression, pathological counts.
  [`launchWatchdog.test.ts:37`](../../dashboard/electron/__tests__/launchWatchdog.test.ts#L37)

- Verifier + cacheHook matrix; await-ordering assertion.
  [`updateInstaller.test.ts:385`](../../dashboard/electron/__tests__/updateInstaller.test.ts#L385)

- Failure-retry arm/clear + post-destroy short-circuit.
  [`updateManager.test.ts:66`](../../dashboard/electron/__tests__/updateManager.test.ts#L66)

- Error toast, dedup, retry, and reset-on-download-success cases.
  [`UpdateBanner.test.tsx:566`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L566)
