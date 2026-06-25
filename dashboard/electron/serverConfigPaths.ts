import { app } from 'electron';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Server user-config location helpers.
 *
 * The server's sparse config overlay lives in a DEDICATED subdirectory of the
 * Electron userData dir, NOT at the userData root. We mount only this subdir
 * into the container (USER_CONFIG_DIR) so the server never sees the rest of the
 * Electron/Chromium profile (caches, Local State, cookies, dashboard-config.json).
 *
 * Layering (read by the Python backend's config.py):
 *   - Docker:  this dir is bind-mounted to /user-config; backend reads
 *              /user-config/config.yaml.
 *   - Native (macOS MLX): the spawned server gets USER_CONFIG_DIR=<this dir>;
 *              backend's get_user_config_dir() honours that env var.
 */

/** Dedicated directory holding the server's user config overlay (+ its logs). */
export function getServerConfigDir(): string {
  return path.join(app.getPath('userData'), 'server-config');
}

/** Absolute path of the user's sparse config overlay (config.yaml). */
export function getServerConfigPath(): string {
  return path.join(getServerConfigDir(), 'config.yaml');
}

const SPARSE_STUB: string = [
  '# ============================================================================',
  '# TranscriptionSuite — User Configuration (sparse overrides)',
  '# ============================================================================',
  '# Only the keys you set here override the server defaults; everything else',
  '# is inherited from the bundled config.yaml. See the full reference at',
  '# server/config.yaml in the project repository.',
  '#',
  '# Uncomment and edit only what you want to change.',
  '',
  '# main_transcriber:',
  '#   model: "nvidia/parakeet-tdt-0.6b-v3"',
  '#   compute_type: "default"',
  '#   device: "cuda"',
  '',
  '# diarization:',
  '#   parallel: false',
  '',
].join('\n');

/**
 * Ensure the dedicated server-config dir exists and contains a config.yaml.
 *
 * - Migrates a legacy `userData/config.yaml` (the previous location) into the
 *   subdir exactly once, preserving any user overrides.
 * - Otherwise seeds a sparse, comment-only stub.
 *
 * Idempotent. Returns the absolute path to config.yaml.
 */
export function ensureServerConfigSeed(): string {
  const dir = getServerConfigDir();
  const target = getServerConfigPath();
  fs.mkdirSync(dir, { recursive: true });

  // One-time migration from the legacy userData/config.yaml location.
  const legacy = path.join(app.getPath('userData'), 'config.yaml');
  if (!fs.existsSync(target) && fs.existsSync(legacy)) {
    try {
      fs.renameSync(legacy, target);
      return target;
    } catch {
      // Fall through to stub seeding if the move fails for any reason.
    }
  }

  // Seed a sparse stub if nothing exists. 'wx' makes the existence check and the
  // write a single atomic syscall, avoiding a TOCTOU race with a parallel start.
  try {
    fs.writeFileSync(target, SPARSE_STUB, { encoding: 'utf-8', flag: 'wx' });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'EEXIST') {
      throw error;
    }
  }
  return target;
}
