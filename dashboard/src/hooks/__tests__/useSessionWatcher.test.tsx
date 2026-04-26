/**
 * useSessionWatcher — active flag persistence regression coverage (Issue #100).
 *
 * Before #100, only the watch path persisted across app restarts; the active
 * toggle was deliberately ephemeral. Users perceived the half-state as the app
 * forgetting their setting. The hook now hydrates BOTH the path and the active
 * flag on mount and persists every active-flag transition (UI toggle,
 * auto-disable on start failure, auto-disable on path change).
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useSessionWatcher } from '../useSessionWatcher';
import { useImportQueueStore } from '../../stores/importQueueStore';
import { getConfig, setConfig } from '../../config/store';

vi.mock('../../config/store', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../config/store')>();
  return {
    ...actual,
    getConfig: vi.fn(),
    setConfig: vi.fn(),
  };
});

const mockGetConfig = vi.mocked(getConfig);
const mockSetConfig = vi.mocked(setConfig);

interface WatcherStub {
  startSession: ReturnType<typeof vi.fn>;
  stopSession: ReturnType<typeof vi.fn>;
  checkPath: ReturnType<typeof vi.fn>;
}

function installElectronStub(): WatcherStub {
  const stub: WatcherStub = {
    startSession: vi.fn(() => Promise.resolve()),
    stopSession: vi.fn(() => Promise.resolve()),
    checkPath: vi.fn(() => Promise.resolve(true)),
  };
  (window as unknown as Record<string, unknown>).electronAPI = {
    watcher: stub,
  };
  return stub;
}

function clearElectronStub() {
  delete (window as unknown as Record<string, unknown>).electronAPI;
}

describe('useSessionWatcher — active flag persistence (Issue #100)', () => {
  beforeEach(() => {
    // Reset only the watcher slice — leave the rest of the store intact.
    useImportQueueStore.setState({
      sessionWatchPath: '',
      sessionWatchActive: false,
      watchLog: [],
    });
    mockGetConfig.mockReset();
    mockSetConfig.mockReset();
    mockSetConfig.mockResolvedValue(undefined);
  });

  afterEach(() => {
    clearElectronStub();
  });

  it('hydrates path and active flag, re-arms watcher when both are truthy', async () => {
    const stub = installElectronStub();
    mockGetConfig.mockImplementation(async (key) => {
      if (key === 'folderWatch.sessionPath') return '/foo';
      if (key === 'folderWatch.sessionWatchActive') return true;
      return undefined;
    });

    renderHook(() => useSessionWatcher());

    await waitFor(() => {
      expect(useImportQueueStore.getState().sessionWatchActive).toBe(true);
    });
    expect(useImportQueueStore.getState().sessionWatchPath).toBe('/foo');
    expect(stub.startSession).toHaveBeenCalledTimes(1);
    expect(stub.startSession).toHaveBeenCalledWith('/foo');
  });

  it('hydrates path only when active flag is absent — does not re-arm', async () => {
    const stub = installElectronStub();
    mockGetConfig.mockImplementation(async (key) => {
      if (key === 'folderWatch.sessionPath') return '/foo';
      if (key === 'folderWatch.sessionWatchActive') return undefined;
      return undefined;
    });

    renderHook(() => useSessionWatcher());

    await waitFor(() => {
      expect(useImportQueueStore.getState().sessionWatchPath).toBe('/foo');
    });
    expect(useImportQueueStore.getState().sessionWatchActive).toBe(false);
    expect(stub.startSession).not.toHaveBeenCalled();
  });

  it('persists active flag when toggle is invoked via the wrapped setter', async () => {
    installElectronStub();
    mockGetConfig.mockResolvedValue(undefined);

    const { result } = renderHook(() => useSessionWatcher());

    // Let the initial hydration useEffect settle so it doesn't race with the toggle.
    await waitFor(() => expect(mockGetConfig).toHaveBeenCalled());

    act(() => {
      result.current.setSessionWatchActive(true);
    });

    expect(useImportQueueStore.getState().sessionWatchActive).toBe(true);
    await waitFor(() => {
      expect(mockSetConfig).toHaveBeenCalledWith('folderWatch.sessionWatchActive', true);
    });
  });

  it('persists active=false when startSession rejects (auto-disable)', async () => {
    const stub = installElectronStub();
    stub.startSession.mockRejectedValue(new Error('start failed'));
    mockGetConfig.mockImplementation(async (key) => {
      if (key === 'folderWatch.sessionPath') return '/foo';
      if (key === 'folderWatch.sessionWatchActive') return true;
      return undefined;
    });

    renderHook(() => useSessionWatcher());

    // Hydration → re-arm → start rejects → wrapped setter → setConfig(false)
    await waitFor(() => {
      expect(mockSetConfig).toHaveBeenCalledWith('folderWatch.sessionWatchActive', false);
    });
    expect(useImportQueueStore.getState().sessionWatchActive).toBe(false);
  });

  it('persists active=false before new path when setWatchPath runs while active', async () => {
    const stub = installElectronStub();
    mockGetConfig.mockResolvedValue(undefined);
    // Pre-seed an active session so setWatchPath enters its disable branch.
    useImportQueueStore.setState({
      sessionWatchPath: '/foo',
      sessionWatchActive: true,
    });

    const { result } = renderHook(() => useSessionWatcher());
    await waitFor(() => expect(mockGetConfig).toHaveBeenCalled());

    await act(async () => {
      await result.current.setWatchPath('/bar');
    });

    expect(useImportQueueStore.getState().sessionWatchActive).toBe(false);
    expect(useImportQueueStore.getState().sessionWatchPath).toBe('/bar');

    // Both writes happened, and active=false landed before the new path —
    // the order matters because a quit between them must not leave disk in
    // `{ active: true, path: <newPath> }`.
    const activeCallIdx = mockSetConfig.mock.calls.findIndex(
      ([key, value]) => key === 'folderWatch.sessionWatchActive' && value === false,
    );
    const pathCallIdx = mockSetConfig.mock.calls.findIndex(
      ([key, value]) => key === 'folderWatch.sessionPath' && value === '/bar',
    );
    expect(activeCallIdx).toBeGreaterThanOrEqual(0);
    expect(pathCallIdx).toBeGreaterThanOrEqual(0);
    expect(activeCallIdx).toBeLessThan(pathCallIdx);
    // stopSession was triggered by the active=false transition.
    expect(stub.stopSession).toHaveBeenCalled();
  });

  it('does not crash when electronAPI is undefined; hydration still updates state', async () => {
    clearElectronStub();
    mockGetConfig.mockImplementation(async (key) => {
      if (key === 'folderWatch.sessionPath') return '/foo';
      if (key === 'folderWatch.sessionWatchActive') return true;
      return undefined;
    });

    expect(() => renderHook(() => useSessionWatcher())).not.toThrow();

    await waitFor(() => {
      expect(useImportQueueStore.getState().sessionWatchActive).toBe(true);
    });
    // No electronAPI exposed → start effect early-returns; nothing to assert beyond no-throw.
  });
});
