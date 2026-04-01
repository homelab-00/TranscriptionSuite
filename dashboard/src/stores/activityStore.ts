/**
 * Global activity store — tracks all activity across the app.
 *
 * Replaces the former downloadStore with a unified 4-category model:
 * download, server, warning, info.
 *
 * Components that produce activity push events here (addActivity, updateActivity, etc.),
 * and the UI (floating notifications + Activity panel) subscribes to the store.
 */

import { create } from 'zustand';

// ─── Types ───────────────────────────────────────────────────────────────────

export type ActivityCategory = 'download' | 'server' | 'warning' | 'info';
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
  category: ActivityCategory;
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
  dismissed: boolean; // User dismissed from floating widget
  sessionId: string; // Groups items by server start

  /** Legacy download type — preserved for icon/color mapping in UI */
  legacyType?: LegacyDownloadType;

  /** Error message */
  error?: string;
}

interface ActivityStore {
  items: ActivityItem[];
  sessionId: string;

  // Core operations
  addActivity: (
    item: Partial<ActivityItem> & { id: string; category: ActivityCategory; label: string },
  ) => void;
  updateActivity: (id: string, updates: Partial<ActivityItem>) => void;

  // UI operations
  dismissActivity: (id: string) => void;
  clearSession: (sessionId: string) => void;
  clearAll: () => void;

  // Settings
  notificationPreferences: Record<ActivityCategory, boolean>;
  setNotificationPreference: (category: ActivityCategory, enabled: boolean) => void;

  // Session management
  setSessionId: (sessionId: string) => void;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function updateItem(
  items: readonly ActivityItem[],
  id: string,
  patch: Partial<ActivityItem>,
): ActivityItem[] {
  return items.map((item) => (item.id === id ? { ...item, ...patch } : item));
}

const DEFAULT_PREFERENCES: Record<ActivityCategory, boolean> = {
  download: true,
  server: true,
  warning: true,
  info: true,
};

function loadPreferences(): Record<ActivityCategory, boolean> {
  try {
    const stored = localStorage.getItem('activity-notification-preferences');
    if (stored) return { ...DEFAULT_PREFERENCES, ...JSON.parse(stored) };
  } catch {
    // Ignore parse errors
  }
  return { ...DEFAULT_PREFERENCES };
}

function savePreferences(prefs: Record<ActivityCategory, boolean>): void {
  try {
    localStorage.setItem('activity-notification-preferences', JSON.stringify(prefs));
  } catch {
    // Ignore storage errors
  }
}

// ─── Store ───────────────────────────────────────────────────────────────────

export const useActivityStore = create<ActivityStore>((set) => ({
  items: [],
  sessionId: `session-${Date.now()}`,
  notificationPreferences: loadPreferences(),

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
            sessionId: item.sessionId ?? existing.sessionId,
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
            sessionId: state.sessionId,
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

  clearSession: (sessionId) =>
    set((state) => ({
      items: state.items.filter((item) => item.sessionId !== sessionId),
    })),

  clearAll: () =>
    set((state) => ({
      items: state.items.filter((item) => item.status === 'active'),
    })),

  setNotificationPreference: (category, enabled) =>
    set((state) => {
      const updated = { ...state.notificationPreferences, [category]: enabled };
      savePreferences(updated);
      return { notificationPreferences: updated };
    }),

  setSessionId: (sessionId) => set({ sessionId }),
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
