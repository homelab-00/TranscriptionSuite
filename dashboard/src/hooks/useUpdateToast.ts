import { useEffect } from 'react';
import { toast } from 'sonner';
import { getConfig, setConfig } from '../config/store';

// Mirrors the `updates.download()` IPC return union in `src/types/electron.d.ts`.
type DownloadResult =
  | { ok: true; reason?: 'already-downloading' }
  | { ok: false; reason: 'no-update-available' | 'error'; message?: string }
  | { ok: false; reason: 'manual-download-required'; downloadUrl: string }
  | {
      ok: false;
      reason: 'incompatible-server';
      detail: { serverVersion: string; compatibleRange: string; deployment: 'local' | 'remote' };
    };

// Predicate narrows `DownloadResult` to the ok:false subset. TS's built-in
// narrowing via `if (r.ok) return;` is unreliable here because variant A
// (`{ ok: true; reason?: 'already-downloading' }`) has an optional discriminant
// that defeats auto-narrowing through subsequent `if (r.reason === ...)` checks.
// A predicate with an explicit `r is <union>` return type sidesteps that.
// Adapted from UpdateBanner.tsx (same repo) — shared download-union narrowing.
function isFailedDownload(r: DownloadResult): r is Extract<DownloadResult, { ok: false }> {
  return !r.ok;
}

/**
 * Singleton hook (mount once at app root). Subscribes to the main-process
 * `updates:updateAvailable` push and raises a persistent Update/Dismiss toast.
 *
 * - Update  → api.updates.download() (per-platform routing lives in main;
 *             on Linux read-only AppImage it returns manual-download-required,
 *             which we route to the release page).
 * - Dismiss → persists updates.dismissedAppVersion so this version is
 *             suppressed until a newer one appears.
 * Per-version de-dup: the toast uses a stable id and is skipped when the
 * pushed version equals the stored dismissedAppVersion.
 */
export function useUpdateToast(): void {
  useEffect(() => {
    const api = window.electronAPI;
    if (!api?.updates?.onUpdateAvailable) return;

    const unsubscribe = api.updates.onUpdateAvailable(({ version }) => {
      void (async () => {
        const dismissed = await getConfig<string>('updates.dismissedAppVersion');
        if (dismissed && dismissed === version) return;

        const toastId = `update-available-${version}`;
        toast(`Version ${version} is available`, {
          id: toastId,
          duration: Infinity,
          action: {
            label: 'Update',
            onClick: () => {
              toast.dismiss(toastId);
              void (async () => {
                try {
                  const r = await api.updates.download();
                  if (!isFailedDownload(r)) return;
                  if (r.reason === 'manual-download-required') {
                    await api.updates.openReleasePage(r.downloadUrl);
                  } else if (r.reason === 'incompatible-server') {
                    toast.error(
                      'Update blocked: the running server version is not compatible with this update.',
                    );
                  } else {
                    toast.error(r.message ?? 'Update download failed. Please try again.');
                  }
                } catch (err) {
                  console.error('[useUpdateToast] update failed:', err);
                  toast.error('Update failed to start. Please try again.');
                }
              })();
            },
          },
          cancel: {
            label: 'Dismiss',
            onClick: () => {
              toast.dismiss(toastId);
              void setConfig('updates.dismissedAppVersion', version);
            },
          },
        });
      })();
    });

    return () => {
      unsubscribe();
    };
  }, []);
}
