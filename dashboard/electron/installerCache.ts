/**
 * installerCache — manage a single cached copy of the previously-running
 * Dashboard binary so M6's launch watchdog can offer a rollback after
 * repeated launch failures of a new version.
 *
 * Scope: Linux AppImage only. Caching on Windows (NSIS) and macOS (DMG/ZIP)
 * is deferred to M7 — those platforms handle replacement differently and a
 * naive "copy the running bundle" approach does not produce a re-runnable
 * installer.
 *
 * Disk policy: keep exactly one cache file; delete any prior entries before
 * writing a new one. Per D6 (~150 MB budget per entry).
 */

import { promises as fsp } from 'fs';
import path from 'path';

export interface CacheArgs {
  sourcePath: string;
  version: string;
  userDataDir: string;
  platform?: NodeJS.Platform;
}

export interface CacheResult {
  ok: boolean;
  cachedPath?: string;
  reason?:
    | 'platform-not-supported'
    | 'source-missing' // ENOENT on realpath/stat — file absent / dangling symlink.
    | 'source-stat-failed' // non-ENOENT errno (EACCES/EPERM/EIO/ELOOP) on realpath/stat — exists but unreadable.
    | 'source-not-appimage' // basename doesn't end in `.AppImage` — future-caller hazard gate.
    | 'source-too-small'
    | 'write-error'
    | 'userdata-unreadable' // realpath of userData or cache dir failed with non-ENOENT — static perm/FS issue.
    | 'cache-symlink-outside-userdata' // allow-list failed: cache dir's realpath escapes userData.
    | 'cache-toctou-detected'; // post-mkdir invariant re-check failed — concurrent process manipulating dir.
  message?: string;
}

export const MIN_CACHED_INSTALLER_BYTES = 1_000_000;

export interface CachedInstaller {
  path: string;
  version: string;
}

const CACHE_DIR_NAME = 'previous-installer';
const APPIMAGE_SUFFIX = '.AppImage';
// Minimal future-caller defense: the sole current caller (main.ts) passes
// `process.env.APPIMAGE`, but cachePreviousInstaller is a general function
// and a future caller could hand us an arbitrary readable file (e.g.
// /etc/shadow). Reject anything whose basename doesn't end in .AppImage
// BEFORE we touch the filesystem.
const APPIMAGE_SOURCE_RE = /\.AppImage$/;

function cacheDir(userDataDir: string): string {
  return path.join(userDataDir, CACHE_DIR_NAME);
}

function cacheFileName(version: string): string {
  // Escape characters that have meaning on common filesystems. Electron's
  // `app.getVersion()` is semver-like, but a pre-release tag may carry `+`
  // or `/`. Keep alphanumerics, dots, dashes, underscores; replace anything
  // else with a single dash.
  const safe = version.replace(/[^A-Za-z0-9._-]/g, '-');
  return `TranscriptionSuite-${safe}${APPIMAGE_SUFFIX}`;
}

// Allow only characters that legitimate semver-ish version strings use. Rejects
// path-traversal attempts like `TranscriptionSuite-../../evil.AppImage` whose
// inner would otherwise parse as `../../evil` and surface in the rollback dialog.
const SAFE_VERSION_RE = /^[A-Za-z0-9._-]+$/;

// Pure-dot inners like `..` / `.` / `...` pass SAFE_VERSION_RE but are
// nonsensical as "version" strings. On disk they can't be `../..` traversal
// (no slash), but the bare dots would surface in the rollback dialog and
// store payload. Reject them explicitly.
const DOT_ONLY_RE = /^\.+$/;

export function parseVersionFromFileName(name: string): string | null {
  if (!name.startsWith('TranscriptionSuite-') || !name.endsWith(APPIMAGE_SUFFIX)) {
    return null;
  }
  const inner = name.slice('TranscriptionSuite-'.length, -APPIMAGE_SUFFIX.length);
  if (inner.length === 0 || !SAFE_VERSION_RE.test(inner) || DOT_ONLY_RE.test(inner)) {
    return null;
  }
  return inner;
}

// Type-safe errno extraction. Native modules and programmer errors
// (e.g. TypeError from invalid args) throw plain Error / non-Error
// objects without a `.code` field; treating those as "non-ENOENT errno"
// would silently mislabel them as `source-stat-failed`. Route anything
// without a recognizable string `.code` into a distinct branch the
// caller surfaces verbatim.
function classifySourceError(err: unknown): CacheResult {
  if (!(err instanceof Error)) {
    return { ok: false, reason: 'source-stat-failed', message: String(err) };
  }
  const code = (err as NodeJS.ErrnoException).code;
  if (code === 'ENOENT') return { ok: false, reason: 'source-missing' };
  return { ok: false, reason: 'source-stat-failed', message: err.message };
}

export async function cachePreviousInstaller(args: CacheArgs): Promise<CacheResult> {
  const platform = args.platform ?? process.platform;
  if (platform !== 'linux') {
    return { ok: false, reason: 'platform-not-supported' };
  }

  // Basename allow-list: a future caller could pass an arbitrary readable
  // file (e.g. /etc/shadow) and the cache machinery would happily write
  // it into the rollback slot. Reject anything whose basename doesn't end
  // in `.AppImage` BEFORE touching the filesystem.
  //
  // Trailing-separator defense: `path.basename('foo.AppImage/')` returns
  // `'foo.AppImage'` on POSIX, which would falsely pass the suffix check
  // when the caller handed us a directory path. Reject paths ending with
  // a separator before the basename check.
  if (
    args.sourcePath.endsWith(path.sep) ||
    !APPIMAGE_SOURCE_RE.test(path.basename(args.sourcePath))
  ) {
    return { ok: false, reason: 'source-not-appimage' };
  }

  // Resolve the source's realpath ONCE, then route both stat and copyFile
  // through the same resolved path. Closes the TOCTOU window where a
  // symlink `sourcePath` is retargeted between the pre-copy size check
  // and the later copyFile — without this, a retarget could land an
  // unrelated file in the cache despite the size guard succeeding.
  //
  // ENOENT (source missing / dangling symlink) → `source-missing`; any
  // other errno (EACCES / EPERM / EIO / ELOOP) → `source-stat-failed` so
  // an operator in logs can distinguish "file doesn't exist" from "file
  // exists but can't be read". The err.message rides along for diag.
  let sourceReal: string;
  try {
    sourceReal = await fsp.realpath(args.sourcePath);
  } catch (err) {
    return classifySourceError(err);
  }

  // Pre-copy size guard: validate the source AppImage is at least
  // MIN_CACHED_INSTALLER_BYTES BEFORE copying. Without this, a truncated
  // download writes through; the read-side `getCachedInstaller` filter then
  // hides the real fault (bad source) as "no cache available." Pre-copy
  // surfaces the failure mode in main-process logs as `'source-too-small'`.
  //
  // Same ENOENT-vs-other classification as the realpath catch above.
  try {
    const sourceStat = await fsp.stat(sourceReal);
    if (sourceStat.size < MIN_CACHED_INSTALLER_BYTES) {
      return { ok: false, reason: 'source-too-small' };
    }
  } catch (err) {
    return classifySourceError(err);
  }

  const dir = cacheDir(args.userDataDir);

  // Symlink-collision defense: cache dir's realpath MUST descend from
  // userData's realpath (or equal it). Closes both the exact-parent
  // collision (`previous-installer/` → AppImage parent) and the broader
  // sibling-symlink hole (`previous-installer/` → any directory outside
  // userData where the unlink loop would wipe arbitrary files).
  //
  // Legitimate first-run: if either userData or the cache dir doesn't exist
  // yet (ENOENT), no symlink can possibly resolve under either path, so the
  // allow-list check is vacuously satisfied — fall through to mkdir.
  //
  // Error classification:
  //   `userdata-unreadable`           — non-ENOENT errno on realpath of
  //     userDataDir or cache dir (static perm/FS issue; operator should
  //     check mounts + permissions).
  //   `cache-symlink-outside-userdata` — allow-list failed: cache dir
  //     resolves to somewhere outside userData (hostile symlink present).
  let userDataReal: string | null = null;
  try {
    userDataReal = await fsp.realpath(args.userDataDir);
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    if (code !== 'ENOENT') {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, reason: 'userdata-unreadable', message };
    }
  }
  if (userDataReal !== null) {
    let dirReal: string | null = null;
    try {
      dirReal = await fsp.realpath(dir);
    } catch (err) {
      const code = (err as NodeJS.ErrnoException).code;
      if (code !== 'ENOENT') {
        const message = err instanceof Error ? err.message : String(err);
        return { ok: false, reason: 'userdata-unreadable', message };
      }
    }
    if (dirReal !== null) {
      const allowed = dirReal === userDataReal || dirReal.startsWith(userDataReal + path.sep);
      if (!allowed) {
        return { ok: false, reason: 'cache-symlink-outside-userdata' };
      }
    }
  }

  try {
    await fsp.mkdir(dir, { recursive: true });

    // Post-mkdir invariant re-check (canonical TOCTOU defense + first-run
    // closure). Covers (a) a concurrent process swapping `dir` for a symlink
    // between the initial allow-list check and the unlink loop below, and
    // (b) the first-run case where `userData` was ENOENT initially — mkdir
    // recursive may have just materialized it (or a dangling symlink may
    // have been followed). Re-realpath BOTH paths and re-verify the
    // descendant invariant unconditionally.
    //
    // Both failure modes here (realpath throws OR !stillAllowed) are
    // classified as `cache-toctou-detected` — the pre-mkdir gate already
    // passed, so any failure at THIS point is specifically a race signal:
    // something (concurrent process / adversarial symlink swap / mkdir
    // recursive following a dangling symlink) moved the target between
    // the two checks. That's a different story to operators than the
    // static `userdata-unreadable` classification used above.
    let userDataRealNow: string;
    let dirRealNow: string;
    try {
      userDataRealNow = await fsp.realpath(args.userDataDir);
      dirRealNow = await fsp.realpath(dir);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, reason: 'cache-toctou-detected', message };
    }
    const stillAllowed =
      dirRealNow === userDataRealNow || dirRealNow.startsWith(userDataRealNow + path.sep);
    if (!stillAllowed) {
      return { ok: false, reason: 'cache-toctou-detected' };
    }

    // Atomic write: copy source into `<destPath>.tmp`, then POSIX-rename
    // it to destPath. Because tmp shares `dir` (same filesystem by
    // construction, both under userDataDir), the rename is atomic. On
    // any failure before the rename the prior cache entry is untouched —
    // we haven't run the unlink loop yet, so a mid-write failure degrades
    // to "prior cache still usable" rather than "no cache at all".
    //
    // The `.tmp` suffix is invisible to `parseVersionFromFileName` (it
    // bails at the `.AppImage` suffix check), so `getCachedInstaller`
    // will never surface an orphan tmp as a rollback candidate. The
    // unlink-priors loop below DOES sweep orphan `.tmp` files from
    // prior crashed writes — see `isSweepable` comment below.
    const destPath = path.join(dir, cacheFileName(args.version));
    const tmpPath = destPath + '.tmp';
    try {
      await fsp.copyFile(sourceReal, tmpPath);
      await fsp.rename(tmpPath, destPath);
    } catch (err) {
      // Best-effort cleanup of our OWN in-flight tmp. If copyFile failed
      // before writing anything the unlink hits ENOENT — swallow. Any
      // surviving tmp residue is swept by the next successful write's
      // sweep loop below.
      await fsp.unlink(tmpPath).catch(() => {});
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, reason: 'write-error', message };
    }

    // Delete any prior cache entries AFTER the rename succeeds (we keep
    // exactly one). Sweep:
    //  (a) completed `TranscriptionSuite-<version>.AppImage` files from
    //      previous cache generations — the single-slot invariant;
    //  (b) orphan `.tmp` files from timed-out / crashed prior writes —
    //      without this the timeout path in UpdateInstaller.install()
    //      would leak ~150 MB per hang since parseVersionFromFileName
    //      alone rejects the `.tmp` suffix.
    // The `full === destPath` skip prevents us from self-unlinking the
    // file we just successfully renamed into place.
    //
    // Defense-in-depth: this loop runs under the symlink-collision allow
    // list above, so even if `dir` resolves to an unexpected descendant
    // of userData, only our own filename patterns (version-parseable
    // name, with or without trailing `.tmp`) are eligible.
    let entries: string[] = [];
    try {
      entries = await fsp.readdir(dir);
    } catch {
      entries = [];
    }
    const isSweepable = (name: string): boolean => {
      if (parseVersionFromFileName(name) !== null) return true;
      if (name.endsWith('.tmp')) {
        const inner = name.slice(0, -'.tmp'.length);
        return parseVersionFromFileName(inner) !== null;
      }
      return false;
    };
    for (const name of entries) {
      if (!isSweepable(name)) continue;
      const full = path.join(dir, name);
      if (full === destPath) continue;
      // lstat first — if a hostile/buggy operator has pre-planted a
      // directory matching our filename pattern (e.g.
      // `TranscriptionSuite-1.0.0.AppImage/`), `unlink` fails with
      // EISDIR and leaves the dir in place, silently. We deliberately
      // do NOT `fsp.rm({recursive:true})` here — the cache is a
      // rollback slot, not user data we can aggressively recover from
      // adversarial state. Better to skip and let the operator
      // investigate than to wipe unrelated content inside the same-
      // named directory. lstat failure is also swallowed (the entry
      // may have been removed by a concurrent call).
      let entryStat: import('fs').Stats | null = null;
      try {
        entryStat = await fsp.lstat(full);
      } catch {
        continue;
      }
      if (entryStat.isDirectory()) continue;
      try {
        await fsp.unlink(full);
      } catch {
        // Ignore individual unlink failures; worst case is a stale prior
        // entry that the NEXT successful write will sweep.
      }
    }

    return { ok: true, cachedPath: destPath };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, reason: 'write-error', message };
  }
}

export async function getCachedInstaller(userDataDir: string): Promise<CachedInstaller | null> {
  const dir = cacheDir(userDataDir);
  let entries: string[];
  try {
    entries = await fsp.readdir(dir);
  } catch {
    return null;
  }

  for (const name of entries) {
    const version = parseVersionFromFileName(name);
    if (!version) continue;
    const full = path.join(dir, name);
    try {
      await fsp.access(full);
    } catch {
      continue;
    }
    // Size filter: 0-byte / truncated files would hand the user a corrupt
    // AppImage that doesn't execute. Minimum 1 MB is well below any healthy
    // Electron bundle (~60 MB+) and well above common truncation artifacts.
    try {
      const st = await fsp.stat(full);
      if (st.size < MIN_CACHED_INSTALLER_BYTES) continue;
    } catch {
      continue;
    }
    return { path: full, version };
  }
  return null;
}

export interface RestoreArgs {
  cachedPath: string;
  targetPath: string;
  platform?: NodeJS.Platform;
}

export interface RestoreResult {
  ok: boolean;
  reason?: 'platform-not-supported' | 'cache-missing' | 'write-error';
  message?: string;
}

/**
 * Copy a cached installer back to the target path. Linux AppImage caveat:
 * this cannot overwrite a running AppImage. Callers are expected to quit
 * the app first or call this helper from an external helper process.
 */
export async function restoreCachedInstaller(args: RestoreArgs): Promise<RestoreResult> {
  const platform = args.platform ?? process.platform;
  if (platform !== 'linux') {
    return { ok: false, reason: 'platform-not-supported' };
  }

  try {
    await fsp.access(args.cachedPath);
  } catch {
    return { ok: false, reason: 'cache-missing' };
  }

  try {
    await fsp.copyFile(args.cachedPath, args.targetPath);
    return { ok: true };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, reason: 'write-error', message };
  }
}
