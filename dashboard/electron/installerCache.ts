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
  reason?: 'platform-not-supported' | 'source-missing' | 'write-error';
  message?: string;
}

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

function parseVersionFromFileName(name: string): string | null {
  if (!name.startsWith('TranscriptionSuite-') || !name.endsWith(APPIMAGE_SUFFIX)) {
    return null;
  }
  const inner = name.slice('TranscriptionSuite-'.length, -APPIMAGE_SUFFIX.length);
  return inner.length > 0 ? inner : null;
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

  const dir = cacheDir(args.userDataDir);
  try {
    await fsp.mkdir(dir, { recursive: true });

    // Delete any prior cache entries (we keep exactly one).
    let entries: string[] = [];
    try {
      entries = await fsp.readdir(dir);
    } catch {
      entries = [];
    }
    for (const name of entries) {
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
