---
title: 'In-App Update — Installer-Cache Error-Classification Refinement'
type: 'refactor'
created: '2026-04-13'
status: 'done'
context: []
baseline_commit: 'd217251784d54060b67480fbba6fb158a2381485'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `cachePreviousInstaller`'s `CacheResult.reason` union has four over-broad buckets that make operator debugging ambiguous: (a) `'source-missing'` today catches both a genuine ENOENT AND any other errno (EACCES/EPERM/EIO/ELOOP) from `realpath`/`stat`, so an operator seeing "source-missing" in logs can't tell "file absent" from "permission denied"; (b) `'cache-collision'` today catches three semantically distinct conditions — a hostile symlink that leaves the userData allow-list, a non-ENOENT failure resolving userData or the cache dir, and a post-mkdir TOCTOU race — all with the same log string; (c) `sourcePath` is unvalidated — the current sole caller (`main.ts:527`) hardcodes `process.env.APPIMAGE`, but `cachePreviousInstaller` is a general function and a future caller could pass an arbitrary readable file (e.g. `/etc/shadow`) and it would land in the rollback slot; (d) the sweep loop tolerates a directory that matches our filename pattern — `unlink` fails with EISDIR and the catch swallows it, so the hostile directory persists across installs and confuses `getCachedInstaller`.

**Approach:** Replace `'source-missing'` / `'cache-collision'` with narrower reasons whose names name the specific failure mode. Add a pre-realpath basename allow-list (`.AppImage` suffix) that rejects non-AppImage sources early. In the sweep, `lstat` each entry before `unlink` and skip directories (log-only; no recursive delete — the cache is a rollback slot, not user data worth aggressive recovery).

## Boundaries & Constraints

**Always:**
- ENOENT on source `realpath`/`stat` MUST map to `'source-missing'`. Non-ENOENT errors MUST map to `'source-stat-failed'`. The two must be distinguishable from the result without parsing `message`.
- Each current `'cache-collision'` return path MUST be reclassified. No non-enumerated fall-through code may remain.
- The basename check MUST run AFTER `platform !== 'linux'` short-circuit (so the platform-not-supported case stays first).
- The sweep MUST skip directory entries matching our filename pattern; it MUST NOT `fsp.rm({recursive:true})` them (risk of wiping unrelated user content accidentally placed inside a same-named directory).
- Existing acceptance tests that assert on the SPECIFIC failure mode (e.g. symlink-collision → `cache-symlink-outside-userdata`) MUST be updated. Tests asserting only `ok === false` without a reason check do not need updating.

**Ask First:**
- Adding a "configured install-root" constraint on `sourcePath` (beyond the `.AppImage` basename check). The deferred item mentioned it as optional — it requires plumbing a new `CacheArgs.installRoot` field. Skip unless the human explicitly asks.
- Deleting directory matches recursively (as opposed to skipping them). Safer default is skip.

**Never:**
- Do NOT keep `'cache-collision'` as a union member after this change. All paths get specific reasons; a legacy catch-all invites drift back to the ambiguous state.
- Do NOT attempt to self-heal the hostile-directory state by deleting it. Skip and leave the operator to investigate.
- Do NOT break the public import surface (`MIN_CACHED_INSTALLER_BYTES`, `parseVersionFromFileName`, `cachePreviousInstaller`, `getCachedInstaller`, `restoreCachedInstaller`).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected reason |
|----------|--------------|-----------------|
| Source path ENOENT | dangling symlink / absent file | `source-missing` |
| Source path EACCES on parent dir | permission-denied traversal | `source-stat-failed` |
| Source path not `.AppImage` | basename check fails | `source-not-appimage` |
| userData realpath EACCES | userData exists but unreadable | `userdata-unreadable` |
| Cache dir realpath non-ENOENT error | e.g. ELOOP on existing symlink | `userdata-unreadable` |
| Cache dir escapes userData via symlink | allow-list fails | `cache-symlink-outside-userdata` |
| Post-mkdir allow-list fails (concurrent swap) | TOCTOU race after initial gate passed | `cache-toctou-detected` |
| Post-mkdir realpath throws | rare race on both paths | `cache-toctou-detected` |
| Sweep encounters a directory matching our pattern | `previous-installer/TranscriptionSuite-1.0.0.AppImage/` as a dir | Skip silently; successful write still returns `{ok:true}` |
| All existing happy paths | healthy first-run, sibling-symlink collision, size guard, symlink parity | No regression — same observable behavior minus the new classifications |

</frozen-after-approval>

## Code Map

- `dashboard/electron/installerCache.ts` — `CacheResult.reason` union (line 28-34); source realpath/stat error paths (lines 97-116); allow-list branches (lines 130-155); post-mkdir re-check (lines 168-180); sweep loop (lines 238-248).
- `dashboard/electron/__tests__/installerCache.test.ts` — existing tests asserting `reason === 'source-missing'` (line 109) and `reason === 'cache-collision'` (`symlink-collision defense`, `userData allow-list defense` describes) need reason-string updates; add new describes for the split classifications.
- `dashboard/electron/main.ts` (informational; no changes) — `cacheHook` at 523-537 logs `result.reason` via `console.warn`; the new, narrower strings just show up in logs directly.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/installerCache.ts` — expand `CacheResult.reason` union: add `'source-stat-failed'`, `'source-not-appimage'`, `'userdata-unreadable'`, `'cache-symlink-outside-userdata'`, `'cache-toctou-detected'`. Remove `'cache-collision'`.
- [x] `dashboard/electron/installerCache.ts` — add a `const APPIMAGE_SOURCE_RE = /\.AppImage$/` basename check. Place it AFTER the `platform !== 'linux'` return, BEFORE `fsp.realpath(args.sourcePath)`. Returns `{ok:false, reason:'source-not-appimage'}` when `path.basename(args.sourcePath)` fails the regex.
- [x] `dashboard/electron/installerCache.ts` — replace the two `catch { return source-missing }` blocks (realpath and stat) with code-discriminating catches: ENOENT → `'source-missing'`; any other errno → `'source-stat-failed'` (include err.message in the result for operator diagnostics). Use `(err as NodeJS.ErrnoException).code === 'ENOENT'` for the discriminator.
- [x] `dashboard/electron/installerCache.ts` — reclassify the three `cache-collision` sites: (1) `fsp.realpath(args.userDataDir)` non-ENOENT failure → `'userdata-unreadable'`; (2) `fsp.realpath(dir)` non-ENOENT failure → `'userdata-unreadable'`; (3) allow-list `!allowed` → `'cache-symlink-outside-userdata'`. For the post-mkdir block: both realpath failure AND `!stillAllowed` → `'cache-toctou-detected'`.
- [x] `dashboard/electron/installerCache.ts` — in the sweep loop, `fsp.lstat(full)` each entry before unlink. If `stat.isDirectory()`, `continue` (log nothing — a warn per directory would spam logs on repeat installs). `lstat` failure: swallow (the entry may have been removed by a concurrent call). Keep the existing `full === destPath` skip.
- [x] `dashboard/electron/__tests__/installerCache.test.ts` — update the two `symlink-collision defense` tests and the two `userData allow-list defense` tests to assert the new reasons (`cache-symlink-outside-userdata` for allow-list failures; `userdata-unreadable` for EACCES on userData realpath). Add new cases: (a) source is a plain text file (not `.AppImage`) → `'source-not-appimage'`; (b) realpath source throws EACCES (mock) → `'source-stat-failed'`; (c) pre-plant a directory `previous-installer/TranscriptionSuite-1.0.0.AppImage/` with a file inside → next `cachePreviousInstaller` still returns `{ok:true}` AND the hostile directory + its contents survive intact; (d) post-mkdir concurrent swap surrogate: mock `fsp.realpath(args.userDataDir)` to succeed once then fail the second time → `'cache-toctou-detected'`.

**Acceptance Criteria:**
- Given a sourcePath whose basename is `foo.txt`, when `cachePreviousInstaller` runs, then result is `{ok:false, reason:'source-not-appimage'}` with no FS access attempted.
- Given `fsp.realpath(args.sourcePath)` rejects with an EACCES error, when `cachePreviousInstaller` runs, then result is `{ok:false, reason:'source-stat-failed', message:<err.message>}`.
- Given a cache dir symlink that escapes userData, when `cachePreviousInstaller` runs, then result is `{ok:false, reason:'cache-symlink-outside-userdata'}` (previously `'cache-collision'`).
- Given userData itself is unreadable (mocked EACCES on its realpath), when `cachePreviousInstaller` runs, then result is `{ok:false, reason:'userdata-unreadable'}`.
- Given a pre-planted directory named `TranscriptionSuite-1.0.0.AppImage/` under `previous-installer/` containing an unrelated file, when a fresh `cachePreviousInstaller` write succeeds, then `result.ok === true`, the hostile directory still exists on disk, AND its inner file is untouched.
- Given all existing tests in `installerCache.test.ts`, when they run after the change, then they pass (after reason-string updates) — no observable-behavior regression beyond the reason-string rename.

## Design Notes

The basename check is the minimal future-caller defense. A fuller `installRoot` allow-list was deferred as "optional" in the originating deferred note — plumbing it would add a `CacheArgs.installRoot?: string` field + updater at the sole caller; unjustified for zero current consumers. Callers passing `process.env.APPIMAGE` always satisfy the `.AppImage` basename.

Skipping directories in the sweep rather than recursively deleting them is a deliberate asymmetry: the cache is advisory (rollback slot, not critical state), so hostile-FS state is handled by NOT making things worse. An operator can inspect and clean manually; the read-side `getCachedInstaller` already filters directories via its `size < MIN_CACHED_INSTALLER_BYTES` check.

`cache-toctou-detected` vs `userdata-unreadable` is the PRE-vs-POST-mkdir distinction: before mkdir, an unreadable userData is a static misconfiguration (permissions / FS state); after mkdir, any re-check failure is specifically a race signal (concurrent process manipulating the cache dir while we were in it). Logs with `'cache-toctou-detected'` should prompt operators to look for adversarial concurrent processes; `'userdata-unreadable'` should prompt checking FS permissions and the userData mount.

## Verification

**Commands:**
- `cd dashboard && npx vitest run electron/__tests__/installerCache.test.ts` — expected: updated + new tests green.
- `cd dashboard && npm run typecheck` — expected: no type errors after the union expansion.

## Suggested Review Order

**Source-side classification (basename gate + errno discriminator)**

- Entry point: the new `CacheResult.reason` union — read this first to grasp the new vocabulary.
  [`installerCache.ts:18`](../../dashboard/electron/installerCache.ts#L18)

- `classifySourceError` shared helper — type-safe errno extraction added in-review (HIGH from edge hunter), routes non-Error throws into `source-stat-failed` instead of silently passing through.
  [`installerCache.ts:98`](../../dashboard/electron/installerCache.ts#L98)

- Basename gate, with in-review trailing-separator defense for directory paths.
  [`installerCache.ts:122`](../../dashboard/electron/installerCache.ts#L122)

**Allow-list re-classification (pre-mkdir vs post-mkdir distinction)**

- Pre-mkdir realpath catches → `userdata-unreadable` (static perm/FS issue).
  [`installerCache.ts:170`](../../dashboard/electron/installerCache.ts#L170)

- Allow-list `!allowed` → `cache-symlink-outside-userdata` (hostile symlink present).
  [`installerCache.ts:187`](../../dashboard/electron/installerCache.ts#L187)

- Post-mkdir block, both branches → `cache-toctou-detected` (race signal); see comment for the static-vs-race rationale.
  [`installerCache.ts:209`](../../dashboard/electron/installerCache.ts#L209)

**Sweep loop (lstat + skip directories)**

- `lstat`-then-skip-if-directory; deliberate "skip vs recursive-delete" choice documented inline.
  [`installerCache.ts:303`](../../dashboard/electron/installerCache.ts#L303)

**Tests**

- `error classification` describe — five cases covering each new reason.
  [`installerCache.test.ts:732`](../../dashboard/electron/__tests__/installerCache.test.ts#L732)

- TOCTOU userData-realpath test, with in-review `realMkdir`-bind cleanup + `message` assertion.
  [`installerCache.test.ts:821`](../../dashboard/electron/__tests__/installerCache.test.ts#L821)

- TOCTOU cache-dir-realpath test — added in-review to cover the second post-mkdir branch.
  [`installerCache.test.ts:867`](../../dashboard/electron/__tests__/installerCache.test.ts#L867)

- `source-stat-failed` via `fsp.stat` rejection — added in-review for parity with the realpath-branch test.
  [`installerCache.test.ts:912`](../../dashboard/electron/__tests__/installerCache.test.ts#L912)

- Hostile `.tmp`-suffixed directory test — added in-review for parity with the plain-directory test.
  [`installerCache.test.ts:937`](../../dashboard/electron/__tests__/installerCache.test.ts#L937)
