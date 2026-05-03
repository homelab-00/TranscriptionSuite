---
title: 'In-App Update Banner — Error-Toast Dedup Hardening'
type: 'refactor'
created: '2026-04-13'
status: 'done'
baseline_commit: 'deb54e94810ab6f59f821285268865bc18cc44b9'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-banner-resilience.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `UpdateBanner`'s error-toast dedup uses a component-local `useRef<string | null>` keyed on user-visible copy (`UpdateBanner.tsx:208`, `215`, `289`). Five known defects: (1) React remount wipes the ref, re-toasting; (2) rapid `error→downloading→error` loops re-toast near-duplicate messages (different IPs, whitespace) that pass `===`; (3) `handleRetry` clears the ref BEFORE awaiting `api.download()` (line 409) so two concurrent retries both toast; (4) the clear branch only fires on `downloading|downloaded` (line 300) — post-`cancelled`/`idle`, a later same-message error is silently dropped; (5) `handleInstall` stores `"Install already in progress."` but any cross-path source emitting a different copy for the same semantic event both toast.

**Approach:** Hoist dedup out of the component into module-level `{ key, timestamp }`. Dedup by stable **semantic key** composed with a **5 s time window**. Extend state-transition clear to `idle|cancelled`. Stop pre-clearing in `handleRetry`. Export `__resetErrorToastDedup()` for tests.

## Boundaries & Constraints

**Always:**

- Dedup state lives at module scope in `UpdateBanner.tsx`; MUST survive a React remount.
- Dedup predicate: skip iff `incomingKey === state.key && (now - state.timestamp) < 5000`.
- Every toast call site passes a **stable semantic key** literal distinct from the user-visible message.
- Clear (reset key/timestamp) fires on installer transitions into `downloading|downloaded|idle|cancelled`.
- `__resetErrorToastDedup()` is exported and called in the test suite's `beforeEach`.
- `handleRetry` does NOT clear dedup state before awaiting `api.download()`.

**Ask First:**

- Changing the 5 s window or introducing per-key windows.
- Any rename or addition to the key set beyond the Design Notes table.
- Adding a `reason?: string` classifier to the `InstallerStatus` error broadcast (main-side change — flagged out of scope).

**Never:**

- Dedup by copy string alone.
- Re-introduce pre-await clearing in any retry path.
- Expose mutable module state outside `__resetErrorToastDedup`.
- Add an `inFlightRef` concurrency guard — the window absorbs overlapping retries; revisit only if data shows repeat calls.
- Touch `dashboard/electron/updateInstaller.ts` or other main-process files.
- Add new runtime dependencies.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior |
|----------|--------------|---------------------------|
| Identical key within 5 s | `key='download-error'`, `delta=500` ms | Skip toast |
| Identical key after 5 s | same key, `delta=5001` ms | Fire toast; update state |
| Different key | state populated | Fire toast; overwrite state |
| Installer → `downloading`/`downloaded`/`idle`/`cancelled` | state populated | Clear state; next same-key toast fires |
| Cross-path shared key within 5 s | `handleInstall` fires `'install-already-requested'`, installer then emits same key w/ different copy | 1 toast total |
| Two rapid `handleRetry` calls both fail identically | state populated after 1st toast | 2nd suppressed by window |
| Banner unmount + remount within 5 s with populated state | module state survives | Same-key incoming is deduped |
| First-error-of-session | `{key:null, timestamp:0}` | Toast fires unconditionally |

</frozen-after-approval>

## Code Map

- `dashboard/components/ui/UpdateBanner.tsx` -- hosts `lastErrorMessageRef` (line 208); all 11 toast call sites; state-transition clear in `onInstallerStatus` (line 287–304).
- `dashboard/components/ui/__tests__/UpdateBanner.test.tsx` -- existing 3 dedup tests at lines 624, 682, 1110; `beforeEach` near line 150.

## Tasks & Acceptance

**Execution:**

- [x] `dashboard/components/ui/UpdateBanner.tsx` -- delete `lastErrorMessageRef` (line 208). Add module-level `const dedupState: { key: string | null; timestamp: number } = { key: null, timestamp: 0 }` and `const DEDUP_WINDOW_MS = 5_000`. Add `function tryToastDedup(key: string, now: number): boolean` returning `true` (and mutating state) iff `state.key !== key || now - state.timestamp >= DEDUP_WINDOW_MS`; `false` on skip. Add `function resetToastDedup(): void`. Export `function __resetErrorToastDedup(): void` wrapping it with a `/** test-only */` JSDoc.
- [x] `dashboard/components/ui/UpdateBanner.tsx` -- change signature to `toastInvocationError(key: string, message: string)`; body is `if (!tryToastDedup(key, Date.now())) return; toast.error(message);`. Update all callers with the Design Notes keys.
- [x] `dashboard/components/ui/UpdateBanner.tsx` -- in the `onInstallerStatus` `'error'` branch (line 287): derive `const key = s.message ?? 'unknown error'`, guard with `tryToastDedup(key, Date.now())`, then compose copy + `toast.error(...)`. Drop the `lastErrorMessageRef` reads/writes.
- [x] `dashboard/components/ui/UpdateBanner.tsx` -- extend the success branch (line 300) from `downloading|downloaded` to include `idle|cancelled`; replace the ref assignment with `resetToastDedup()`.
- [x] `dashboard/components/ui/UpdateBanner.tsx` -- remove `lastErrorMessageRef.current = null` at `handleRetry` (line 409). Add: `// Dedup state clears on installer's post-retry transition; the 5 s window absorbs overlapping retry clicks.`
- [x] `dashboard/components/ui/__tests__/UpdateBanner.test.tsx` -- import `__resetErrorToastDedup`; call in the outer `beforeEach`. Update the 3 existing dedup tests to match the new dedup contract (note: `'resets the dedup ref after a successful downloading/downloaded transition'` at line 682 still passes structurally; `'install "install-already-requested" dedups'` at line 1110 now relies on the shared key).
- [x] `dashboard/components/ui/__tests__/UpdateBanner.test.tsx` -- add 6 tests. Use `vi.useFakeTimers()` for time-advancement cases:
  1. `'time window: same key re-toasts after 5001 ms'` — 2 toasts
  2. `'time window: same key back-to-back dedups'` — 1 toast (no intervening `downloading`)
  3. `'idle transition clears dedup state'` — error → idle → same error → 2 toasts
  4. `'cancelled transition clears dedup state'` — error → cancelled → same error → 2 toasts
  5. `'two rapid handleRetry calls with identical failure → one toast'` — mock `api.download` to resolve twice with `{ok:false, reason:'error', message:'flaky'}`; fire retry twice in the same task
  6. `'dedup state survives unmount + remount within 5 s'` — render, emit error, `cleanup()`, re-render, emit same error, assert 1 total toast (document that this relies on module-level state)

**Acceptance Criteria:**

- Given module state is `{key:null, timestamp:0}`, when an error broadcast arrives, then `toast.error` fires once AND state reflects the derived key + invocation time.
- Given `dedupState.key='install-already-requested'` set 3 s ago, when `onInstallerStatus` emits a message mapping to that key, then no 2nd toast fires.
- Given two `handleRetry` invocations both resolve with identical `{ok:false, reason:'error', message:'X'}`, when both settle, then `toast.error` was called exactly once across both.
- Given the banner is unmounted then remounted within 5 s with `dedupState.key='download-error'`, when the remounted instance emits a same-key failure, then `toast.error` is NOT called a 2nd time.
- Given `__resetErrorToastDedup()` is called, when the next call site fires, then dedup evaluates as first-of-session.
- `npx vitest run components/ui/__tests__/UpdateBanner.test.tsx` — all pass; `npx tsc --noEmit` — no new errors.

## Design Notes

**Exhaustive key table (all 12 current call sites):**

| Call site | Line | Key |
|---|---|---|
| `toastInvocationError` in `handleSnooze` | 334 | `'snooze-save-failed'` |
| `reportDownloadFailure` → `incompatible-server` | 366 | `'download-incompatible'` |
| `reportDownloadFailure` → `no-update-available` | 372 | `'no-update-available'` |
| `reportDownloadFailure` → `error` | 375 | `'download-error'` |
| `reportDownloadFailure` → `default` | 383 | `'download-error'` |
| `handleConfirmInstall` catch | 400 | `'download-error'` |
| `handleRetry` catch | 416 | `'download-error'` |
| `handleInstall` → `install-already-requested` | 433 | `'install-already-requested'` |
| `handleInstall` → `no-update-ready`/`no-version` | 437 | `'no-update-ready'` |
| `handleInstall` default | 440 | `'install-error'` |
| `handleInstall` catch | 446 | `'install-error'` |
| Installer `'error'` subscription | 289 | `s.message ?? 'unknown error'` |

Three `download-error` and two `install-error` collapses are intentional: the user-visible copy varies (it still interpolates `result.reason` / `err.message`), but the dedup contract treats "a download attempt failed" as one event class. An operator seeing three flavors in ~200 ms reads one toast.

**Singleton reasoning:** `UpdateBanner` is always single-mounted under `MainApp`. StrictMode, parent re-key, or a future navigation refactor would remount it and wipe a `useRef`. A module-level singleton survives. `__` prefix on the reset export signals "internal — do not import from app code."

**Forward-compat:** if `InstallerStatus` later gains a `reason?: string` classifier, the subscription changes to `const key = s.reason ?? s.message ?? 'unknown error'`. The shared-key contract with `handleInstall` activates automatically. Out of scope for this spec.

## Verification

**Commands:**

- `cd dashboard && npx vitest run components/ui/__tests__/UpdateBanner.test.tsx` -- all existing + 6 new tests pass.
- `cd dashboard && npx tsc --noEmit` -- no new type errors.
- `cd dashboard && npm run ui:contract:check` -- clean (no classNames touched).

## Suggested Review Order

**Architectural core — module-level dedup singleton**

- Entry point. The `{ key, timestamp }` state hoisted out of the React tree so remounts don't erase dedup memory.
  [`UpdateBanner.tsx:72`](../../dashboard/components/ui/UpdateBanner.tsx#L72)

- Dedup predicate — key-equality AND 5 s time-window composed together.
  [`UpdateBanner.tsx:75`](../../dashboard/components/ui/UpdateBanner.tsx#L75)

- Test-only export (prefixed `__`) consumed by `beforeEach` to isolate state between tests.
  [`UpdateBanner.tsx:90`](../../dashboard/components/ui/UpdateBanner.tsx#L90)

**Key contract — stable semantic identifiers at every toast call site**

- `toastInvocationError` signature change: keys are now a first-class argument, distinct from user-visible copy.
  [`UpdateBanner.tsx:242`](../../dashboard/components/ui/UpdateBanner.tsx#L242)

- Example cross-path key assignment — `handleInstall` emits `'install-already-requested'` for forward-compat with a future main-side classifier.
  [`UpdateBanner.tsx:478`](../../dashboard/components/ui/UpdateBanner.tsx#L478)

**State-transition clear — widened to idle and cancelled**

- Installer `error` branch goes through `tryToastDedup` using `s.message` as the key (forward-compat with `s.reason ?? s.message`).
  [`UpdateBanner.tsx:323`](../../dashboard/components/ui/UpdateBanner.tsx#L323)

- Extended clear branch — `downloading | downloaded | idle | cancelled` all reset dedup so the next same-key error re-toasts.
  [`UpdateBanner.tsx:342`](../../dashboard/components/ui/UpdateBanner.tsx#L342)

**Concurrency simplification — pre-await clear removed**

- `handleRetry` no longer pre-clears dedup; the 5 s window absorbs overlapping retry clicks.
  [`UpdateBanner.tsx:450`](../../dashboard/components/ui/UpdateBanner.tsx#L450)

**Tests — new coverage for the new contract**

- `beforeEach` reset so module state doesn't leak across cases.
  [`UpdateBanner.test.tsx:158`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L158)

- Fake-timer test locks the 5 s boundary — re-toasts at 5001 ms, dedups below.
  [`UpdateBanner.test.tsx:716`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L716)

- Rapid-retry race: two identical `{ok:false}` returns → exactly one new toast.
  [`UpdateBanner.test.tsx:809`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L809)

- Remount preservation — the StrictMode/re-key regression this spec exists to prevent.
  [`UpdateBanner.test.tsx:845`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L845)
