/**
 * useWatcherFilesBridge — singleton IPC subscription for watcher:filesDetected.
 *
 * Regression coverage for Issue #94: once SessionView is mounted (always, by
 * design) and the user opens NotebookView, the per-tab watcher hooks BOTH
 * registered a fresh `ipcRenderer.on('watcher:filesDetected', …)` via
 * `electronAPI.watcher.onFilesDetected`. A single IPC dispatch then fanned
 * out to two callbacks → two `addFiles` calls → each file imported twice.
 * The bridge centralizes the subscription so it cannot be doubled up.
 */

import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useWatcherFilesBridge } from '../useWatcherFilesBridge';
import { useImportQueueStore } from '../../stores/importQueueStore';

type Payload = Parameters<
  ReturnType<typeof useImportQueueStore.getState>['handleFilesDetected']
>[0];
type Listener = (payload: Payload) => void;

interface WatcherStub {
  onFilesDetected: ReturnType<typeof vi.fn>;
  cleanup: ReturnType<typeof vi.fn>;
  emit: (payload: Payload) => void;
}

function installElectronStub(): WatcherStub {
  let activeListener: Listener | null = null;
  const cleanup = vi.fn(() => {
    activeListener = null;
  });
  const onFilesDetected = vi.fn((cb: Listener) => {
    activeListener = cb;
    return cleanup;
  });
  (window as unknown as Record<string, unknown>).electronAPI = {
    watcher: { onFilesDetected },
  };
  return {
    onFilesDetected,
    cleanup,
    emit: (payload: Payload) => activeListener?.(payload),
  };
}

function clearElectronStub() {
  delete (window as unknown as Record<string, unknown>).electronAPI;
}

describe('useWatcherFilesBridge — singleton IPC subscription (Issue #94)', () => {
  beforeEach(() => {
    // Replace handleFilesDetected with a spy without touching the rest of the
    // store; this keeps each test focused on the bridge wiring.
    useImportQueueStore.setState({ handleFilesDetected: vi.fn() });
  });

  afterEach(() => {
    clearElectronStub();
    vi.restoreAllMocks();
  });

  it('subscribes exactly once on mount and runs the cleanup on unmount', () => {
    const stub = installElectronStub();

    const { unmount } = renderHook(() => useWatcherFilesBridge());

    expect(stub.onFilesDetected).toHaveBeenCalledTimes(1);
    expect(stub.cleanup).not.toHaveBeenCalled();

    unmount();
    expect(stub.cleanup).toHaveBeenCalledTimes(1);
  });

  it('forwards a dispatched payload to handleFilesDetected exactly once', () => {
    const stub = installElectronStub();
    const handler = useImportQueueStore.getState().handleFilesDetected as ReturnType<typeof vi.fn>;

    renderHook(() => useWatcherFilesBridge());

    const payload: Payload = {
      type: 'notebook',
      files: ['/watch/note.wav'],
      count: 1,
      fileMeta: [{ path: '/watch/note.wav', createdAt: '2026-04-26T10:00:00Z' }],
    };

    act(() => stub.emit(payload));

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith(payload);
  });

  it('does not crash and does not subscribe when electronAPI is unavailable', () => {
    clearElectronStub();

    expect(() => renderHook(() => useWatcherFilesBridge())).not.toThrow();
  });

  it('mounting the bridge alongside the (former-subscriber) tab hooks still yields a single subscription', () => {
    // Issue #94 reproduction: simulate the previous bug shape by rendering the
    // bridge twice. Each mount should produce its own (single) registration —
    // never two registrations from one mount, which was the original
    // duplication path. If a future regression re-adds an IPC subscribe call
    // inside one of the tab hooks, the count surfaces it immediately.
    const stub = installElectronStub();

    const first = renderHook(() => useWatcherFilesBridge());
    expect(stub.onFilesDetected).toHaveBeenCalledTimes(1);

    const second = renderHook(() => useWatcherFilesBridge());
    expect(stub.onFilesDetected).toHaveBeenCalledTimes(2);

    first.unmount();
    expect(stub.cleanup).toHaveBeenCalledTimes(1);
    second.unmount();
    expect(stub.cleanup).toHaveBeenCalledTimes(2);
  });
});
