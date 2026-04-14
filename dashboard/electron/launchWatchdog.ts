/**
 * launchWatchdog — per-version launch-attempt counter for M6 rollback.
 *
 * The counter lives in electron-store under `updates.launchAttempts =
 * { version, count }`.
 *
 *  - Every app.whenReady() increments the counter for the running version.
 *  - When the main window stays alive past ready-to-show for ~10 s, the
 *    watchdog's owner calls confirmLaunchStable() and the counter is
 *    reset to 0.
 *  - Once count reaches 3 AND a cached previous installer exists for a
 *    different version, recordLaunchAttempt() signals that the caller
 *    should offer a restore dialog before continuing startup.
 *
 * The watchdog never actually performs the restore — that is a manual
 * swap step handled by the main process, because the running AppImage
 * cannot overwrite itself.
 */

import type Store from 'electron-store';
import type { CachedInstaller } from './installerCache.js';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyStore = Store<any>;

export interface LaunchAttemptsRecord {
  version: string;
  count: number;
}

export interface RecordLaunchAttemptResult {
  count: number;
  shouldPromptRestore: boolean;
}

export const LAUNCH_ATTEMPTS_KEY = 'updates.launchAttempts';
export const RESTORE_PROMPT_THRESHOLD = 3;

export class LaunchWatchdog {
  private readonly store: AnyStore;

  constructor(store: AnyStore) {
    this.store = store;
  }

  /**
   * Record a new launch attempt. Call once from main.ts before creating
   * the main window.
   *
   * `cached` is the result of `getCachedInstaller(userDataDir)` from
   * installerCache.ts. Pass `null` on non-Linux or when no cache exists.
   */
  recordLaunchAttempt(
    currentVersion: string,
    cached: CachedInstaller | null,
  ): RecordLaunchAttemptResult {
    const raw = this.store.get(LAUNCH_ATTEMPTS_KEY) as LaunchAttemptsRecord | undefined;
    // Validate aggressively: Infinity / NaN / negatives / non-integers are
    // either store corruption or deliberate tampering. Either way, ignore
    // the record and treat this as a fresh launch for the current version.
    const record: LaunchAttemptsRecord | null =
      raw &&
      typeof raw.version === 'string' &&
      Number.isInteger(raw.count) &&
      raw.count >= 0 &&
      raw.count < 1000
        ? raw
        : null;

    let nextCount: number;
    if (!record || record.version !== currentVersion) {
      // Version changed (upgrade/downgrade) OR no record yet. Fresh start.
      nextCount = 1;
    } else {
      nextCount = record.count + 1;
    }

    this.store.set(LAUNCH_ATTEMPTS_KEY, { version: currentVersion, count: nextCount });

    const shouldPromptRestore =
      nextCount >= RESTORE_PROMPT_THRESHOLD && cached !== null && cached.version !== currentVersion;

    return { count: nextCount, shouldPromptRestore };
  }

  /**
   * Signal that the app reached a stable running state. Resets the
   * counter to 0 but preserves the version so the next failed launch
   * increments from zero.
   */
  confirmLaunchStable(): void {
    const raw = this.store.get(LAUNCH_ATTEMPTS_KEY) as LaunchAttemptsRecord | undefined;
    const version = raw && typeof raw.version === 'string' ? raw.version : null;
    if (!version) return;
    this.store.set(LAUNCH_ATTEMPTS_KEY, { version, count: 0 });
  }

  /** Currently no timers or listeners — reserved for future teardown. */
  destroy(): void {
    // no-op
  }
}
