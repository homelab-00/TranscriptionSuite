/**
 * platformGate — resolves which install path the in-app updater should
 * take for the current platform/runtime context. Pure-functional with an
 * injectable `fsAccess` so the resolution matrix is fully testable.
 *
 * Decision matrix (M7):
 *   • darwin  → manual-download   reason: macos-unsigned
 *               (Squirrel rejects unsigned builds; until code signing is
 *                set up, the only path forward is download-from-GitHub)
 *   • win32   → electron-updater
 *               (NSIS handles SmartScreen via UI affordance in UpdateModal)
 *   • linux + APPIMAGE writable      → electron-updater (M1–M6 path)
 *   • linux + APPIMAGE not writable  → manual-download   reason: appimage-not-writable
 *   • linux + APPIMAGE absent        → manual-download   reason: appimage-missing
 *   • anything else                  → manual-download   reason: unsupported-platform
 *
 * `fsAccess` rejection is treated as "not writable" — fail-closed so the
 * user always has a path forward (browser-open) rather than a stuck UI.
 */

import { promises as fsp, constants as fsConstants } from 'fs';
import path from 'path';

export type InstallStrategy = 'electron-updater' | 'manual-download';

export type StrategyReason =
  | 'macos-unsigned'
  | 'appimage-not-writable'
  | 'appimage-missing'
  | 'linux-non-appimage'
  | 'unsupported-platform';

export interface ResolveStrategyOpts {
  platform: NodeJS.Platform;
  appImagePath?: string | null;
  fsAccess?: (path: string, mode: number) => Promise<void>;
}

export interface InstallStrategyResult {
  strategy: InstallStrategy;
  reason?: StrategyReason;
}

const defaultFsAccess = (path: string, mode: number): Promise<void> => fsp.access(path, mode);

export async function resolveInstallStrategy(
  opts: ResolveStrategyOpts,
): Promise<InstallStrategyResult> {
  const { platform, appImagePath } = opts;
  const fsAccess = opts.fsAccess ?? defaultFsAccess;

  if (platform === 'darwin') {
    return { strategy: 'manual-download', reason: 'macos-unsigned' };
  }

  if (platform === 'win32') {
    return { strategy: 'electron-updater' };
  }

  if (platform === 'linux') {
    if (!appImagePath) {
      return { strategy: 'manual-download', reason: 'appimage-missing' };
    }
    // electron-updater replaces the AppImage atomically via rename() in the
    // parent directory, so we need write access on BOTH the file (so it can
    // be replaced) AND its parent dir (so the rename can complete). Most
    // real-world failure modes (immutable rootfs, read-only NFS mount, /opt
    // owned by root) are dir-level — checking only the file misses them.
    try {
      await fsAccess(appImagePath, fsConstants.W_OK);
      await fsAccess(path.dirname(appImagePath), fsConstants.W_OK);
      return { strategy: 'electron-updater' };
    } catch {
      return { strategy: 'manual-download', reason: 'appimage-not-writable' };
    }
  }

  return { strategy: 'manual-download', reason: 'unsupported-platform' };
}
