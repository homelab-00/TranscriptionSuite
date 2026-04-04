/**
 * Global activity store — tracks download activity across the app.
 *
 * Consumers push events via addActivity/updateActivity. The floating
 * notification widget (ActivityNotifications) subscribes here.
 */

import { create } from 'zustand';

// ─── Types ───────────────────────────────────────────────────────────────────

export type ActivityStatus = 'active' | 'complete' | 'error' | 'dismissed';

/**
 * Legacy download types preserved for backward compatibility with existing
 * IPC events from the bootstrap log parser.
 */
export type LegacyDownloadType =
  | 'docker-image'
  | 'sidecar-image'
  | 'ml-model'
  | 'runtime-dep'
  | 'model-preload';

export interface ActivityItem {
  id: string;
  category: 'download';
  label: string;
  status: ActivityStatus;
  startedAt: number;
  completedAt?: number;
  durationMs?: number;

  // Download-specific
  progress?: number; // 0-100, undefined = indeterminate spinner
  totalSize?: string; // "2.1 GB"
  downloadedSize?: string; // "720 MB"
  detail?: string; // "12 / 47 packages"

  // Warning-specific
  severity?: 'warning' | 'error';
  persistent?: boolean;

  // Server-specific
  phase?: 'bootstrap' | 'lifespan' | 'ready';

  // Developer detail
  syncMode?: 'delta' | 'rebuild' | 'cache-hit';
  expandableDetail?: string;

  // UI state (frontend-only, not from server)
  dismissed: boolean;

  /** Legacy download type — preserved for icon/color mapping in UI */
  legacyType?: LegacyDownloadType;

  /** Error message */
  error?: string;
}

interface ActivityStore {
  items: ActivityItem[];

  // Core operations
  addActivity: (
    item: Partial<ActivityItem> & { id: string; category: 'download'; label: string },
  ) => void;
  updateActivity: (id: string, updates: Partial<ActivityItem>) => void;

  // UI operations
  dismissActivity: (id: string) => void;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function updateItem(
  items: readonly ActivityItem[],
  id: string,
  patch: Partial<ActivityItem>,
): ActivityItem[] {
  return items.map((item) => (item.id === id ? { ...item, ...patch } : item));
}

// ─── Store ───────────────────────────────────────────────────────────────────

export const useActivityStore = create<ActivityStore>((set) => ({
  items: [],

  addActivity: (item) =>
    set((state) => {
      const existing = state.items.find((i) => i.id === item.id);
      if (existing) {
        // Upsert: merge new fields into existing item
        return {
          items: updateItem(state.items, item.id, {
            ...item,
            // Preserve UI state unless explicitly overridden
            dismissed: item.dismissed ?? existing.dismissed,
            // Preserve startedAt from original item
            startedAt: existing.startedAt,
          }),
        };
      }
      return {
        items: [
          ...state.items,
          {
            status: 'active' as ActivityStatus,
            startedAt: Date.now(),
            dismissed: false,
            ...item,
          },
        ],
      };
    }),

  updateActivity: (id, updates) =>
    set((state) => ({
      items: updateItem(state.items, id, updates),
    })),

  dismissActivity: (id) =>
    set((state) => ({
      items: updateItem(state.items, id, { dismissed: true }),
    })),
}));

// ─── Selectors ───────────────────────────────────────────────────────────────

/** Active (non-dismissed) items for the floating notification widget. */
export const selectVisibleNotifications = (state: ActivityStore): ActivityItem[] =>
  state.items.filter((item) => !item.dismissed);

/** Items currently active (in-progress). */
export const selectActiveItems = (state: ActivityStore): ActivityItem[] =>
  state.items.filter((item) => item.status === 'active');

/** Whether any item is currently active. */
export const selectHasActiveItems = (state: ActivityStore): boolean =>
  state.items.some((item) => item.status === 'active');
