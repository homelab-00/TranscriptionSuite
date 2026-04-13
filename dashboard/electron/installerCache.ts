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
    | 'source-missing'
    | 'source-too-small'
    | 'write-error'
    | 'cache-collision';
  message?: string;
}

export const MIN_CACHED_INSTALLER_BYTES = 1_000_000;

export interface CachedInstaller {
  path: string;
  version: string;
}

const CACHE_DIR_NAME = 'previous-installer';
const APPIMAGE_SUFFIX = '.AppImage';

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

export async function cachePreviousInstaller(args: CacheArgs): Promise<CacheResult> {
  const platform = args.platform ?? process.platform;
  if (platform !== 'linux') {
    return { ok: false, reason: 'platform-not-supported' };
  }

  try {
    await fsp.access(args.sourcePath);
  } catch {
    return { ok: false, reason: 'source-missing' };
  }

  // Pre-copy size guard: validate the source AppImage is at least
  // MIN_CACHED_INSTALLER_BYTES BEFORE copying. Without this, a truncated
  // download writes through; the read-side `getCachedInstaller` filter then
  // hides the real fault (bad source) as "no cache available." Pre-copy
  // surfaces the failure mode in main-process logs as `'source-too-small'`.
  try {
    const sourceStat = await fsp.stat(args.sourcePath);
    if (sourceStat.size < MIN_CACHED_INSTALLER_BYTES) {
      return { ok: false, reason: 'source-too-small' };
    }
  } catch {
    return { ok: false, reason: 'source-missing' };
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
  // Fail-CLOSED on any other realpath error (EACCES/ELOOP/etc.).
  let userDataReal: string | null = null;
  try {
    userDataReal = await fsp.realpath(args.userDataDir);
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    if (code !== 'ENOENT') {
      return { ok: false, reason: 'cache-collision' };
    }
  }
  if (userDataReal !== null) {
    let dirReal: string | null = null;
    try {
      dirReal = await fsp.realpath(dir);
    } catch (err) {
      const code = (err as NodeJS.ErrnoException).code;
      if (code !== 'ENOENT') {
        return { ok: false, reason: 'cache-collision' };
      }
    }
    if (dirReal !== null) {
      const allowed = dirReal === userDataReal || dirReal.startsWith(userDataReal + path.sep);
      if (!allowed) {
        return { ok: false, reason: 'cache-collision' };
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
    // descendant invariant unconditionally. Fail-CLOSED on any realpath
    // error here — a real cache write must have a resolvable path pair.
    let userDataRealNow: string;
    let dirRealNow: string;
    try {
      userDataRealNow = await fsp.realpath(args.userDataDir);
      dirRealNow = await fsp.realpath(dir);
    } catch {
      return { ok: false, reason: 'cache-collision' };
    }
    const stillAllowed =
      dirRealNow === userDataRealNow || dirRealNow.startsWith(userDataRealNow + path.sep);
    if (!stillAllowed) {
      return { ok: false, reason: 'cache-collision' };
    }

    // Delete any prior cache entries (we keep exactly one). Filter by the
    // same `parseVersionFromFileName` gate the read side uses — only our own
    // `TranscriptionSuite-<version>.AppImage` files are eligible. This is
    // defense-in-depth for the equality branch of the allow-list above: if a
    // hostile symlink loop makes `dir` resolve to the userData root itself,
    // the loop only touches our own files and unrelated userData contents
    // survive intact.
    let entries: string[] = [];
    try {
      entries = await fsp.readdir(dir);
    } catch {
      entries = [];
    }
    for (const name of entries) {
      if (parseVersionFromFileName(name) === null) continue;
      try {
        await fsp.unlink(path.join(dir, name));
      } catch {
        // Ignore individual unlink failures; the next copyFile will either
        // succeed on its new filename or surface a real write error below.
      }
    }

    const destPath = path.join(dir, cacheFileName(args.version));
    await fsp.copyFile(args.sourcePath, destPath);
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
