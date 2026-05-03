---
title: 'In-App Update — M1-M7 + Hardening Test-Coverage Closeout'
type: 'chore'
created: '2026-04-13'
status: 'done'
context: []
baseline_commit: '1b5cdb5f0eaba6ac0d8c240adcdbcfc3fb924301'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Several deferred coverage gaps from M1-M7 + hardening reviews remain unexercised: (a) `handleRetry`'s catch arm (when `api.download()` throws rather than returns `{ok:false}`) is unreached; (b) the snooze re-surface branch (banner re-appears after the 4 h window expires) is untested — only the within-4 h stay-hidden branch is; (c) the `STATUS_POLL_MS` (60 s) `getStatus()` re-poll never fires under the existing fake timers; (d) UpdateBanner's `clearInterval` + unsubscribe on unmount have no assertion; (e) `installerCache.MIN_CACHED_INSTALLER_BYTES` is consumed by both write-side guard and read-side filter with no invariant test guarding their parity; (f) the symlink-collision equality-case test only verifies one-level userData survival — nested userData state could be wiped silently by a refactor; (g) `isTrustedReleaseUrl` + `buildReleaseUrl` are security-relevant top-level functions in `main.ts` with no direct unit coverage (their guards against `%2e%2e`, userinfo bypass, and `vv` prefix injection are tested only implicitly via M7's IPC handler tests).

**Approach:** Add focused tests in the existing test files for items (a)-(f). For item (g), extract the two helpers to a new `dashboard/electron/releaseUrl.ts` module (pure functions, no side effects) and add a dedicated test file. `main.ts` re-imports from the new module — zero behavior change.

## Boundaries & Constraints

**Always:**
- Tests for items (a)-(f) MUST be additive only — no production-code changes outside the (g) refactor.
- The (g) extraction MUST preserve byte-for-byte identical behavior. The new module exports `isTrustedReleaseUrl` + `buildReleaseUrl` AND the `RELEASE_PATH_RE` constant if the test needs it; `main.ts` imports them and the existing call sites stay structurally unchanged.
- Snooze-resurface test MUST use `vi.useFakeTimers()` to fast-forward past `snoozedUntil` rather than mocking `Date.now` — the banner already binds `Date.now()` via its `nowTimer`, so timer advancement is the canonical way to reach the resurface branch.
- The 60 s `STATUS_POLL_MS` test MUST assert the `getStatus` mock fire-count increases after `vi.advanceTimersByTime(60_000)`, not just that the mock was called once.

**Ask First:**
- Adding new production-code paths beyond the releaseUrl extraction (e.g. exposing internal banner state for testing). The spec is test-coverage-only; widening into refactors invalidates the chore framing.
- Hoisting `STATUS_POLL_MS` or `SNOOZE_MS` into a shared constants file. Out of scope.

**Never:**
- Do NOT modify `UpdateBanner.tsx` business logic for any coverage gap. If a gap can only be covered by adding instrumentation, leave it deferred.
- Do NOT extract `resolveExpectedSha256` or other main.ts helpers — only the two release-URL functions named in the deferred item.
- Do NOT add tests that exercise real network or real Electron app instances. All tests stay in the existing vitest unit-test boundary.

## I/O & Edge-Case Matrix

| Test target | Input / State | Expected assertion |
|-------------|--------------|-------------------|
| handleRetry catch arm | `api.download.mockRejectedValue(new Error('boom'))`, click Retry on a toast | Single toast with `'Download failed: boom'` (uses `'download-error'` dedup key) |
| Snooze resurface | Click Later, fake-timer advance past `now + SNOOZE_MS`, render | Banner re-appears (state: `available`) |
| 60 s status poll | mount banner, fake-timer advance 60_000 ms | `api.getStatus` mock call count goes from 1 (mount) to 2 (poll) |
| Unmount cleanup | mount banner, unmount | `api.onInstallerStatus` unsubscribe fn invoked once; `clearInterval` evidence (subsequent fake-timer advance does NOT re-fire poll) |
| MIN bytes invariant | direct constant assertion | `MIN_CACHED_INSTALLER_BYTES` value used by both write-side `cachePreviousInstaller` and read-side `getCachedInstaller` is identical |
| Symlink depth >1 | userData with nested `nested/dir/random.txt`; equality-case symlink rejected | After rejection, `nested/dir/random.txt` still readable with original bytes |
| `isTrustedReleaseUrl` direct | `https://x:y@github.com/...`, `/releases/%2e%2e/...`, `https://github.com.evil.com/...`, `vv1.3.3` paths, valid `/releases/tag/v1.3.3` | All hostile inputs return `false`; valid input returns `true` |
| `buildReleaseUrl` direct | `null`, `'1.3.3'`, `'v1.3.3'`, `'vv1.3.3'`, `''` | `null`/`''` → `/releases/latest`; `'v…'` and `'vv…'` both strip to a single `v` prefix |

</frozen-after-approval>

## Code Map

- `dashboard/electron/main.ts:594-624` — `buildReleaseUrl` and `isTrustedReleaseUrl` to extract.
- `dashboard/electron/releaseUrl.ts` (NEW) — destination module for the two helpers.
- `dashboard/electron/__tests__/releaseUrl.test.ts` (NEW) — direct unit tests.
- `dashboard/components/ui/UpdateBanner.tsx:450-461` — `handleRetry` catch arm under test.
- `dashboard/components/ui/UpdateBanner.tsx:41,283-292,347-355` — `STATUS_POLL_MS` constant + status poll setInterval + cleanup.
- `dashboard/components/ui/UpdateBanner.tsx:453-493` — existing snooze test pattern (`Later click persists snooze + hides banner; stays hidden on remount within 4h`).
- `dashboard/components/ui/__tests__/UpdateBanner.test.tsx` — append new tests in the existing top-level `describe('UpdateBanner component')` and the existing M6-toasts describe.
- `dashboard/electron/installerCache.ts:37` — `MIN_CACHED_INSTALLER_BYTES` constant.
- `dashboard/electron/__tests__/installerCache.test.ts` — append new MIN-invariant + nested-survival tests.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/releaseUrl.ts` — NEW file. Move `RELEASE_PATH_RE`, `isTrustedReleaseUrl`, `buildReleaseUrl` verbatim from `main.ts` (preserve comments). Export all three.
- [x] `dashboard/electron/main.ts` — replace the moved bodies with `import { buildReleaseUrl, isTrustedReleaseUrl } from './releaseUrl.js';`. Delete the original definitions. Call sites at 562 and 1556 stay unchanged.
- [x] `dashboard/electron/__tests__/releaseUrl.test.ts` — NEW file. `describe('isTrustedReleaseUrl')` with cases: valid `/releases/latest`, valid `/releases/tag/v1.3.3`, `https://github.com.evil.com/releases/latest` (origin spoof), `https://x:y@github.com/releases/latest` (userinfo bypass), `https://github.com/releases/%2e%2e/foo` (percent encoding bypass), `https://github.com/homelab-00/Other/releases/latest` (wrong repo), `https://github.com/releases/tag/vfoo bar` (path injection), `not-a-url`. `describe('buildReleaseUrl')` with cases: `null` → `/releases/latest`, `''` → `/releases/latest`, `'1.3.3'` → `/releases/tag/v1.3.3`, `'v1.3.3'` → `/releases/tag/v1.3.3` (single v), `'vv1.3.3'` → `/releases/tag/v1.3.3` (vv guard).
- [x] `dashboard/components/ui/__tests__/UpdateBanner.test.tsx` — add `describe('Deferred coverage closeout')` containing: (1) handleRetry catch arm — emit error state, click Retry button on the toast (or invoke retry directly), with `h.download.mockRejectedValue(new Error('boom'))`. Assert single toast with `'Download failed: boom'`. (2) Snooze resurface — Later click, `vi.useFakeTimers()`, advance past SNOOZE_MS (4 h = 14_400_000 ms), trigger re-render, assert banner visible with `available` state. (3) 60 s status poll — mount banner, fake-timer advance 60_000 ms, assert `h.getStatus` call count is 2 (mount + poll). (4) Unmount cleanup — mount banner, capture the unsubscribe spy returned by `onInstallerStatus`, unmount, advance fake timers 60_000 ms, assert unsubscribe was called AND `h.getStatus` call count did not increment past mount.
- [x] `dashboard/electron/__tests__/installerCache.test.ts` — add: (1) MIN-invariant test that calls `cachePreviousInstaller` with a source one byte under MIN (rejected) and one byte at MIN (accepted), THEN calls `getCachedInstaller` against a manually-placed file one byte under MIN (filtered to null) and at MIN (returned) — exercising both sides of the same constant. (2) Nested-userData-survival test: pre-seed `userData/nested/dir/keep.txt` (1 KB), trigger the equality-case symlink rejection (existing test scaffold at line 289), assert `nested/dir/keep.txt` is byte-identical after the rejection.

**Acceptance Criteria:**
- Given `api.download` mocked to throw `new Error('boom')`, when `handleRetry` is invoked, then exactly one toast surfaces with text containing `'Download failed: boom'`.
- Given the banner is snoozed via Later click, when the fake clock advances past `SNOOZE_MS` and a re-render happens, then the `available` banner is visible again.
- Given the banner is mounted with `api.getStatus` having recorded one call, when fake timers advance 60_000 ms, then `api.getStatus` call count is exactly 2.
- Given the banner is mounted then unmounted, when fake timers advance 60_000 ms post-unmount, then the `onInstallerStatus` unsubscribe spy was called once AND `api.getStatus` call count did not increment.
- Given a source AppImage of size `MIN_CACHED_INSTALLER_BYTES - 1` AND another at `MIN_CACHED_INSTALLER_BYTES`, when both write+read paths exercise these sizes, then under-MIN is rejected on write AND filtered on read; at-MIN is accepted on write AND returned on read.
- Given a userData with nested `nested/dir/keep.txt` (1 KB content), when the equality-case symlink-collision rejection fires, then `nested/dir/keep.txt` is byte-identical (no traversal-into-userData side effects).
- Given the new `releaseUrl.ts` module, when the test suite runs, then all 13 test cases pass, and `npm run typecheck` is clean (no missing-import errors at the moved call sites in `main.ts`).

## Verification

**Commands:**
- `cd dashboard && npx vitest run electron/__tests__/releaseUrl.test.ts electron/__tests__/installerCache.test.ts components/ui/__tests__/UpdateBanner.test.tsx` — expected: all new tests green, no regressions on existing.
- `cd dashboard && npm run typecheck` — expected: clean; the main.ts import + new module compile.

## Suggested Review Order

**Pure-function extraction (releaseUrl module)**

- Entry point: the new `releaseUrl.ts` module — read this first to understand what was extracted from main.ts and why.
  [`releaseUrl.ts:1`](../../dashboard/electron/releaseUrl.ts#L1)

- `buildReleaseUrl` — in-review docstring patch honestly describes the single-v strip and the documented `vv1.3.3` regression path.
  [`releaseUrl.ts:28`](../../dashboard/electron/releaseUrl.ts#L28)

- `isTrustedReleaseUrl` — origin allow-list, userinfo bypass defense, percent-encoding bypass defense (path-only).
  [`releaseUrl.ts:49`](../../dashboard/electron/releaseUrl.ts#L49)

**Direct unit coverage for the extracted module**

- `isTrustedReleaseUrl` — 17 cases covering valid + 6 hostile + intentional-permissive (query/fragment %).
  [`releaseUrl.test.ts:18`](../../dashboard/electron/__tests__/releaseUrl.test.ts#L18)

- `buildReleaseUrl` — 6 cases including the `vv` round-trip witness.
  [`releaseUrl.test.ts:167`](../../dashboard/electron/__tests__/releaseUrl.test.ts#L167)

**UpdateBanner deferred-coverage closeout**

- `Deferred coverage closeout` describe — handleRetry catch arm + snooze resurface + 60 s poll + unmount cleanup. Includes the in-review tightening (toBe vs toBeGreaterThan, `vi.getTimerCount() === 0`, second-toast shape).
  [`UpdateBanner.test.tsx:1383`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L1383)

**installerCache invariant + nested-survival**

- MIN-bytes invariant: write-side rejects MIN-1, read-side filters MIN-1. Locks the constant against drift between consumers.
  [`installerCache.test.ts:1005`](../../dashboard/electron/__tests__/installerCache.test.ts#L1005)

- Nested userData survival: equality-case symlink rejection leaves arbitrary deep state byte-identical. In-review patch pins `result.ok === true` (current behavior).
  [`installerCache.test.ts:1063`](../../dashboard/electron/__tests__/installerCache.test.ts#L1063)
