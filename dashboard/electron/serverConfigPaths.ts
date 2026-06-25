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

  // Atomically claim config.yaml with a sparse stub. 'wx' is create-exclusive —
  // it creates the file only if it does not already exist, in a single syscall,
  // so there is no check-then-use (TOCTOU) race. EEXIST means a real config is
  // already present: leave it untouched.
  let created = false;
  try {
    fs.writeFileSync(target, SPARSE_STUB, { encoding: 'utf-8', flag: 'wx' });
    created = true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'EEXIST') {
      throw error;
    }
  }

  // Only when WE just created the stub (target did not pre-exist) do we migrate a
  // legacy userData/config.yaml over it — so an existing real config is never
  // clobbered. Copy-then-remove (not rename) handles a cross-device userData and
  // never deletes the legacy file until its contents are safely at the new path.
  if (created) {
    const legacy = path.join(app.getPath('userData'), 'config.yaml');
    try {
      const legacyText = fs.readFileSync(legacy, 'utf-8');
      fs.writeFileSync(target, legacyText, 'utf-8');
      fs.rmSync(legacy, { force: true });
    } catch (err) {
      // ENOENT simply means there is no legacy file to migrate.
      const code = (err as NodeJS.ErrnoException)?.code;
      if (code && code !== 'ENOENT') {
        console.error(`[serverConfig] Legacy config migration failed: ${String(err)}`);
      }
    }
  }

  return target;
}
