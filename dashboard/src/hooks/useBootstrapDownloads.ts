/**
 * useBootstrapDownloads — bridges Electron IPC events to the activity store.
 *
 * Subscribes to two IPC channels:
 * 1. `docker:downloadEvent` — existing bootstrap log parser events (Docker pulls, model preloads)
 * 2. `activity:event` — new startup event watcher events (JSON Lines from startup-events.jsonl)
 *
 * Must be mounted at the app root so it runs regardless of active tab.
 */

import { useEffect } from 'react';
import { useActivityStore, type LegacyDownloadType } from '../stores/activityStore';

/** Map legacy download event actions to ActivityStatus. */
function mapAction(action: 'start' | 'complete' | 'fail'): 'active' | 'complete' | 'error' {
  switch (action) {
    case 'start':
      return 'active';
    case 'complete':
      return 'complete';
    case 'fail':
      return 'error';
  }
}

export function useBootstrapDownloads(): void {
  useEffect(() => {
    const api = window.electronAPI?.docker;
    if (!api) return;

    const cleanups: Array<() => void> = [];

    // 1. Bridge legacy download events (bootstrap log parser)
    if (api.onDownloadEvent) {
      const cleanup = api.onDownloadEvent((event) => {
        const store = useActivityStore.getState();
        const status = mapAction(event.action);

        store.addActivity({
          id: event.id,
          category: 'download',
          label: event.label,
          status,
          legacyType: event.type as LegacyDownloadType,
          ...(status === 'error' && event.error ? { error: event.error } : {}),
          ...(status === 'complete' ? { completedAt: Date.now() } : {}),
        });
      });
      cleanups.push(cleanup);
    }

    // 2. Bridge startup event watcher (JSON Lines file events)
    if (api.onActivityEvent) {
      const cleanup = api.onActivityEvent((event) => {
        const store = useActivityStore.getState();

        store.addActivity({
          id: event.id,
          category: 'download',
          label: event.label,
          status: (event.status ?? 'active') as 'active' | 'complete' | 'error',
          ...(event.progress !== undefined ? { progress: event.progress } : {}),
          ...(event.totalSize ? { totalSize: event.totalSize } : {}),
          ...(event.downloadedSize ? { downloadedSize: event.downloadedSize } : {}),
          ...(event.detail ? { detail: event.detail } : {}),
          ...(event.severity ? { severity: event.severity as 'warning' | 'error' } : {}),
          ...(event.persistent !== undefined ? { persistent: event.persistent } : {}),
          ...(event.phase ? { phase: event.phase as 'bootstrap' | 'lifespan' | 'ready' } : {}),
          ...(event.syncMode
            ? { syncMode: event.syncMode as 'delta' | 'rebuild' | 'cache-hit' }
            : {}),
          ...(event.expandableDetail ? { expandableDetail: event.expandableDetail } : {}),
          ...(event.durationMs !== undefined ? { durationMs: event.durationMs } : {}),
          ...(event.status === 'complete' || event.status === 'error'
            ? { completedAt: Date.now() }
            : {}),
        });
      });
      cleanups.push(cleanup);
    }

    return () => cleanups.forEach((fn) => fn());
  }, []);
}
