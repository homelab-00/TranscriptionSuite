---
title: 'UpdateBanner resilience — surface invocation failures as toasts'
type: 'bugfix'
created: '2026-04-13'
status: 'done'
baseline_commit: '4116452e569652701d573c0a4033a16cf72e7e83'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/deferred-work.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-m6-safety-errors.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `UpdateBanner` swallows user-facing invocation failures into a silent `console.error`: `api.download()` throws, `api.install()` throws, and `setConfig()` throws all log-only, and every discriminated `{ok:false, reason}` return from `api.download()` / `api.install()` is ignored entirely. A double-click on [Quit & Install] produces `{ok:false, reason:'install-already-requested'}` that the user never sees; a broken snooze write silently desyncs the persisted state from the in-memory state.

**Approach:** Toast on invocation throws AND on every `{ok:false}` return with copy tailored per reason, consuming the shapes already defined in `electron.d.ts`. Route the new invocation-failure toasts through the existing component-local `lastErrorMessageRef` so repeated identical failures within a session coalesce to one toast. No IPC contract changes. No dedup-hardening (module-level hoist + time-window — deferred to a separate spec).

## Boundaries & Constraints

**Always:**
- Per-reason copy and silent branches: see I/O Matrix. Invocation throws surface the raw `Error.message` (exception: `setConfig` failures get a fixed `"Could not save snooze preference."` — store internals are noise to the user).
- Invocation-failure toasts consult the same `lastErrorMessageRef` as the existing installer-`'error'` branch, so a triple-click producing two identical `install-already-requested` returns toasts exactly once.
- `setConfig` failure in `handleSnooze` still updates in-memory `snoozedUntil` (banner hides even if persistence fails).
- Catches on non-user-facing IPC paths (`getInstallerStatus`, `getStatus`, `getVersion`, `getConfig`) stay `console.error`-only. Those fall under the separate "getInstallerStatus retry-with-backoff" deferred item.

**Ask First:**
- Adding a new IPC reason string (would require `electron.d.ts` change).
- Routing invocation failures to the banner's visual instead of toast.
- Changing dedup semantics (identity-only for now; time-window + module-level hoist are deferred).

**Never:**
- Do NOT hoist `lastErrorMessageRef` to module scope — deferred.
- Do NOT add a 5 s time-window dedup — deferred.
- Do NOT add a local `installing` flag or disabled-button polish — the `'install-already-requested'` toast IS the feedback.
- Do NOT drift into other deferred items (a11y sweep, `nowTimer` → `setTimeout`, `isElectron()` helper drift, CompatGuard memoization, retry-with-backoff on the read-only IPC paths).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior |
|---|---|---|
| `api.download()` throws | `new Error('net down')` | `toast.error("Download failed: net down")` |
| `api.download()` `{ok:true}` / `{ok:true, reason:'already-downloading'}` | happy / benign | no toast |
| `api.download()` `{ok:false, reason:'error', message:'foo'}` | generic fault | `toast.error("Download failed: foo")` (fallback `'unknown error'` if `message` absent) |
| `api.download()` `{ok:false, reason:'no-update-available'}` | stale click | `toast.error("No update available to download.")` |
| `api.download()` `{ok:false, reason:'manual-download-required', …}` | M7 gate | no toast (installer status drives the visual) |
| `api.download()` `{ok:false, reason:'incompatible-server', detail}` | M4 gate | `toast.error("Server v{detail.serverVersion} is not compatible with this Dashboard (requires {detail.compatibleRange}).")` |
| `api.install()` throws | rejected promise | `toast.error("Install failed: {Error.message}")` |
| `api.install()` `{ok:true}` | success (quitting) | no toast |
| `api.install()` `{ok:false, reason:'install-already-requested'}` | double-click | `toast.error("Install already in progress.")` on 2nd click; 3rd identical failure in same session suppressed by identity dedup |
| `api.install()` `{ok:false, reason:'no-update-ready' \| 'no-version'}` | race | `toast.error("No update is ready to install.")` |
| `api.install()` other `{ok:false, reason}` | unseen | `toast.error("Install failed: {reason ?? 'unknown error'}")` |
| `handleSnooze` → `setConfig` rejects | store unwritable | `toast.error("Could not save snooze preference.")`; in-memory `snoozedUntil` still updated |

</frozen-after-approval>

## Code Map

- `dashboard/components/ui/UpdateBanner.tsx` — extend `handleConfirmInstall`, `handleRetry`, `handleInstall`, `handleSnooze` to toast on throws AND inspect discriminated `{ok:false}` returns with per-reason copy. Route invocation-failure toasts through the existing `lastErrorMessageRef` identity check.
- `dashboard/components/ui/__tests__/UpdateBanner.test.tsx` — new `describe('UpdateBanner invocation-failure toasts')` block covering every row of the matrix.

## Tasks & Acceptance

**Execution:**
- [x] `UpdateBanner.tsx` — added `toastInvocationError` useCallback helper that consults / updates `lastErrorMessageRef`. Added `reportDownloadFailure` useCallback (shared by `handleConfirmInstall` + `handleRetry`) that branches per-reason via positive `if` checks (switched from switch-default after TS narrowing didn't compose across negated checks — see Spec Change Log #1). Extended `handleInstall` with per-reason branching. Extended `handleSnooze` catch with `toastInvocationError("Could not save snooze preference.")`. Defined local `DownloadResult` type mirroring `electron.d.ts` (see Spec Change Log #2). Read-only IPC catches untouched.
- [x] `UpdateBanner.test.tsx` — added `describe('UpdateBanner invocation-failure toasts')` with 11 tests covering every matrix row: download throw, download `{ok:false, reason:'error'}`, download `manual-download-required` silence, download `incompatible-server` with detail-string assertion, download `no-update-available`, install throw, install `install-already-requested` triple-click dedup, install `no-update-ready`, install `no-version`, install unknown-reason generic toast, snooze `setConfig` throw + in-memory state check.

**Acceptance Criteria:**
- Given `api.download()` rejects with `new Error('net down')`, when the user confirms [Install] in the modal, then `toastErrorMock` is called once with a string matching `/download failed/i` AND `/net down/`.
- Given `api.install()` returns `{ok:false, reason:'install-already-requested'}` on the second click AND a third rapid click returns the same, when the user clicks [Quit & Install] three times, then `toastErrorMock` is called exactly once with `"Install already in progress."` (identity dedup suppresses the 3rd).
- Given `api.download()` returns `{ok:false, reason:'manual-download-required', downloadUrl:'…'}`, when `handleConfirmInstall` runs, then `toastErrorMock` is NOT called (installer status drives the visual).
- Given `api.download()` returns `{ok:false, reason:'incompatible-server', detail:{serverVersion:'2.0.0', compatibleRange:'>=1.0.0 <2.0.0', deployment:'local'}}`, when `handleConfirmInstall` runs, then `toastErrorMock` is called with a string containing both `'2.0.0'` and `'>=1.0.0 <2.0.0'`.
- Given `handleSnooze`'s `setConfig` rejects, when the user clicks [Later], then `toastErrorMock` is called with `"Could not save snooze preference."` AND the banner transitions to the snoozed/hidden state on the same tick (in-memory `snoozedUntil` updated regardless of persistence failure).
- `cd dashboard && npm run typecheck && npm run test -- UpdateBanner && npm run build:electron` — all green.

## Spec Change Log

1. **Switch-on-reason → positive-branch if/else.** Spec said "switch on `reason`". Initial implementation used a `switch` with a `default` case falling through from `case 'error':` to an `result.message` access. TS reported `Property 'message' does not exist on type '{ ok: true; reason?: "already-downloading"; } | { ok: false; reason: "no-update-available" | "error"; message?: string; }'` — after negated `reason !== X` narrowing, TS re-widened the union to include variant A (the `ok:true` branch), even with a prior `if (result.ok) return;` guard. Rewrote as positive-narrowing `if (result.reason === 'X')` branches, one per failure reason. TS narrows cleanly into each branch. Same behavior; same exhaustiveness; more verbose but survives TS's narrowing quirks. KEEP: the positive-branch shape. Reverting to switch-default on `'error'` will re-surface the same TS error.

2. **Local `DownloadResult` type.** Spec said "consuming the shapes already defined in `electron.d.ts`". Initial implementation used `Awaited<ReturnType<NonNullable<typeof window.electronAPI>['updates']['download']>>` to derive the type inline. TS handled the derived type correctly BUT the verbose expression obscured intent at the call site. Defined a local `DownloadResult` type mirroring the 4-variant union in `electron.d.ts` (line 186-199). If `electron.d.ts` adds a new discriminated variant, the local copy will drift — acceptable trade-off because the compile will catch a mismatch inside `reportDownloadFailure` before runtime.

3. **Exhaustiveness check via `isFailedDownload` type-guard + switch-default `never` (review patch).** Triggered by blind-hunter #4 + edge-hunter #9 (same finding, found independently): the original positive-branch `if/else` chain comment claimed "exhaustive" but had no compile-time check — a new `DownloadResult` variant would silently no-op. First fix attempt inserted `const _exhaustive: never = result;` after the last positive branch, but TS couldn't narrow `result` to `never` because variant A (`{ ok: true; reason?: 'already-downloading' }`) has an optional discriminant that re-enters the narrowing union through subsequent positive `if (result.reason === 'X')` checks. Second attempt assigned through `Extract<DownloadResult, { ok: false }>` after `if (result.ok) return;` — also failed for the same auto-narrowing reason. Final shape: a module-level `isFailedDownload(r): r is Extract<DownloadResult, { ok: false }>` predicate whose explicit `r is <union>` return type sidesteps TS's narrowing limitation; the switch's `default` case then narrows to `never` correctly. Runtime `console.warn` + generic toast remain as belt-and-suspenders for transitional builds where `electron.d.ts` and this component briefly disagree. KEEP: the predicate pattern. Do NOT revert to `if (result.ok) return;` + positive-branch chain — the exhaustiveness check will silently fail.

## Design Notes

**Why branch on `{ok:false}` and not just throws:** The M1-M7 IPC handlers use `ok:false, reason:…` for *expected* failure paths (race, not-ready, manual-download) and `throw` only for unexpected runtime faults. Without branching on the returned shape, `install-already-requested` (benign double-click) is indistinguishable from `no-update-ready` (stale click) and from unseen errors (truly broken) — all three swallowed to `console.error` with no user signal.

**Why reuse the existing `lastErrorMessageRef` (and not introduce a new one):** Invocation failures and installer-`'error'` broadcasts both produce user-facing toasts. Sharing a single dedup ref means a triple-click spamming `install-already-requested` coalesces correctly, AND prevents the edge case where an installer-error toast and an invocation-error toast with identical copy both fire back-to-back. The ref stays component-local with identity-only checks — the module-level hoist and 5 s time-window are deferred so this spec stays surgical.

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` — zero errors.
- `cd dashboard && npm run test -- UpdateBanner` — all existing + new cases pass (no regressions in the 30+ existing tests).
- `cd dashboard && npm run build:electron` — compiles.

**Manual checks:**
- `grep -nE "console\.error\('UpdateBanner:" dashboard/components/ui/UpdateBanner.tsx` — user-facing invocation catches (in `handleConfirmInstall`, `handleRetry`, `handleInstall`, `handleSnooze`) are paired with a `toast.error(…)` / `toastInvocationError(…)` in the same block. Non-user-facing catches (`getInstallerStatus`, `getStatus`, `getVersion`, `getConfig`) remain `console.error`-only — by design.

## Suggested Review Order

**Entry point — the dedup helper everyone funnels through**

- Shared module-scoped identity-dedup gate; called from both the M6 installer-error branch and all four new invocation-failure paths.
  [`UpdateBanner.tsx:216`](../../dashboard/components/ui/UpdateBanner.tsx#L216)

**Download result branching (handleConfirmInstall + handleRetry)**

- Type-guard predicate — TS's built-in narrowing doesn't compose across positive `if (result.reason === 'X')` branches when variant A has an optional discriminant. Predicate sidesteps the limitation and enables the compile-time `never` check.
  [`UpdateBanner.tsx:83`](../../dashboard/components/ui/UpdateBanner.tsx#L83)

- The shared download-failure reporter. Switch with compile-time exhaustiveness via the `default` `never` case; runtime `console.warn` + generic toast as belt-and-suspenders.
  [`UpdateBanner.tsx:358`](../../dashboard/components/ui/UpdateBanner.tsx#L358)

- Callers: `handleConfirmInstall` (modal confirm) and `handleRetry` (error-toast action). Both await `api.download()`, throw-catch toasts with `Error.message`, then delegate `{ok:false}` to `reportDownloadFailure`.
  [`UpdateBanner.tsx:393`](../../dashboard/components/ui/UpdateBanner.tsx#L393)

**Install result branching (handleInstall)**

- Per-reason toast copy via switch on untyped `result.reason` (the `install()` IPC return type uses `reason?: string`, no literal union to exhaustiveness-check). `'install-already-requested'` toast is deduped by the shared ref — triple-click yields one toast.
  [`UpdateBanner.tsx:424`](../../dashboard/components/ui/UpdateBanner.tsx#L424)

**Snooze persistence failure (handleSnooze)**

- Catch now toasts `"Could not save snooze preference."` — the in-memory `setSnoozedUntil` already fired above the try, so the banner still hides on this tick regardless of persistence success.
  [`UpdateBanner.tsx:322`](../../dashboard/components/ui/UpdateBanner.tsx#L322)

**Type scaffolding**

- Local mirror of the `electron.d.ts` `download()` union — acknowledged drift risk per Spec Change Log #2.
  [`UpdateBanner.tsx:63`](../../dashboard/components/ui/UpdateBanner.tsx#L63)

**Tests — matrix parity**

- All 11 matrix rows live in this new describe block; uses the existing `buildHarness`/`installHarness`/`toastErrorMock` scaffolding with no new helpers.
  [`UpdateBanner.test.tsx:995`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L995)

- Triple-click dedup test — mocks `install` with a `{ok:true} → {ok:false,…} → {ok:false,…}` sequence and asserts exactly one toast across three clicks.
  [`UpdateBanner.test.tsx:1110`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L1110)

- Snooze persistence-failure test — asserts both the toast AND that the banner hides on the same tick despite the rejection.
  [`UpdateBanner.test.tsx:1184`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L1184)
