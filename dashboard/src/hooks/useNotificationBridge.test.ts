/**
 * useNotificationBridge — IPC-to-notifications-store bridge (GH-207).
 *
 * Covers the docker:downloadEvent start/complete path, the activity:event
 * model-load progress path, the server-ready aggregate completion, and the
 * legacy-card dedupe (a granular `model-load-*` event dismisses the coarse
 * `model-preload` toast while keeping its record).
 */

import { renderHook } from '@testing-library/react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { useNotificationBridge } from './useNotificationBridge';
import { useNotificationsStore, type AppNotification } from '../stores/notificationsStore';

type Callback = (event: Record<string, unknown>) => void;

let downloadEventCallback: Callback | null = null;
let activityEventCallback: Callback | null = null;

/** Newest log entry addressed by its producer event id. */
function newest(id: string): AppNotification | undefined {
  const items = useNotificationsStore.getState().notifications;
  for (let i = items.length - 1; i >= 0; i -= 1) {
    if (items[i].id === id) return items[i];
  }
  return undefined;
}

beforeEach(() => {
  useNotificationsStore.setState({ notifications: [] });
  downloadEventCallback = null;
  activityEventCallback = null;
  // updates / mlx / notificationLog are intentionally absent: the hook
  // optional-chains each, so leaving them off exercises the no-op branches.
  (window as unknown as { electronAPI: unknown }).electronAPI = {
    docker: {
      onDownloadEvent: (cb: Callback) => {
        downloadEventCallback = cb;
        return vi.fn();
      },
      onActivityEvent: (cb: Callback) => {
        activityEventCallback = cb;
        return vi.fn();
      },
    },
  };
});

afterEach(() => {
  delete (window as unknown as { electronAPI?: unknown }).electronAPI;
});

describe('useNotificationBridge (GH-207)', () => {
  it('records a docker download from start to completion', () => {
    renderHook(() => useNotificationBridge());

    downloadEventCallback!({
      action: 'start',
      id: 'docker-image-latest',
      label: 'Server Image (latest)',
    });
    expect(newest('docker-image-latest')?.title).toBe('Server Image (latest)');
    expect(newest('docker-image-latest')?.status).toBe('active');

    downloadEventCallback!({
      action: 'complete',
      id: 'docker-image-latest',
      label: 'Server Image (latest) downloaded',
    });
    const done = newest('docker-image-latest');
    expect(done?.status).toBe('complete');
    expect(done?.title).toBe('Server Image (latest) downloaded');
  });

  it('records model-load progress from an activity:event', () => {
    renderHook(() => useNotificationBridge());

    activityEventCallback!({
      id: 'model-load-parakeet',
      category: 'download',
      label: 'Downloading parakeet-tdt-0.6b-v2...',
      status: 'active',
      progress: 10,
    });

    const item = newest('model-load-parakeet');
    expect(item).toBeDefined();
    expect(item!.title).toBe('Downloading parakeet-tdt-0.6b-v2...');
    expect(item!.progress).toBe(10);
    expect(item!.entryId).toBeTruthy();
  });

  it('completes the server-start aggregate when a server-ready event arrives', () => {
    renderHook(() => useNotificationBridge());

    // A coarse stage event opens the aggregate card in the active state.
    activityEventCallback!({
      id: 'bootstrap-env',
      category: 'server',
      label: 'Preparing environment',
      status: 'active',
    });
    expect(newest('server-start')?.status).toBe('active');

    activityEventCallback!({
      id: 'server-ready',
      category: 'server',
      label: 'Server ready',
      status: 'complete',
    });

    const aggregate = newest('server-start');
    expect(aggregate?.status).toBe('complete');
    expect(aggregate?.progress).toBe(100);
  });

  it('dismisses the model-preload toast when a granular model-load-* event arrives, keeping the record', () => {
    renderHook(() => useNotificationBridge());

    useNotificationsStore.getState().notify({
      id: 'model-preload',
      category: 'download',
      title: 'Loading Model',
      status: 'active',
    });
    expect(newest('model-preload')?.toastDismissed).toBe(false);

    activityEventCallback!({
      id: 'model-load-x',
      category: 'download',
      label: 'Downloading x...',
      status: 'active',
    });

    const preload = newest('model-preload');
    expect(preload).toBeDefined();
    expect(preload!.toastDismissed).toBe(true);
    expect(newest('model-load-x')?.title).toBe('Downloading x...');
  });
});
