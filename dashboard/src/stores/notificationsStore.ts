/**
 * Session notifications store - the app-wide notification log.
 *
 * Every tracked action (downloads, server lifecycle, recordings, imports,
 * notebook notes, transcription completions) is recorded here for the
 * lifetime of the app session. Producers address notifications by a stable
 * event `id`; the store keeps a unique `entryId` per log row so a re-fired
 * event (e.g. a second server start) opens a NEW row instead of overwriting
 * history. Toasts are dismissable (`toastDismissed`), records are not:
 * there is deliberately no remove/delete action in this store.
 *
 * Semi-persistence (file-backed, cleared on app quit) is wired in
 * useNotificationBridge via the notificationLog IPC surface.
 */

import { create } from 'zustand';

// --- Types -------------------------------------------------------------------

export type NotificationCategory =
  | 'download'
  | 'server'
  | 'update'
  | 'recording'
  | 'import'
  | 'note'
  | 'transcription';

export type NotificationStatus = 'active' | 'complete' | 'error';

export interface AppNotification {
  /** Unique log-entry key (React key + persistence identity). */
  entryId: string;
  /** Caller-supplied event key; updates target the newest entry with this id. */
  id: string;
  category: NotificationCategory;
  title: string;
  /** Secondary explanatory line (stage label, filename, hint). */
  detail?: string;
  status: NotificationStatus;
  createdAt: number;
  completedAt?: number;
  /** 0-100; undefined while active renders an indeterminate bar. */
  progress?: number;
  downloadedSize?: string;
  totalSize?: string;
  severity?: 'warning' | 'error';
  error?: string;
  /** Full transcript text for transcription records (collapsible in the view). */
  transcript?: string;
  /** Hides the floating toast only - the record always stays in the log. */
  toastDismissed: boolean;
}

export type NotifyInput = Partial<AppNotification> & {
  id: string;
  category: NotificationCategory;
  title: string;
};

interface NotificationsStore {
  notifications: AppNotification[];
  /** Upsert by event id: merges into the newest matching entry, or opens a new log row. */
  notify: (item: NotifyInput) => void;
  /** Patch the newest entry with this event id; no-op if none exists. */
  updateNotification: (id: string, patch: Partial<AppNotification>) => void;
  /** Hide the toast for an entryId (exact) or event id (newest match). Never removes. */
  dismissToast: (key: string) => void;
  /** Merge persisted entries in (renderer reload recovery); duplicate entryIds are skipped. */
  hydrate: (items: AppNotification[]) => void;
}

export const MAX_NOTIFICATIONS = 500;
export const MAX_TRANSCRIPT_CHARS = 200_000;

// --- Helpers -----------------------------------------------------------------

let entrySeq = 0;

function nextEntryId(id: string): string {
  entrySeq += 1;
  return `${id}#${Date.now().toString(36)}-${entrySeq}`;
}

function findNewest(items: readonly AppNotification[], id: string): AppNotification | undefined {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    if (items[i].id === id) return items[i];
  }
  return undefined;
}

/** Drop explicitly-undefined keys so callers cannot clobber defaults or merged state. */
function stripUndefined<T extends object>(obj: T): Partial<T> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v !== undefined) out[k] = v;
  }
  return out as Partial<T>;
}

/** Truncate huge transcripts and stamp completedAt on terminal states. */
function finalize(n: AppNotification): AppNotification {
  const transcript =
    n.transcript !== undefined && n.transcript.length > MAX_TRANSCRIPT_CHARS
      ? `${n.transcript.slice(0, MAX_TRANSCRIPT_CHARS)}\n... [truncated - the full text is saved with the recording]`
      : n.transcript;
  const completedAt =
    n.status !== 'active' && n.completedAt === undefined ? Date.now() : n.completedAt;
  return { ...n, transcript, completedAt };
}

/** Enforce the log cap, dropping the oldest non-active entries first. */
function capLog(items: AppNotification[]): AppNotification[] {
  if (items.length <= MAX_NOTIFICATIONS) return items;
  const overflow = items.length - MAX_NOTIFICATIONS;
  const removable = new Set(
    items
      .filter((n) => n.status !== 'active')
      .slice(0, overflow)
      .map((n) => n.entryId),
  );
  return items.filter((n) => !removable.has(n.entryId));
}

// --- Store -------------------------------------------------------------------

export const useNotificationsStore = create<NotificationsStore>((set) => ({
  notifications: [],

  notify: (item) =>
    set((state) => {
      const existing = findNewest(state.notifications, item.id);
      const incomingStatus = item.status ?? 'active';
      const isReactivation =
        existing !== undefined && existing.status !== 'active' && incomingStatus === 'active';

      if (existing && !isReactivation) {
        const cleanItem = stripUndefined(item);
        return {
          notifications: state.notifications.map((n) =>
            n.entryId !== existing.entryId
              ? n
              : finalize({
                  ...n,
                  ...cleanItem,
                  entryId: n.entryId,
                  createdAt: n.createdAt,
                  toastDismissed: item.toastDismissed ?? n.toastDismissed,
                }),
          ),
        };
      }

      const entry = finalize({
        status: 'active',
        createdAt: Date.now(),
        toastDismissed: false,
        ...stripUndefined(item),
        entryId: nextEntryId(item.id),
      } as AppNotification);
      return { notifications: capLog([...state.notifications, entry]) };
    }),

  updateNotification: (id, patch) =>
    set((state) => {
      const target = findNewest(state.notifications, id);
      if (!target) return state;
      const cleanPatch = stripUndefined(patch);
      return {
        notifications: state.notifications.map((n) =>
          n.entryId !== target.entryId
            ? n
            : finalize({
                ...n,
                ...cleanPatch,
                entryId: n.entryId,
                id: n.id,
                createdAt: n.createdAt,
              }),
        ),
      };
    }),

  dismissToast: (key) =>
    set((state) => {
      const target =
        state.notifications.find((n) => n.entryId === key) ?? findNewest(state.notifications, key);
      if (!target) return state;
      return {
        notifications: state.notifications.map((n) =>
          n.entryId === target.entryId ? { ...n, toastDismissed: true } : n,
        ),
      };
    }),

  hydrate: (items) =>
    set((state) => {
      // Merge, do not bail: an async producer (e.g. the installer-status
      // snapshot in the bridge) can write before load() resolves, and the
      // persisted session log must survive that race. Persisted entries are
      // older, so they go first. Non-active entries had their toast moment
      // in the previous renderer life - mute them so a reload does not
      // replay a toast flood.
      const existingEntryIds = new Set(state.notifications.map((n) => n.entryId));
      const restored = items
        .filter((n) => !existingEntryIds.has(n.entryId))
        .map((n) => (n.status === 'active' ? n : { ...n, toastDismissed: true }));
      if (restored.length === 0) return state;
      return { notifications: [...restored, ...state.notifications] };
    }),
}));

// --- Selectors ---------------------------------------------------------------

/** Everything, insertion order (the view sorts newest-first itself). */
export const selectAllNotifications = (state: NotificationsStore): AppNotification[] =>
  state.notifications;

/** Items whose floating toast has not been dismissed. */
export const selectToastNotifications = (state: NotificationsStore): AppNotification[] =>
  state.notifications.filter((n) => !n.toastDismissed);
