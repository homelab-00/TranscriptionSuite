/**
 * GH-318 - the renderer side of the download hub. Covers the rules the
 * issue cares about: a running download never produces a toast, the end of a
 * download leaves exactly one history row without progress fields, and only a
 * failure raises a toast.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { applyDownloadChange, useDownloadsBridge } from '../useDownloadsBridge';
import { useDownloadsStore } from '../../stores/downloadsStore';
import { useNotificationsStore, type AppNotification } from '../../stores/notificationsStore';
import { useAriaAnnouncerStore } from '../../stores/ariaAnnouncerStore';

function item(patch: Partial<DownloadItem>): DownloadItem {
  return {
    id: 'model-load-x',
    runId: 'model-load-x@1',
    kind: 'model',
    source: 'server',
    label: 'parakeet',
    status: 'active',
    cancellable: false,
    startedAt: 1_000,
    updatedAt: 1_000,
    errorToast: true,
    ...patch,
  };
}

const notifications = (): AppNotification[] => useNotificationsStore.getState().notifications;
const bar = (): DownloadItem[] => useDownloadsStore.getState().items;

beforeEach(() => {
  vi.useFakeTimers();
  useDownloadsStore.setState({ items: [] });
  useNotificationsStore.setState({ notifications: [] });
  useAriaAnnouncerStore.setState({ politeMessage: '', assertiveMessage: '' });
});

afterEach(() => {
  vi.useRealTimers();
  delete (window as { electronAPI?: unknown }).electronAPI;
});

describe('applyDownloadChange', () => {
  it('shows a running download in the bar without any notification', () => {
    applyDownloadChange({ type: 'upsert', item: item({ bytesDone: 1, bytesTotal: 10 }) }, false);

    expect(bar()).toHaveLength(1);
    expect(notifications()).toHaveLength(0);
  });

  it('writes one muted history row without progress fields when a download completes', () => {
    applyDownloadChange({ type: 'upsert', item: item({}) }, false);
    applyDownloadChange(
      {
        type: 'upsert',
        item: item({
          status: 'complete',
          bytesDone: 1024 ** 3,
          bytesTotal: 1024 ** 3,
          updatedAt: 131_000,
          endedAt: 131_000,
        }),
      },
      false,
    );

    expect(notifications()).toHaveLength(1);
    const row = notifications()[0];
    expect(row).toMatchObject({
      category: 'download',
      title: 'parakeet downloaded',
      detail: '1.0 GB in 2m 10s',
      status: 'complete',
      toastDismissed: true,
    });
    expect(row.progress).toBeUndefined();
  });

  it('does not duplicate the history row when the terminal event is delivered twice', () => {
    const done = item({ status: 'complete', updatedAt: 5_000, endedAt: 5_000 });
    applyDownloadChange({ type: 'upsert', item: done }, false);
    applyDownloadChange({ type: 'upsert', item: done }, false);
    applyDownloadChange({ type: 'upsert', item: done }, true);

    expect(notifications()).toHaveLength(1);
  });

  it('raises a toast and keeps the item in the bar when a download fails', () => {
    applyDownloadChange(
      {
        type: 'upsert',
        item: item({ status: 'error', error: 'network down', updatedAt: 2_000, endedAt: 2_000 }),
      },
      false,
    );

    expect(notifications()[0]).toMatchObject({
      title: 'parakeet download failed',
      status: 'error',
      error: 'network down',
      toastDismissed: false,
    });
    expect(bar()).toHaveLength(1);
  });

  it('stays silent on failure when the source raises its own toast', () => {
    applyDownloadChange(
      {
        type: 'upsert',
        item: item({ status: 'error', error: 'x', errorToast: false, updatedAt: 2_000 }),
      },
      false,
    );

    expect(notifications()[0].toastDismissed).toBe(true);
  });

  it('records a cancelled download as a muted row and clears it from the bar', () => {
    applyDownloadChange({ type: 'upsert', item: item({}) }, false);
    applyDownloadChange(
      {
        type: 'upsert',
        item: item({ status: 'cancelled', detail: 'Cancelled by user', updatedAt: 2_000 }),
      },
      false,
    );

    expect(notifications()[0]).toMatchObject({
      title: 'parakeet download cancelled',
      detail: 'Cancelled by user',
      status: 'complete',
      toastDismissed: true,
    });
    expect(bar()).toHaveLength(0);
  });

  it('lets a completed item linger for two seconds before leaving the bar', () => {
    applyDownloadChange({ type: 'upsert', item: item({}) }, false);
    applyDownloadChange(
      { type: 'upsert', item: item({ status: 'complete', updatedAt: 2_000 }) },
      false,
    );
    expect(bar()).toHaveLength(1);

    vi.advanceTimersByTime(2_000);
    expect(bar()).toHaveLength(0);
  });

  it('mutes the toast and skips the bar linger for a replayed terminal item', () => {
    applyDownloadChange(
      { type: 'upsert', item: item({ status: 'error', error: 'x', updatedAt: 2_000 }) },
      true,
    );
    applyDownloadChange(
      {
        type: 'upsert',
        item: item({ id: 'b', runId: 'b@1', status: 'complete', updatedAt: 2_000 }),
      },
      true,
    );

    expect(notifications().every((n) => n.toastDismissed)).toBe(true);
    // The failure is still visible in the bar; the finished one is not.
    expect(bar().map((i) => i.runId)).toEqual(['model-load-x@1']);
  });

  it('removes a discarded item without a history row', () => {
    applyDownloadChange({ type: 'upsert', item: item({}) }, false);
    applyDownloadChange({ type: 'remove', runId: 'model-load-x@1' }, false);

    expect(bar()).toHaveLength(0);
    expect(notifications()).toHaveLength(0);
  });

  it('announces start and completion politely and a failure assertively', () => {
    applyDownloadChange({ type: 'upsert', item: item({}) }, false);
    expect(useAriaAnnouncerStore.getState().politeMessage).toBe('Downloading parakeet');

    applyDownloadChange({ type: 'upsert', item: item({ updatedAt: 1_500, bytesDone: 5 }) }, false);
    expect(useAriaAnnouncerStore.getState().politeMessage).toBe('Downloading parakeet');

    applyDownloadChange(
      { type: 'upsert', item: item({ status: 'error', error: 'x', updatedAt: 2_000 }) },
      false,
    );
    expect(useAriaAnnouncerStore.getState().assertiveMessage).toBe('parakeet download failed');
  });
});

describe('useDownloadsBridge', () => {
  it('hydrates from the snapshot and then follows live changes', async () => {
    let listener: ((change: DownloadChange) => void) | null = null;
    const unsubscribe = vi.fn();
    (window as { electronAPI?: unknown }).electronAPI = {
      downloads: {
        getSnapshot: vi.fn(async () => [item({ bytesDone: 3, bytesTotal: 9 })]),
        cancel: vi.fn(),
        onChanged: (cb: (change: DownloadChange) => void) => {
          listener = cb;
          return unsubscribe;
        },
      },
    };

    const { unmount } = renderHook(() => useDownloadsBridge());
    await act(async () => {
      for (let i = 0; i < 3; i += 1) await Promise.resolve();
    });
    expect(bar()[0].bytesDone).toBe(3);

    act(() => {
      listener?.({ type: 'upsert', item: item({ bytesDone: 6, bytesTotal: 9, updatedAt: 3_000 }) });
    });
    expect(bar()[0].bytesDone).toBe(6);

    unmount();
    expect(unsubscribe).toHaveBeenCalledTimes(1);
  });

  it('does nothing outside Electron', () => {
    expect(() => renderHook(() => useDownloadsBridge())).not.toThrow();
  });
});
