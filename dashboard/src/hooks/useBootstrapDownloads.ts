/**
 * useBootstrapDownloads — bridges Electron IPC download events to the Zustand download store.
 *
 * Subscribes to `docker:downloadEvent` from the main process (bootstrap log parser)
 * and maps start/complete/fail actions to the corresponding download store methods.
 * Must be mounted at the app root so it runs regardless of active tab.
 */

import { useEffect } from 'react';
import { useDownloadStore } from '../stores/downloadStore';

export function useBootstrapDownloads(): void {
  useEffect(() => {
    const api = window.electronAPI?.docker;
    if (!api?.onDownloadEvent) return;

    const cleanup = api.onDownloadEvent((event) => {
      const store = useDownloadStore.getState();

      switch (event.action) {
        case 'start':
          store.addDownload(event.id, 'runtime-dep', event.label);
          break;
        case 'complete':
          store.completeDownload(event.id);
          break;
        case 'fail':
          store.failDownload(event.id, event.error ?? 'Installation failed');
          break;
      }
    });

    return cleanup;
  }, []);
}
