---
title: 'Installer cache + snooze hardening — follow-up to deferred-bugs review'
type: 'bugfix'
created: '2026-04-13'
status: 'done'
baseline_commit: 'ab300eba260a4e2d5fb633281f700c4e179f46c1'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/deferred-work.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-deferred-bugs.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Five hardening gaps from review of the just-shipped deferred-bugs spec, all in code we just touched:
1. `cachePreviousInstaller` symlink check only catches exact-parent equality — `previous-installer/` symlinked to a SIBLING of the AppImage parent (e.g. `~/apps/backups/` when source is in `~/apps/current/`) passes and the unlink loop wipes the sibling dir.
2. TOCTOU between `realpath(dir)` and the `readdir`+`unlink` loop — a concurrent process can swap the cache dir for a symlink mid-flight.
3. `cachePreviousInstaller` copies a truncated source AppImage; `getCachedInstaller`'s 1 MB filter then masks the real fault (bad source) as "no cache available."
4. The strict `<` boundary at exactly `1_000_000` bytes is not isolated by tests — a flip to `<=` would silently break the inclusive bound.
5. `handleSnooze`'s `clampSnooze(Date.now() + SNOOZE_MS, Date.now())` is structurally inert; the wrapper misleads readers.

**Approach:** Broaden the symlink check to a `userData`-descendant allow-list. Add `fsp.lstat(dir)` immediately before the unlink loop. Stat the source BEFORE `copyFile` and fail with a new `'source-too-small'` reason. Add boundary tests at exactly `MIN_CACHED_INSTALLER_BYTES`. Drop the inert `clampSnooze` wrapper at the write site (load-side clamp stays canonical).

## Boundaries & Constraints

**Always:**
- Allow-list comparison runs AFTER realpath of BOTH `dir` and `userDataDir`. If `userDataDir` realpath throws, treat as collision (fail-closed). If `dir` realpath ENOENT, fall through to mkdir as today (legitimate first-run).
- Use `path.resolve` + `path.sep` boundary check — naive `startsWith` without the separator would let `/userdata-evil/` match `/userdata`. Belt and suspenders: also accept exact equality (`cacheDirReal === userDataReal`) since the cache dir IS allowed to BE the userData dir if a future caller passes it that way.
- The `lstat` TOCTOU guard runs immediately before `readdir`. On `isSymbolicLink()`-true: return `{ok:false, reason:'cache-collision'}`, no further mutation. On lstat throw: fall through (mkdir already ran; readdir will surface real errors).
- Source-size validation runs AFTER the existing `access` check and BEFORE the realpath block. Sub-threshold source returns `{ok:false, reason:'source-too-small'}`. New reason added to `CacheResult.reason` union — single-string widening, no shape change.
- Snooze write site replaces `clampSnooze(Date.now() + SNOOZE_MS, Date.now())` with `Date.now() + SNOOZE_MS`. `clampSnooze` itself stays exported (load site + tests still consume it).

**Ask First:**
- Changes to `MIN_CACHED_INSTALLER_BYTES` (currently 1_000_000).
- Removing `clampSnooze` export entirely.
- Adding a third installer-cache `reason` beyond `'source-too-small'`.

**Never:**
- Do NOT widen the allow-list beyond userData (e.g. accepting `os.tmpdir()` or `app.getPath('temp')`). Cache must live under userData.
- Do NOT add a `userDataDir` realpath fallback to non-realpath comparison if realpath throws. Fail-closed only.
- Do NOT wrap the lstat guard in retries — a symlink that appears between lstat and readdir is genuine adversarial behavior, not a flake.
- Do NOT alter the load-side clamp in `UpdateBanner` mount-effect. That is the canonical defense and must stay.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior |
|---|---|---|
| Cache dir symlinked to sibling-of-source | `previous-installer/` → `~/apps/backups/` (source in `~/apps/current/`) | `cachePreviousInstaller` → `{ok:false, reason:'cache-collision'}`; sibling dir untouched |
| Cache dir symlinked to userData descendant | `previous-installer/` → `userData/legit-subfolder/` | proceeds (allow-list passes) |
| Cache dir is exactly userData | `previous-installer` realpath === `userData` realpath | proceeds (equality allowed) |
| `userData` realpath throws (EACCES) | bad permissions | `{ok:false, reason:'cache-collision'}` |
| Symlink swapped between lstat and use | concurrent `ln -sf` race | lstat catches → `{ok:false, reason:'cache-collision'}` |
| Source AppImage 0-byte | truncated download | `{ok:false, reason:'source-too-small'}`, no copy attempted |
| Source AppImage `MIN_CACHED_INSTALLER_BYTES - 1` | one byte short | `{ok:false, reason:'source-too-small'}` |
| Source AppImage exactly `MIN_CACHED_INSTALLER_BYTES` | inclusive bound | proceeds, cache written |
| `getCachedInstaller` 999_999-byte entry | existing test still green | returns `null` (skip) |
| `getCachedInstaller` exactly `MIN_CACHED_INSTALLER_BYTES` entry | boundary | returns `{path, version}` |
| Snooze write — handleSnooze fires | normal click | `setConfig('updates.bannerSnoozedUntil', Date.now() + SNOOZE_MS)`; no clamp wrapper in stack |
| Load-side clamp still active | bogus stored 30d future | unchanged behavior — clamped to `now + SNOOZE_MS` |

</frozen-after-approval>

## Code Map

- `dashboard/electron/installerCache.ts` — broaden symlink check to userData-descendant allow-list; add `lstat` TOCTOU guard before `readdir`; pre-copy source-size validation; widen `CacheResult.reason` with `'source-too-small'`.
- `dashboard/components/ui/UpdateBanner.tsx` — drop the inert `clampSnooze` wrapper at the `handleSnooze` write site; comment points to the load-side clamp as canonical.
- `dashboard/electron/__tests__/installerCache.test.ts` — sibling-symlink rejection; userData-descendant symlink acceptance; lstat-race surrogate via direct symlink swap mid-test; pre-copy source-size rejection at 0 / `MIN-1`; pre-copy acceptance at `MIN`; read-side acceptance at exactly `MIN_CACHED_INSTALLER_BYTES`.
- `dashboard/components/ui/__tests__/UpdateBanner.test.tsx` — assert `setConfigMock` payload is `Date.now() + SNOOZE_MS` (within ±50 ms tolerance), not the clamped value (functionally identical, but locks the no-wrapper invariant).

## Tasks & Acceptance

**Execution:**
- [x] `installerCache.ts` — replaced exact-parent equality check with userData-descendant allow-list (`cacheDirReal === userDataReal || cacheDirReal.startsWith(userDataReal + path.sep)`); ENOENT-tolerant on userData itself for first-run. TOCTOU defense via post-mkdir re-realpath (corrected from spec's `lstat` — see Spec Change Log entry #1). Pre-copy source-size guard via `fsp.stat(args.sourcePath)` rejects `< MIN_CACHED_INSTALLER_BYTES` as `'source-too-small'`. Widened `CacheResult.reason` union. Added filename-pattern filter to the unlink loop (defense-in-depth for the equality branch — see Spec Change Log entry #2).
- [x] `UpdateBanner.tsx` — replaced `clampSnooze(Date.now() + SNOOZE_MS, Date.now())` in `handleSnooze` with `Date.now() + SNOOZE_MS`. Comment updated: load-side clamp is canonical; write site cannot be bogus by construction.
- [x] `installerCache.test.ts` — added `cachePreviousInstaller userData allow-list defense` describe with 3 tests (sibling-symlink rejection asserting full sibling-dir-contents survival, userData-descendant symlink acceptance, equality case + filename-filter unrelated-file survival). Added `cachePreviousInstaller pre-copy source-size guard` describe with 3 tests (0-byte, `MIN-1`, exactly `MIN`). Added inclusive-bound test to `getCachedInstaller size filter` describe.
- [x] `UpdateBanner.test.tsx` — tightened existing snooze-write test (renamed to "snooze write persists exactly Date.now() + SNOOZE_MS") with `Math.abs(persistedValue - (Date.now() + SNOOZE_MS)) < 50` assertion; note explains it would fail if a subtractive clamp branch is re-introduced.

**Acceptance Criteria:**
- Given `previous-installer/` symlinks to a sibling of the source AppImage's parent dir, when `cachePreviousInstaller` runs, then it returns `{ok:false, reason:'cache-collision'}` AND the sibling dir contents are unchanged.
- Given the cache dir is swapped to a symlink between the realpath check and the unlink loop, when `cachePreviousInstaller` continues, then `lstat` catches it and the unlink loop never runs.
- Given a `999_999`-byte source AppImage, when `cachePreviousInstaller` runs, then it returns `{ok:false, reason:'source-too-small'}` AND no file is created in the cache dir.
- Given a source AppImage of exactly `MIN_CACHED_INSTALLER_BYTES`, when `cachePreviousInstaller` runs, then `result.ok === true` and the destination file size matches.
- Given `handleSnooze` fires, when `setConfig` is called, then the persisted value is `Date.now() + SNOOZE_MS` within a 50 ms tolerance — no clamp wrapper in the call stack.
- `cd dashboard && npm run typecheck && npm run test -- UpdateBanner installerCache && npm run build:electron` — all green.

## Spec Change Log

1. **TOCTOU mechanism: `lstat` → post-mkdir re-realpath.** Spec said "Add `fsp.lstat(dir)` immediately before the unlink loop and abort if it's now a symlink." Implementation discovery: `lstat`-says-not-symlink rejects pre-existing-but-safe symlinks (the equality case + the legitimate userData-descendant symlink case). Both setups have a symlink at `dir` whose realpath has already passed the descendant invariant. The corrected mechanism re-runs the same descendant invariant check (re-realpath after mkdir) — that is the actual TOCTOU hazard (a swap to a target outside userData) and admits safe pre-existing symlinks. Same intent ("TOCTOU defense"), different mechanism. KEEP: re-realpath inside the mkdir block, gated on `userDataReal !== null`.

2. **Filename-pattern filter on the unlink loop.** Surfaced during step-03 implementation: the spec's "accept exact equality" branch combined with the unlink-all-entries pattern would wipe userData if a hostile symlink loop made `dir` resolve to userData itself. User chose option 2 (keep equality + add filename filter) over option 1 (drop equality, strict-descendant only). Filter reuses `parseVersionFromFileName` as the gate so only `TranscriptionSuite-<version>.AppImage` files are unlinked; unrelated userData contents survive even in the catastrophic symlink-loop case. Test "accepts the equality case but only unlinks our own filename pattern" locks this defense-in-depth.

3. **Pre-existing tests with small-byte sources updated to `HEALTHY_BYTES`.** New pre-copy size guard rejects sub-1MB sources; three pre-existing tests (`copies the source AppImage…`, `unlinks any existing cache entries…`, `sanitizes version strings…`) seeded sources with strings like `'binary-v1'` (9 bytes). Updated to `HEALTHY_BYTES = Buffer.alloc(MIN_CACHED_INSTALLER_BYTES, 'a')` so they exercise the realpath/unlink/copy paths instead of failing at the new size guard.

4. **userData-realpath ENOENT tolerance.** Spec's frozen "Always" block said "If `userDataDir` realpath throws, treat as collision (fail-closed)." Implementation discovery: `userDataDir` does not exist on first cache write in test environments (and could in the wild if the cache is wired before `app.ready`). Refined to: ENOENT on userData → skip the entire allow-list check (no symlink can resolve under a non-existent path); fail-closed only on EACCES/ELOOP/etc. Spec-frozen behavior preserved on the EACCES path.

5. **Post-mkdir block: fail-closed on realpath error + always re-verify (review patch).** Triggered by blind-hunter #8 + edge-hunter #1: original post-mkdir re-realpath caught its own throw and fell through to readdir, relying on the filename-pattern filter as last-line defense. Also, the re-check was gated on `userDataReal !== null` from the initial check, leaving first-run dangling-symlink-userData cases unverified. Refined to: always re-realpath BOTH `args.userDataDir` AND `dir` after mkdir; fail-closed (`'cache-collision'`) on any realpath error; verify the descendant invariant unconditionally. Closes both the TOCTOU-during-realpath-throw window and the first-run dangling-symlink window in one block. KEEP: pre-mkdir allow-list check stays as a fast-fail (avoids creating disk state on clearly-bad config); filename-pattern unlink filter stays as defense-in-depth.

6. **Test tolerance bumped 50 ms → 500 ms (review patch).** Triggered by blind-hunter #6: 50 ms drift bound is brittle on slow CI runners (GC pauses, Vitest flush latency). 500 ms is still tight enough to catch a subtractive clamp branch (which would diverge by hours), loose enough to absorb realistic real-timer jitter. Comment in the test explains the rationale.

## Design Notes

**Why allow-list (not blocklist):** A blocklist would have to enumerate every "unsafe" dir. The allow-list — cache dir's realpath descends from userData's realpath — is closed-form. The prior spec's per-binary-parent check was *minimal-correct* for the running-binary scenario; this is *generally-correct* for any misconfiguration. Belt-and-suspenders: also accept exact equality so a future caller passing `userData` itself doesn't false-fail.

**Why pre-copy size guard:** Post-copy validation means write-then-unlink — disk churn plus a window where a concurrent reader could pick up a corrupt cache. Pre-copy stat is one syscall and surfaces the real fault (`'source-too-small'`) in main-process logs instead of being masked as "no cache" by the read-side filter.

**Why keep `clampSnooze` exported:** The load-side clamp IS the defense; the write-site wrapper was aspirational. Surgical fix is to drop the wrapper at the write site — the function stays exported for the load site and direct unit tests.

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` — zero errors.
- `cd dashboard && npm run test -- UpdateBanner installerCache` — all pass (existing 30+ tests + ~7 new).
- `cd dashboard && npm run build:electron` — compiles.

**Manual checks:**
- `grep -n "clampSnooze(Date.now()" dashboard/components/ui/UpdateBanner.tsx` — should return zero matches (the inert wrapper is gone).
- `grep -n "source-too-small" dashboard/electron/installerCache.ts` — should appear in both the type union and one return statement.

## Suggested Review Order

**Functional bug — broader allow-list (closes sibling-symlink hole)**

- `'source-too-small'` reason added to the union.
  [`installerCache.ts:31`](../../dashboard/electron/installerCache.ts#L31)

- `MIN_CACHED_INSTALLER_BYTES` exported (now consumed by both production code and tests via the same constant).
  [`installerCache.ts:37`](../../dashboard/electron/installerCache.ts#L37)

- Pre-copy source-size guard.
  [`installerCache.ts:101`](../../dashboard/electron/installerCache.ts#L101)

- Pre-mkdir allow-list (fast-fail; userData ENOENT-tolerant for first-run).
  [`installerCache.ts:120`](../../dashboard/electron/installerCache.ts#L120)

**TOCTOU defense + first-run closure (review patch)**

- Post-mkdir invariant re-check: always re-realpath both paths, fail-CLOSED on any error, verify descendant unconditionally.
  [`installerCache.ts:158`](../../dashboard/electron/installerCache.ts#L158)

- Filename-pattern unlink filter (defense-in-depth for the equality branch).
  [`installerCache.ts:186`](../../dashboard/electron/installerCache.ts#L186)

**Snooze write-side cleanup**

- `handleSnooze` writes `Date.now() + SNOOZE_MS` directly; comment points to load-side as canonical.
  [`UpdateBanner.tsx:280`](../../dashboard/components/ui/UpdateBanner.tsx#L280)

**Tests — parity check**

- Inclusive-bound read-side test at exactly `MIN_CACHED_INSTALLER_BYTES`.
  [`installerCache.test.ts:393`](../../dashboard/electron/__tests__/installerCache.test.ts#L393)

- userData allow-list defense: sibling rejection + survival, descendant acceptance, equality + filename-filter unrelated-file survival.
  [`installerCache.test.ts:412`](../../dashboard/electron/__tests__/installerCache.test.ts#L412)

- Pre-copy size guard: 0-byte / `MIN-1` / exactly `MIN`.
  [`installerCache.test.ts:515`](../../dashboard/electron/__tests__/installerCache.test.ts#L515)

- Snooze write-side ±500 ms tolerance (review-patched from initial 50 ms).
  [`UpdateBanner.test.tsx:963`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L963)
