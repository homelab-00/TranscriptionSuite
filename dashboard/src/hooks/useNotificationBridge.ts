/**
 * useNotificationBridge - the single renderer-side event funnel for the
 * session notifications store. Successor to the legacy bootstrap-downloads
 * bridge.
 *
 * Responsibilities:
 *  1. Hydrate the store from the semi-persistent session file, then persist
 *     changes back (debounced) so a renderer reload keeps the session log.
 *  2. Subscribe to every notification-relevant IPC channel:
 *     docker:downloadEvent, activity:event, updates:installerStatus (+ a
 *     mount-time snapshot: that channel is broadcast-only with no replay),
 *     updates:updateAvailable, mlx:statusChanged.
 *
 * Must be mounted exactly once at the app root (App.tsx).
 */

import { useEffect } from 'react';
import {
  useNotificationsStore,
  type AppNotification,
  type NotificationCategory,
  type NotificationStatus,
} from '../stores/notificationsStore';
import { mapStartupEvent, serverStartPatch, SERVER_START_ID } from '../utils/startupEventMapping';

const PERSIST_DEBOUNCE_MS = 400;

const NOTIFICATION_CATEGORIES: readonly NotificationCategory[] = [
  'download',
  'server',
  'update',
  'recording',
  'import',
  'note',
  'transcription',
];
const NOTIFICATION_STATUSES: readonly NotificationStatus[] = ['active', 'complete', 'error'];

/** Never trust file content: reject the whole array if any entry is malformed. */
function isNotificationArray(value: unknown): value is AppNotification[] {
  return (
    Array.isArray(value) &&
    value.every((v) => {
      if (typeof v !== 'object' || v === null) return false;
      const n = v as AppNotification;
      return (
        typeof n.entryId === 'string' &&
        typeof n.id === 'string' &&
        typeof n.title === 'string' &&
        (NOTIFICATION_CATEGORIES as string[]).includes(n.category) &&
        (NOTIFICATION_STATUSES as string[]).includes(n.status) &&
        typeof n.createdAt === 'number' &&
        Number.isFinite(n.createdAt) &&
        typeof n.toastDismissed === 'boolean'
      );
    })
  );
}

export function useNotificationBridge(): void {
  // 1. Hydration + debounced persistence
  useEffect(() => {
    const api = window.electronAPI?.notificationLog;
    if (!api) return;

    let cancelled = false;
    void api
      .load()
      .then((items) => {
        if (!cancelled && isNotificationArray(items)) {
          useNotificationsStore.getState().hydrate(items);
        }
      })
      .catch(() => {});

    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = useNotificationsStore.subscribe(() => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        void api.persist(useNotificationsStore.getState().notifications).catch(() => {});
      }, PERSIST_DEBOUNCE_MS);
    });

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      unsubscribe();
    };
  }, []);

  // 2. IPC event subscriptions
  useEffect(() => {
    const docker = window.electronAPI?.docker;
    const updates = window.electronAPI?.updates;
    const mlx = window.electronAPI?.mlx;
    const cleanups: Array<() => void> = [];
    const store = () => useNotificationsStore.getState();

    // Bootstrap-log download events (docker pulls, GGML host download, model preloads).
    if (docker?.onDownloadEvent) {
      cleanups.push(
        docker.onDownloadEvent((event) => {
          const status =
            event.action === 'start'
              ? 'active'
              : event.action === 'complete'
                ? 'complete'
                : 'error';
          store().notify({
            id: event.id,
            category: 'download',
            title: event.label,
            status,
            ...(event.progress !== undefined ? { progress: event.progress } : {}),
            ...(event.downloadedSize ? { downloadedSize: event.downloadedSize } : {}),
            ...(event.totalSize ? { totalSize: event.totalSize } : {}),
            ...(status === 'error' && event.error ? { error: event.error } : {}),
          });
        }),
      );
    }

    // startup-events.jsonl stream (server stages, HF model downloads, warnings).
    if (docker?.onActivityEvent) {
      cleanups.push(
        docker.onActivityEvent((event) => {
          // A granular model-load event supersedes the coarse log-parser card
          // (GH-207): hide its toast; the record itself stays in the log and
          // completes on its own when the parser sees the loaded line.
          if (event.id.startsWith('model-load-')) {
            store().dismissToast('model-preload');
          }
          const entry = mapStartupEvent(event);
          if (entry) store().notify(entry);
          const aggregate = serverStartPatch(event);
          if (aggregate) store().notify(aggregate);
        }),
      );
    }

    // App auto-update pipeline (real percent). Broadcast-only channel: also
    // fetch a snapshot on mount so a renderer reload mid-download recovers.
    const handleInstallerStatus = (status: InstallerStatus) => {
      const s = store();
      switch (status.state) {
        case 'downloading':
          s.notify({
            id: 'app-update-download',
            category: 'update',
            title: `Downloading update v${status.version ?? ''}`.trim(),
            status: 'active',
            ...(status.percent !== undefined && Number.isFinite(status.percent)
              ? { progress: Math.round(status.percent) }
              : {}),
          });
          break;
        case 'downloaded':
          s.notify({
            id: 'app-update-download',
            category: 'update',
            title: `Update v${status.version ?? ''} downloaded`.trim(),
            detail: 'Restart the app to install.',
            status: 'complete',
          });
          break;
        case 'cancelled':
          s.updateNotification('app-update-download', {
            title: 'Update download cancelled',
            status: 'complete',
          });
          break;
        case 'error':
          s.updateNotification('app-update-download', {
            title: 'Update download failed',
            status: 'error',
            error: status.message ?? 'Unknown error',
          });
          break;
        default:
          break; // idle / checking / verifying / manual-download-required: no card
      }
    };
    if (updates?.onInstallerStatus) {
      cleanups.push(updates.onInstallerStatus(handleInstallerStatus));
      void updates
        .getInstallerStatus?.()
        .then(handleInstallerStatus)
        .catch(() => {});
    }
    if (updates?.onUpdateAvailable) {
      cleanups.push(
        updates.onUpdateAvailable((payload) => {
          store().notify({
            id: `update-available-${payload.version}`,
            category: 'update',
            title: `Update available - v${payload.version}`,
            status: 'complete',
            // useUpdateToast already shows the actionable toast; log-only here.
            toastDismissed: true,
          });
        }),
      );
    }

    // Bare-metal Metal/MLX lifecycle (no JSONL events exist on that path).
    if (mlx?.onStatusChanged) {
      cleanups.push(
        mlx.onStatusChanged((status) => {
          if (status === 'running') {
            store().notify({
              id: SERVER_START_ID,
              category: 'server',
              title: 'Server ready',
              status: 'complete',
              progress: 100,
            });
          } else if (status === 'error') {
            store().notify({
              id: SERVER_START_ID,
              category: 'server',
              title: 'Server failed to start',
              status: 'error',
              error: 'The MLX server process reported an error - check the Logs tab.',
            });
          }
        }),
      );
    }

    return () => cleanups.forEach((fn) => fn());
  }, []);
}
