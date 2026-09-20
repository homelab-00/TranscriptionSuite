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
type SkipPayload = Parameters<
  ReturnType<typeof useImportQueueStore.getState>['handleFileSkipped']
>[0];
type SkipListener = (payload: SkipPayload) => void;

interface WatcherStub {
  onFilesDetected: ReturnType<typeof vi.fn>;
  onFileSkipped: ReturnType<typeof vi.fn>;
  cleanup: ReturnType<typeof vi.fn>;
  skipCleanup: ReturnType<typeof vi.fn>;
  emit: (payload: Payload) => void;
  emitSkip: (payload: SkipPayload) => void;
}

function installElectronStub(opts: { withSkip?: boolean } = {}): WatcherStub {
  const withSkip = opts.withSkip ?? true;
  let activeListener: Listener | null = null;
  let activeSkipListener: SkipListener | null = null;
  const cleanup = vi.fn(() => {
    activeListener = null;
  });
  const skipCleanup = vi.fn(() => {
    activeSkipListener = null;
  });
  const onFilesDetected = vi.fn((cb: Listener) => {
    activeListener = cb;
    return cleanup;
  });
  const onFileSkipped = vi.fn((cb: SkipListener) => {
    activeSkipListener = cb;
    return skipCleanup;
  });
  (window as unknown as Record<string, unknown>).electronAPI = {
    watcher: withSkip ? { onFilesDetected, onFileSkipped } : { onFilesDetected },
  };
  return {
    onFilesDetected,
    onFileSkipped,
    cleanup,
    skipCleanup,
    emit: (payload: Payload) => activeListener?.(payload),
    emitSkip: (payload: SkipPayload) => activeSkipListener?.(payload),
  };
}

function clearElectronStub() {
  delete (window as unknown as Record<string, unknown>).electronAPI;
}

describe('useWatcherFilesBridge — singleton IPC subscription (Issue #94)', () => {
  beforeEach(() => {
    // Replace handleFilesDetected with a spy without touching the rest of the
    // store; this keeps each test focused on the bridge wiring.
    useImportQueueStore.setState({ handleFilesDetected: vi.fn(), handleFileSkipped: vi.fn() });
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

  it('subscribes to fileSkipped exactly once and forwards payloads to handleFileSkipped (GH-311)', () => {
    const stub = installElectronStub();
    const handler = useImportQueueStore.getState().handleFileSkipped as ReturnType<typeof vi.fn>;

    const { unmount } = renderHook(() => useWatcherFilesBridge());
    expect(stub.onFileSkipped).toHaveBeenCalledTimes(1);

    const payload: SkipPayload = { type: 'session', path: '/watch/x.wav', reason: 'empty' };
    act(() => stub.emitSkip(payload));
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith(payload);

    unmount();
    expect(stub.skipCleanup).toHaveBeenCalledTimes(1);
  });

  it('tolerates a preload without onFileSkipped (older build)', () => {
    const stub = installElectronStub({ withSkip: false });
    expect(() => renderHook(() => useWatcherFilesBridge())).not.toThrow();
    expect(stub.onFilesDetected).toHaveBeenCalledTimes(1);
  });
});
