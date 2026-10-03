/**
 * useNotificationBridge - the single renderer-side event funnel for the
 * session notifications store. Successor to the legacy bootstrap-downloads
 * bridge.
 *
 * Responsibilities:
 *  1. Hydrate the store from the semi-persistent session file, then persist
 *     changes back (debounced) so a renderer reload keeps the session log.
 *  2. Subscribe to every notification-relevant IPC channel:
 *     activity:event, updates:updateAvailable, mlx:statusChanged.
 *
 * Downloads are not handled here (GH-318): live download progress belongs to
 * the download bar, and useDownloadsBridge writes the single history row a
 * download leaves behind when it ends.
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

    // startup-events.jsonl stream (server stages and warnings).
    if (docker?.onActivityEvent) {
      cleanups.push(
        docker.onActivityEvent((event) => {
          const entry = mapStartupEvent(event);
          if (entry) store().notify(entry);
          const aggregate = serverStartPatch(event);
          if (aggregate) store().notify(aggregate);
        }),
      );
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
              // Clear any lingering active-phase stage label.
              detail: '',
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
