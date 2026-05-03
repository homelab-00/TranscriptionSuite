---
title: 'Deferred functional-bug fixes surfaced by M1-M7 review'
type: 'bugfix'
created: '2026-04-13'
status: 'done'
baseline_commit: '0c933f45c9c59a7012678b835f1ad7ea24dd4120'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/deferred-work.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-m6-safety-errors.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-m7-platforms.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Five functional defects from the M1-M7 review backlog are still open. All are real code-path hazards, not polish:
1. `UpdateBanner.deriveBannerState` has no `case 'verifying':` → switch falls through to `availableFromPoll`, re-enabling `[Download]` mid-verify. A fast double-click re-enters `UpdateInstaller.startDownload()` (which only guards `'downloading'`).
2. Snooze is persisted as an absolute epoch with no clock sanity — NTP correction, VM suspend, or clock-forward can stretch the 4 h snooze to days.
3. `installerCache.parseVersionFromFileName` accepts any characters → `TranscriptionSuite-../../evil.AppImage` parses version as `../../evil`, surfacing in the rollback dialog + store.
4. `installerCache` has no symlink defense → a `previous-installer/` symlinked to the AppImage's parent dir lets the unlink loop delete the running binary.
5. `getCachedInstaller` accepts 0-byte / truncated files → rollback can hand the user a corrupt AppImage that won't execute.

**Approach:** Add a `case 'verifying':` mapping to the `downloading` visual (same button surface, spinner). Clamp persisted snooze to `min(stored, Date.now() + SNOOZE_MS)` at load AND write. Restrict `parseVersionFromFileName`'s inner to `/^[A-Za-z0-9._-]+$/`. Before any `installerCache` disk mutation, `fsp.realpath`-compare cache dir against the source AppImage's parent dir. Filter `getCachedInstaller` by `stat.size >= 1_000_000` (1 MB).

## Boundaries & Constraints

**Always:**
- No behavior change on any existing happy path — every pre-existing test must stay green.
- `verifying` case returns `{state:'downloading', version:installer.version}`. Do NOT add a new `BannerVisualState` variant — cascades to every switch consumer.
- Snooze clamp applied in TWO places: load (mount-effect `getConfig` handler) AND write (`handleSnooze` before `setConfig`). Defense in depth against a store written before the clamp.
- `parseVersionFromFileName` rejection → `null` → `getCachedInstaller` skips with `continue` (not early-return, not throw).
- `cachePreviousInstaller` realpath check runs BEFORE `fsp.mkdir` — a hostile symlink must not even trigger dir creation. Match OR either side throws → return `{ok:false, reason:'cache-collision'}`, zero disk mutation.
- `getCachedInstaller` stat check wraps in try/catch; ENOENT / race → skip entry, continue loop.
- Minimum cached-installer size: 1 MB. Electron base bundle ~60 MB; 1 MB is two orders of magnitude below legitimate AND above common truncation artifacts (<64 KB blocks).

**Ask First:**
- Changes to `InstallerStatus` union shape (frozen by M6/M7).
- New `BannerVisualState` variant.
- Changes to the 4 h snooze constant or the rollback-dialog flow.

**Never:**
- Do NOT per-version-key the snooze (brainstorming-locked: single epoch, max 4 h staleness).
- Do NOT add installer-cache `reason` strings beyond the single new `'cache-collision'`.
- Do NOT widen the `verifying` visual with new copy ("Verifying v1.3.3…") — scope expansion into a new variant.
- Do NOT drift into other deferred-work items (a11y, IPC rejection tests, strategy-compat ordering, manual-download truncate — each a separate spec).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior |
|---|---|---|
| Verifying + updateAvailable poll | `installer.state='verifying'` | `deriveBannerState` → `{state:'downloading', version}`; no `[Download]` in DOM |
| Double-click Download mid-verify | click, click | neither reaches `startDownload()` (no button to click) |
| Snooze bogus future | persisted `now + 30d` | clamped to `now + SNOOZE_MS` on load |
| Snooze legitimate | persisted `now + 3h` | unchanged |
| Filename traversal | `TranscriptionSuite-../../evil.AppImage` | `parseVersionFromFileName` returns `null` |
| Filename pre-release | `TranscriptionSuite-1.3.2-rc.1.AppImage` | returns `'1.3.2-rc.1'` |
| Cache-dir symlink collision | `previous-installer/` → AppImage parent | `cachePreviousInstaller` → `{ok:false, reason:'cache-collision'}`, no disk mutation |
| realpath throws | EACCES / ELOOP | treat as collision — abort |
| 0-byte cache entry | truncated file | `getCachedInstaller` skips via stat filter |
| Stat throws | ENOENT race | skip entry, continue |

</frozen-after-approval>

## Code Map

- `dashboard/components/ui/UpdateBanner.tsx` — add `verifying` switch case; wrap snooze load + write with clamp helper.
- `dashboard/electron/installerCache.ts` — regex-guard `parseVersionFromFileName`; realpath check at top of `cachePreviousInstaller`; stat-size filter in `getCachedInstaller`; widen `CacheResult.reason` with `'cache-collision'`.
- `dashboard/components/ui/__tests__/UpdateBanner.test.tsx` — cases for verifying mapping + bogus-future snooze clamp.
- `dashboard/electron/__tests__/installerCache.test.ts` — cases for traversal rejection, symlink collision, 0-byte skip, healthy small file passthrough.

## Tasks & Acceptance

**Execution:**
- [x] `UpdateBanner.tsx` — added `case 'verifying':` returning `{state:'downloading', version:installer.version}`. Extracted exported `clampSnooze(stored, now)` helper with `<= 0` fast-path. Applied in mount-effect `getConfig` handler AND in `handleSnooze` before `setConfig`.
- [x] `installerCache.ts` — added `SAFE_VERSION_RE` charset guard in `parseVersionFromFileName` (also exported the function for direct unit testing). Widened `CacheResult.reason` with `'cache-collision'`. Added realpath check at top of `cachePreviousInstaller`, BEFORE `mkdir`: compares `realpath(dir)` vs `realpath(dirname(sourcePath))` with ENOENT-tolerant inner try/catch on the dir side (legitimate first-run case). Added `MIN_CACHED_INSTALLER_BYTES = 1_000_000` filter via `fsp.stat` in `getCachedInstaller`.
- [x] `UpdateBanner.test.tsx` — added `deriveBannerState` `verifying`-case test in pure-function block. Added "Deferred bug fixes" describe block: render-side `verifying` no-`[Download]` assertion; `clampSnooze` direct unit test (bogus 30d → `now + SNOOZE_MS`, legitimate 3h pass-through, 0 fast-path); end-to-end load-time clamp via configStore + deriveBannerState future-time verification (avoids fake-timer fragility); write-side clamp assertion on `setConfig` payload.
- [x] `installerCache.test.ts` — added charset-guard describe block (traversal, shell-meta, whitespace, legitimate prereleases). Added symlink-collision describe (collide → `{ok:false, reason:'cache-collision'}`, no source mutation; non-symlinked → success). Added size-filter describe (0-byte skip, 999_999-byte skip, 1MB pass, sibling-after-skip pass). Updated 2 pre-existing tests to use `HEALTHY_BYTES` (1MB) for size-filter compatibility.

**Acceptance Criteria:**
- Given `installer.state='verifying'`, when `deriveBannerState` runs, then it returns `{state:'downloading', version:installer.version}` regardless of `updateStatus`, and the rendered DOM contains no `[Download]` button.
- Given persisted `updates.bannerSnoozedUntil > Date.now() + SNOOZE_MS`, when `UpdateBanner` mounts, then the effective `snoozedUntil` ≤ `Date.now() + SNOOZE_MS`.
- Given a cache entry named `TranscriptionSuite-../../evil.AppImage`, when `getCachedInstaller` runs, then it returns `null` (skips the poisoned entry).
- Given `previous-installer/` is symlinked to `path.dirname(process.env.APPIMAGE)`, when `cachePreviousInstaller` runs, then it returns `{ok:false, reason:'cache-collision'}` AND no filesystem mutation occurs.
- Given a 0-byte file in `previous-installer/`, when `getCachedInstaller` runs, then it returns `null`.
- `cd dashboard && npm run typecheck && npm run test -- UpdateBanner installerCache && npm run build:electron` — all green.

## Design Notes

**Why `verifying` → `downloading` visual (not a new variant):** From the user's POV, hashing a 200 MB AppImage is still "wait, not click" — seconds of in-flight work. A dedicated `verifying` label would mean new `BannerVisualState` enum + new copy + a new switch-consumer surface, all cascading well beyond this spec. If product wants distinct copy later, it's a tight follow-up patch on an already-exhaustive switch.

**Why realpath-compare the parent dir (not the source path itself):** The hazard is "cache dir resolves to something that ALSO contains the running binary." Comparing against `path.dirname(sourcePath)` catches the exact failure mode (unlink loop deletes running AppImage). Comparing against `sourcePath` itself would miss the case where cache dir symlinks to a SIBLING of the binary. Parent-dir is the minimal-correct check.

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` — zero errors.
- `cd dashboard && npm run test -- UpdateBanner installerCache` — all pass.
- `cd dashboard && npm run build:electron` — compiles.

## Suggested Review Order

**Functional bug — exhaustive switch case**

- The original ship-bug: missing `case 'verifying':` let a fast double-click re-enter `startDownload()` mid-verify.
  [`UpdateBanner.tsx:130`](../../dashboard/components/ui/UpdateBanner.tsx#L130)

**Snooze clock-skew defense**

- Pure clamp helper with `Number.isFinite` guard (post-review patch — NaN would otherwise silently un-snooze).
  [`UpdateBanner.tsx:54`](../../dashboard/components/ui/UpdateBanner.tsx#L54)

- Load-time clamp at the mount-effect handler — the primary defense against a stored bogus epoch.
  [`UpdateBanner.tsx:227`](../../dashboard/components/ui/UpdateBanner.tsx#L227)

- Write-time clamp in `handleSnooze` — defense in depth (currently inert by construction; documented in deferred-work).
  [`UpdateBanner.tsx:280`](../../dashboard/components/ui/UpdateBanner.tsx#L280)

**Filename charset hardening**

- `SAFE_VERSION_RE` rejects shell-meta / whitespace / traversal-shape strings.
  [`installerCache.ts:60`](../../dashboard/electron/installerCache.ts#L60)

- `DOT_ONLY_RE` post-review patch rejects `.`/`..`/`...` that would otherwise pass the broader regex.
  [`installerCache.ts:64`](../../dashboard/electron/installerCache.ts#L64)

- Combined gate in `parseVersionFromFileName` (exported for direct unit testing).
  [`installerCache.ts:66`](../../dashboard/electron/installerCache.ts#L66)

**Symlink-collision defense (cache write-side)**

- Realpath comparison runs BEFORE `mkdir` so a hostile symlink can't even trigger dir creation; ENOENT-tolerant inner try/catch preserves first-run.
  [`installerCache.ts:91`](../../dashboard/electron/installerCache.ts#L91)

- New `cache-collision` reason added to `CacheResult.reason` union — single-string widening.
  [`installerCache.ts:28`](../../dashboard/electron/installerCache.ts#L28)

**Size filter (cache read-side)**

- Streaming `fsp.stat` filter via shared `MIN_CACHED_INSTALLER_BYTES` constant; skip-on-throw via `continue`.
  [`installerCache.ts:166`](../../dashboard/electron/installerCache.ts#L166)

**Tests — parity check**

- `verifying`-state pure-mapper test + render-side no-`[Download]` assertion.
  [`UpdateBanner.test.tsx:270`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L270)

- `clampSnooze` direct unit tests including post-review NaN/Infinity rejection.
  [`UpdateBanner.test.tsx:917`](../../dashboard/components/ui/__tests__/UpdateBanner.test.tsx#L917)

- `parseVersionFromFileName` charset matrix including post-review pure-dot rejection.
  [`installerCache.test.ts:263`](../../dashboard/electron/__tests__/installerCache.test.ts#L263)

- Symlink-collision integration test asserts `{ok:false, reason:'cache-collision'}` AND zero source mutation.
  [`installerCache.test.ts:277`](../../dashboard/electron/__tests__/installerCache.test.ts#L277)

- Size-filter coverage at 0-byte / 999_999-byte / 1MB / sibling-after-skip boundaries.
  [`installerCache.test.ts:337`](../../dashboard/electron/__tests__/installerCache.test.ts#L337)
