/**
 * UpdateBanner — persistent banner surfacing in-app Dashboard updates.
 *
 * Five visual states driven by InstallerStatus + UpdateStatus:
 *   • available        — "v{x} available — [Download] [Later]"
 *   • downloading      — "Downloading v{x} — {n}%"  (progress bar, no buttons)
 *   • ready            — "v{x} ready — [Quit & Install] [Later]"
 *   • ready_blocked    — "v{x} ready — will install when jobs finish"
 *                        (install disabled, no Later)
 *   • manual-download  — "v{x} available — auto-update unavailable on this
 *                        platform [Download from GitHub] [Later]"
 *                        (M7: read-only AppImage on Linux, macOS until signing)
 *
 * Hidden when no update is available or when the user snoozed the banner
 * within the last 4 hours. Snooze is persisted under
 * `updates.bannerSnoozedUntil` (epoch ms).
 *
 * IMPORTANT: This component MUST call `updates.getInstallerStatus()` on mount.
 * Installer state is broadcast only on transitions, so a DevTools reload
 * during an active download would otherwise see `state: 'idle'` until the
 * next transition. See _bmad-output/implementation-artifacts/deferred-work.md.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { getConfig, setConfig } from '../../src/config/store';
import { UpdateModal } from './UpdateModal';

/**
 * Tailored copy for known error messages coming out of `UpdateInstaller`.
 * Returns null to fall back to the generic "Update failed: <msg>" pattern.
 */
function errorToastCopy(message: string): string | null {
  if (message === 'checksum-mismatch') {
    return 'Downloaded update failed integrity check. Retry to download again.';
  }
  return null;
}

const SNOOZE_MS = 4 * 60 * 60 * 1000;
const STATUS_POLL_MS = 60_000;
const NOW_TICK_MS = 30_000;

export type BannerVisualState =
  | 'hidden'
  | 'available'
  | 'downloading'
  | 'ready'
  | 'ready_blocked'
  | 'manual-download';

export interface DerivedBanner {
  state: BannerVisualState;
  version: string | null;
  percent?: number;
  /** M7: GitHub release URL surfaced via [Download from GitHub] in the manual-download state. */
  downloadUrl?: string;
  /** M7: strategy reason ('macos-unsigned', 'appimage-not-writable', etc.) — drives tooltip copy. */
  reason?: string;
}

/**
 * M7: human-readable tooltip for the [Download from GitHub] button per
 * the strategy reason. Falls back to a generic "Auto-update unavailable"
 * label when the reason is unknown.
 */
export function manualDownloadTooltip(reason: string | undefined): string {
  switch (reason) {
    case 'macos-unsigned':
      return 'macOS auto-update unavailable until code signing is set up';
    case 'appimage-not-writable':
      return 'AppImage location is read-only — install requires writing to disk';
    case 'appimage-missing':
      return 'Auto-update requires the AppImage build of TranscriptionSuite';
    case 'unsupported-platform':
      return 'Platform not supported by auto-update';
    default:
      return 'Auto-update unavailable on this platform';
  }
}

/**
 * Pure mapping from upstream signals → banner visual state.
 * Exported so the test suite can hit every I/O matrix row without rendering.
 */
export function deriveBannerState(
  installer: InstallerStatus | null,
  updateStatus: UpdateStatus | null,
  isBusy: boolean,
  now: number,
  snoozedUntil: number,
): DerivedBanner {
  const snoozed = snoozedUntil > now;
  // Optional-chain .app as well — a persisted UpdateStatus from an older app
  // version may be missing .app entirely, and unguarded access would crash.
  const latestVersion = updateStatus?.app?.latest ?? null;
  const updateAvailable = updateStatus?.app?.updateAvailable === true;
  const availableFromPoll: DerivedBanner =
    !snoozed && updateAvailable && latestVersion != null && latestVersion !== ''
      ? { state: 'available', version: latestVersion }
      : { state: 'hidden', version: null };

  if (!installer) return availableFromPoll;

  switch (installer.state) {
    case 'downloading':
      return {
        state: 'downloading',
        version: installer.version,
        percent: installer.percent,
      };
    case 'checking':
      return { state: 'downloading', version: latestVersion, percent: 0 };
    case 'downloaded':
      return {
        state: isBusy ? 'ready_blocked' : 'ready',
        version: installer.version,
      };
    case 'manual-download-required':
      // M7: snoozed banner stays hidden even with an installer signal —
      // a snoozed manual-download is functionally identical to a snoozed
      // available, and the user explicitly chose Later.
      if (snoozed) return { state: 'hidden', version: null };
      return {
        state: 'manual-download',
        version: installer.version,
        downloadUrl: installer.downloadUrl,
        reason: installer.reason,
      };
    case 'idle':
    case 'cancelled':
    case 'error':
    default:
      return availableFromPoll;
  }
}

export interface UpdateBannerProps {
  // M3-HANDOFF: replace with the server-side isAppIdle() predicate once M3 ships.
  isBusy: boolean;
}

function isElectron(): boolean {
  return typeof window !== 'undefined' && 'electronAPI' in window && !!window.electronAPI;
}

export function UpdateBanner({ isBusy }: UpdateBannerProps) {
  const [installer, setInstaller] = useState<InstallerStatus | null>(null);
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus | null>(null);
  const [snoozedUntil, setSnoozedUntil] = useState<number>(0);
  const [now, setNow] = useState<number>(() => Date.now());
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [appVersion, setAppVersion] = useState<string>('');
  // M6: track the last error message we toasted so repeated error broadcasts
  // with the same message do not spam the user. Initialized to null on mount
  // so the first error transition always toasts.
  const lastErrorMessageRef = useRef<string | null>(null);

  useEffect(() => {
    if (!isElectron()) return;
    const api = window.electronAPI?.updates;
    if (!api) return;

    let cancelled = false;

    // Mount-time installer sync — required because installer state is never replayed.
    // Only apply the snapshot if a live transition event hasn't already populated
    // state; otherwise the async snapshot could clobber a fresher update.
    api
      .getInstallerStatus()
      .then((s) => {
        if (!cancelled) setInstaller((prev) => prev ?? s);
      })
      .catch((err: unknown) => {
        console.error('UpdateBanner: getInstallerStatus failed', err);
      });

    // Resolve current app version for the modal's "current → target" header.
    // Best-effort — if it fails, the modal falls back to "latest" without the arrow.
    // Extracted local to avoid `.then()` on an undefined optional-chain result.
    const getVersionFn = window.electronAPI?.app?.getVersion;
    if (typeof getVersionFn === 'function') {
      getVersionFn()
        .then((v) => {
          if (!cancelled && typeof v === 'string' && v) setAppVersion(v);
        })
        .catch((err: unknown) => {
          console.error('UpdateBanner: getVersion failed', err);
        });
    }

    // Initial UpdateStatus read + 60s poll to surface newly-scheduled checks.
    const pollStatus = () => {
      api
        .getStatus()
        .then((s) => {
          if (!cancelled) setUpdateStatus(s);
        })
        .catch((err: unknown) => {
          console.error('UpdateBanner: getStatus failed', err);
        });
    };
    pollStatus();
    const statusTimer = setInterval(pollStatus, STATUS_POLL_MS);

    // Read persisted snooze.
    getConfig<number>('updates.bannerSnoozedUntil')
      .then((v) => {
        if (!cancelled) setSnoozedUntil(typeof v === 'number' ? v : 0);
      })
      .catch((err: unknown) => {
        console.error('UpdateBanner: getConfig snooze failed', err);
      });

    // Live installer transitions.
    const unsubscribe = api.onInstallerStatus((s) => {
      if (cancelled) return;
      setInstaller(s);

      // M6: surface installer errors as a sonner toast with a [Retry] action.
      // Dedup on the message string so repeated broadcasts (e.g. electron-
      // updater re-emitting error on every internal retry) do not spam.
      if (s.state === 'error') {
        const message = s.message ?? 'unknown error';
        if (lastErrorMessageRef.current === message) return;
        lastErrorMessageRef.current = message;
        const copy = errorToastCopy(message) ?? `Update failed: ${message}`;
        toast.error(copy, {
          action: {
            label: 'Retry',
            onClick: () => {
              void handleRetry();
            },
          },
        });
      } else if (s.state === 'downloading' || s.state === 'downloaded') {
        // Successful path — reset the dedup so a future error after a fresh
        // retry cycle can toast again.
        lastErrorMessageRef.current = null;
      }
    });

    // Track current time so the snoozed banner re-appears after expiry.
    const nowTimer = setInterval(() => {
      if (!cancelled) setNow(Date.now());
    }, NOW_TICK_MS);

    return () => {
      cancelled = true;
      clearInterval(statusTimer);
      clearInterval(nowTimer);
      if (typeof unsubscribe === 'function') unsubscribe();
    };
  }, []);

  const handleSnooze = useCallback(async () => {
    const until = Date.now() + SNOOZE_MS;
    setSnoozedUntil(until);
    try {
      await setConfig('updates.bannerSnoozedUntil', until);
    } catch (err) {
      console.error('UpdateBanner: setConfig snooze failed', err);
    }
  }, []);

  const handleDownload = useCallback(() => {
    // Pre-install modal (M5) intercepts [Download] so the user sees release
    // notes + compat verdict + recovery path before any network work starts.
    // The actual `api.download()` call now lives in handleConfirmInstall.
    setIsModalOpen(true);
  }, []);

  const handleConfirmInstall = useCallback(async () => {
    const api = window.electronAPI?.updates;
    if (!api) return;
    try {
      await api.download();
    } catch (err) {
      console.error('UpdateBanner: download invocation failed', err);
    }
  }, []);

  // M6: [Retry] action on error toasts — re-runs the download. We clear the
  // dedup ref so a subsequent error of the same message still toasts.
  const handleRetry = useCallback(async () => {
    const api = window.electronAPI?.updates;
    if (!api) return;
    lastErrorMessageRef.current = null;
    try {
      await api.download();
    } catch (err) {
      console.error('UpdateBanner: retry download invocation failed', err);
    }
  }, []);

  const handleModalClose = useCallback(() => setIsModalOpen(false), []);

  const handleInstall = useCallback(async () => {
    const api = window.electronAPI?.updates;
    if (!api) return;
    try {
      await api.install();
    } catch (err) {
      console.error('UpdateBanner: install invocation failed', err);
    }
  }, []);

  // M7: open the GitHub release page for the manual-download fallback.
  // The URL was supplied by the main-process strategy resolver; we just
  // pass it through. Failures are logged but not toasted — the user can
  // retry the click and there is no recovery action beyond opening the
  // page manually.
  const handleOpenReleasePage = useCallback(async (url: string) => {
    const api = window.electronAPI?.updates;
    if (!api || !url) return;
    try {
      await api.openReleasePage(url);
    } catch (err) {
      console.error('UpdateBanner: openReleasePage invocation failed', err);
    }
  }, []);

  const derived = deriveBannerState(installer, updateStatus, isBusy, now, snoozedUntil);

  // Reset modal-open flag when state leaves `available`. Without this, the
  // flag leaks across state transitions (available → downloading → available
  // after a cancelled download would silently re-open the modal). The
  // dependency on derived.state keeps the effect cheap.
  useEffect(() => {
    if (derived.state !== 'available' && isModalOpen) {
      setIsModalOpen(false);
    }
  }, [derived.state, isModalOpen]);

  const accent = 'border-cyan-400/30 bg-cyan-400/10 text-cyan-200';
  const primaryBtn =
    'rounded bg-cyan-400/20 px-3 py-1 text-xs font-medium text-cyan-100 transition-colors hover:bg-cyan-400/30';
  const disabledBtn =
    'rounded bg-white/10 px-3 py-1 text-xs font-medium text-slate-400 cursor-not-allowed';
  const laterBtn =
    'rounded bg-white/5 px-3 py-1 text-xs font-medium text-slate-300 transition-colors hover:bg-white/10';

  let bannerContent: React.ReactNode = null;
  switch (derived.state) {
    case 'available':
      bannerContent = (
        <div
          role="status"
          aria-label="Update available"
          className={`flex items-center justify-between gap-3 border ${accent} px-4 py-2 text-sm`}
        >
          <span>{derived.version} available</span>
          <div className="flex items-center gap-2">
            <button type="button" onClick={handleDownload} className={primaryBtn}>
              Download
            </button>
            <button type="button" onClick={handleSnooze} className={laterBtn}>
              Later
            </button>
          </div>
        </div>
      );
      break;

    case 'downloading': {
      // Nullish coalescing doesn't defend against NaN (electron-updater can emit
      // partial progress during early connection). Clamp explicitly.
      const rawPercent = derived.percent;
      const percent = Number.isFinite(rawPercent)
        ? Math.max(0, Math.min(100, rawPercent as number))
        : 0;
      bannerContent = (
        <div
          role="status"
          aria-label="Update downloading"
          className={`flex flex-col gap-1 border ${accent} px-4 py-2 text-sm`}
        >
          <span>
            Downloading {derived.version ?? '…'} — {percent}%
          </span>
          <div className="h-1 w-full overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full rounded-full bg-cyan-400/70 transition-all duration-300"
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>
      );
      break;
    }

    case 'ready':
      bannerContent = (
        <div
          role="status"
          aria-label="Update ready"
          className={`flex items-center justify-between gap-3 border ${accent} px-4 py-2 text-sm`}
        >
          <span>{derived.version} ready</span>
          <div className="flex items-center gap-2">
            <button type="button" onClick={handleInstall} className={primaryBtn}>
              Quit & Install
            </button>
            <button type="button" onClick={handleSnooze} className={laterBtn}>
              Later
            </button>
          </div>
        </div>
      );
      break;

    case 'ready_blocked':
      bannerContent = (
        <div
          role="status"
          aria-label="Update ready, queued"
          className={`flex items-center justify-between gap-3 border ${accent} px-4 py-2 text-sm`}
        >
          <span>{derived.version} ready — will install when jobs finish</span>
          <button
            type="button"
            disabled
            title="Will install when jobs finish"
            className={disabledBtn}
          >
            Quit & Install
          </button>
        </div>
      );
      break;

    case 'manual-download': {
      const versionLabel = derived.version ?? 'latest';
      const tooltip = manualDownloadTooltip(derived.reason);
      const url = derived.downloadUrl ?? '';
      bannerContent = (
        <div
          role="status"
          aria-label="Update available, manual download required"
          className={`flex items-center justify-between gap-3 border ${accent} px-4 py-2 text-sm`}
        >
          <span>{versionLabel} available — auto-update unavailable on this platform</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                void handleOpenReleasePage(url);
              }}
              title={tooltip}
              disabled={!url}
              className={url ? primaryBtn : disabledBtn}
            >
              Download from GitHub
            </button>
            <button type="button" onClick={handleSnooze} className={laterBtn}>
              Later
            </button>
          </div>
        </div>
      );
      break;
    }

    default:
      bannerContent = null;
  }

  // The modal belongs to the `available` state only — no other state has a
  // [Download] button to intercept. When state flips away, the modal closes
  // naturally on the next render.
  const showModal = isModalOpen && derived.state === 'available';

  if (!bannerContent && !showModal) return null;

  return (
    <>
      {bannerContent}
      <UpdateModal
        isOpen={showModal}
        targetVersion={derived.version}
        currentVersion={appVersion}
        onClose={handleModalClose}
        onConfirmInstall={handleConfirmInstall}
      />
    </>
  );
}
