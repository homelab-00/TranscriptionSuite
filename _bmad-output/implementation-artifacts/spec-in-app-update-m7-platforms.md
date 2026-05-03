---
title: 'M7: Platform hardening for in-app Dashboard updates (Linux/Windows/macOS)'
type: 'feature'
created: '2026-04-13'
status: 'done'
baseline_commit: 'cae599d'
context:
  - '{project-root}/_bmad-output/brainstorming/brainstorming-session-2026-04-12-in-app-updates.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-m1-electron-updater.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-m2-banner-ui.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-m5-pre-install-modal.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-m6-safety-errors.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** M1–M6 assume the happy path: a writable Linux AppImage that electron-updater can overwrite in place. Three platform realities break that: (1) AppImages in read-only locations (`/opt`, NFS, immutable rootfs) crash the install with no recovery UX; (2) Windows NSIS triggers SmartScreen on every unsigned install and the app gives users no heads-up; (3) macOS Squirrel rejects unsigned updates outright — `autoUpdater` errors silently and the user sees no path forward.

**Approach:** A new `platformGate.ts` resolves an install strategy (`electron-updater` vs `manual-download`) per platform/runtime context. `UpdateInstaller` short-circuits to a new `manual-download-required` state when the strategy says so, carrying a release URL the banner exposes via `[Download from GitHub]`. `UpdateModal` adds a Windows-only SmartScreen callout. macOS always resolves to `manual-download` regardless of release contents.

## Boundaries & Constraints

**Always:**
- New `dashboard/electron/platformGate.ts` exports `resolveInstallStrategy(opts: { platform: NodeJS.Platform; appImagePath?: string | null; fsAccess?: (p: string, mode: number) => Promise<void> }): Promise<{ strategy: 'electron-updater' | 'manual-download'; reason?: 'macos-unsigned' | 'appimage-not-writable' | 'appimage-missing' | 'linux-non-appimage' | 'unsupported-platform' }>`. Pure-functional; `fsAccess` defaults to `fs.promises.access(path, fs.constants.W_OK)`. Decision matrix: `darwin` → `manual-download` reason `macos-unsigned`; `win32` → `electron-updater`; `linux` + APPIMAGE set + writable → `electron-updater`; `linux` + APPIMAGE set + not writable → `manual-download` reason `appimage-not-writable`; `linux` + APPIMAGE absent → `manual-download` reason `appimage-missing`; anything else → `manual-download` reason `unsupported-platform`. `fsAccess` rejection is treated as "not writable" — fail-closed.
- `updateInstaller.ts` constructor gains optional dep `platformStrategy?: () => Promise<{ strategy; reason?; downloadUrl?: string; version?: string | null }>`. Widen `InstallerStatus` with `| { state: 'manual-download-required'; version: string | null; downloadUrl: string; reason: string }`. In `startDownload()`, BEFORE `checkForUpdates()`, await `platformStrategy()` if wired. If `strategy === 'manual-download'`, transition to `manual-download-required` with `version` + `downloadUrl` from the resolver and return `{ ok: false, reason: 'manual-download-required', downloadUrl }`. Undefined `platformStrategy` = M1 behavior preserved (no test regression). `cancelDownload()` accepts the new state and flips to `cancelled`.
- `main.ts` wires the closure: calls `resolveInstallStrategy({ platform: process.platform, appImagePath: process.env.APPIMAGE ?? null })`; reads `version` from `updateManager.getStatus().app.latest`; constructs `downloadUrl` as `https://github.com/homelab-00/TranscriptionSuite/releases/tag/v${version}` when `version` is non-empty, otherwise `https://github.com/homelab-00/TranscriptionSuite/releases/latest`.
- `main.ts` registers `updates:openReleasePage(url: string)` IPC. Validates the URL parses and its `origin === 'https://github.com'` AND its `pathname` starts with `/homelab-00/TranscriptionSuite/releases/`. Reject anything else with `{ ok: false, reason: 'untrusted-url' }`. On accept, `shell.openExternal(url)` and return `{ ok: true }`.
- `preload.ts` exposes `updates.openReleasePage(url)`. `dashboard/src/types/electron.d.ts` mirrors the new IPC and the new `manual-download-required` variant.
- `UpdateBanner.tsx` extends `BannerVisualState` with `'manual-download'`. `deriveBannerState` adds `case 'manual-download-required'` returning `{ state: 'manual-download', version, downloadUrl, reason }`. New visual block: `"v{x} available — auto-update unavailable on this platform"` + `[Download from GitHub]` + `[Later]`. Click → `api.openReleasePage(downloadUrl)` (logs failure but does NOT toast). The button's `title` exposes a reason-tailored tooltip ("AppImage location is read-only" / "macOS auto-update unavailable until code signing" / "Auto-update requires the AppImage build" / "Platform not supported by auto-update").
- `UpdateModal.tsx` reads `process.platform` once via `window.electronAPI.app.getPlatform()` (cached in state, default `'unknown'`). When the resolved value is `'win32'`, render an Info-toned callout block above the footer buttons: `"First-time install on Windows: SmartScreen may show 'Windows protected your PC'. Click 'More info' → 'Run anyway' to proceed."` Lucide `Info` icon, slate styling consistent with the existing `slate` badge tone. Hidden on every other platform.
- Tests: new `platformGate.test.ts` (full strategy matrix + injected `fsAccess` rejection); extend `updateInstaller.test.ts` (strategy short-circuits before `checkForUpdates`; `downloadUrl`/`version` propagate; absent strategy preserves M1; `cancelDownload` from manual-download-required); extend `UpdateBanner.test.tsx` (manual-download render, click dispatches `openReleasePage`, reason tooltip per reason); extend `UpdateModal.test.tsx` (callout visible only on `win32`, hidden on `linux`/`darwin`/`unknown`).

**Ask First:**
- Switching the read-only AppImage UX from "open release page in browser" to the brainstorming's "download to `~/Downloads`, open folder when complete" — the latter requires a `ManualDownloader` module duplicating electron-updater's HTTPS stream + SHA-256 + progress; current spec opts for the simpler `shell.openExternal`.
- Bypassing strategy entirely on macOS (e.g. not constructing `UpdateInstaller`) instead of routing through `manual-download-required`.
- Adding a permanent macOS Settings card explaining the limitation (out of scope here; banner appears only when an update is available).
- Disabling the M5 modal entirely on the manual-download path (current spec already bypasses it because the banner click goes straight to `openReleasePage`).

**Never:**
- Do NOT call `autoUpdater.checkForUpdates()` when strategy resolves to `manual-download` — Squirrel/Mac will emit a misleading error and pollute the installer status.
- Do NOT widen `updates:openReleasePage` to accept arbitrary URLs — `https://github.com/homelab-00/TranscriptionSuite/releases/...` only.
- Do NOT block `updateManager` polling on macOS — users still need to know a new version exists.
- Do NOT change `cacheHook` / `verifier` / `LaunchWatchdog` / `CompatGuard` contracts (M4–M6 frozen).
- Do NOT add a separate macOS "auto-update is broken" banner when no update is available — the manual-download state surfaces only when there IS one.
- Do NOT render the Windows SmartScreen callout outside `UpdateModal` (e.g. on the banner) — the modal is the single pre-install context where it's actionable.
- Do NOT touch `gracefulShutdown`, `installGate`, `appState`, or `dockerManager`.

## I/O & Edge-Case Matrix

| Scenario | Expected Behavior |
|---|---|
| Linux + writable APPIMAGE | Strategy `electron-updater`; M1–M6 path unchanged. |
| Linux + read-only APPIMAGE | Strategy `manual-download` reason `appimage-not-writable`; banner shows manual-download block; click opens release page. |
| Linux without APPIMAGE (dev / unpacked deb) | Strategy `manual-download` reason `appimage-missing`; banner falls back to `/releases/latest` URL when `version` is null. |
| Windows | Strategy `electron-updater`; UpdateModal renders SmartScreen callout above footer buttons. |
| macOS | Strategy `manual-download` reason `macos-unsigned`; banner shows manual-download block whenever `updateAvailable === true`. |
| `updates:openReleasePage` with non-github.com URL | Returns `{ ok: false, reason: 'untrusted-url' }`; no `shell.openExternal` call. |
| `fsAccess` throws an unexpected error | Treated as "not writable" → `appimage-not-writable`; banner is still actionable. |
| User clicks Later on the manual-download banner | Existing 4 h snooze applies; banner re-surfaces after expiry. |
| Strategy = manual-download with `updateManager.getStatus().app.latest === null` | `version` null, `downloadUrl` falls back to `/releases/latest`; banner copy reads "latest" in place of version. |
| User cancels during `manual-download-required` | `cancelDownload()` flips to `cancelled`; banner returns to `available` (or hidden if snoozed). |

</frozen-after-approval>

## Spec Change Log

- **2026-04-13 — post-draft hardening (patches applied in-review):**
  - `updates:download` IPC handler now resolves platform strategy BEFORE the M4 compat check. Prior order made macOS users with an incompatible server see `incompatible-server` instead of `manual-download-required`, masking the M7 manual-download UX. Strategy resolution is extracted to `resolveStrategyForUpdater()` so the IPC handler and the `UpdateInstaller.platformStrategy` closure share one source of truth (and one timeout).
  - `resolveStrategyForUpdater()` wraps `resolveInstallStrategy` in a 5 s wall-clock `Promise.race` timeout. A hung NFS mount could otherwise stall `fsp.access` indefinitely, deadlocking the IPC handler. On timeout we fail-CLOSED to `manual-download` (fail-OPEN to electron-updater would defeat the gate's purpose on macOS).
  - `isTrustedReleaseUrl` tightened from `pathname.startsWith(...)` to a strict regex requiring one of the known release shapes (`/releases`, `/releases/latest`, `/releases/tag/v…`). Also rejects URLs with userinfo (`https://x:y@github.com/…` previously passed because `parsed.origin` ignores userinfo) and any percent-encoded path segments (defeats `%2e%2e/` traversal that survives WHATWG normalization and bypasses a startsWith check).
  - `buildReleaseUrl` strips a leading `v` from `version` before re-prefixing — defends against a future `vv1.3.3` URL if `updateManager` ever stores `app.latest` with the tag prefix already attached.
  - `platformGate.ts` now checks BOTH the AppImage file AND its parent directory for `W_OK`. electron-updater replaces the AppImage atomically via `rename()` in the parent dir, so a writable file in a read-only parent (immutable rootfs, NFS, /opt) would silently fail an in-place update. Two new `platformGate.test.ts` cases lock this in.

## Code Map

- `dashboard/electron/platformGate.ts` — NEW; pure install-strategy resolver with injectable `fsAccess`.
- `dashboard/electron/updateInstaller.ts` — add `platformStrategy` dep + `manual-download-required` state + pre-check short-circuit in `startDownload`; widen `cancelDownload` accept-set.
- `dashboard/electron/main.ts` — wire `platformStrategy` closure; `downloadUrl` builder; `updates:openReleasePage` IPC handler with github.com allow-list.
- `dashboard/electron/preload.ts` — expose `updates.openReleasePage`; mirror new state.
- `dashboard/src/types/electron.d.ts` — mirror new IPC + state variant.
- `dashboard/components/ui/UpdateBanner.tsx` — `manual-download` visual state, click handler, reason tooltip.
- `dashboard/components/ui/UpdateModal.tsx` — Windows-only SmartScreen callout block.
- Tests (new): `dashboard/electron/__tests__/platformGate.test.ts`.
- Tests (extend): `dashboard/electron/__tests__/updateInstaller.test.ts`, `dashboard/components/ui/__tests__/UpdateBanner.test.tsx`, `dashboard/components/ui/__tests__/UpdateModal.test.tsx`.

Not changed: `installerCache.ts`, `launchWatchdog.ts`, `checksumVerifier.ts`, `compatGuard.ts`, `installGate.ts`, `appState.ts`, `dockerManager.ts`, `updateManager.ts`.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/platformGate.ts` — implement `resolveInstallStrategy` covering the 6-row matrix; default `fsAccess` to `fs.promises.access(p, W_OK)`.
- [x] `dashboard/electron/updateInstaller.ts` — extend `InstallerStatus`; new `platformStrategy` dep; pre-check short-circuit; preserve M1 when dep absent; allow `cancelDownload` from `manual-download-required`.
- [x] `dashboard/electron/main.ts` — strategy closure; `downloadUrl` builder; `updates:openReleasePage` IPC with github.com allow-list.
- [x] `dashboard/electron/preload.ts` + `dashboard/src/types/electron.d.ts` — mirror state + add `openReleasePage`.
- [x] `dashboard/components/ui/UpdateBanner.tsx` — `manual-download` visual state, click handler, reason tooltip.
- [x] `dashboard/components/ui/UpdateModal.tsx` — Windows SmartScreen callout (visible iff `getPlatform() === 'win32'`).
- [x] `dashboard/electron/__tests__/platformGate.test.ts` — full matrix incl. throwing `fsAccess`.
- [x] `dashboard/electron/__tests__/updateInstaller.test.ts` — strategy short-circuit, `downloadUrl` propagation, M1-preserve, cancel from new state.
- [x] `dashboard/components/ui/__tests__/UpdateBanner.test.tsx` — manual-download render, click → `openReleasePage` IPC, reason-tailored tooltip.
- [x] `dashboard/components/ui/__tests__/UpdateModal.test.tsx` — Windows callout visibility per platform.

**Acceptance Criteria:**
- Given `process.platform === 'darwin'`, when `startDownload()` runs, then no `autoUpdater.checkForUpdates()` is invoked and status transitions to `manual-download-required` with `reason === 'macos-unsigned'`.
- Given Linux + `process.env.APPIMAGE` set + path is not writable, when `startDownload()` runs, then status is `manual-download-required` with `reason === 'appimage-not-writable'` and `downloadUrl` ends with `/releases/tag/v<version>`.
- Given Linux + writable `APPIMAGE`, when `startDownload()` runs, then `autoUpdater.checkForUpdates()` IS invoked (M1 behavior preserved).
- Given the banner is in `manual-download` state, when `[Download from GitHub]` is clicked, then `updates:openReleasePage` IPC fires with the strategy's `downloadUrl`.
- Given `updates:openReleasePage` IPC receives `https://evil.example/x`, when handler runs, then it returns `{ ok: false, reason: 'untrusted-url' }` and does NOT call `shell.openExternal`.
- Given `process.platform === 'win32'`, when `UpdateModal` opens, then the SmartScreen callout block renders. Given any other platform, it does NOT render.
- `cd dashboard && npm run typecheck && npm run test && npm run build:electron` — all green.

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` — zero errors.
- `cd dashboard && npm run test -- platformGate updateInstaller UpdateBanner UpdateModal` — all green.
- `cd dashboard && npm run build:electron` — compiles.

**Manual gate (Linux AppImage):**
- `chmod a-w` the running AppImage → relaunch → trigger update poll → expect manual-download banner with `[Download from GitHub]` opening the release page in the default browser.
- `chmod u+w` the AppImage → relaunch → expect normal `[Download]` flow.

## Design Notes

**Deviation from brainstorming on Linux fallback UX.** The brainstorming says: "fall back to 'download to `~/Downloads`, open folder when complete'". This spec opens the browser to the GitHub release page instead. Rationale: a true `~/Downloads` flow would duplicate electron-updater's HTTPS stream + SHA-256 verify + progress reporting for one rare fallback path (read-only AppImage location is uncommon — typically only `/opt` or NFS mounts). Browser-open is one `shell.openExternal` line and gives the user the same recovery: download via browser, manually move to a writable location. If the user prefers the brainstorming UX, [E]dit at the checkpoint and the implementation will fork into a `ManualDownloader` module.

**Strategy resolution timing.** Strategy is resolved once per `startDownload()` call, not cached. Cheap (`fs.access` on a single path) and rare (per-attempt, not per-event). Re-resolving means a user who `chmod`s their AppImage between attempts gets the right path on the next try.

**macOS keeps polling.** `updateManager` continues its 24 h GitHub poll on macOS; only the install side flips to manual. Without polling, macOS users would never see "v1.4.0 available" and would have no nudge to update.

**Why not skip `UpdateInstaller` on macOS entirely?** Keeping the IPC contract uniform across platforms means the renderer never special-cases — the `manual-download-required` state is the single switch. A future signed-macOS build can flip macOS to `electron-updater` in one line.

## Suggested Review Order

**Strategy resolver — start here**

- The pure 6-row decision matrix; injectable `fsAccess` for testability.
  [`platformGate.ts:46`](../../dashboard/electron/platformGate.ts#L46)

- Pre-check short-circuit: strategy is resolved BEFORE `checkForUpdates()` to avoid Squirrel/Mac's misleading error event.
  [`updateInstaller.ts:193`](../../dashboard/electron/updateInstaller.ts#L193)

- Fail-open wrapper around `platformStrategy()` so a thrown resolver never bricks the install path.
  [`updateInstaller.ts:441`](../../dashboard/electron/updateInstaller.ts#L441)

**main.ts wiring + URL safety**

- Single-source-of-truth resolver shared by IPC handler and UpdateInstaller; 5 s timeout fail-CLOSED to manual-download.
  [`main.ts:555`](../../dashboard/electron/main.ts#L555)

- IPC handler resolves strategy BEFORE the M4 compat check — fixes review-found macOS UX masking.
  [`main.ts:1486`](../../dashboard/electron/main.ts#L1486)

- Strict allow-list: origin + no-userinfo + no-percent-encoding + regex on known release shapes.
  [`main.ts:613`](../../dashboard/electron/main.ts#L613)

- `buildReleaseUrl` strips a leading `v` (defends against `vv1.3.3`); falls back to `/releases/latest` when version unknown.
  [`main.ts:594`](../../dashboard/electron/main.ts#L594)

- `updates:openReleasePage` IPC handler — validates URL, then `shell.openExternal`.
  [`main.ts:1554`](../../dashboard/electron/main.ts#L1554)

**Renderer surfaces**

- Reason-tailored tooltip per strategy reason — single source for banner button copy.
  [`UpdateBanner.tsx:67`](../../dashboard/components/ui/UpdateBanner.tsx#L67)

- New `case 'manual-download-required'` in `deriveBannerState`; honors snooze for parity with `available`.
  [`UpdateBanner.tsx:119`](../../dashboard/components/ui/UpdateBanner.tsx#L119)

- `manual-download` visual block with disabled-when-empty CTA + reason tooltip.
  [`UpdateBanner.tsx:432`](../../dashboard/components/ui/UpdateBanner.tsx#L432)

- Click handler invokes `updates:openReleasePage` with the strategy-supplied URL.
  [`UpdateBanner.tsx:313`](../../dashboard/components/ui/UpdateBanner.tsx#L313)

- Windows-only SmartScreen callout; renders only when `getPlatform() === 'win32'`.
  [`UpdateModal.tsx:434`](../../dashboard/components/ui/UpdateModal.tsx#L434)

**Type mirroring**

- `manual-download-required` variant added to the canonical `InstallerStatus` union (mirrored in preload + electron.d.ts).
  [`updateManager.ts:60`](../../dashboard/electron/updateManager.ts#L60)

- `openReleasePage` IPC exposed on the contextBridge `updates` namespace.
  [`preload.ts:590`](../../dashboard/electron/preload.ts#L590)

**Tests — parity check**

- 15-row matrix covering every platform/path combination + parent-dir writability + fsAccess fail-closed.
  [`platformGate.test.ts:14`](../../dashboard/electron/__tests__/platformGate.test.ts#L14)

- `M7: platformStrategy` block — short-circuit assertion, M1-preserve when absent, cancel from new state, throw → fail-open.
  [`updateInstaller.test.ts:586`](../../dashboard/electron/__tests__/updateInstaller.test.ts#L586)

- `M7: manual-download state` block — visual render, IPC dispatch, reason tooltips, snooze parity.
  [`UpdateBanner.test.tsx:693`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L693)

- `M7: SmartScreen callout` block — visibility per platform (`win32` shows; `linux`/`darwin`/`unknown` hide).
  [`UpdateModal.test.tsx:752`](../../dashboard/components/ui/__tests__/UpdateModal.test.tsx#L752)
