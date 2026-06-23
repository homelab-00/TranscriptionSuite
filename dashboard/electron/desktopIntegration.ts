/**
 * XDG desktop-file self-installation for the Linux AppImage build.
 *
 * Why this exists
 * ───────────────
 * On Wayland we claim a global-shortcuts app id through the XDG host portal's
 * `org.freedesktop.host.portal.Registry.Register` (see waylandShortcuts.ts).
 * That portal resolves the supplied app id by asking GLib for
 * `<app_id>.desktop` via `g_desktop_app_info_new()`, which only searches
 * `$XDG_DATA_HOME/applications` and `$XDG_DATA_DIRS/applications`. An AppImage's
 * own desktop file lives inside its ephemeral `/tmp/.mount_*` directory, which
 * is NOT on that search path, so the lookup fails with
 * `App info not found for '<app_id>'` and the subsequent
 * `GlobalShortcuts.CreateSession` is rejected with `An app id is required`.
 *
 * Verified against xdg-desktop-portal 1.22.1 source (registry.c, xdp-app-info.c,
 * xdp-app-info-host.c): `Register` checks only that the desktop file EXISTS — it
 * never reads the file's Exec/TryExec nor the caller's `/proc/<pid>/exe`. So
 * installing a desktop file named exactly after the app id, with Exec pointing
 * at the AppImage, is sufficient for `Register` (and thus CreateSession) to pass.
 *
 * First-launch caveat: the portal daemon caches desktop-file lookups and only
 * refreshes them asynchronously (GLib GFileMonitor / inotify). On the very first
 * launch — when this file did not previously exist — `Register` can race the
 * inotify event and still fail; it then succeeds automatically on the next
 * launch (file pre-exists, cache warm). We therefore install the file as early
 * as possible (main.ts module load) and rely on registerHostAppId()'s existing
 * graceful fallback for the rare first-launch miss.
 *
 * The desktop-integration layout (target dir, `Exec="$APPIMAGE"`, `TryExec`)
 * follows the standard AppImage desktop-integration convention used by
 * appimaged / AppImageLauncher.
 */

import fs from 'fs';
import os from 'os';
import path from 'path';

import { PORTAL_APP_ID } from './waylandShortcuts.js';

// ─── Constants ────────────────────────────────────────────────────────────────

/** Basename of the desktop file we install — MUST equal `<PORTAL_APP_ID>.desktop`. */
export const DESKTOP_FILE_NAME = `${PORTAL_APP_ID}.desktop`;

/**
 * Wrong-basename desktop files shipped by older versions that we clean up so the
 * portal resolves exactly one identity. (v1.1.0 installed `transcriptionsuite.desktop`,
 * derived from the lowercased product name, before the reverse-DNS id was adopted.)
 */
const STALE_DESKTOP_BASENAMES = ['transcriptionsuite.desktop'] as const;

// ─── Injectable filesystem (keeps the module unit-testable without touching $HOME) ──

interface DesktopFs {
  existsSync(target: string): boolean;
  readFileSync(target: string, encoding: 'utf8'): string;
  writeFileSync(target: string, data: string, options: { mode: number }): void;
  mkdirSync(target: string, options: { recursive: boolean }): void;
  rmSync(target: string, options: { force: boolean }): void;
}

const realFs: DesktopFs = {
  existsSync: (p) => fs.existsSync(p),
  readFileSync: (p, enc) => fs.readFileSync(p, enc),
  writeFileSync: (p, data, opts) => fs.writeFileSync(p, data, opts),
  mkdirSync: (p, opts) => {
    fs.mkdirSync(p, opts);
  },
  rmSync: (p, opts) => fs.rmSync(p, opts),
};

// ─── Pure helpers ─────────────────────────────────────────────────────────────

/** The XDG applications directory the host portal searches first. */
export function applicationsDir(
  env: NodeJS.ProcessEnv = process.env,
  homedir: () => string = os.homedir,
): string {
  const dataHome = env.XDG_DATA_HOME?.trim() || path.join(homedir(), '.local', 'share');
  return path.join(dataHome, 'applications');
}

/** Absolute path of the desktop file to install. */
export function desktopFileTargetPath(
  env: NodeJS.ProcessEnv = process.env,
  homedir: () => string = os.homedir,
): string {
  return path.join(applicationsDir(env, homedir), DESKTOP_FILE_NAME);
}

/**
 * Quote a path for a desktop-entry `Exec` field. Per the freedesktop Desktop
 * Entry spec, arguments with reserved characters are double-quoted and the
 * characters `"`, backtick, `$` and `\` are backslash-escaped inside the quotes.
 */
export function quoteExecArg(value: string): string {
  const escaped = value.replace(/(["`$\\])/g, '\\$1');
  return `"${escaped}"`;
}

interface DesktopFileFields {
  appImagePath: string;
  version?: string;
}

/** Build the `[Desktop Entry]` text. `Exec`/`TryExec` point at the AppImage. */
export function buildDesktopFileContent({ appImagePath, version }: DesktopFileFields): string {
  const lines = [
    '[Desktop Entry]',
    'Type=Application',
    'Name=TranscriptionSuite',
    'Comment=Desktop dashboard for managing TranscriptionSuite server and transcription workflows',
    `Exec=${quoteExecArg(appImagePath)} %U`,
    // TryExec carries the raw (unquoted) path; it lets the entry self-hide if the
    // AppImage is moved or deleted.
    `TryExec=${appImagePath}`,
    `Icon=${PORTAL_APP_ID}`,
    'Terminal=false',
    'Categories=AudioVideo;Utility;',
    // Must match Electron's Wayland app_id for correct taskbar grouping.
    `StartupWMClass=${PORTAL_APP_ID}`,
    'StartupNotify=true',
  ];
  if (version) lines.push(`X-AppImage-Version=${version}`);
  lines.push(''); // trailing newline
  return lines.join('\n');
}

/**
 * Whether an already-installed desktop file targets the given AppImage path, so
 * a rewrite can be skipped. Keyed on the raw `TryExec` line (the AppImage path
 * embeds the version, so a version bump changes the path and forces a refresh).
 */
export function desktopFileMatchesAppImage(content: string, appImagePath: string): boolean {
  return content.includes(`TryExec=${appImagePath}`);
}

// ─── Install / repair ─────────────────────────────────────────────────────────

interface Logger {
  log(message: string): void;
  warn(message: string, err?: unknown): void;
}

export interface EnsureDesktopFileOptions {
  platform?: NodeJS.Platform;
  env?: NodeJS.ProcessEnv;
  homedir?: () => string;
  version?: string;
  fileSystem?: DesktopFs;
  logger?: Logger;
}

function safeRead(fileSystem: DesktopFs, target: string): string {
  try {
    return fileSystem.readFileSync(target, 'utf8');
  } catch {
    return '';
  }
}

/**
 * Remove wrong-basename desktop files from earlier versions. Only deletes a file
 * recognisably ours (its content mentions TranscriptionSuite), so we never nuke
 * an unrelated entry that happens to share the legacy basename.
 */
function removeStaleDesktopFiles(dir: string, fileSystem: DesktopFs, logger: Logger): void {
  for (const basename of STALE_DESKTOP_BASENAMES) {
    const stalePath = path.join(dir, basename);
    try {
      if (!fileSystem.existsSync(stalePath)) continue;
      if (!safeRead(fileSystem, stalePath).includes('TranscriptionSuite')) continue;
      fileSystem.rmSync(stalePath, { force: true });
      logger.log(`[DesktopIntegration] Removed stale desktop file: ${stalePath}`);
    } catch (err) {
      logger.warn(`[DesktopIntegration] Could not remove stale desktop file ${stalePath}:`, err);
    }
  }
}

/**
 * Install (or repair) the XDG desktop file so the Wayland host portal can resolve
 * our app id. No-op unless running as a Linux AppImage (`$APPIMAGE` set). Fully
 * best-effort and non-fatal — any failure (read-only HOME, etc.) is logged and
 * swallowed so it can never block startup.
 *
 * @returns true when the file is present/installed for this AppImage, false when
 *   skipped (not an AppImage) or on failure.
 */
export function ensureDesktopFileInstalled(options: EnsureDesktopFileOptions = {}): boolean {
  const {
    platform = process.platform,
    env = process.env,
    homedir = os.homedir,
    version,
    fileSystem = realFs,
    logger = console,
  } = options;

  // AppImage-only: $APPIMAGE is the absolute path of the running .AppImage. In
  // dev / extracted runs it is unset, and the ephemeral in-mount /tmp/.mount_*
  // path must never be written into Exec, so we skip entirely.
  const appImagePath = env.APPIMAGE;
  if (platform !== 'linux' || !appImagePath) return false;

  try {
    const dir = applicationsDir(env, homedir);
    const target = path.join(dir, DESKTOP_FILE_NAME);

    removeStaleDesktopFiles(dir, fileSystem, logger);

    if (
      fileSystem.existsSync(target) &&
      desktopFileMatchesAppImage(safeRead(fileSystem, target), appImagePath)
    ) {
      // Already installed and pointing at this AppImage — nothing to do.
      return true;
    }

    fileSystem.mkdirSync(dir, { recursive: true });
    fileSystem.writeFileSync(target, buildDesktopFileContent({ appImagePath, version }), {
      mode: 0o644,
    });
    logger.log(`[DesktopIntegration] Installed desktop file: ${target}`);
    return true;
  } catch (err) {
    logger.warn('[DesktopIntegration] Failed to install desktop file (non-fatal):', err);
    return false;
  }
}
