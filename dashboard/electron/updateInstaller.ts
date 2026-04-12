/**
 * UpdateInstaller — wraps electron-updater's autoUpdater to provide a
 * controllable download/install lifecycle for the Dashboard's in-app
 * update feature.
 *
 * Scope (M1 — plumbing only):
 *  - Configures autoUpdater with autoDownload=false and
 *    autoInstallOnAppQuit=false; every download and install is explicit.
 *  - startDownload() drives the state machine: idle → checking → downloading
 *    → downloaded (or → idle / error / cancelled at the intermediate steps).
 *  - Broadcasts InstallerStatus transitions via an internal EventEmitter.
 *  - Stores the CancellationToken used by downloadUpdate() so
 *    cancelDownload() can abort in flight.
 *
 * Intentionally deferred to later milestones:
 *  - M2 renders the status in a banner.
 *  - M3 gates install() behind the active-transcription safety check.
 *  - M4 adds the manifest.json compatibility guard in front of startDownload.
 *  - M6 adds SHA-512 verification beyond electron-updater's built-in check.
 *  - M7 handles platform quirks (read-only AppImage, Windows SmartScreen,
 *    macOS notarization). M1 surfaces read-only failures via the `error`
 *    status — no recovery here.
 *
 * UpdateManager (the existing polling/notification manager) is untouched;
 * the two version-check paths (UpdateManager's GitHub poll and autoUpdater's
 * check) coexist in M1 by design and will be reconciled in M4.
 */

import { EventEmitter } from 'events';
import { CancellationToken, autoUpdater } from 'electron-updater';
import type { ProgressInfo } from 'electron-updater';
import type { InstallerStatus } from './updateManager.js';

export type StartDownloadResult =
  | { ok: true; reason?: 'already-downloading' }
  | { ok: false; reason: 'no-update-available' | 'error'; message?: string };

export interface UpdateInstallerLogger {
  info: (...args: unknown[]) => void;
  warn: (...args: unknown[]) => void;
  error: (...args: unknown[]) => void;
  debug?: (...args: unknown[]) => void;
}

const defaultLogger: UpdateInstallerLogger = {
  info: (...args) => console.info('[UpdateInstaller]', ...args),
  warn: (...args) => console.warn('[UpdateInstaller]', ...args),
  error: (...args) => console.error('[UpdateInstaller]', ...args),
};

/**
 * Minimal shape we consume from an UpdateInfo. electron-updater provides a
 * larger type with many optional/required fields (files, path, sha512, …)
 * we don't touch; keeping the seam narrow lets tests fake it ergonomically.
 */
export interface UpdateInfoLike {
  version: string;
}

/**
 * Minimal subset of the autoUpdater surface we actually use. Having an
 * explicit seam makes the class testable with a fake EventEmitter-based
 * autoUpdater in unit tests.
 */
export interface AutoUpdaterLike extends EventEmitter {
  autoDownload: boolean;
  autoInstallOnAppQuit: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  logger: any;
  checkForUpdates(): Promise<{
    updateInfo?: UpdateInfoLike;
    cancellationToken?: CancellationToken;
  } | null>;
  downloadUpdate(cancellationToken?: CancellationToken): Promise<string[]>;
  quitAndInstall(isSilent?: boolean, isForceRunAfter?: boolean): void;
}

export class UpdateInstaller {
  private readonly emitter = new EventEmitter();
  private readonly updater: AutoUpdaterLike;
  private readonly logger: UpdateInstallerLogger;
  private status: InstallerStatus = { state: 'idle' };
  private cancellationToken: CancellationToken | null = null;
  private currentVersion: string | null = null;
  private installRequested = false;
  private boundListeners: Array<{ event: string; handler: (...args: unknown[]) => void }> = [];

  constructor(
    logger: UpdateInstallerLogger = defaultLogger,
    updater: AutoUpdaterLike = autoUpdater as unknown as AutoUpdaterLike,
  ) {
    this.logger = logger;
    this.updater = updater;
    this.configureUpdater();
    this.bindEvents();
  }

  getStatus(): InstallerStatus {
    // Return a shallow clone so callers can't mutate the internal state.
    return { ...this.status } as InstallerStatus;
  }

  /**
   * Subscribe to status transitions. Returns an unsubscribe function.
   */
  on(event: 'status', cb: (status: InstallerStatus) => void): () => void {
    this.emitter.on(event, cb);
    return () => {
      this.emitter.off(event, cb);
    };
  }

  /**
   * Check GitHub for updates and, if a newer version is available, start
   * downloading it. Guards against concurrent calls.
   */
  async startDownload(): Promise<StartDownloadResult> {
    if (this.status.state === 'downloading') {
      return { ok: true, reason: 'already-downloading' };
    }

    this.setStatus({ state: 'checking' });

    let result: { updateInfo?: UpdateInfoLike; cancellationToken?: CancellationToken } | null;
    try {
      result = await this.updater.checkForUpdates();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this.setStatus({ state: 'error', message });
      return { ok: false, reason: 'error', message };
    }

    if (!result || !result.updateInfo) {
      this.setStatus({ state: 'idle' });
      return { ok: false, reason: 'no-update-available' };
    }

    const info = result.updateInfo;
    this.currentVersion = info.version;

    const token = result.cancellationToken ?? new CancellationToken();
    this.cancellationToken = token;

    this.setStatus({
      state: 'downloading',
      version: info.version,
      percent: 0,
      bytesPerSecond: 0,
      transferred: 0,
      total: 0,
    });

    try {
      await this.updater.downloadUpdate(token);
      return { ok: true };
    } catch (err) {
      if (token.cancelled) {
        // cancelDownload() already transitioned status to 'cancelled'.
        return { ok: true };
      }
      const message = err instanceof Error ? err.message : String(err);
      // Guard: the 'error' event handler may have already transitioned us.
      if (this.status.state !== 'error') {
        this.setStatus({ state: 'error', message });
      }
      return { ok: false, reason: 'error', message };
    }
  }

  /**
   * Quit the app and install the downloaded update. No-op when no update
   * is ready. M3 will wrap this in the active-transcription safety gate.
   *
   * M1 assumption: the AppImage lives in a writable location on Linux.
   * When it doesn't, autoUpdater emits an error long before install()
   * is reachable, and the status already reflects that.
   */
  install(): { ok: boolean; reason?: string } {
    if (this.status.state !== 'downloaded') {
      return { ok: false, reason: 'no-update-ready' };
    }
    if (this.installRequested) {
      // Guard: quitAndInstall begins tearing the app down; a second IPC-
      // invoked call while that's in flight is undefined behavior.
      return { ok: false, reason: 'install-already-requested' };
    }
    this.installRequested = true;
    this.updater.quitAndInstall(false, true);
    return { ok: true };
  }

  /**
   * Cancel any active download. No-op when idle or not downloading.
   */
  cancelDownload(): { ok: boolean } {
    if (this.status.state !== 'downloading') {
      return { ok: true };
    }
    if (this.cancellationToken && !this.cancellationToken.cancelled) {
      this.cancellationToken.cancel();
    }
    this.setStatus({ state: 'cancelled' });
    return { ok: true };
  }

  /**
   * Remove all listeners and cancel any active download. Called from
   * main.ts's gracefulShutdown() so the orphan download Promise resolves/
   * rejects cleanly before the process exits.
   */
  destroy(): void {
    if (this.status.state === 'downloading' && this.cancellationToken?.cancelled === false) {
      this.cancellationToken.cancel();
    }
    for (const { event, handler } of this.boundListeners) {
      this.updater.off(event, handler);
    }
    this.boundListeners = [];
    this.emitter.removeAllListeners();
  }

  // ─── Internals ────────────────────────────────────────────────────────

  private configureUpdater(): void {
    this.updater.autoDownload = false;
    this.updater.autoInstallOnAppQuit = false;
    this.updater.logger = this.logger;
  }

  private bindEvents(): void {
    const bind = (event: string, handler: (...args: unknown[]) => void): void => {
      this.updater.on(event, handler);
      this.boundListeners.push({ event, handler });
    };

    bind('checking-for-update', () => {
      this.logger.info('checking for updates');
    });

    bind('update-available', (...args) => {
      const info = args[0] as UpdateInfoLike;
      this.currentVersion = info.version;
      // Status transition is driven by startDownload(); this handler only
      // captures the version string for use by later download-progress
      // events, which don't carry version information themselves.
    });

    bind('update-not-available', () => {
      // startDownload()'s post-check logic handles the idle transition.
      // This event is informational only.
    });

    bind('download-progress', (...args) => {
      // Don't regress terminal/abort states. A late progress event from a
      // cancelled run, or one that lands after 'downloaded', is noise.
      if (
        this.status.state === 'cancelled' ||
        this.status.state === 'error' ||
        this.status.state === 'downloaded'
      ) {
        return;
      }
      const progress = args[0] as ProgressInfo;
      this.setStatus({
        state: 'downloading',
        version: this.currentVersion ?? 'unknown',
        percent: progress.percent,
        bytesPerSecond: progress.bytesPerSecond,
        transferred: progress.transferred,
        total: progress.total,
      });
    });

    bind('update-downloaded', (...args) => {
      if (this.status.state === 'cancelled' || this.status.state === 'error') {
        return;
      }
      const info = args[0] as UpdateInfoLike;
      this.setStatus({ state: 'downloaded', version: info.version });
    });

    bind('error', (...args) => {
      // Don't clobber terminal states. If the download already completed
      // successfully ('downloaded'), or the user aborted ('cancelled'), a
      // later autoUpdater error is unrelated noise and shouldn't poison
      // the installer status.
      if (this.status.state === 'downloaded' || this.status.state === 'cancelled') {
        const err = args[0] as Error | undefined;
        this.logger.warn('autoUpdater error after terminal state:', err?.message ?? String(err));
        return;
      }
      const err = args[0] as Error | undefined;
      const message = err?.message ?? String(err);
      this.logger.error('autoUpdater error:', message);
      this.setStatus({ state: 'error', message });
    });
  }

  private setStatus(next: InstallerStatus): void {
    this.status = next;
    this.emitter.emit('status', next);
  }
}
