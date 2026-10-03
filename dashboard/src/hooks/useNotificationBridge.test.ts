/**
 * useNotificationBridge — IPC-to-notifications-store bridge (GH-207).
 *
 * Covers the server-start aggregate card and startup warnings. Downloads are
 * deliberately absent: since GH-318 they belong to the download bar
 * (useDownloadsBridge) and must not reach the notifications store while
 * they run.
 */

import { renderHook } from '@testing-library/react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { useNotificationBridge } from './useNotificationBridge';
import { useNotificationsStore, type AppNotification } from '../stores/notificationsStore';

type Callback = (event: Record<string, unknown>) => void;

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
  activityEventCallback = null;
  // updates / mlx / notificationLog are intentionally absent: the hook
  // optional-chains each, so leaving them off exercises the no-op branches.
  (window as unknown as { electronAPI: unknown }).electronAPI = {
    docker: {
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
  it('leaves download events to the download bar - no notification while one runs', () => {
    renderHook(() => useNotificationBridge());

    activityEventCallback!({
      id: 'model-load-parakeet',
      category: 'download',
      label: 'Downloading parakeet-tdt-0.6b-v2...',
      status: 'active',
      progress: 10,
    });

    expect(newest('model-load-parakeet')).toBeUndefined();
  });

  it('records a startup warning from an activity:event', () => {
    renderHook(() => useNotificationBridge());

    activityEventCallback!({
      id: 'warn-nemo',
      category: 'warning',
      label: 'NeMo backend unavailable',
      severity: 'warning',
    });

    expect(newest('warn-nemo')).toMatchObject({ category: 'server', severity: 'warning' });
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

  it('ignores installer status - the app update download belongs to the download bar', () => {
    let installerCb: ((status: Record<string, unknown>) => void) | null = null;
    (window as unknown as { electronAPI: unknown }).electronAPI = {
      docker: { onActivityEvent: () => vi.fn() },
      updates: {
        onInstallerStatus: (cb: (status: Record<string, unknown>) => void) => {
          installerCb = cb;
          return vi.fn();
        },
        getInstallerStatus: vi.fn().mockResolvedValue({ state: 'idle' }),
      },
    };
    renderHook(() => useNotificationBridge());

    (installerCb as ((status: Record<string, unknown>) => void) | null)?.({
      state: 'downloading',
      version: '9.9.9',
      percent: 42,
    });

    expect(useNotificationsStore.getState().notifications).toHaveLength(0);
  });

  it('completes the server-start aggregate when MLX reports running', () => {
    let mlxCb: ((status: string) => void) | null = null;
    (window as unknown as { electronAPI: unknown }).electronAPI = {
      docker: {
        onActivityEvent: () => vi.fn(),
      },
      mlx: {
        onStatusChanged: (cb: (status: string) => void) => {
          mlxCb = cb;
          return vi.fn();
        },
      },
    };
    renderHook(() => useNotificationBridge());

    mlxCb!('running');

    const aggregate = newest('server-start');
    expect(aggregate?.status).toBe('complete');
    expect(aggregate?.title).toBe('Server ready');
  });
});
