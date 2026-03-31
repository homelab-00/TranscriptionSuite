/**
 * Global download store — tracks all download activity across the app.
 *
 * Components that trigger downloads push events here (addDownload, updateProgress, etc.),
 * and the UI (floating notifications + Downloads tab) subscribes to the store.
 *
 * Download types:
 * - docker-image: Main server Docker image pull
 * - sidecar-image: Vulkan whisper.cpp sidecar image pull
 * - ml-model: ML model download (alignment models, etc.)
 * - runtime-dep: Runtime dependency installation
 */

import { create } from 'zustand';

// ─── Types ───────────────────────────────────────────────────────────────────

export type DownloadType = 'docker-image' | 'sidecar-image' | 'ml-model' | 'runtime-dep';

export type DownloadStatus = 'queued' | 'downloading' | 'complete' | 'error' | 'cancelled';

export interface DownloadItem {
  id: string;
  type: DownloadType;
  label: string;
  status: DownloadStatus;
  /** 0–100, undefined = indeterminate progress */
  progress?: number;
  /** Human-readable size string (e.g. "1.2 GB") */
  size?: string;
  error?: string;
  startedAt: number;
  completedAt?: number;
  /** User has dismissed this notification from the floating widget */
  dismissed: boolean;
}

interface DownloadStore {
  items: DownloadItem[];

  /** Register a new download. Returns the item id for later updates. */
  addDownload: (id: string, type: DownloadType, label: string, size?: string) => void;

  /** Update progress (0–100). Automatically sets status to 'downloading'. */
  updateProgress: (id: string, progress: number) => void;

  /** Mark a download as complete. */
  completeDownload: (id: string) => void;

  /** Mark a download as failed with an error message. */
  failDownload: (id: string, error: string) => void;

  /** Mark a download as cancelled. */
  cancelDownload: (id: string) => void;

  /** Dismiss a single notification from the floating widget. */
  dismissDownload: (id: string) => void;

  /** Remove all completed/cancelled/error items from history. */
  clearHistory: () => void;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function updateItem(
  items: readonly DownloadItem[],
  id: string,
  patch: Partial<DownloadItem>,
): DownloadItem[] {
  return items.map((item) => (item.id === id ? { ...item, ...patch } : item));
}

// ─── Store ───────────────────────────────────────────────────────────────────

export const useDownloadStore = create<DownloadStore>((set) => ({
  items: [],

  addDownload: (id, type, label, size) =>
    set((state) => {
      // If an item with this id already exists, reset it
      const existing = state.items.find((i) => i.id === id);
      if (existing) {
        return {
          items: updateItem(state.items, id, {
            type,
            label,
            size,
            status: 'queued',
            progress: undefined,
            error: undefined,
            startedAt: Date.now(),
            completedAt: undefined,
            dismissed: false,
          }),
        };
      }
      return {
        items: [
          ...state.items,
          {
            id,
            type,
            label,
            size,
            status: 'queued',
            progress: undefined,
            error: undefined,
            startedAt: Date.now(),
            completedAt: undefined,
            dismissed: false,
          },
        ],
      };
    }),

  updateProgress: (id, progress) =>
    set((state) => ({
      items: updateItem(state.items, id, { status: 'downloading', progress }),
    })),

  completeDownload: (id) =>
    set((state) => ({
      items: updateItem(state.items, id, {
        status: 'complete',
        progress: 100,
        completedAt: Date.now(),
      }),
    })),

  failDownload: (id, error) =>
    set((state) => ({
      items: updateItem(state.items, id, {
        status: 'error',
        error,
        completedAt: Date.now(),
      }),
    })),

  cancelDownload: (id) =>
    set((state) => ({
      items: updateItem(state.items, id, {
        status: 'cancelled',
        completedAt: Date.now(),
      }),
    })),

  dismissDownload: (id) =>
    set((state) => ({
      items: updateItem(state.items, id, { dismissed: true }),
    })),

  clearHistory: () =>
    set((state) => ({
      items: state.items.filter(
        (item) => item.status === 'queued' || item.status === 'downloading',
      ),
    })),
}));

// ─── Selectors ───────────────────────────────────────────────────────────────

/** Active (non-dismissed) items for the floating notification widget. */
export const selectVisibleNotifications = (state: DownloadStore): DownloadItem[] =>
  state.items.filter((item) => !item.dismissed);

/** Items currently downloading or queued. */
export const selectActiveDownloads = (state: DownloadStore): DownloadItem[] =>
  state.items.filter((item) => item.status === 'queued' || item.status === 'downloading');

/** Whether any download is currently in progress. */
export const selectHasActiveDownloads = (state: DownloadStore): boolean =>
  state.items.some((item) => item.status === 'queued' || item.status === 'downloading');
