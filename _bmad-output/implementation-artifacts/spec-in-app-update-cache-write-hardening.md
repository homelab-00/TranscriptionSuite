---
title: 'In-App Update — Cache Write-Site Timeout + Atomic-Copy Hardening'
type: 'refactor'
created: '2026-04-13'
status: 'done'
context: []
baseline_commit: '359d34529ae8bcd5b92bada90291f7d5986220c5'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The installer-cache write path has three latent fault modes that each land the user in a worse state than "no cache at all": (a) `UpdateInstaller.install()` awaits `cacheHook` without a wall-clock bound, so a ~150 MB `copyFile` onto hung storage (USB stick, failing SSD, NFS) blocks the user's "Install" click indefinitely — contradicting the invariant comment at `updateInstaller.ts:77` ("losing the rollback slot is preferable to blocking"); (b) `cachePreviousInstaller` stats `args.sourcePath` then copies it later, so a symlink retarget between the two calls defeats the pre-copy size guard; (c) the unlink-then-copy order wipes the prior cache entry BEFORE the new one is written, so a `copyFile` failure (ENOSPC mid-write, EIO) leaves zero cache where one previously existed.

**Approach:** Wrap the `cacheHook` await with `Promise.race` + a 30 s timeout; on timeout, warn-log and fall through to `quitAndInstall()`. In `cachePreviousInstaller`, resolve `sourceReal = fsp.realpath(args.sourcePath)` once, then stat AND copy that resolved path. Reorder the write to `copyFile → destPath.tmp` → `rename → destPath` → unlink-prior-entries-except-destPath; on any failure before the `rename`, the prior entry survives and the orphaned `.tmp` is swept on the next successful write.

## Boundaries & Constraints

**Always:**
- Cache-hook outcomes (resolve / reject / timeout) MUST all continue to `quitAndInstall()`. Losing the rollback slot is strictly preferable to blocking a user-initiated update (pre-existing invariant, `updateInstaller.ts:77`).
- The atomic write MUST preserve the prior cache entry until the new entry has successfully been `rename`d into place. A failed copy for v1.3.3 must leave v1.3.2 untouched on disk.
- Realpath parity: stat and copy MUST both go through the same resolved path. Capture it once at the top of the write path.
- `tmpPath` MUST live in the same directory as `destPath` so the final `rename` is POSIX-atomic (same filesystem).
- Timeout bound MUST accommodate realistic slow-but-working storage (USB 2.0, slow HDD) for a ~150 MB copy. Use 30 s.

**Ask First:**
- Raising the timeout above 30 s — would prolong a hung "Install" click past one attention span.
- Changing the tmp suffix away from `.tmp` — `parseVersionFromFileName` rejects non-`.AppImage` names, which is the property that keeps stray tmps from surfacing in the rollback path; any alternate suffix must preserve that filter.

**Never:**
- Do NOT attempt crash-recovery of a stray `.tmp` on next startup. The unlink loop on the next successful write (or an orphan sweep path — out of scope) is the only cleanup channel.
- Do NOT swap `copyFile` for `rename(source, destPath)`: the source is the *running* AppImage, and renaming it mid-install would yank the backing file out from under the live process.
- Do NOT branch timeout / rejection into distinct post-hook paths. One "warn-log and proceed" branch for both.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior |
|----------|--------------|---------------------------|
| Healthy cacheHook | resolves <1 s | `install()` → `quitAndInstall()` |
| Hung cacheHook | never resolves | After 30 s: warn-log `'cache-hook timed out'`, `install()` → `quitAndInstall()`, returns `{ok:true}` |
| Rejecting cacheHook | throws (existing path) | Warn-log rejection message, `install()` → `quitAndInstall()` (unchanged behavior) |
| Source symlink retarget | source symlinked, attacker swaps target mid-write | realpath captured once → stat + copy both use the resolved path; retarget has no effect |
| `copyFile` ENOSPC mid-tmp | disk fills during `destPath.tmp` write | No `rename`; prior `TranscriptionSuite-<oldver>.AppImage` survives; returns `write-error`; tmp unlinked best-effort |
| `rename` fails (EXDEV / other) | cross-fs or permission denied | Prior entry intact; returns `write-error`; tmp may linger until next successful write sweep |
| First-run | cache dir empty | copy-to-tmp → rename → no prior unlink needed; returns `{ok:true}` |

</frozen-after-approval>

## Code Map

- `dashboard/electron/updateInstaller.ts` — `install()` awaits `cacheHook` unconditionally at the block wrapped by the "losing the rollback slot is preferable to blocking" comment (lines 289-300).
- `dashboard/electron/installerCache.ts` — `cachePreviousInstaller` stats source at line 100, unlinks prior entries at lines 185-193, then `copyFile(args.sourcePath, destPath)` at line 196.
- `dashboard/electron/__tests__/updateInstaller.test.ts` — existing cacheHook tests (`installRequested`, "cache hook rejected") around lines 495-540. Add new `describe('cacheHook timeout')` alongside.
- `dashboard/electron/__tests__/installerCache.test.ts` — existing happy-path + unlink-prior tests at lines 38-76; symlink-collision / allow-list / size-guard describes at 276, 412, 515. Append new describes for atomic-write + realpath parity.
- `dashboard/electron/main.ts` (informational, no changes) — wires `cacheHook: async (ctx) => cachePreviousInstaller(...)` at 523-537. The new Promise.race lives inside `install()`, so this call site is unchanged.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/updateInstaller.ts` — add `const CACHE_HOOK_TIMEOUT_MS = 30_000` module-level constant. Replace the `await this.cacheHook({ version })` line with `Promise.race` of the hook and a `new Promise((res) => setTimeout(() => res('__timeout__'), CACHE_HOOK_TIMEOUT_MS))`. Use a unique sentinel (module-local `Symbol()` preferred over the string above) to distinguish timeout from an `undefined` hook resolution. On timeout, `logger.warn('cache-hook timed out after 30s; install proceeding without rollback slot')`. Existing try/catch around the await stays; its catch arm still handles rejections. — Closes "cacheHook await has no timeout" (Installer-cache review #1, MEDIUM).
- [x] `dashboard/electron/installerCache.ts` — in `cachePreviousInstaller`, compute `sourceReal` via `fsp.realpath(args.sourcePath)` BEFORE the existing stat/size block. Map ENOENT → `'source-missing'`; pass other errno codes through to the existing error mapping (Group B will refine this further). Replace subsequent `fsp.stat(args.sourcePath)` and `fsp.copyFile(args.sourcePath, …)` with `fsp.stat(sourceReal)` and `fsp.copyFile(sourceReal, …)`. — Closes "TOCTOU on source AppImage" (Installer-cache review #2, LOW).
- [x] `dashboard/electron/installerCache.ts` — reorder the write: compute `destPath = path.join(dir, cacheFileName(version))`, `tmpPath = destPath + '.tmp'`. Sequence: `copyFile(sourceReal, tmpPath)` → `rename(tmpPath, destPath)` → run the unlink-prior-entries loop (same filter as today, but now additionally skip when `path.join(dir, name) === destPath`). Wrap copy + rename in a try/catch that, on error, invokes a best-effort `fsp.unlink(tmpPath).catch(() => {})` and returns the existing `{ok:false, reason:'write-error', message}`. Prior-entry unlink loop MUST run only AFTER a successful `rename`. — Closes "delete-then-copy loses cache on copyFile failure" (M6 review #2, LOW-but-real).
- [x] `dashboard/electron/__tests__/updateInstaller.test.ts` — add `describe('cacheHook timeout')`: (a) `vi.useFakeTimers()`; hook returns a never-resolving Promise; detach `install()`; advance 30_000 ms → awaited promise is `{ok:true}`, `logger.warn` called with `'cache-hook timed out'` substring, `updater.quitAndInstall` called once. (b) hook resolves immediately → `{ok:true}`, no timeout-log, quitAndInstall called once. Restore real timers in `afterEach`.
- [x] `dashboard/electron/__tests__/installerCache.test.ts` — add `describe('atomic-write')`: pre-seed `TranscriptionSuite-1.3.2.AppImage` (`HEALTHY_BYTES`), then (a) `vi.spyOn(fsp, 'copyFile').mockRejectedValueOnce(Object.assign(new Error('ENOSPC'), { code:'ENOSPC' }))` → `result.ok===false`, `readdirSync(dir)` equals `['TranscriptionSuite-1.3.2.AppImage']` (no new `.AppImage`, no `.tmp` residue). (b) `vi.spyOn(fsp, 'rename').mockRejectedValueOnce(new Error('EXDEV'))` → same invariant. Add `describe('source realpath parity')`: symlink `link.AppImage → real.AppImage` (HEALTHY_BYTES); pass `link.AppImage` as `sourcePath`; `vi.spyOn(fsp, 'copyFile')`; assert the first copyFile arg equals `fsp.realpath(symlinkPath)` result (not the symlink input).

**Acceptance Criteria:**
- Given a never-resolving `cacheHook` under `vi.useFakeTimers()`, when the clock advances 30_000 ms, then `quitAndInstall` is called once, `logger.warn` received `'cache-hook timed out'`, and `install()` returned `{ok:true}`.
- Given a cache dir pre-seeded with `TranscriptionSuite-1.3.2.AppImage` and a `copyFile` rejecting ENOSPC, when `cachePreviousInstaller` runs for v1.3.3, then the dir contains exactly `['TranscriptionSuite-1.3.2.AppImage']` — no `-1.3.3.AppImage`, no `.tmp` residue.
- Given `sourcePath` is a symlink to a real file, when `cachePreviousInstaller` runs, then the first `fsp.copyFile` arg equals the `fsp.realpath` result, not the symlink path.
- Given the full pre-existing `installerCache.test.ts` + `updateInstaller.test.ts` suites, then every prior test still passes (regression floor).

## Design Notes

30 s covers realistic slow-but-working media (USB 2.0, slow HDD) for a ~150 MB copy; a failing medium never completes. The pre-existing invariant at `updateInstaller.ts:77` is the authority for "drop the rollback slot rather than block".

`tmpPath = destPath + '.tmp'` shares `dir` under `userDataDir` → same filesystem → POSIX-atomic `rename`. `parseVersionFromFileName` rejects non-`.AppImage` names so stray `.tmp` files from crashed writes are invisible to `getCachedInstaller` and swept on the next successful write's unlink loop. Realpath parity is the cheapest retarget-race defense; a pinned-fd alternative isn't justified for the millisecond-wide threat on `process.env.APPIMAGE`.

## Verification

**Commands:**
- `cd dashboard && npx vitest run electron/__tests__/installerCache.test.ts electron/__tests__/updateInstaller.test.ts` — expected: all existing + new tests green.
- `cd dashboard && npm run typecheck` — expected: no type errors.

## Suggested Review Order

**cacheHook timeout bound + timer-leak hygiene**

- Entry point: the new 30 s bound on the install-path cacheHook await — read this first to grasp why.
  [`updateInstaller.ts:101`](../../dashboard/electron/updateInstaller.ts#L101)

- The Promise.race + sentinel that distinguishes a timed-out hook from one that legitimately resolved with `undefined`.
  [`updateInstaller.ts:321`](../../dashboard/electron/updateInstaller.ts#L321)

- `finally { clearTimeout(timeoutId) }` — in-review patch preventing event-loop leak on the fast path.
  [`updateInstaller.ts:338`](../../dashboard/electron/updateInstaller.ts#L338)

**Atomic cache write + source-realpath parity**

- `sourceReal` captured once; stat + copyFile both reuse it — closes the symlink-retarget TOCTOU window.
  [`installerCache.ts:97`](../../dashboard/electron/installerCache.ts#L97)

- `copyFile → tmpPath` then `rename → destPath`; prior entry is untouched if anything before the rename fails.
  [`installerCache.ts:195`](../../dashboard/electron/installerCache.ts#L195)

- `isSweepable` — in-review patch extending the sweep to include orphan `.AppImage.tmp` files from crashed writes.
  [`installerCache.ts:230`](../../dashboard/electron/installerCache.ts#L230)

**Regression tests**

- Two-case timeout describe — the real contract: after 30 s of never-resolving hook, install still completes.
  [`updateInstaller.test.ts:586`](../../dashboard/electron/__tests__/updateInstaller.test.ts#L586)

- ENOSPC / EXDEV cases assert prior entry survives; orphan-sweep case exercises the in-review patch.
  [`installerCache.test.ts:584`](../../dashboard/electron/__tests__/installerCache.test.ts#L584)

- Realpath-parity witness — copyFile's first arg is the resolved realpath, not the symlink.
  [`installerCache.test.ts:686`](../../dashboard/electron/__tests__/installerCache.test.ts#L686)
