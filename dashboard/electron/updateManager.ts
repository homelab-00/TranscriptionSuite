/**
 * UpdateManager — periodic update checking for the app (GitHub Releases)
 * and Docker server image (GHCR tags).
 *
 * • Checks are opt-in (disabled by default).
 * • Notifications are gated by the existing `app.showNotifications` flag.
 * • Notification deduplication: a version is only notified once (persisted
 *   in electron-store under `updates.lastNotified.*`).
 * • No download or auto-install — notification-only.
 */

import { Notification, app } from 'electron';
import type Store from 'electron-store';
import { dockerManager } from './dockerManager.js';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyStore = Store<any>;

// ─── Types ──────────────────────────────────────────────────────────────────

export interface ComponentUpdateStatus {
  current: string | null;
  latest: string | null;
  updateAvailable: boolean;
  error: string | null;
  /**
   * Markdown body from the GitHub release (app channel only). Trimmed to
   * 50 000 chars at capture time. `null` when absent, empty, or when the
   * source is not a GitHub release (e.g., the `server` channel on GHCR).
   */
  releaseNotes: string | null;
}

const RELEASE_NOTES_MAX_CHARS = 50_000;

/**
 * Truncate a string to at most `max` code points (not UTF-16 units). Plain
 * `.slice(0, N)` splits astral characters (emoji, CJK outside BMP) at the
 * surrogate-pair boundary and produces a lone surrogate, which `remark-gfm`
 * either replaces with U+FFFD or throws on. Iterating via `Array.from` is
 * O(n) in N — acceptable for the 50 000-cap hot path — and produces a well-
 * formed string on every input.
 */
export function sanitizeReleaseBody(body: unknown): string | null {
  if (typeof body !== 'string') return null;
  const trimmed = body.trim();
  if (!trimmed) return null;
  if (trimmed.length <= RELEASE_NOTES_MAX_CHARS) return trimmed;
  const codepoints = Array.from(trimmed);
  if (codepoints.length <= RELEASE_NOTES_MAX_CHARS) return trimmed;
  return codepoints.slice(0, RELEASE_NOTES_MAX_CHARS).join('');
}

/**
 * Runtime state of the UpdateInstaller (electron-updater wrapper).
 *
 * Ephemeral — never persisted across app launches; always starts at
 * `{ state: 'idle' }`. M2's banner maps these 1:1 to its visual states.
 */
export type InstallerStatus =
  | { state: 'idle' }
  | { state: 'checking' }
  | {
      state: 'downloading';
      version: string;
      percent: number;
      bytesPerSecond: number;
      transferred: number;
      total: number;
    }
  | { state: 'verifying'; version: string }
  | { state: 'downloaded'; version: string }
  | { state: 'cancelled' }
  | { state: 'error'; message: string }
  | {
      state: 'manual-download-required';
      version: string | null;
      downloadUrl: string;
      reason: string;
    };

export interface UpdateStatus {
  lastChecked: string; // ISO timestamp
  app: ComponentUpdateStatus;
  server: ComponentUpdateStatus;
  /**
   * Optional — populated by UpdateInstaller on each state transition.
   * Absent in persisted statuses from versions before M1.
   */
  installer?: InstallerStatus;
}

// ─── Constants ──────────────────────────────────────────────────────────────

const GITHUB_RELEASES_URL =
  'https://api.github.com/repos/homelab-00/TranscriptionSuite/releases/latest';

const GHCR_TOKEN_URL =
  'https://ghcr.io/token?service=ghcr.io&scope=repository:homelab-00/transcriptionsuite-server:pull';

const GHCR_TAGS_URL = 'https://ghcr.io/v2/homelab-00/transcriptionsuite-server/tags/list';

const INTERVAL_MS: Record<string, number> = {
  '24h': 24 * 60 * 60 * 1000,
  '7d': 7 * 24 * 60 * 60 * 1000,
  '28d': 28 * 24 * 60 * 60 * 1000,
};

/**
 * On a failed `check()` we schedule a single-shot retry at this interval
 * (in addition to the regular `setInterval` cadence). Brainstorming D:
 * "Network failure — silent retry every 1h, no user notification."
 */
export const FAILURE_RETRY_MS = 60 * 60 * 1000;

// ─── Semver helpers ─────────────────────────────────────────────────────────

interface SemVer {
  major: number;
  minor: number;
  patch: number;
}

/**
 * Parse a "vX.Y.Z" or "X.Y.Z" string into a numeric triple.
 * Returns null for pre-releases, "latest", or anything unparsable.
 */
function parseSemVer(raw: string): SemVer | null {
  const cleaned = raw.replace(/^v/, '');
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(cleaned);
  if (!match) return null;
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
  };
}

/** Return > 0 if a > b, < 0 if a < b, 0 if equal. */
function compareSemVer(a: SemVer, b: SemVer): number {
  if (a.major !== b.major) return a.major - b.major;
  if (a.minor !== b.minor) return a.minor - b.minor;
  return a.patch - b.patch;
}

/** Find the highest stable semver tag from a list of strings. */
function highestSemVer(tags: string[]): string | null {
  let best: SemVer | null = null;
  let bestRaw: string | null = null;
  for (const tag of tags) {
    const sv = parseSemVer(tag);
    if (!sv) continue;
    if (!best || compareSemVer(sv, best) > 0) {
      best = sv;
      bestRaw = tag.replace(/^v/, ''); // normalize without v prefix
    }
  }
  return bestRaw;
}

// ─── UpdateManager ──────────────────────────────────────────────────────────

export class UpdateManager {
  private store: AnyStore;
  private timer: ReturnType<typeof setInterval> | null = null;
  private failureRetryTimer: ReturnType<typeof setTimeout> | null = null;
  private destroyed = false;

  constructor(store: AnyStore) {
    this.store = store;
  }

  /**
   * Start the update manager. Performs an initial check and schedules
   * periodic checks if enabled.
   */
  start(): void {
    if (!this.isEnabled()) return;
    // Fire-and-forget initial check
    this.check().catch((err) => console.error('UpdateManager: initial check failed', err));
    this.scheduleTimer();
  }

  /**
   * Call after update-related config keys change.
   * Clears the old timer and (re-)schedules if still enabled.
   */
  reconfigure(): void {
    this.clearTimer();
    if (this.isEnabled()) {
      this.scheduleTimer();
    }
  }

  /**
   * Perform a full update check right now.
   * Persists the result and optionally shows a notification.
   */
  async check(): Promise<UpdateStatus> {
    if (this.destroyed) {
      // Defensive: an in-flight failureRetryTimer that fires right as
      // destroy() runs, or a check() that was awaiting fetch across
      // teardown, would otherwise write to the store post-shutdown.
      const current = app.getVersion();
      return {
        lastChecked: new Date().toISOString(),
        app: {
          current,
          latest: null,
          updateAvailable: false,
          error: 'destroyed',
          releaseNotes: null,
        },
        server: {
          current: null,
          latest: null,
          updateAvailable: false,
          error: 'destroyed',
          releaseNotes: null,
        },
      };
    }
    const [appResult, serverResult] = await Promise.allSettled([
      this.checkApp(),
      this.checkServer(),
    ]);

    const appStatus: ComponentUpdateStatus =
      appResult.status === 'fulfilled'
        ? appResult.value
        : {
            current: app.getVersion(),
            latest: null,
            updateAvailable: false,
            error: String(appResult.reason),
            releaseNotes: null,
          };

    const serverStatus: ComponentUpdateStatus =
      serverResult.status === 'fulfilled'
        ? serverResult.value
        : {
            current: null,
            latest: null,
            updateAvailable: false,
            error: String(serverResult.reason),
            releaseNotes: null,
          };

    const status: UpdateStatus = {
      lastChecked: new Date().toISOString(),
      app: appStatus,
      server: serverStatus,
    };

    // Guard against a late in-flight check completing after destroy().
    if (this.destroyed) {
      return status;
    }

    this.store.set('updates.lastStatus', status);
    this.maybeNotify(status);

    // M6: single-shot retry in 1 h when either component errored, cleared
    // on the next fully-green check. The regular setInterval is untouched
    // so this only shortens the next probe — it never extends it.
    if (appStatus.error !== null || serverStatus.error !== null) {
      this.scheduleFailureRetry();
    } else {
      this.clearFailureRetry();
    }

    return status;
  }

  /** Return the last persisted status (or null if never checked). */
  getStatus(): UpdateStatus | null {
    return (this.store.get('updates.lastStatus') as UpdateStatus) ?? null;
  }

  /** Stop the timer (called on app quit). */
  destroy(): void {
    this.destroyed = true;
    this.clearTimer();
    this.clearFailureRetry();
  }

  // ─── Private ────────────────────────────────────────────────────────────

  private isEnabled(): boolean {
    return (this.store.get('app.updateChecksEnabled') as boolean) ?? false;
  }

  private getIntervalMs(): number {
    const mode = (this.store.get('app.updateCheckIntervalMode') as string) ?? '24h';
    if (mode === 'custom') {
      const hours = (this.store.get('app.updateCheckCustomHours') as number) ?? 24;
      return Math.max(hours, 1) * 60 * 60 * 1000;
    }
    return INTERVAL_MS[mode] ?? INTERVAL_MS['24h'];
  }

  private scheduleTimer(): void {
    this.clearTimer();
    const ms = this.getIntervalMs();
    this.timer = setInterval(() => {
      this.check().catch((err) => console.error('UpdateManager: scheduled check failed', err));
    }, ms);
  }

  private clearTimer(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  private scheduleFailureRetry(): void {
    this.clearFailureRetry();
    if (this.destroyed) return;
    this.failureRetryTimer = setTimeout(() => {
      this.failureRetryTimer = null;
      if (this.destroyed) return;
      this.check().catch((err) => console.error('UpdateManager: failure-retry check failed', err));
    }, FAILURE_RETRY_MS);
  }

  private clearFailureRetry(): void {
    if (this.failureRetryTimer) {
      clearTimeout(this.failureRetryTimer);
      this.failureRetryTimer = null;
    }
  }

  /** Test-only hook — expose timer presence so unit tests can assert arm/clear. */
  hasFailureRetry(): boolean {
    return this.failureRetryTimer !== null;
  }

  // ─── App version check (GitHub Releases) ────────────────────────────────

  private async checkApp(): Promise<ComponentUpdateStatus> {
    const currentVersion = app.getVersion();

    try {
      const res = await fetch(GITHUB_RELEASES_URL, {
        headers: { Accept: 'application/vnd.github+json' },
        signal: AbortSignal.timeout(15_000),
      });

      if (!res.ok) {
        throw new Error(`GitHub API returned ${res.status}`);
      }

      const data = (await res.json()) as { tag_name?: string; body?: string };
      const latestTag = data.tag_name ?? '';
      const releaseNotes = sanitizeReleaseBody(data.body);
      const latestSv = parseSemVer(latestTag);
      const currentSv = parseSemVer(currentVersion);

      if (!latestSv) {
        return {
          current: currentVersion,
          latest: latestTag || null,
          updateAvailable: false,
          error: `Could not parse latest tag: ${latestTag}`,
          releaseNotes,
        };
      }

      const updateAvailable = currentSv !== null && compareSemVer(latestSv, currentSv) > 0;

      return {
        current: currentVersion,
        latest: latestSv ? `${latestSv.major}.${latestSv.minor}.${latestSv.patch}` : null,
        updateAvailable,
        error: null,
        releaseNotes,
      };
    } catch (err) {
      return {
        current: currentVersion,
        latest: null,
        updateAvailable: false,
        error: err instanceof Error ? err.message : String(err),
        releaseNotes: null,
      };
    }
  }

  // ─── Server image check (GHCR) ─────────────────────────────────────────

  private async checkServer(): Promise<ComponentUpdateStatus> {
    // Local: highest semver tag from locally pulled Docker images
    let localVersion: string | null = null;
    try {
      const images = await dockerManager.listImages();
      const tags = images.map((img) => img.tag);
      localVersion = highestSemVer(tags);
    } catch {
      // Docker may not be available
    }

    try {
      // Anonymous token for GHCR public repo
      const tokenRes = await fetch(GHCR_TOKEN_URL, {
        signal: AbortSignal.timeout(15_000),
      });
      if (!tokenRes.ok) {
        throw new Error(`GHCR token request returned ${tokenRes.status}`);
      }
      const tokenData = (await tokenRes.json()) as { token?: string };
      const token = tokenData.token;
      if (!token) throw new Error('No token in GHCR response');

      const tagsRes = await fetch(GHCR_TAGS_URL, {
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(15_000),
      });
      if (!tagsRes.ok) {
        throw new Error(`GHCR tags request returned ${tagsRes.status}`);
      }
      const tagsData = (await tagsRes.json()) as { tags?: string[] };
      const remoteTags = tagsData.tags ?? [];
      const remoteVersion = highestSemVer(remoteTags);

      let updateAvailable = false;
      if (localVersion && remoteVersion) {
        const localSv = parseSemVer(localVersion);
        const remoteSv = parseSemVer(remoteVersion);
        if (localSv && remoteSv) {
          updateAvailable = compareSemVer(remoteSv, localSv) > 0;
        }
      }

      return {
        current: localVersion,
        latest: remoteVersion,
        updateAvailable,
        error: null,
        releaseNotes: null,
      };
    } catch (err) {
      return {
        current: localVersion,
        latest: null,
        updateAvailable: false,
        error: err instanceof Error ? err.message : String(err),
        releaseNotes: null,
      };
    }
  }

  // ─── Notifications ─────────────────────────────────────────────────────

  private maybeNotify(status: UpdateStatus): void {
    const showNotifications = (this.store.get('app.showNotifications') as boolean) ?? true;
    if (!showNotifications) return;

    const lastNotifiedApp = (this.store.get('updates.lastNotified.appLatest') as string) ?? '';
    const lastNotifiedServer =
      (this.store.get('updates.lastNotified.serverLatest') as string) ?? '';

    const newApp =
      status.app.updateAvailable && status.app.latest && status.app.latest !== lastNotifiedApp;

    const newServer =
      status.server.updateAvailable &&
      status.server.latest &&
      status.server.latest !== lastNotifiedServer;

    if (!newApp && !newServer) return;

    const lines: string[] = [];
    if (newApp) {
      lines.push(`Dashboard: ${status.app.current} → ${status.app.latest}`);
      this.store.set('updates.lastNotified.appLatest', status.app.latest);
    }
    if (newServer) {
      lines.push(`Server: ${status.server.current ?? 'none'} → ${status.server.latest}`);
      this.store.set('updates.lastNotified.serverLatest', status.server.latest);
    }

    const notification = new Notification({
      title: 'TranscriptionSuite Update Available',
      body: lines.join('\n'),
      silent: true,
    });
    notification.show();
  }
}
