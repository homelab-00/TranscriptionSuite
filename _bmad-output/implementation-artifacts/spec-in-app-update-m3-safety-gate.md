---
title: 'M3: Transcription-safety gate for in-app Dashboard updates'
type: 'feature'
created: '2026-04-12'
status: 'done'
baseline_commit: 'a32ca61155e4f2075de1d59d3694b5dc9e60ea4d'
context:
  - '{project-root}/_bmad-output/brainstorming/brainstorming-session-2026-04-12-in-app-updates.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-m1-electron-updater.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-m2-banner-ui.md'
  - '{project-root}/_bmad-output/implementation-artifacts/deferred-work.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** M1 wired `electron-updater` and M2 shipped the banner, but `updates:install` invokes `autoUpdater.quitAndInstall()` with no active-transcription check — a click in the narrow `ready` window or a race against a just-starting job can terminate an in-flight transcription (violates "AVOID DATA LOSS AT ALL COSTS"). Separately, `gracefulShutdown()` (`main.ts:1680-1735`) force-stops Docker with a 30s timeout **without consulting `is_busy`** — a pre-existing bug the brainstorming doc flagged as naturally fixed by M3's predicate. M2's `isBusy` prop is a renderer-side proxy (`clientRunning || isUploading`) that misses remote recordings, other-client activity, and server-side diarization.

**Approach:** Add a new main-process primitive `isAppIdle()` in `dashboard/electron/appState.ts` that fetches `/api/admin/status` (already exposes `models.job_tracker.is_busy` + `active_user` — see `model_manager.py:908`) with a 5s timeout, fail-closed. Gate `updates:install` via a small `InstallGate` class: idle → proceed; busy → mark `pendingInstall`, start a 30s poll, respond `{ok:false, reason:'deferred-until-idle', detail}`. When the poll sees idle → broadcast `updates:installReady` IPC event; the renderer shows a `sonner` toast with `[Install now] [Later]`. Reuse the same predicate in `gracefulShutdown()`: if busy, prompt the user via async `dialog.showMessageBox` with `[Wait for transcription] / [Quit anyway]`. Swap `UpdateBanner`'s `isBusy` proxy in `App.tsx` to OR in the authoritative `adminStatus.models.job_tracker.is_busy` signal.

## Boundaries & Constraints

**Always:**
- New file `dashboard/electron/appState.ts` exports `isAppIdle(timeoutMs?: number): Promise<{idle, reason?}>` and `class InstallGate`. No growth of `updateInstaller.ts` or `updateManager.ts`.
- `isAppIdle` reads base URL + auth token from the `electron-store` singleton already imported in `main.ts`, using the same store-key hierarchy as `dashboard/src/config/store.ts::getServerBaseUrl` / `getAuthToken` (`connection.*` → `server.*` fallbacks). Default timeout `5000`; `gracefulShutdown` passes `2000`.
- Fetch `${baseUrl}/api/admin/status` with `Authorization: Bearer ${token}` when token present. Reads `.models.job_tracker.is_busy` + `.active_user`. On HTTP !ok / network error / `AbortSignal.timeout` firing → `{idle:false, reason:'server-unreachable'}`. On missing `models.job_tracker` → `{idle:false, reason:'unknown'}`. On busy → ``reason: `active transcription${active_user ? ` (${active_user})` : ''}` ``.
- `InstallGate` is a thin orchestrator injected with `{ idleCheck, onReady, doInstall, pollMs=30_000 }`. Methods: `async requestInstall(): Promise<{ok,reason?,detail?}>`, `cancelPending(): {ok:true}`, `isPending(): boolean`, `destroy(): void`. Only one pending install; second `requestInstall` while pending → `{ok:false, reason:'already-deferred'}`. Poll-to-idle → fire `onReady()` once (does NOT auto-invoke `doInstall` — user must re-confirm via toast).
- `main.ts` constructs one `installGate` near `updateInstaller` (line ~466) with `onReady = () => broadcast('updates:installReady')` and `doInstall = () => updateInstaller.install()`. Rewrites the `updates:install` handler (line ~1245) to delegate to `installGate.requestInstall()`. Adds `updates:cancelPendingInstall` handler. Destroys the gate alongside `updateInstaller.destroy()` at line ~1728.
- `gracefulShutdown()` — before the existing `Promise.race(forceStopContainer, timeout)` at line 1708, invoke `isAppIdle(2000)`. If `!idle.idle && reason !== 'server-unreachable'` → show async `dialog.showMessageBox` (`type:'warning'`, `buttons:['Wait for transcription','Quit anyway']`, `defaultId:0`, `cancelId:0`, `message:'Active transcription in progress'`, `detail:idle.reason`). Response 0 ("Wait") → poll `isAppIdle(2000)` every 5s up to **120s ceiling**, then proceed. Response 1 → proceed immediately. Idle OR `server-unreachable` → no dialog, existing flow.
- `dashboard/App.tsx` — change `<UpdateBanner isBusy>` prop to `(adminStatus?.models as any)?.job_tracker?.is_busy || clientRunning || isUploading`. Remove the `// M3-HANDOFF:` comment. Hoist `useAdminStatus()` to `AppInner` scope if not already present. Subscribe to `window.electronAPI.updates.onInstallReady(...)` via `useEffect` → `sonner` `toast.info('Update ready to install', { action:{label:'Install now', onClick:() => updates.install()}, cancel:{label:'Later', onClick:() => updates.cancelPendingInstall()}, duration: Infinity })`. Cleanup unsubscribe on unmount. Skip when `onInstallReady` is absent.
- `preload.ts` extends `updates` namespace with `cancelPendingInstall(): Promise<{ok:boolean}>` + `onInstallReady(cb): () => void` (mirror existing `onInstallerStatus` pattern). Type mirror in `src/types/electron.d.ts`.

**Ask First:**
- Any UI text beyond toast (`'Update ready to install'` / `[Install now]` / `[Later]`) and dialog (`'Active transcription in progress'` / `[Wait for transcription]` / `[Quit anyway]`).
- Any change to `/api/admin/status` response shape. M3 consumes existing fields only.
- Any change to the 30s poll interval, 5s wait-loop, or 120s gracefulShutdown ceiling.

**Never:**
- Do NOT add server-side push (WebSocket/SSE) for busy transitions — polling only.
- Do NOT change `UpdateInstaller`'s state machine or the frozen `InstallerStatus` union. Gating is a pre-check outside the class.
- Do NOT touch `UpdateBanner.tsx` internals. Only the `isBusy` prop expression in `App.tsx` changes.
- Do NOT auto-invoke install on idle — require user tap on the toast.
- Do NOT poll `/api/admin/status` when no install is pending.
- Do NOT persist `pendingInstall` across Dashboard restarts.
- Do NOT gate `updates:download` — downloads proceed during transcription (locked decision P2 axis-5=C).
- Do NOT wire `isAppIdle` into call sites beyond `updates:install` and `gracefulShutdown` in M3.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior |
|---|---|---|
| Install, idle | `isAppIdle → {idle:true}` | `requestInstall` → `doInstall`; returns its `{ok,reason?}` verbatim. App quits + relaunches. |
| Install, busy | `isAppIdle → {idle:false, reason:'active transcription (u)'}` | pending=true, 30s poll starts. Returns `{ok:false, reason:'deferred-until-idle', detail:'active transcription (u)'}`. |
| Install, server unreachable | `isAppIdle → {idle:false, reason:'server-unreachable'}` | Fail-closed. Same as busy (reason `'deferred-until-idle'`, detail `'server-unreachable'`). |
| Install while pending | `isPending() === true` | `{ok:false, reason:'already-deferred'}`. No second interval. |
| Poll tick → idle | pending=true, tick idle | Clear interval, pending=false, fire `onReady()` once. Installer state stays `downloaded`. |
| Install now from toast | renderer calls `updates.install()` | Re-runs full idleCheck. Busy-again → new pending cycle. |
| Later from toast | renderer calls `updates.cancelPendingInstall()` | Interval + flag cleared; `{ok:true}`. Idempotent if not pending. |
| Destroy mid-poll | `gracefulShutdown` runs | `destroy()` clears interval; `onReady` never fires post-destroy. |
| gracefulShutdown, idle | `isAppIdle(2000) → {idle:true}` | No dialog; existing stop flow. |
| gracefulShutdown, busy, Wait | dialog returns 0 | Poll 5s × up to 120s. Idle → proceed. Ceiling → force-stop (`[Shutdown] Idle-wait ceiling reached` logged). |
| gracefulShutdown, busy, Quit anyway | dialog returns 1 | Proceed immediately. |
| gracefulShutdown, unreachable | reason `'server-unreachable'` | No dialog; existing flow (can't preserve the unreachable). |
| gracefulShutdown, remote server | `useRemote=true`, existing stop-block skip | `isAppIdle` + dialog skipped too. Unaffected. |

</frozen-after-approval>

## Code Map

- `dashboard/electron/appState.ts` -- NEW. `isAppIdle(timeoutMs)` + `class InstallGate`. Reads `electron-store` for URL+token.
- `dashboard/electron/main.ts` -- construct `installGate` (~line 466); rewrite `updates:install` + add `updates:cancelPendingInstall` (~line 1245); wire idle-check + dialog + 5s/120s wait loop into `gracefulShutdown()` (~line 1705); `installGate.destroy()` in cleanup.
- `dashboard/electron/preload.ts` -- extend `updates` namespace (~line 493) with `cancelPendingInstall` + `onInstallReady`.
- `dashboard/src/types/electron.d.ts` -- mirror.
- `dashboard/App.tsx` -- swap `isBusy` expression; remove M3-HANDOFF comment; add `onInstallReady` → Sonner toast effect.
- `dashboard/electron/__tests__/appState.test.ts` -- NEW. Vitest. Mocks `fetch` + electron-store. Covers every I/O matrix row for `isAppIdle` (idle, busy, unreachable, timeout, malformed, with/without token) and `InstallGate` (idle request, busy defer, poll-to-ready, second-request guard, cancel, destroy-mid-poll).

Not changed (frozen): `updateInstaller.ts`, `updateManager.ts`, `UpdateBanner.tsx`, `server/backend/api/routes/admin.py`, `server/backend/core/model_manager.py`.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/appState.ts` -- `isAppIdle(timeoutMs=5000)` fetches `/api/admin/status`, reads `.models.job_tracker.{is_busy,active_user}`, fail-closed on HTTP !ok / network error / `AbortSignal.timeout`. `InstallGate` orchestrator with `requestInstall`/`cancelPending`/`isPending`/`destroy`; destroy-mid-tick safe (re-checks `this.pending` after the awaited idleCheck).
- [x] `dashboard/electron/main.ts` -- imported `createAppState` + `InstallGate`; constructed `appState` + `installGate` right after `updateInstaller` setup; rewrote `updates:install` to delegate to `installGate.requestInstall()`; added `updates:cancelPendingInstall` handler; integrated `isAppIdle(2000)` + async `dialog.showMessageBox` + 5s/120s wait loop into `gracefulShutdown()`; added `installGate.destroy()` to the cleanup block next to `updateInstaller.destroy()`.
- [x] `dashboard/electron/preload.ts` -- extended `updates` namespace (both the `ElectronAPI` interface at line 203 and the preload bridge at line 493) with `cancelPendingInstall()` and `onInstallReady(cb)`. Loosened `install()` return type to include optional `detail`.
- [x] `dashboard/src/types/electron.d.ts` -- mirrored the two new methods and the `detail?: string` field on `install()`.
- [x] `dashboard/App.tsx` -- added `toast` to sonner import; imported `useAdminStatus`; derived `serverIsBusy` from `(adminStatus?.models as ...)?.job_tracker?.is_busy`; swapped `<UpdateBanner isBusy>` to `serverIsBusy || clientRunning || isUploading`; removed the `// M3-HANDOFF:` comment; added a `useEffect` subscribing to `onInstallReady` that fires a Sonner toast with `[Install now]` (→ `updates.install()`) and `[Later]` (→ `updates.cancelPendingInstall()`) actions, unsubscribe on unmount.
- [x] `dashboard/electron/__tests__/appState.test.ts` -- 21 Vitest cases. 12 hit `isAppIdle` (idle, busy with active_user, busy without active_user, HTTP !ok, fetch throws, timeout, missing `models.job_tracker`, is_busy non-boolean, token present/absent, URL built from connection.* locally, remote tailscale, remote lan). 9 hit `InstallGate` (idle request, busy defer with detail, already-deferred, poll→onReady, poll-still-busy, cancelPending, cancelPending idempotent, destroy-mid-tick race).

**Acceptance Criteria:**
- Given `/api/admin/status.models.job_tracker.is_busy=true` and the user invokes `updates:install`, when the handler runs, then it returns `{ok:false, reason:'deferred-until-idle', detail:'active transcription...'}` and no `quitAndInstall` call is made.
- Given `pendingInstall=true`, when the next 30s poll sees `is_busy=false`, then `updates:installReady` is broadcast to all BrowserWindows and the renderer surfaces a Sonner toast with Install now / Later actions.
- Given the user clicks `[Later]`, when `updates:cancelPendingInstall` fires, then the interval is cleared, `isPending()===false`, and no further broadcasts occur.
- Given `gracefulShutdown()` runs while `is_busy=true`, when the dialog resolves, then "Wait" polls every 5s up to 120s before force-stop; "Quit anyway" force-stops immediately.
- Given the server is unreachable during `gracefulShutdown()`, when `isAppIdle(2000)` times out, then no dialog is shown and the existing 30s force-stop path runs unchanged.
- Given `npm run typecheck && npm run test -- appState` from `dashboard/`, zero errors and all new unit tests pass.

## Design Notes

**Post-review defensive patches** (blind hunter + edge-case hunter findings classified `patch`, applied post-draft):
1. `isAppIdle` now distinguishes `reason:'auth-error'` (HTTP 401/403) from `reason:'server-unreachable'` — a non-admin `connection.authToken` used to silently make the shutdown gate a no-op; `gracefulShutdown` now treats both reasons (plus `unknown`) as "can't probe, proceed with quit" but logs the specific reason for diagnostics.
2. `InstallGate` adds a `requesting` flag that's set synchronously before awaiting the initial `idleCheck`. Without it, two concurrent `requestInstall` calls both slipped past the `this.pending` null-check and orphaned the first caller's `setInterval` — a 30s-interval leak that persisted until process exit.
3. `InstallGate.tick()` adds a `tickInFlight` guard so overlapping ticks (if fetch latency ever exceeds `pollMs`) can't issue concurrent `idleCheck` fetches. The single-fire-of-`onReady` guarantee was already covered by the post-await `!this.pending` check, but the overlap guard keeps server load predictable.
4. `InstallGate.destroy()` sets a `destroyed` flag; a `requestInstall` that's mid-`await` at destroy time resolves with `{ok:false, reason:'destroyed'}` instead of installing a doomed-to-leak interval.
5. `gracefulShutdown` skips the blocking dialog when the shutdown is signal-driven (SIGINT/SIGTERM/SIGHUP) — dialogs during systemd/Wayland session teardown risk hanging the logout until the 90s kernel SIGKILL. A new `signalShutdown` flag set by the signal handlers routes around the dialog.
6. The `updates:installReady` Sonner toast now passes a stable `id: 'update-install-ready'` and explicitly `toast.dismiss(id)` from both action handlers (Install now / Later) — prevents rare stacking when rapid defer→idle→defer→idle cycles emit multiple `installReady` events, and guarantees dismissal despite the `duration: Infinity` setting.

**Why main owns the pending state:** A window close / reload would strand a renderer-owned pending flag. Main-owned state matches the locked "auto-queued until idle" decision — user can close the window (tray stays alive) and still get the toast on reopen, provided main is alive.

**Why fail-closed server-unreachable on install but open on shutdown:** For install, blocking is safe — worst case the user retries. For shutdown, blocking a quit on an unreachable server is a worse UX than force-stopping; we can't preserve what we can't reach.

**Why re-validate idle on "Install now" click:** Between broadcast and click the server may have started another job. Re-validation is defense in depth, matching M1's internal `install()` guard philosophy.

**Why OR three signals for `isBusy`:** Server `is_busy` covers STT jobs; `clientRunning` covers local live-mode; `isUploading` covers the upload-to-job-start window (~1-5s). OR-union prevents false-idle during client-side-only work.

**Why 120s ceiling on "Wait":** Longer than the 30s force-stop timeout, shorter than realistic transcription durations. Indefinite wait risks hanging quit on a multi-hour longform job.

## Verification

**Commands (from `dashboard/`):**
- `npm run typecheck` -- zero errors.
- `npm run test -- appState` -- all new tests pass.
- `npm run build:electron` -- compiles.

**Manual gate (Linux, single session):**
1. Start a longform transcription (≥2 min audio).
2. In DevTools while running: `await window.electronAPI.updates.install()` → expect `{ok:false, reason:'deferred-until-idle', detail:'active transcription (...)'}`.
3. Subscribe: `window.electronAPI.updates.onInstallReady(() => console.log('READY'))`.
4. Wait for transcription to finish. Within 30s see `READY` + Sonner toast with `[Install now] [Later]`.
5. Click `[Later]` → toast dismisses; confirm no repeat broadcasts. Click `[Install now]` on a fresh request → app quits + relaunches.
6. `gracefulShutdown`: start a transcription, `File → Quit` → dialog appears; `[Wait for transcription]` → observe polling until idle; `[Quit anyway]` → container force-stops immediately.

## Suggested Review Order

**Core primitive**

- Entry point — fail-closed idle probe with distinct `auth-error` / `server-unreachable` / `unknown` / busy reasons.
  [`appState.ts:41`](../../dashboard/electron/appState.ts#L41)

- 401/403 distinguished from network failure so shutdown can log auth-mode separately without blocking quit.
  [`appState.ts:57`](../../dashboard/electron/appState.ts#L57)

**Install-gate state machine**

- `InstallGate` class — pending-install orchestration with serialization flags.
  [`appState.ts:95`](../../dashboard/electron/appState.ts#L95)

- `requesting` flag prevents concurrent callers from orphaning intervals during the awaited `idleCheck`.
  [`appState.ts:115`](../../dashboard/electron/appState.ts#L115)

- `tickInFlight` guard keeps the poll single-flight even if `idleCheck` latency ever exceeds `pollMs`.
  [`appState.ts:153`](../../dashboard/electron/appState.ts#L153)

**Main-process wiring**

- `installGate` constructed with `onReady = broadcast('updates:installReady')` and `doInstall = updateInstaller.install()`.
  [`main.ts:490`](../../dashboard/electron/main.ts#L490)

- `updates:install` IPC delegates to the gate; `updates:cancelPendingInstall` is the renderer's Later-click escape hatch.
  [`main.ts:1265`](../../dashboard/electron/main.ts#L1265)

**Graceful-shutdown retrofit (pre-existing data-loss fix)**

- Idle-probe + dialog gate — skipped when signal-driven, or when we can't verify state (unreachable/auth-error/unknown).
  [`main.ts:1741`](../../dashboard/electron/main.ts#L1741)

- 5s × 120s-ceiling Wait loop with structured log line on ceiling hit.
  [`main.ts:1766`](../../dashboard/electron/main.ts#L1766)

- `installGate.destroy()` joins the existing cleanup block before `updateInstaller.destroy()`.
  [`main.ts:1801`](../../dashboard/electron/main.ts#L1801)

- `signalShutdown` flag set by SIGINT/SIGTERM/SIGHUP handlers so session teardown can't block on a modal dialog.
  [`main.ts:1820`](../../dashboard/electron/main.ts#L1820)

**Renderer UX**

- `isBusy` prop now ORs the authoritative `serverIsBusy` with the existing client-side proxy.
  [`App.tsx:113`](../../dashboard/App.tsx#L113)

- Sonner toast on `updates:installReady` with stable id + explicit `dismiss` from both action handlers.
  [`App.tsx:127`](../../dashboard/App.tsx#L127)

**IPC surface**

- Preload bridge exposes `cancelPendingInstall` + `onInstallReady` (mirror of `onInstallerStatus` unsubscribe pattern).
  [`preload.ts:508`](../../dashboard/electron/preload.ts#L508)

- Type mirror adds `detail?: string` on `install()` response plus the two new methods.
  [`electron.d.ts:192`](../../dashboard/src/types/electron.d.ts#L192)

**Tests**

- 25 Vitest cases — 14 on `isAppIdle` (including 401/403 auth-error split, URL builder variants), 11 on `InstallGate` (including concurrent-request serialization and destroy-mid-tick race).
  [`appState.test.ts:1`](../../dashboard/electron/__tests__/appState.test.ts#L1)
