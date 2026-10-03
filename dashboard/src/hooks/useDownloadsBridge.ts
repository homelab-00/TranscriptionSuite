/**
 * useDownloadsBridge - feeds the universal download bar (GH-318) from the
 * main-process DownloadHub.
 *
 * Responsibilities:
 *  1. Mirror hub changes into the downloads store (the bar's live state),
 *     starting from a snapshot so a renderer reload mid-download recovers.
 *  2. On the terminal transition of a download, write exactly one history
 *     row into the notifications store - no progress fields, and a toast
 *     only for a failure the source does not already toast itself.
 *
 * While a download runs it never touches the notifications store: the bar is
 * the only place live download progress is shown.
 *
 * Must be mounted exactly once at the app root (App.tsx).
 */

import { useEffect } from 'react';
import { useDownloadsStore } from '../stores/downloadsStore';
import { useNotificationsStore } from '../stores/notificationsStore';
import { useAriaAnnouncerStore } from '../stores/ariaAnnouncerStore';
import { formatBytes, formatDuration } from '../utils/downloadProgress';

/** How long a finished download stays in the bar as confirmation. */
const COMPLETE_LINGER_MS = 2_000;

function historyTitle(item: DownloadItem): string {
  if (item.status === 'error') return `${item.label} download failed`;
  if (item.status === 'cancelled') return `${item.label} download cancelled`;
  return `${item.label} downloaded`;
}

/** "2.6 GB in 3m 12s" - whichever parts are known. */
function completionDetail(item: DownloadItem): string | undefined {
  const bytes = item.bytesTotal ?? item.bytesDone;
  const size = bytes !== undefined && bytes > 0 ? formatBytes(bytes) : undefined;
  const elapsedSeconds =
    item.endedAt !== undefined ? Math.round((item.endedAt - item.startedAt) / 1000) : 0;
  const duration = elapsedSeconds > 0 ? formatDuration(elapsedSeconds) : undefined;
  if (size && duration) return `${size} in ${duration}`;
  return size ?? duration;
}

/**
 * Write the history row for an ended download - once. The entryId is derived
 * from the run, so a re-delivered terminal event or a reload snapshot finds
 * the existing row instead of adding a second one.
 */
function recordHistory(item: DownloadItem, replay: boolean): void {
  const entryId = `download:${item.runId}`;
  const store = useNotificationsStore.getState();
  if (store.notifications.some((n) => n.entryId === entryId)) return;

  const failed = item.status === 'error';
  const detail = item.status === 'cancelled' ? item.detail || 'Cancelled' : completionDetail(item);
  store.notify({
    entryId,
    id: entryId,
    category: 'download',
    title: historyTitle(item),
    ...(detail && !failed ? { detail } : {}),
    status: failed ? 'error' : 'complete',
    ...(failed ? { error: item.error ?? 'Download failed' } : {}),
    // Only a live failure toasts. A replayed one had its moment before the
    // reload, and the bar still shows it until dismissed.
    toastDismissed: replay || !(failed && item.errorToast),
  });
}

/**
 * Apply one hub change. `replay` marks items coming from the mount-time
 * snapshot rather than a live transition.
 */
export function applyDownloadChange(change: DownloadChange, replay: boolean): void {
  const downloads = useDownloadsStore.getState();
  if (change.type === 'remove') {
    downloads.remove(change.runId);
    return;
  }

  const { item } = change;
  const isNewRun = !downloads.items.some((i) => i.runId === item.runId);

  if (item.status === 'active') {
    downloads.upsert(item);
    if (isNewRun && !replay) {
      useAriaAnnouncerStore.getState().announce(`Downloading ${item.label}`, 'polite');
    }
    return;
  }

  const alreadyRecorded = useNotificationsStore
    .getState()
    .notifications.some((n) => n.entryId === `download:${item.runId}`);
  recordHistory(item, replay);

  if (item.status === 'complete') {
    // A finished download seen only through the snapshot never showed in this
    // renderer life - no point flashing a "done" confirmation for it.
    if (replay) return;
    downloads.upsert(item);
    setTimeout(() => useDownloadsStore.getState().dismiss(item.runId), COMPLETE_LINGER_MS);
  } else {
    downloads.upsert(item); // error stays until dismissed; cancelled is dropped by the store
  }

  if (!replay && !alreadyRecorded) {
    const announcer = useAriaAnnouncerStore.getState();
    if (item.status === 'error') announcer.announce(historyTitle(item), 'assertive');
    else if (item.status === 'complete') announcer.announce(historyTitle(item), 'polite');
  }
}

export function useDownloadsBridge(): void {
  useEffect(() => {
    const api = window.electronAPI?.downloads;
    if (!api) return;

    let cancelled = false;
    const unsubscribe = api.onChanged((change) => applyDownloadChange(change, false));
    // downloads:changed is broadcast-only with no replay, so fetch the
    // current state once. The store ignores anything older than what a live
    // event already delivered.
    void api
      .getSnapshot()
      .then((items) => {
        if (cancelled) return;
        for (const item of items) applyDownloadChange({ type: 'upsert', item }, true);
      })
      .catch(() => {});

    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);
}
