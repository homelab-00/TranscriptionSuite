---
title: 'M1: electron-updater wiring for in-app Dashboard updates'
type: 'feature'
created: '2026-04-12'
status: 'done'
baseline_commit: '5f5b9cc23d8758073509ed22532922203a0eaca2'
context:
  - '{project-root}/_bmad-output/brainstorming/brainstorming-session-2026-04-12-in-app-updates.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Dashboard currently only *notifies* the user that a new version exists (`updateManager.ts:318-352`). There is no in-app path to download or install — users must visit GitHub manually. This is the M1 slice of a multi-milestone plan (see brainstorming doc under `_bmad-output/brainstorming/`). M1 ships the plumbing; UI, safety gate, compat guard, rollback, and platform hardening are M2–M7.

**Approach:** Add `electron-updater` as a dependency, configure electron-builder's GitHub publish provider, ensure release CI publishes the `latest-*.yml` metadata files that `autoUpdater` requires, and introduce a new `UpdateInstaller` class (separate from the existing `UpdateManager`) that wraps `electron-updater`'s `autoUpdater`. Expose three new IPC channels (`updates:download`, `updates:install`, `updates:cancelDownload`) plus a status-event channel. Surface installer state through the existing `UpdateStatus` type via a new optional `installer` field.

## Boundaries & Constraints

**Always:**
- `UpdateInstaller` lives in a new file `dashboard/electron/updateInstaller.ts`. Do NOT grow `updateManager.ts`.
- `autoUpdater.autoDownload = false` and `autoUpdater.autoInstallOnAppQuit = false` — every download and install is explicit.
- Publish config: `provider: 'github'`, `owner: 'homelab-00'`, `repo: 'TranscriptionSuite'`.
- `UpdateInstaller.startDownload()` calls `autoUpdater.checkForUpdates()` first, then chains to `downloadUpdate()` using the info that call populates. The existing `UpdateManager` GitHub poll is unchanged — two version-check paths coexist in M1 and will be reconciled in M4 via `manifest.json`.
- The release workflow must ship `latest-linux.yml` alongside the AppImage as a GitHub release asset. Without that file, `autoUpdater` cannot discover updates.
- Pass `--publish=never` to `electron-builder` in the `package:*` npm scripts so electron-builder generates the `latest-*.yml` metadata locally without attempting to publish itself (existing `softprops/action-gh-release` step keeps doing the publishing).
- Extend — do not break — `UpdateStatus`. The new `installer` field must be optional so persisted statuses from earlier versions still deserialize.
- Mirror the existing preload callback-registration pattern: `onInstallerStatus(cb) → unsubscribeFn`.
- electron-updater's built-in integrity check is SHA-512 (over the `latest-*.yml` hash). That IS the M1 integrity mechanism — manifest.json SHA-256 hashes from the brainstorming doc arrive in M6, not here.

**Ask First:**
- Any scope creep into M2 (UI) / M3 (safety gate) / M4 (manifest + compat) / M5 (modal) / M6 (rollback) / M7 (platforms). If a task starts to need those, HALT.
- Any publish configuration beyond `provider: 'github'` with `owner` + `repo` (e.g. prerelease channels — deferred per brainstorming).
- Any release-workflow change beyond adding `dashboard/release/*.yml` to the per-platform upload patterns.

**Never:**
- No renderer-side auto-trigger of `startDownload()` on mount. M1 ships plumbing; the button arrives in M2.
- No manifest.json fetch, no additional hash verification beyond electron-updater's SHA-512. M4 and M6 own those.
- No unifying of the two version-check paths (UpdateManager's GitHub poll vs. `autoUpdater.checkForUpdates()`). That reconciliation is M4's job.
- No changes to `gracefulShutdown()` in `main.ts`. The pre-existing data-loss issue there is tracked for M3.
- No code signing, notarization, or macOS auto-update behavior. Unsigned v1 is a locked decision.
- Do NOT call `autoUpdater.quitAndInstall()` from any path that is not a direct IPC response to `updates:install`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| `updates:download` invoked, no update exists | `autoUpdater.checkForUpdates()` returns "no newer version" | Status transitions `idle → checking → idle`. Handler resolves `{ok:false, reason:'no-update-available'}` | N/A |
| `updates:download` invoked, newer version exists | `checkForUpdates()` finds newer version | Status `idle → checking → downloading` with `version, percent, bytesPerSecond, transferred, total` updated on each `download-progress` event. Resolves `{ok:true}` once download starts | On `error`: status → `{state:'error', message}`; handler rejects with same message |
| `update-downloaded` fires | Download complete | Status → `{state:'downloaded', version}` | N/A |
| `updates:download` called while already `downloading` | Second concurrent call | Do NOT start a second download. Resolve with `{ok:true, reason:'already-downloading'}`; no state change | N/A |
| `updates:install` invoked | `state === 'downloaded'` | Call `autoUpdater.quitAndInstall(false, true)` (silent=false, forceRunAfter=true) | If `state !== 'downloaded'`: return `{ok:false, reason:'no-update-ready'}`; do NOT throw |
| `updates:cancelDownload` invoked | `state === 'downloading'` | Call stored `CancellationToken.cancel()`; status → `{state:'cancelled'}` within 2s | If no active download: no-op; return `{ok:true}` |
| `autoUpdater.error` fires | Any error during check/download (including read-only AppImage path) | Status → `{state:'error', message}`; log via `console.error`; main process does NOT crash | Error swallowed at boundary; renderer surfaces via M2 banner when built |
| App quits mid-download | Partial cached in `app.getPath('userData')/pending/` by electron-updater | Next launch starts at `{state:'idle'}`. User must re-invoke `updates:download`; electron-updater auto-resumes from the cache internally | N/A |
| Fresh app launch | No prior install state persisted | Installer status starts at `{state:'idle'}` | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/package.json` — add `electron-updater` dependency; add `build.publish` GitHub provider block; append `--publish=never` to `package:linux`, `package:windows`, `package:mac` scripts.
- `dashboard/electron/updateInstaller.ts` — NEW. `UpdateInstaller` class wrapping `autoUpdater`; exposes `startDownload()`, `install()`, `cancelDownload()`, `getStatus()`, `on('status', cb)`, `destroy()`. Internal Node `EventEmitter` for status transitions. Also wires `checking-for-update` and `update-not-available` events.
- `dashboard/electron/updateManager.ts` — extend exports only: add `InstallerStatus` discriminated union (six states: `idle | checking | downloading | downloaded | cancelled | error`); add optional `installer?: InstallerStatus` field to `UpdateStatus`. No behavior changes.
- `dashboard/electron/main.ts` — instantiate `UpdateInstaller` near line 463; register the three new IPC handlers next to the existing `updates:*` block (near lines 1216-1222); forward installer status events to all BrowserWindows via `BrowserWindow.getAllWindows().forEach(w => w.webContents.send('updates:installerStatus', status))`; destroy the installer in `gracefulShutdown()` near line 1694.
- `dashboard/electron/preload.ts` — extend the existing `updates` namespace (lines 188-191 and 464-467) with `download()`, `install()`, `cancelDownload()`, `onInstallerStatus(cb)`.
- `dashboard/src/types/electron.d.ts` — mirror the type additions (new `InstallerStatus`, new `installer` field on `UpdateStatus`, new methods on `window.electronAPI.updates`).
- `.github/workflows/release.yml` — extend each per-platform `upload-artifact` `path` block to include `dashboard/release/*.yml`, so `latest-linux.yml` (and `latest.yml` / `latest-mac.yml` for future milestones) ship as release assets.
- `dashboard/electron/__tests__/updateInstaller.test.ts` — NEW. Vitest unit tests driving each I/O matrix row via a mocked `electron-updater` module.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/package.json` -- added `"electron-updater": "^6.3.9"`; added `build.publish` GitHub provider; appended ` --publish=never` to `package:linux`, `package:windows`, `package:mac` scripts.
- [x] `dashboard/electron/updateInstaller.ts` -- new file. Class `UpdateInstaller` with event wiring, state machine, concurrent-call guards, `startDownload`/`install`/`cancelDownload`/`destroy`/`on('status')`/`getStatus`. Uses narrow `UpdateInfoLike` + `AutoUpdaterLike` seams for test injectability.
- [x] `dashboard/electron/updateManager.ts` -- exported `InstallerStatus` union (six states) + optional `installer?: InstallerStatus` on `UpdateStatus`. No behavior changes.
- [x] `dashboard/electron/main.ts` -- constructed `updateInstaller`; registered `updates:download`, `updates:install`, `updates:cancelDownload`, `updates:getInstallerStatus`; forwarded `'status'` events via `BrowserWindow.getAllWindows().forEach(w => !w.isDestroyed() && w.webContents.send('updates:installerStatus', status))`; added `updateInstaller.destroy()` to `gracefulShutdown()`.
- [x] `dashboard/electron/preload.ts` -- extended `updates` namespace with `download`, `install`, `cancelDownload`, `getInstallerStatus`, `onInstallerStatus`. Added `InstallerStatus` export next to `TrayMenuState`.
- [x] `dashboard/src/types/electron.d.ts` -- mirrored `InstallerStatus` + new fields on `window.electronAPI.updates`.
- [x] `.github/workflows/release.yml` -- added `dashboard/release/*.yml` to Linux, Windows, and macOS `upload-artifact` patterns. (macOS Metal skipped — custom hdiutil DMG, no electron-updater metadata.)
- [x] `dashboard/electron/__tests__/updateInstaller.test.ts` -- 13 Vitest cases covering configuration, idle start, check-only paths, download state machine, progress updates, concurrent-call guard, error branches, install guard, cancel, late-event ordering, destroy cleanup. Uses `vi.hoisted` for the fake CancellationToken to avoid hoisting errors.

**Acceptance Criteria:**
- Given the Dashboard is built with electron-updater wired and a newer GitHub release exists (with `latest-linux.yml` published alongside the AppImage), when `window.electronAPI.updates.download()` is invoked from DevTools, then the installer transitions `idle → checking → downloading → downloaded` and a subsequent `install()` relaunches the app into the new version. (Manual gate — Linux AppImage in a writable location.)
- Given an active download, when `updates:cancelDownload` is invoked, then the installer status transitions to `cancelled` and the download stops within 2 seconds.
- Given `autoUpdater.downloadUpdate()` fails (e.g. read-only AppImage path, network drop mid-download), when the `error` event fires, then the installer status transitions to `error` with a message and the main process does not crash.
- Given `npm run typecheck && npm run test` runs from `dashboard/`, it completes with zero errors and all new unit tests pass.

## Design Notes

**Why keep `UpdateInstaller` as a class (not a module):** Codebase convention — `UpdateManager`, `DockerManager`, `MlxServerManager`, `TrayManager` are all classes with `destroy()` lifecycles, wired into `gracefulShutdown()`. A class also enables per-test instance isolation with fresh mocks, which a module-scoped singleton makes awkward.

**Why two version-check paths in M1:** `UpdateManager`'s GitHub API poll drives UX notifications and is stable today. `autoUpdater.checkForUpdates()` is required by electron-updater to populate the `updateInfo` that `downloadUpdate()` consumes, and also validates the `latest-linux.yml` integrity. Consolidating these into one source-of-truth (the `manifest.json` the brainstorming doc defines) is explicitly M4. Running them in parallel in M1 is intentional and temporary.

**`build.publish` side effect:** Adding the publish block affects all `package:*` targets, not just Linux. The `--publish=never` flag keeps electron-builder from actually publishing; we only want its `latest-*.yml` metadata generation. The existing release workflow's `softprops/action-gh-release` step continues to do the actual publishing.

**`InstallerStatus` shape:**
```typescript
type InstallerStatus =
  | { state: 'idle' }
  | { state: 'checking' }
  | { state: 'downloading'; version: string; percent: number; bytesPerSecond: number; transferred: number; total: number }
  | { state: 'downloaded'; version: string }
  | { state: 'cancelled' }
  | { state: 'error'; message: string };
```
M2's banner maps these to its visual states (idle = no banner; checking = spinner/transient; other four = visible banner states from the brainstorming doc).

**AppImage writability caveat:** electron-updater's Linux path respawns the AppImage in-place, which only works when the AppImage lives in a writable location. When it doesn't, `autoUpdater` emits `error` — M1 surfaces this via the `error` status; a dedicated "download to ~/Downloads" fallback is M7. Document the assumption with a single-line comment at the wiring site.

## Verification

**Commands (from `dashboard/`):**
- `npm install` -- expected: resolves `electron-updater` cleanly.
- `npm run typecheck` -- expected: zero errors (covers both renderer and `electron/tsconfig.json`).
- `npm run test -- updateInstaller` -- expected: all new unit tests pass.
- `npm run build:electron` -- expected: TypeScript compiles main and renderer without errors.
- `npm run package:linux` -- expected: succeeds, producing `dashboard/release/TranscriptionSuite-<version>.AppImage` **and** `dashboard/release/latest-linux.yml`.

**Manual check (the M1 gate — Linux AppImage only):**
1. **Prerequisite — produce two real releases.** Cut git tags `v1.3.2-m1-test` and `v1.3.3-m1-test` pointing at commits where the current app version matches. Push tags; wait for the `Release` GitHub Actions workflow to complete and create two draft releases with `*.AppImage`, `*.yml`, and `*.asc` assets. Publish both drafts (electron-updater ignores drafts).
2. Download and run `v1.3.2-m1-test` AppImage from a writable location (e.g. `~/Applications/`).
3. Open DevTools; invoke `await window.electronAPI.updates.download()`.
4. Observe status transitions `idle → checking → downloading → downloaded` via the `updates:installerStatus` event channel (subscribe with `window.electronAPI.updates.onInstallerStatus(console.log)` first).
5. Invoke `await window.electronAPI.updates.install()`.
6. Expected: app quits and relaunches. Confirm via `app.getVersion()` in the relaunched DevTools that the version is now `1.3.3-m1-test`.

## Suggested Review Order

**State-machine core**

- The design seam: `UpdateInstaller` wraps `autoUpdater` via a narrow `AutoUpdaterLike` interface for testability.
  [`updateInstaller.ts:78`](../../dashboard/electron/updateInstaller.ts#L78)

- `startDownload()` is the orchestration — checks, transitions, chains `downloadUpdate(token)`, guards concurrent calls.
  [`updateInstaller.ts:110`](../../dashboard/electron/updateInstaller.ts#L110)

- `destroy()` cancels an in-flight download so `gracefulShutdown()` doesn't leave an orphan Promise (post-review patch).
  [`updateInstaller.ts:211`](../../dashboard/electron/updateInstaller.ts#L211)

- Event handlers: guards protect `downloaded` and `cancelled` from late `download-progress` / `error` events (post-review patches).
  [`updateInstaller.ts:230`](../../dashboard/electron/updateInstaller.ts#L230)

- `install()` uses an `installRequested` latch so the IPC handler can't double-fire `quitAndInstall` (post-review patch).
  [`updateInstaller.ts:178`](../../dashboard/electron/updateInstaller.ts#L178)

**Main-process wiring**

- Instantiation + subscription that forwards each `InstallerStatus` to every live BrowserWindow.
  [`main.ts:466`](../../dashboard/electron/main.ts#L466)

- Four new IPC handlers sit next to the existing `updates:*` block; `updates:getInstallerStatus` is added for renderer-on-mount sync.
  [`main.ts:1240`](../../dashboard/electron/main.ts#L1240)

- `gracefulShutdown()` now destroys the installer right after the update manager — the cancel-in-destroy path closes the loop.
  [`main.ts:1727`](../../dashboard/electron/main.ts#L1727)

**Type surface (main + renderer)**

- `InstallerStatus` discriminated union + optional `installer?` field extending the persisted `UpdateStatus`.
  [`updateManager.ts:34`](../../dashboard/electron/updateManager.ts#L34)

- Preload bridge exposes the new methods following the existing `onXxx(cb) → unsubscribe` pattern.
  [`preload.ts:493`](../../dashboard/electron/preload.ts#L493)

- Renderer ambient mirror keeps `window.electronAPI.updates` strictly typed in dashboard code.
  [`electron.d.ts:183`](../../dashboard/src/types/electron.d.ts#L183)

**Release packaging & CI**

- `electron-updater` added as a runtime dep; `--publish=never` keeps electron-builder from racing the existing softprops publish step.
  [`package.json:20`](../../dashboard/package.json#L20)

- The GitHub publish provider block is what `autoUpdater.checkForUpdates()` reads from at runtime.
  [`package.json:191`](../../dashboard/package.json#L191)

- `dashboard/release/*.yml` added to each platform upload so `latest-linux.yml` actually reaches the release assets.
  [`release.yml:53`](../../.github/workflows/release.yml#L53)

**Tests**

- 18 Vitest cases drive every I/O matrix row and every post-review patch via an `EventEmitter`-based fake `autoUpdater`.
  [`updateInstaller.test.ts:1`](../../dashboard/electron/__tests__/updateInstaller.test.ts#L1)
