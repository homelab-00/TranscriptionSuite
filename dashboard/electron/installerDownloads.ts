/**
 * Reports the app-update pipeline into the DownloadHub (GH-318).
 *
 * Both updaters speak `InstallerStatus`: electron-updater (via
 * UpdateInstaller) and the macOS DMG variant updater. Each gets its own
 * adapter instance because only the electron-updater path can be cancelled.
 *
 * `errorToast` is off: the UpdateBanner already raises an actionable Retry
 * toast on failure, so the download bar must not raise a second one.
 */

import type { DownloadHub } from './downloadHub.js';
import type { InstallerStatus } from './updateManager.js';

const APP_UPDATE_ID = 'app-update';

export function createInstallerDownloadAdapter(
  hub: DownloadHub,
  options: { cancel?: () => void },
): (status: InstallerStatus) => void {
  // Distinguishes "checked, nothing to fetch" (drop silently) from "the DMG
  // path finished and went back to idle" (a completed download).
  let sawBytes = false;

  const begin = (label: string, detail?: string) =>
    hub.begin({
      id: APP_UPDATE_ID,
      kind: 'app-update',
      label,
      ...(detail ? { detail } : {}),
      ...(options.cancel ? { cancel: options.cancel } : {}),
      errorToast: false,
    });

  return (status) => {
    switch (status.state) {
      case 'checking':
        sawBytes = false;
        begin('App update', 'Preparing');
        break;
      case 'downloading': {
        if (!hub.active(APP_UPDATE_ID)) sawBytes = false;
        const label = `App update v${status.version}`;
        begin(label).update({
          label,
          detail: '',
          bytesDone: status.transferred,
          bytesTotal: status.total,
          ...(status.bytesPerSecond > 0 ? { bytesPerSecond: status.bytesPerSecond } : {}),
        });
        sawBytes = true;
        break;
      }
      case 'verifying':
        hub.active(APP_UPDATE_ID)?.update({ detail: 'Verifying' });
        break;
      case 'downloaded':
        hub.active(APP_UPDATE_ID)?.complete();
        break;
      case 'idle':
        if (sawBytes) hub.active(APP_UPDATE_ID)?.complete();
        else hub.active(APP_UPDATE_ID)?.discard();
        break;
      case 'manual-download-required':
        hub.active(APP_UPDATE_ID)?.discard();
        break;
      case 'cancelled':
        hub.active(APP_UPDATE_ID)?.cancel();
        break;
      case 'error':
        hub.active(APP_UPDATE_ID)?.fail(status.message);
        break;
    }
  };
}
