---
title: 'M2: Update banner UI for in-app Dashboard updates'
type: 'feature'
created: '2026-04-12'
status: 'done'
baseline_commit: '2d7e86428f803832d0cffc9756ead6ae3313d97f'
context:
  - '{project-root}/_bmad-output/brainstorming/brainstorming-session-2026-04-12-in-app-updates.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-m1-electron-updater.md'
  - '{project-root}/_bmad-output/implementation-artifacts/deferred-work.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** M1 wired `electron-updater` and exposed `updates:download | install | cancelDownload | getInstallerStatus | onInstallerStatus` over IPC, but the renderer has no UI. Users cannot see an available update, trigger a download, or install — the M1 plumbing is exercisable only from DevTools.

**Approach:** Add one `<UpdateBanner>` component mounted at app scope above `SessionView` (next to `QueuePausedBanner`). It renders four visual states driven by `InstallerStatus` + `UpdateStatus.app.updateAvailable`: `available` (`[Download] [Later]`), `downloading` (inline progress), `ready` (`[Quit & Install] [Later]`), and `ready_blocked` (disabled install with tooltip when a transcription or import is active). "Later" snoozes the banner for 4 hours, persisted in electron-store so dismissal survives restart.

## Boundaries & Constraints

**Always:**
- New component at `dashboard/components/ui/UpdateBanner.tsx`. No growth of `App.tsx` beyond the mount line and the `isBusy` prop wiring (`clientRunning || isUploading`).
- On mount, the component MUST call `window.electronAPI.updates.getInstallerStatus()` — installer state is broadcast only on transitions, never replayed (per `deferred-work.md` M1 note), so without mount-time sync the banner stays blank after a DevTools reload during an active download.
- Snooze persistence uses one electron-store key: `updates.bannerSnoozedUntil` (epoch ms number; `0` = never snoozed). Register default in `main.ts` next to `updates.lastStatus`.
- Snooze duration is a module-level `const SNOOZE_MS = 4 * 60 * 60 * 1000`. No user preference, no runtime config.
- "Later" is available only in `available` and `ready` states. `downloading` and `ready_blocked` MUST NOT show a Later button.
- Read `UpdateStatus` via `updates.getStatus()` on mount and on a 60s interval while mounted, so a newly-polled "update available" surfaces without requiring an installer transition.
- State mapping is driven by a pure exported function so the test suite can hit it directly.

**Ask First:**
- Any UI text beyond the brainstorming-doc labels (`"{version} available"`, `"Downloading {version} — {percent}%"`, `"{version} ready"`, `"{version} ready — will install when jobs finish"`, plus `[Download]`, `[Quit & Install]`, `[Later]`).
- Any glass/accent styling beyond the `QueuePausedBanner` amber pattern. Use cyan/blue for M2 to distinguish from the queue-paused amber; do not invent new design tokens.

**Never:**
- Do NOT implement the real idle detector — that is M3. Use the client-side proxy `isBusy = clientRunning || isUploading` and mark the site `// M3-HANDOFF:`.
- Do NOT fetch or parse `manifest.json` — that is M4.
- Do NOT open a pre-install modal or render release notes — that is M5. In M2 `[Quit & Install]` calls `updates.install()` directly.
- Do NOT add visual states for `error` or `cancelled`. Both collapse to "no banner" in M2; M6 owns recovery UX.
- Do NOT touch `updateManager.ts`, `updateInstaller.ts`, `gracefulShutdown()`, or installer IPC contract — frozen from M1.
- Do NOT add a Settings row, toast, or tray indicator. The banner is the only new UI in M2.
- Do NOT per-version-key the snooze. Single epoch-ms field is sufficient (max 4h staleness for a newer version is acceptable).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior |
|---|---|---|
| Update available, idle, not snoozed | `app.updateAvailable=true, app.latest='1.3.3'`, installer `idle`, snoozedUntil<now | `available` banner with `[Download] [Later]` |
| Update available but snoozed | snoozedUntil > now | No banner |
| Downloading | installer `{state:'downloading', percent:43, version:'1.3.3'}` | `downloading` banner: `"Downloading 1.3.3 — 43%"` + progress bar, no buttons |
| Checking (transient) | installer `state='checking'` | `downloading` banner at 0% using `updateStatus.app.latest` or last-known version |
| Downloaded, idle app | installer `downloaded`, `isBusy=false` | `ready` banner with `[Quit & Install] [Later]` |
| Downloaded, busy app | installer `downloaded`, `isBusy=true` | `ready_blocked`; install button disabled + `title="Will install when jobs finish"`; no Later |
| Later clicked | Any state with Later visible | `setConfig('updates.bannerSnoozedUntil', Date.now() + SNOOZE_MS)`; banner unmounts. `setConfig` rejection → `console.error`, banner still hides optimistically |
| Download clicked | `available` | Call `updates.download()`. IPC rejection → log, banner stays put (next status event will correct) |
| Quit & Install clicked | `ready` (not `ready_blocked`) | Call `updates.install()`. IPC rejection → log |
| Mount during active download | DevTools reload while installer `downloading` | `getInstallerStatus()` called once; `downloading` renders immediately without waiting for next event |
| Installer cancelled or error | `state='cancelled' | 'error'` | No banner; on next transition back to a mapped state, banner resumes normal mapping |
| `window.electronAPI` absent | browser dev mode | Banner never renders; no IPC/config calls |

</frozen-after-approval>

## Code Map

- `dashboard/components/ui/UpdateBanner.tsx` -- NEW. Functional component owning IPC subscription, 60s `getStatus()` poll, snooze read/write, exported pure `deriveBannerState(...)`, four visual variants. Model markup after `QueuePausedBanner.tsx` (swap amber → cyan/blue).
- `dashboard/App.tsx` -- one import + one JSX line mounting `<UpdateBanner isBusy={clientRunning || isUploading} />` immediately above `<QueuePausedBanner />` (line ~689).
- `dashboard/electron/main.ts` -- add `'updates.bannerSnoozedUntil': 0` to `defaults` near `'updates.lastStatus'` (line ~426).
- `dashboard/components/ui/__tests__/UpdateBanner.test.tsx` -- NEW. Vitest + `@testing-library/react`; mocks `window.electronAPI.updates.{getStatus, getInstallerStatus, onInstallerStatus, download, install}` and `getConfig/setConfig`. Covers every I/O matrix row plus the mount-time `getInstallerStatus` call.

Note: `updates.*` keys are NOT in `ClientConfig` (same pattern as the existing `updates.lastStatus`). Do not extend `dashboard/src/config/store.ts`.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/main.ts` -- added `'updates.bannerSnoozedUntil': 0` default next to `updates.lastStatus`.
- [x] `dashboard/components/ui/UpdateBanner.tsx` -- new component with exported pure `deriveBannerState(installer, updateStatus, isBusy, now, snoozedUntil)`. On mount: one-shot `getInstallerStatus()`, `getStatus()` + 60s poll, snooze read, `onInstallerStatus` subscription, 30s `now` tick for snooze-expiry. Four visual variants (available/downloading/ready/ready_blocked) with cyan accent palette modeled on `QueuePausedBanner`.
- [x] `dashboard/App.tsx` -- imported `UpdateBanner`; mounted `<UpdateBanner isBusy={clientRunning || isUploading} />` above `<QueuePausedBanner />` (line 691) with `// M3-HANDOFF:` comment on the `isBusy` prop.
- [x] `dashboard/components/ui/__tests__/UpdateBanner.test.tsx` -- 25 Vitest cases. 13 hit `deriveBannerState` directly (every I/O matrix row plus empty/null `latest` defense and malformed-UpdateStatus defense). 12 hit the component: mount-time `getInstallerStatus` call count, electron-absent path with no-IPC-called assertions, each of 4 visual states, Download/Install click wiring, Later snooze round-trip with `vi.useFakeTimers()`, NaN-percent clamping, late `getInstallerStatus` resolution must not clobber a live transition, and live `onInstallerStatus` reactivity.

**Acceptance Criteria:**
- Given `UpdateStatus.app.updateAvailable=true` and no active snooze, when the window renders, then the `available` banner appears above `SessionView` with `[Download] [Later]` buttons.
- Given installer emits `{state:'downloading', percent:43, version:'1.3.3'}`, when the event is delivered, then banner reads `"Downloading 1.3.3 — 43%"` with a progress bar at 43%.
- Given installer is `downloaded` and `isBusy=true`, when banner renders, then install button is disabled with `title="Will install when jobs finish"` and no Later button renders.
- Given user clicks `[Later]`, when the click fires, then `updates.bannerSnoozedUntil` is written to `Date.now() + 4h` and banner unmounts; re-mounting within 4h does NOT show the banner.
- Given a DevTools reload occurs while `InstallerStatus.state='downloading'`, when banner re-mounts, then `getInstallerStatus()` is called exactly once and `downloading` state renders without waiting for the next event.
- Given `npm run typecheck && npm run test` runs from `dashboard/`, it completes with zero errors and all new unit tests pass.

## Design Notes

**`isBusy` is an M2 proxy.** `clientRunning` + `isUploading` (both already lifted to `AppInner`) cover local transcription + import-queue activity. They miss remote-recording and other-client activity — the authoritative signal is `/api/admin/status.is_busy`, which is M3's `isAppIdle()` deliverable. The `// M3-HANDOFF:` comment marks the swap site.

**Why 60s `getStatus()` poll:** `UpdateManager.check()` persists to electron-store but has no renderer-side event channel. A 60s poll surfaces a just-completed check within a minute without adding an IPC event just for M2. M4 will replace the poll with a push.

**Post-review defensive patches** (blind hunter + edge-case hunter findings classified `patch`):
1. `deriveBannerState` now optional-chains `.app` as well (`updateStatus?.app?.latest`) — guards against malformed persisted status from older app versions.
2. `latestVersion` is rejected when `null` OR empty string (not just truthy check) — prevents silent hide when a future sentinel-empty `latest` appears.
3. Downloading render clamps via `Number.isFinite(percent)` — nullish coalescing alone doesn't stop NaN (electron-updater can emit partial progress during early connection, producing NaN width CSS).
4. Mount-time `getInstallerStatus()` now uses `setInstaller((prev) => prev ?? s)` — without this, a late-resolving stale snapshot could clobber a fresher transition event delivered via `onInstallerStatus`.
5. Absent-electronAPI test now asserts no IPC calls were made — catches regressions where effect logic runs before the `isElectron()` guard.

## Verification

**Commands (from `dashboard/`):**
- `npm run typecheck` -- zero errors.
- `npm run test -- UpdateBanner` -- all new tests pass.
- `npm run build:electron` -- renderer + main compile cleanly.

**Manual gate (single Linux session, no release required):**
1. In DevTools: `await window.electronAPI.config.set('updates.lastStatus', { lastChecked: new Date().toISOString(), app: { current: '1.3.2', latest: '1.3.3', updateAvailable: true, error: null }, server: { current: null, latest: null, updateAvailable: false, error: null } })`.
2. Reload renderer → expect `available` banner with `[Download] [Later]`.
3. Click `[Later]` → banner disappears; `bannerSnoozedUntil` ≈ `now + 14400000`. Reload → stays hidden.
4. Reset: `await window.electronAPI.config.set('updates.bannerSnoozedUntil', 0)`.
5. Exercise remaining three states via the unit-test matrix.

## Suggested Review Order

**State-machine core**

- Entry point — the pure mapping every state transition flows through.
  [`UpdateBanner.tsx:40`](../../dashboard/components/ui/UpdateBanner.tsx#L40)

- Switch branches — four installer states + fallthrough to poll-based `available`.
  [`UpdateBanner.tsx:59`](../../dashboard/components/ui/UpdateBanner.tsx#L59)

**Mount effect — IPC wiring & race-safety**

- `setInstaller((prev) => prev ?? s)` protects against a late `getInstallerStatus` resolution clobbering a live transition event (post-review patch).
  [`UpdateBanner.tsx:103`](../../dashboard/components/ui/UpdateBanner.tsx#L103)

- 60s `getStatus()` poll surfaces a just-completed `UpdateManager.check()` without adding a new IPC event.
  [`UpdateBanner.tsx:116`](../../dashboard/components/ui/UpdateBanner.tsx#L116)

- Snooze read from electron-store on mount.
  [`UpdateBanner.tsx:130`](../../dashboard/components/ui/UpdateBanner.tsx#L130)

- Live transition subscription — unsubscribe fn is called on unmount.
  [`UpdateBanner.tsx:139`](../../dashboard/components/ui/UpdateBanner.tsx#L139)

**Visual states**

- `available` — Download + Later.
  [`UpdateBanner.tsx:199`](../../dashboard/components/ui/UpdateBanner.tsx#L199)

- `downloading` — NaN-safe percent clamp before CSS width (post-review patch).
  [`UpdateBanner.tsx:218`](../../dashboard/components/ui/UpdateBanner.tsx#L218)

- `ready` — Quit & Install + Later.
  [`UpdateBanner.tsx:244`](../../dashboard/components/ui/UpdateBanner.tsx#L244)

- `ready_blocked` — disabled install with title-tooltip, no Later.
  [`UpdateBanner.tsx:263`](../../dashboard/components/ui/UpdateBanner.tsx#L263)

**Integration**

- Mount site with `isBusy` proxy + `M3-HANDOFF:` marker for the future idle-predicate swap.
  [`App.tsx:691`](../../dashboard/App.tsx#L691)

- New electron-store default key for snooze persistence.
  [`main.ts:428`](../../dashboard/electron/main.ts#L428)

**Tests**

- 13 `deriveBannerState` unit tests covering every I/O matrix row plus post-review defensive rows (empty/null `latest`, malformed `UpdateStatus`).
  [`UpdateBanner.test.tsx:123`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L123)

- Mount-time `getInstallerStatus()` call-count assertion — closes the M1 deferred-work gap.
  [`UpdateBanner.test.tsx:234`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L234)

- Late snapshot does NOT clobber a live transition (race-safety regression test).
  [`UpdateBanner.test.tsx:410`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L410)

- `[Later]` snooze round-trip with `vi.useFakeTimers()` — persisted epoch + remount-within-4h still hidden.
  [`UpdateBanner.test.tsx:345`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L345)
