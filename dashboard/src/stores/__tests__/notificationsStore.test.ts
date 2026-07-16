import { describe, it, expect, beforeEach } from 'vitest';
import {
  useNotificationsStore,
  selectToastNotifications,
  MAX_NOTIFICATIONS,
  MAX_TRANSCRIPT_CHARS,
  type AppNotification,
} from '../notificationsStore';

function reset(): void {
  useNotificationsStore.setState({ notifications: [] });
}

function all(): AppNotification[] {
  return useNotificationsStore.getState().notifications;
}

describe('notificationsStore', () => {
  beforeEach(reset);

  it('adds a new notification with defaults', () => {
    useNotificationsStore
      .getState()
      .notify({ id: 'dl-1', category: 'download', title: 'Downloading X' });
    expect(all()).toHaveLength(1);
    const n = all()[0];
    expect(n.status).toBe('active');
    expect(n.toastDismissed).toBe(false);
    expect(n.createdAt).toBeGreaterThan(0);
    expect(n.entryId).toContain('dl-1');
  });

  it('merges updates into the newest entry with the same event id', () => {
    const store = useNotificationsStore.getState();
    store.notify({ id: 'dl-1', category: 'download', title: 'Downloading X', progress: 10 });
    store.notify({ id: 'dl-1', category: 'download', title: 'Downloading X', progress: 80 });
    expect(all()).toHaveLength(1);
    expect(all()[0].progress).toBe(80);
  });

  it('preserves createdAt and toastDismissed across merges', () => {
    const store = useNotificationsStore.getState();
    store.notify({ id: 'dl-1', category: 'download', title: 'Downloading X' });
    const created = all()[0].createdAt;
    store.dismissToast('dl-1');
    store.notify({ id: 'dl-1', category: 'download', title: 'Downloading X', progress: 50 });
    expect(all()[0].createdAt).toBe(created);
    expect(all()[0].toastDismissed).toBe(true);
  });

  it('stamps completedAt when status leaves active', () => {
    const store = useNotificationsStore.getState();
    store.notify({ id: 'dl-1', category: 'download', title: 'Downloading X' });
    expect(all()[0].completedAt).toBeUndefined();
    store.notify({ id: 'dl-1', category: 'download', title: 'Downloaded X', status: 'complete' });
    expect(all()[0].completedAt).toBeGreaterThan(0);
  });

  it('starts a NEW log entry when an event id is re-activated after completion', () => {
    const store = useNotificationsStore.getState();
    store.notify({ id: 'server-start', category: 'server', title: 'Starting server...' });
    store.notify({
      id: 'server-start',
      category: 'server',
      title: 'Server ready',
      status: 'complete',
    });
    store.notify({ id: 'server-start', category: 'server', title: 'Starting server...' });
    expect(all()).toHaveLength(2);
    expect(all()[0].status).toBe('complete');
    expect(all()[1].status).toBe('active');
    expect(all()[1].toastDismissed).toBe(false);
    expect(all()[0].entryId).not.toBe(all()[1].entryId);
  });

  it('dismissToast hides the toast but keeps the record, matching entryId or newest event id', () => {
    const store = useNotificationsStore.getState();
    store.notify({ id: 'dl-1', category: 'download', title: 'Downloading X' });
    store.dismissToast('dl-1');
    expect(all()).toHaveLength(1);
    expect(all()[0].toastDismissed).toBe(true);
    expect(selectToastNotifications(useNotificationsStore.getState())).toHaveLength(0);
    store.dismissToast(all()[0].entryId); // idempotent by entryId too
    expect(all()).toHaveLength(1);
  });

  it('exposes no way to remove a record', () => {
    const state = useNotificationsStore.getState() as unknown as Record<string, unknown>;
    const actions = Object.keys(state).filter((k) => typeof state[k] === 'function');
    expect(actions.sort()).toEqual(['dismissToast', 'hydrate', 'notify', 'updateNotification']);
  });

  it('updateNotification patches the newest entry and never creates one', () => {
    const store = useNotificationsStore.getState();
    store.updateNotification('ghost', { detail: 'nope' });
    expect(all()).toHaveLength(0);
    store.notify({ id: 'imp-1', category: 'import', title: 'Importing' });
    store.updateNotification('imp-1', { transcript: 'hello world' });
    expect(all()[0].transcript).toBe('hello world');
  });

  it('truncates oversized transcripts', () => {
    const store = useNotificationsStore.getState();
    store.notify({
      id: 't-1',
      category: 'transcription',
      title: 'Done',
      status: 'complete',
      transcript: 'x'.repeat(MAX_TRANSCRIPT_CHARS + 100),
    });
    expect(all()[0].transcript!.length).toBeLessThan(MAX_TRANSCRIPT_CHARS + 100);
    expect(all()[0].transcript).toContain('truncated');
  });

  it('caps the log, dropping the oldest non-active entries first', () => {
    const store = useNotificationsStore.getState();
    store.notify({ id: 'keep-active', category: 'download', title: 'Active one' });
    for (let i = 0; i < MAX_NOTIFICATIONS + 5; i += 1) {
      store.notify({ id: `n-${i}`, category: 'import', title: `Entry ${i}`, status: 'complete' });
    }
    expect(all().length).toBeLessThanOrEqual(MAX_NOTIFICATIONS);
    expect(all().some((n) => n.id === 'keep-active')).toBe(true);
  });

  it('hydrate merges persisted entries, mutes stale toasts, and skips duplicate entryIds', () => {
    const store = useNotificationsStore.getState();
    // A producer (e.g. the installer-status snapshot) may win the race and
    // write BEFORE the async load() resolves - hydrate must merge, not bail.
    store.notify({ id: 'live-1', category: 'update', title: 'Live entry' });
    const liveEntryId = all()[0].entryId;
    const items: AppNotification[] = [
      {
        entryId: 'a#1',
        id: 'a',
        category: 'download',
        title: 'Old download',
        status: 'complete',
        createdAt: 1,
        completedAt: 2,
        toastDismissed: false,
      },
      {
        entryId: 'b#1',
        id: 'b',
        category: 'server',
        title: 'Still starting',
        status: 'active',
        createdAt: 3,
        toastDismissed: false,
      },
      {
        entryId: liveEntryId,
        id: 'live-1',
        category: 'update',
        title: 'Duplicate',
        status: 'active',
        createdAt: 4,
        toastDismissed: false,
      },
    ];
    store.hydrate(items);
    expect(all()).toHaveLength(3); // 2 restored + 1 live; duplicate skipped
    expect(all().find((n) => n.id === 'a')!.toastDismissed).toBe(true);
    expect(all().find((n) => n.id === 'b')!.toastDismissed).toBe(false);
    expect(all().find((n) => n.id === 'live-1')!.title).toBe('Live entry');
  });
});
