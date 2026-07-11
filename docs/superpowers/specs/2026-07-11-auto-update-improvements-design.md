# Auto-Update Improvements — Design Spec

**Date:** 2026-07-11
**Branch:** `feature/auto-update-improvements`
**Scope:** Desktop dashboard app self-update only (Electron / GitHub Releases). The
server's `cuda`/`cpu`/`vulkan` Docker-image update path (GHCR / `dockerManager`) is
explicitly out of scope and unchanged.

## 1. Goals

Three user-facing changes to the dashboard's update feature:

1. **On by default, weekly.** Update checks default to enabled and run every 7 days.
   Existing installs are force-migrated ON once; users may disable afterward and the
   choice sticks.
2. **Toast on detection.** When a newer app version is detected, show a `sonner` toast
   with two actions: **Update** and **Dismiss**.
3. **Same-variant download.** Clicking **Update** downloads the release build that
   matches the running app's variant (critically, macOS `-mac-metal` vs standard DMG),
   never a mismatched one.

## 2. Ground Truth (verified)

The app already has a substantial update stack; this is a brownfield modification, not a
greenfield feature.

- **Mechanism:** binary updates use `electron-updater` (`^6.3.9`) via `UpdateInstaller`
  (`dashboard/electron/updateInstaller.ts`), driven by `UpdateManager`
  (`dashboard/electron/updateManager.ts`). The GitHub provider (`homelab-00/TranscriptionSuite`)
  is baked into `app-update.yml` from `build.publish` (`dashboard/package.json:217-223`).
- **Scheduling exists.** `INTERVAL_MS` already contains `'7d'` (`updateManager.ts:104`);
  `reconfigure()` (`updateManager.ts:187`) re-arms the timer and is called on any
  `app.updateCheck*` config change (`main.ts:902`).
- **Two default layers.** Main-process code (e.g. `updateManager.ts:315`) reads the
  electron-store `defaults` block directly; the renderer owns its own defaults because
  `config:get` returns `null` for unset keys (`main.ts:889-896`). Both layers plus the
  Settings placeholder must agree.
- **Toast infra exists.** `sonner 2.0.7`, single `<Toaster>` at `App.tsx:1095`;
  action-button toasts already used at `UpdateBanner.tsx:376`.
- **Variant reality.** The dashboard app varies only by *platform*, except on macOS
  where there is a real fork: `…-arm64-mac-metal.dmg` (bundled MLX backend) vs the
  standard `…-arm64-mac.dmg` / `…-x64-mac.dmg`. Linux (single AppImage) and Windows
  (single NSIS exe) have exactly one asset per platform, so "same variant" is already
  satisfied there by `electron-updater`.
- **macOS is manual-download.** `platformGate.ts:52-53` hard-routes darwin to
  `manual-download` because the builds are **unsigned** — Mac cannot silently
  `quitAndInstall`. The metal DMG additionally has **no** `latest-mac.yml` feed entry
  (built in a separate `release.yml` job), so `electron-updater` cannot see it.
- **Runtime variant probe already exists** (as a diagnostic only): `mlxServerManager.ts:475-500`
  detects metal via `app.isPackaged && fs.existsSync(resourcesPath/backend)`;
  `_metalDmgName()` (`:525-533`) builds the metal DMG name from `app.getVersion()`.
- **Reusable state already declared:** `updates.lastNotified {appLatest, serverLatest}`
  (`main.ts:514`, currently unused) is purpose-built for per-version "already notified"
  dedup; `updates.bannerSnoozedUntil` (`main.ts:515`) backs the banner's 4h snooze.

## 3. Decisions (locked with user)

| # | Decision |
|---|----------|
| Scope | Desktop app only; server Docker image update path untouched. |
| macOS behavior | Download the **matching-variant** DMG and **reveal** it (no silent install). Linux/Windows fully auto-download + install. |
| Dismiss semantics | Suppress until a **newer** version appears (wire up `updates.lastNotified.appLatest`). |
| Existing installs | **Force ON for everyone** via a one-time migration; users may disable afterward and it persists. |
| macOS verify | Verify **standard** DMGs against published `latest-mac.yml` SHA; **metal** DMG best-effort (no feed → skip crypto verify, log + surface release link). Windows/Linux keep electron-updater's sha512. |
| Update click | **Download immediately** (no pre-install compat modal). Progress via existing installer-status UI. |

## 4. Architecture

### 4.1 Shared variant-identity helper (new) — `dashboard/electron/appVariant.ts`

The enabler for requirement (iii). Pure/side-effect-light, unit-testable:

- `detectAppVariant(): AppVariant` where
  `AppVariant = 'mac-metal' | 'mac-standard-arm64' | 'mac-standard-x64' | 'linux' | 'windows'`.
  Encapsulates the `mlxServerManager.ts:475-500` probe (packaged + `resourcesPath/backend`
  existence + `process.arch`).
- `resolveMacDmgAssetName(version, variant): string` — e.g.
  `TranscriptionSuite-<ver>-arm64-mac-metal.dmg`.
- `buildAssetDownloadUrl(version, assetName): string` →
  `https://github.com/homelab-00/TranscriptionSuite/releases/download/v<ver>/<assetName>`.
- `isTrustedAssetUrl(raw): boolean` — allow-list guard for the asset URL shape, mirroring
  the origin / userinfo / percent-encoding defenses in `releaseUrl.ts::isTrustedReleaseUrl`.

**Refactor:** `mlxServerManager` `_metalDmgName()` / metal detection reuse this helper
(behavior-preserving; removes the duplicated probe).

### 4.2 Requirement (i) — default-on weekly + force-on migration

- Flip defaults in **three** sites (all verified):
  - `main.ts:490-491` → `'app.updateChecksEnabled': true`, `'app.updateCheckIntervalMode': '7d'`
  - `src/config/store.ts:134-135` → `updateChecksEnabled: true`, `updateCheckIntervalMode: '7d'`
  - `components/views/SettingsModal.tsx:196-197` → same (pre-load placeholder; avoids flash)
- New config key `updates.forceOnMigrationDone: false` (electron-store defaults block).
- **Migration** at boot in `main.ts` (near other boot migrations, ~L1052): if
  `!store.get('updates.forceOnMigrationDone')` → `store.set('app.updateChecksEnabled', true)`,
  `store.set('app.updateCheckIntervalMode', '7d')`, `store.set('updates.forceOnMigrationDone', true)`,
  then `updateManager.reconfigure()`. Runs exactly once; the user's toggle wins thereafter.

### 4.3 Requirement (ii) — toast with Update / Dismiss

- **Trigger (push):** in `UpdateManager`, when a completed check yields an app version
  newer than `updates.lastNotified.appLatest`, main emits new IPC
  `updates:updateAvailable` `{ version: string, releaseNotes?: string }` to the focused
  window. Once-per-detection; clean dedup; no 60s poll lag.
- **Renderer:** new hook `useUpdateToast` (mounted once in `App.tsx`) subscribes via a new
  preload binding `window.electronAPI.updates.onUpdateAvailable(cb)` and fires:
  `toast(message, { action: {label:'Update', onClick}, cancel: {label:'Dismiss', onClick}, duration: Infinity })`.
- **Update →** `api.updates.download()` (per-platform routing in §4.4). Toast dismisses;
  progress appears in the existing installer UI.
- **Dismiss →** `toast.dismiss(id)` + new binding `api.updates.dismissVersion(version)` →
  main sets `updates.lastNotified.appLatest = version`. Won't re-toast this version;
  reappears on a newer one.
- **Banner coexistence:** the persistent `UpdateBanner` stays as the always-available
  affordance. It is updated to respect the same `updates.lastNotified.appLatest`
  per-version dismissal so the two surfaces never contradict each other.

### 4.4 Requirement (iii) — same-variant download

- **Linux / Windows:** no mechanism change. Toast **Update** → existing
  `updates:download` → `startDownload()` → `electron-updater` (already fetches the single
  correct per-platform asset) → install-when-idle.
- **macOS (new):** `dashboard/electron/macVariantUpdater.ts` —
  `downloadMacVariantDmg(targetVersion, variant, onProgress)`:
  1. `detectAppVariant()` → metal vs standard(arm64/x64).
  2. `resolveMacDmgAssetName(targetVersion, variant)` + `buildAssetDownloadUrl(...)`,
     validated by `isTrustedAssetUrl`.
  3. Download DMG (progress reported through the existing `updates:installerStatus`
     channel/state machine).
  4. **Verify:** standard → fetch `latest-mac.yml`, compare SHA; metal → skip crypto,
     log + keep release link handy.
  5. `shell.showItemInFolder()` / `shell.openPath()` to reveal/mount for drag-install.
     No `quitAndInstall`. On any failure, fall back to `buildReleaseUrl()` +
     `shell.openExternal`.
- **Routing:** `updates:download` in `main.ts` branches on the platform strategy — `auto`
  (Win/Linux) → `startDownload()`; `manual-download` (Mac) → `downloadMacVariantDmg()`.
  Renderer stays uniform (always calls `api.updates.download()`).

## 5. Data / IPC Contracts

**New config keys**
- `updates.forceOnMigrationDone: boolean` (default `false`)

**Reused config keys**
- `updates.lastNotified.appLatest` — toast + banner per-version dedup
- `updates.bannerSnoozedUntil` — unchanged

**IPC**
- New push `updates:updateAvailable` → `{ version: string, releaseNotes?: string }` (main→renderer)
- New invoke `updates:dismissVersion(version: string)` (renderer→main)
- Reused: `updates:download`, `updates:installerStatus`, `updates:getStatus`,
  `updates:openReleasePage` (Mac fallback)

**preload / types**
- `preload.ts`: expose `updates.onUpdateAvailable(cb)` and `updates.dismissVersion(version)`
- `src/types/electron.d.ts`: add the two members + `updates:updateAvailable` payload type

## 6. File Touch List

| File | Change |
|------|--------|
| `dashboard/electron/appVariant.ts` | **new** — variant detection + asset name/URL + trusted-asset guard |
| `dashboard/electron/macVariantUpdater.ts` | **new** — Mac variant-matched DMG download + verify + reveal |
| `dashboard/electron/mlxServerManager.ts` | refactor metal detection / `_metalDmgName` onto `appVariant` |
| `dashboard/electron/updateManager.ts` | emit `updates:updateAvailable` on fresh detection (dedup via `lastNotified`) |
| `dashboard/electron/main.ts` | flip 2 defaults + new key; one-shot force-on migration; `updates:download` Mac routing; `updates:dismissVersion` handler; wire push |
| `dashboard/electron/preload.ts` | expose `onUpdateAvailable`, `dismissVersion` |
| `dashboard/src/types/electron.d.ts` | types for the two new API members + payload |
| `dashboard/src/config/store.ts` | flip renderer defaults |
| `dashboard/components/views/SettingsModal.tsx` | flip placeholder defaults |
| `dashboard/src/hooks/useUpdateToast.ts` (or `components/…`) | **new** — fire the sonner toast |
| `dashboard/App.tsx` | mount `useUpdateToast` |
| `dashboard/components/ui/UpdateBanner.tsx` | respect `lastNotified.appLatest` per-version dismissal |

## 7. Testing

- **Unit (backend/electron, Vitest):**
  - `appVariant`: detection under mocked `app.isPackaged`/`resourcesPath`/`process.arch`/`fs`;
    asset-name resolution for all variants; `isTrustedAssetUrl` incl. userinfo /
    percent-encoding / wrong-origin bypass cases (mirror the `releaseUrl` test style).
  - Force-on migration: runs once, sets keys + flag, is idempotent, and a subsequent
    user-disable is not re-overridden.
  - Toast dedup: `updates:updateAvailable` fires only when version > `lastNotified.appLatest`.
  - `macVariantUpdater`: verify-pass (mock fetch + `latest-mac.yml`), metal skip-verify
    path, reveal call, and release-page fallback on download error.
- **Frontend (Vitest + Testing Library):** `useUpdateToast` fires on event, Update/Dismiss
  wire to `api.updates.download` / `dismissVersion`, no duplicate toast for same version.
- **UI contract:** run the `ui-contract` update sequence after touching `SettingsModal`,
  `UpdateBanner`, and the new toast surface (per project SKILL).
- Follow project pattern: backend tests via build venv; frontend via Node 22.

## 8. Risks / Notes

- **`UpdateBanner` behavior change** (respect `lastNotified`) is the main regression
  surface — keep the change minimal and covered by tests. The prior exploration flagged
  that per-task test subsets missed a route-level regression; run the **full** suite.
- **macOS Intel:** metal is arm64-only; x64 always resolves to the standard DMG.
- **Metal DMG unverified** by design (accepted); revisit if a checksum/manifest lands in CI.
- **CI dependency:** `resolveMacDmgAssetName` must stay in lockstep with the asset names
  produced by `.github/workflows/release.yml` (`build-macos` + `build-macos-metal`).
- Per project rules: run `gitnexus_impact` before editing each existing symbol and
  `gitnexus_detect_changes` before committing (deferred to the implementation phase).
- No AI attribution in any commit/PR text (project rule).

## 9. Out of Scope

- Server Docker image (`cuda`/`cpu`/`vulkan`) variant selection — separate GHCR channel.
- Apple code-signing / notarization / silent macOS auto-install.
- Activating the dormant `manifest.json` SHA-256 verification pipeline.
