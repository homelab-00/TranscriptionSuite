/**
 * Downloads store - the live state behind the universal download bar
 * (GH-318).
 *
 * Deliberately separate from the notifications store: that one is an
 * append-only history log that persists on every change, while this holds
 * only what the bar shows right now (running downloads, a just-finished one
 * for a moment, and failures until dismissed). The main-process DownloadHub
 * is the source of truth; useDownloadsBridge feeds this store from it.
 */

import { create } from 'zustand';

interface DownloadsStore {
  /** Visible items, ordered by start time. */
  items: DownloadItem[];
  /** Insert or replace by runId. Stale updates and cancelled items are dropped. */
  upsert: (item: DownloadItem) => void;
  remove: (runId: string) => void;
  /** User dismissal of a failed (or lingering finished) item. */
  dismiss: (runId: string) => void;
}

function withoutRun(items: DownloadItem[], runId: string): DownloadItem[] {
  return items.some((i) => i.runId === runId) ? items.filter((i) => i.runId !== runId) : items;
}

export const useDownloadsStore = create<DownloadsStore>((set) => ({
  items: [],

  upsert: (item) =>
    set((state) => {
      if (item.status === 'cancelled') return { items: withoutRun(state.items, item.runId) };

      const existing = state.items.find((i) => i.runId === item.runId);
      // A reload snapshot can arrive after a newer live update for the same run.
      if (existing && existing.updatedAt > item.updatedAt) return state;

      // A late event for an older run must not evict the run that replaced it.
      const superseded = state.items.some(
        (i) => i.id === item.id && i.runId !== item.runId && i.startedAt > item.startedAt,
      );
      if (superseded) return state;

      // A new run of the same source supersedes its older failed/finished run.
      const rest = state.items.filter((i) => i.runId !== item.runId && i.id !== item.id);
      return { items: [...rest, item].sort((a, b) => a.startedAt - b.startedAt) };
    }),

  remove: (runId) => set((state) => ({ items: withoutRun(state.items, runId) })),

  dismiss: (runId) => set((state) => ({ items: withoutRun(state.items, runId) })),
}));
