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
import { promises as fsp } from 'fs';
import { CancellationToken, autoUpdater } from 'electron-updater';
import type { ProgressInfo } from 'electron-updater';
import type { InstallerStatus } from './updateManager.js';

export type StartDownloadResult =
  | { ok: true; reason?: 'already-downloading' }
  | { ok: false; reason: 'no-update-available' | 'error'; message?: string }
  | { ok: false; reason: 'manual-download-required'; downloadUrl: string };

/**
 * Platform-strategy resolver wired in M7. Called BEFORE
 * `autoUpdater.checkForUpdates()` so the manual-download branch never
 * triggers Squirrel/Mac's misleading error event. Returns:
 *   • strategy 'electron-updater' → continue M1 path
 *   • strategy 'manual-download'  → short-circuit; transition to
 *     `manual-download-required` carrying the GitHub release URL the
 *     banner exposes via `[Download from GitHub]`.
 *
 * `version` is whatever updateManager's poll already knows; null is
 * tolerated and the resolver should fall back to `/releases/latest` for
 * the URL.
 */
export type PlatformStrategyFn = () => Promise<{
  strategy: 'electron-updater' | 'manual-download';
  reason?: string;
  downloadUrl?: string;
  version?: string | null;
}>;

/**
 * Verifier callback invoked after `update-downloaded`. Returns `ok: true`
 * to proceed, or `ok: false` to abort and place the installer in the
 * `error` state. If omitted entirely, verification is skipped (used in
 * tests and during migration before CompatGuard's manifest is persisted).
 */
export type VerifierFn = (
  downloadedFile: string,
  version: string,
) => Promise<{ ok: true } | { ok: false; reason: string }>;

/**
 * Cache-hook invoked once just before `quitAndInstall()`. Used by main.ts
 * to copy the running AppImage to `userData/previous-installer/` so the
 * M6 launch watchdog can offer a rollback on repeated launch failure.
 *
 * Any rejection is logged but does NOT block the install — losing the
 * rollback slot is preferable to blocking a user-initiated update.
 */
export type CacheHookFn = (ctx: { version: string }) => Promise<void>;

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

// Upper bound on the cacheHook copy. Healthy ~150 MB copies complete well
// under 10s on realistic storage (NVMe/SATA SSD/slow HDD/USB 2.0). Hung or
// failing media never complete, so we bound the wait to cap the time a
// user's "Install" click can hang before quitAndInstall() runs — at the
// cost of the rollback slot on that one install. The invariant at the
// install() docstring ("losing the rollback slot is preferable to blocking")
// is the authority for this tradeoff.
const CACHE_HOOK_TIMEOUT_MS = 30_000;

// Sentinel that lets Promise.race distinguish "hook timed out" from "hook
// resolved with undefined". A plain `symbol` (not `unique symbol`) is
// sufficient — identity comparison via `=== CACHE_HOOK_TIMEOUT` is stable.
const CACHE_HOOK_TIMEOUT: symbol = Symbol('cache-hook-timeout');

/**
 * Minimal shape we consume from an UpdateInfo. electron-updater provides a
 * larger type with many optional/required fields (files, path, sha512, …)
 * we don't touch; keeping the seam narrow lets tests fake it ergonomically.
 *
 * `downloadedFile` is added by the `update-downloaded` event payload. Older
 * `update-available`/progress events don't carry it, so it is optional.
 */
export interface UpdateInfoLike {
  version: string;
  downloadedFile?: string;
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

export interface UpdateInstallerDeps {
  logger?: UpdateInstallerLogger;
  updater?: AutoUpdaterLike;
  verifier?: VerifierFn;
  cacheHook?: CacheHookFn;
  platformStrategy?: PlatformStrategyFn;
}

export class UpdateInstaller {
  private readonly emitter = new EventEmitter();
  private readonly updater: AutoUpdaterLike;
  private readonly logger: UpdateInstallerLogger;
  private readonly verifier: VerifierFn | null;
  private readonly cacheHook: CacheHookFn | null;
  private readonly platformStrategy: PlatformStrategyFn | null;
  private status: InstallerStatus = { state: 'idle' };
  private cancellationToken: CancellationToken | null = null;
  private currentVersion: string | null = null;
  private installRequested = false;
  private boundListeners: Array<{ event: string; handler: (...args: unknown[]) => void }> = [];

  constructor(
    logger: UpdateInstallerLogger = defaultLogger,
    updater: AutoUpdaterLike = autoUpdater as unknown as AutoUpdaterLike,
    deps: {
      verifier?: VerifierFn;
      cacheHook?: CacheHookFn;
      platformStrategy?: PlatformStrategyFn;
    } = {},
  ) {
    this.logger = logger;
    this.updater = updater;
    this.verifier = deps.verifier ?? null;
    this.cacheHook = deps.cacheHook ?? null;
    this.platformStrategy = deps.platformStrategy ?? null;
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

    // M7: resolve the install strategy BEFORE touching autoUpdater. macOS
    // is always unsigned in v1 and Squirrel will emit a misleading error
    // event during checkForUpdates(), permanently poisoning the installer
    // status. Re-resolved per call so a user who chmods their AppImage
    // between attempts gets the right path on the next try.
    if (this.platformStrategy) {
      const strategyResult = await this.resolveStrategySafely();
      if (strategyResult.strategy === 'manual-download') {
        const downloadUrl = strategyResult.downloadUrl ?? '';
        const reason = strategyResult.reason ?? 'unsupported-platform';
        const version = strategyResult.version ?? null;
        this.setStatus({
          state: 'manual-download-required',
          version,
          downloadUrl,
          reason,
        });
        return { ok: false, reason: 'manual-download-required', downloadUrl };
      }
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
   * is ready. M3's installGate and M6's cache hook both wrap this path.
   *
   * M1 assumption: the AppImage lives in a writable location on Linux.
   * When it doesn't, autoUpdater emits an error long before install()
   * is reachable, and the status already reflects that.
   *
   * M6: if a cacheHook was wired, it runs once BEFORE quitAndInstall() so
   * the running AppImage can be copied to userData/previous-installer/
   * for the launch watchdog to use on rollback. A cache-hook rejection is
   * logged but never blocks the install — losing the rollback slot is
   * strictly preferable to blocking a user-initiated update.
   */
  async install(): Promise<{ ok: boolean; reason?: string }> {
    if (this.status.state !== 'downloaded') {
      return { ok: false, reason: 'no-update-ready' };
    }
    if (this.installRequested) {
      // Guard: quitAndInstall begins tearing the app down; a second IPC-
      // invoked call while that's in flight is undefined behavior.
      return { ok: false, reason: 'install-already-requested' };
    }
    if (!this.currentVersion) {
      // Defensive: an install without a known version would write a
      // bogus 'unknown' cache file that the launch watchdog would
      // indefinitely offer as a rollback target.
      return { ok: false, reason: 'no-version' };
    }
    this.installRequested = true;
    const version = this.currentVersion;

    if (this.cacheHook) {
      // Await the cache hook BEFORE quitAndInstall so a slow copyFile
      // cannot be truncated by Electron shutting the process down. A
      // cache-hook rejection OR timeout is logged but never blocks the
      // install — losing the rollback slot is preferable to blocking the
      // user.
      //
      // Promise.race with a sentinel: hung storage (USB stick / failing
      // SSD / NFS mount) would otherwise block here indefinitely, turning
      // a user's "Install" click into a frozen UI for as long as the OS
      // keeps the syscall open. CACHE_HOOK_TIMEOUT_MS bounds that wait;
      // the sentinel lets us tell a timeout from a hook that legitimately
      // resolved with `undefined`.
      //
      // `finally` MUST clearTimeout — on the fast path (hook resolves
      // before the bound) the setTimeout would otherwise fire ~30s later
      // and keep Node's event loop alive past the install, interfering
      // with Electron's shutdown sequence on quitAndInstall.
      let timeoutId: ReturnType<typeof setTimeout> | undefined;
      try {
        const raceResult: unknown = await Promise.race([
          this.cacheHook({ version }),
          new Promise<symbol>((resolve) => {
            timeoutId = setTimeout(() => resolve(CACHE_HOOK_TIMEOUT), CACHE_HOOK_TIMEOUT_MS);
          }),
        ]);
        if (raceResult === CACHE_HOOK_TIMEOUT) {
          this.logger.warn(
            `cache-hook timed out after ${CACHE_HOOK_TIMEOUT_MS}ms; install proceeding without rollback slot`,
          );
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        this.logger.warn('cache-hook rejected (install still proceeds):', message);
      } finally {
        if (timeoutId !== undefined) clearTimeout(timeoutId);
      }
    }

    this.updater.quitAndInstall(false, true);
    return { ok: true };
  }

  /**
   * Cancel any active download (or in-progress verification). No-op when
   * idle or already in a terminal state.
   */
  cancelDownload(): { ok: boolean } {
    if (
      this.status.state !== 'downloading' &&
      this.status.state !== 'verifying' &&
      this.status.state !== 'manual-download-required'
    ) {
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
      this.runVerification(info).catch((err) => {
        const message = err instanceof Error ? err.message : String(err);
        this.logger.error('verifier threw unexpectedly:', message);
        // If we haven't already moved to a terminal state, flip to error.
        if (this.status.state === 'verifying' || this.status.state === 'downloading') {
          this.setStatus({ state: 'error', message: `verifier-threw: ${message}` });
        }
      });
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

  /**
   * Wrap platformStrategy() so a thrown resolver never crashes the install
   * path. Fail-open to electron-updater on resolver error: a stuck UI is
   * worse than a misleading autoUpdater error the user can retry past.
   */
  private async resolveStrategySafely(): Promise<{
    strategy: 'electron-updater' | 'manual-download';
    reason?: string;
    downloadUrl?: string;
    version?: string | null;
  }> {
    if (!this.platformStrategy) return { strategy: 'electron-updater' };
    try {
      return await this.platformStrategy();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this.logger.warn('platformStrategy threw, falling open to electron-updater:', message);
      return { strategy: 'electron-updater' };
    }
  }

  /**
   * Post-download verification path. When no verifier is wired, behaves
   * exactly like M1 (flip straight to `downloaded`). When a verifier is
   * wired, transitions through an intermediate `verifying` state and
   * only flips to `downloaded` when verification succeeds. On failure,
   * unlinks the downloaded file and flips to `error` with the reason
   * bubbled up from the verifier.
   */
  private async runVerification(info: UpdateInfoLike): Promise<void> {
    if (!this.verifier) {
      this.setStatus({ state: 'downloaded', version: info.version });
      return;
    }

    this.setStatus({ state: 'verifying', version: info.version });

    const downloadedFile = info.downloadedFile;
    if (!downloadedFile) {
      this.logger.warn('update-downloaded event missing downloadedFile path — skipping verify');
      this.setStatus({ state: 'downloaded', version: info.version });
      return;
    }

    let verdict: { ok: true } | { ok: false; reason: string };
    try {
      verdict = await this.verifier(downloadedFile, info.version);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this.logger.error('verifier threw:', message);
      this.setStatus({ state: 'error', message: `verifier-threw: ${message}` });
      return;
    }

    // Guard: if the user cancelled or a late error fired while we were
    // awaiting the verifier, don't regress that terminal state.
    if (this.status.state !== 'verifying') {
      this.logger.info('verifier completed after terminal state; dropping result');
      return;
    }

    if (verdict.ok) {
      this.setStatus({ state: 'downloaded', version: info.version });
      return;
    }

    // Checksum mismatch (or other verifier failure). Use an `in` type
    // guard — TypeScript sometimes loses the `verdict.ok === false`
    // narrowing across subsequent statements when `verdict` was assigned
    // inside an enclosing try/catch that used await.
    const failureReason = 'reason' in verdict ? verdict.reason : 'unknown';

    // Unlink the downloaded file so electron-updater doesn't reuse it on
    // the next launch's "resume from cache" path.
    try {
      await fsp.unlink(downloadedFile);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this.logger.warn('failed to unlink un-verified downloaded file:', message);
    }
    // Re-check state: the fsp.unlink await gave cancelDownload() a
    // chance to flip us to 'cancelled'. Don't regress a terminal state.
    if (this.status.state !== 'verifying') {
      this.logger.info('state changed during unlink; dropping error transition');
      return;
    }
    this.setStatus({ state: 'error', message: failureReason });
  }
}
