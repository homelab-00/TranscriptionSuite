/**
 * useNotebookWatcher — active flag persistence regression coverage (Issue #100).
 *
 * Mirror of useSessionWatcher.test.tsx for the notebook side. See the session
 * test file's header for the rationale; the two hooks are intentionally
 * symmetric so divergence (which has bitten us in #93/#94) is visible at a
 * glance.
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useNotebookWatcher } from '../useNotebookWatcher';
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
  startNotebook: ReturnType<typeof vi.fn>;
  stopNotebook: ReturnType<typeof vi.fn>;
  checkPath: ReturnType<typeof vi.fn>;
}

function installElectronStub(): WatcherStub {
  const stub: WatcherStub = {
    startNotebook: vi.fn(() => Promise.resolve()),
    stopNotebook: vi.fn(() => Promise.resolve()),
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

describe('useNotebookWatcher — active flag persistence (Issue #100)', () => {
  beforeEach(() => {
    useImportQueueStore.setState({
      notebookWatchPath: '',
      notebookWatchActive: false,
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
      if (key === 'folderWatch.notebookPath') return '/notes';
      if (key === 'folderWatch.notebookWatchActive') return true;
      return undefined;
    });

    renderHook(() => useNotebookWatcher());

    await waitFor(() => {
      expect(useImportQueueStore.getState().notebookWatchActive).toBe(true);
    });
    expect(useImportQueueStore.getState().notebookWatchPath).toBe('/notes');
    expect(stub.startNotebook).toHaveBeenCalledTimes(1);
    expect(stub.startNotebook).toHaveBeenCalledWith('/notes');
  });

  it('hydrates path only when active flag is absent — does not re-arm', async () => {
    const stub = installElectronStub();
    mockGetConfig.mockImplementation(async (key) => {
      if (key === 'folderWatch.notebookPath') return '/notes';
      if (key === 'folderWatch.notebookWatchActive') return undefined;
      return undefined;
    });

    renderHook(() => useNotebookWatcher());

    await waitFor(() => {
      expect(useImportQueueStore.getState().notebookWatchPath).toBe('/notes');
    });
    expect(useImportQueueStore.getState().notebookWatchActive).toBe(false);
    expect(stub.startNotebook).not.toHaveBeenCalled();
  });

  it('persists active flag when toggle is invoked via the wrapped setter', async () => {
    installElectronStub();
    mockGetConfig.mockResolvedValue(undefined);

    const { result } = renderHook(() => useNotebookWatcher());

    await waitFor(() => expect(mockGetConfig).toHaveBeenCalled());

    act(() => {
      result.current.setNotebookWatchActive(true);
    });

    expect(useImportQueueStore.getState().notebookWatchActive).toBe(true);
    await waitFor(() => {
      expect(mockSetConfig).toHaveBeenCalledWith('folderWatch.notebookWatchActive', true);
    });
  });

  it('persists active=false when startNotebook rejects (auto-disable)', async () => {
    const stub = installElectronStub();
    stub.startNotebook.mockRejectedValue(new Error('start failed'));
    mockGetConfig.mockImplementation(async (key) => {
      if (key === 'folderWatch.notebookPath') return '/notes';
      if (key === 'folderWatch.notebookWatchActive') return true;
      return undefined;
    });

    renderHook(() => useNotebookWatcher());

    await waitFor(() => {
      expect(mockSetConfig).toHaveBeenCalledWith('folderWatch.notebookWatchActive', false);
    });
    expect(useImportQueueStore.getState().notebookWatchActive).toBe(false);
  });

  it('persists active=false before new path when setWatchPath runs while active', async () => {
    const stub = installElectronStub();
    mockGetConfig.mockResolvedValue(undefined);
    useImportQueueStore.setState({
      notebookWatchPath: '/notes',
      notebookWatchActive: true,
    });

    const { result } = renderHook(() => useNotebookWatcher());
    await waitFor(() => expect(mockGetConfig).toHaveBeenCalled());

    await act(async () => {
      await result.current.setWatchPath('/other-notes');
    });

    expect(useImportQueueStore.getState().notebookWatchActive).toBe(false);
    expect(useImportQueueStore.getState().notebookWatchPath).toBe('/other-notes');

    const activeCallIdx = mockSetConfig.mock.calls.findIndex(
      ([key, value]) => key === 'folderWatch.notebookWatchActive' && value === false,
    );
    const pathCallIdx = mockSetConfig.mock.calls.findIndex(
      ([key, value]) => key === 'folderWatch.notebookPath' && value === '/other-notes',
    );
    expect(activeCallIdx).toBeGreaterThanOrEqual(0);
    expect(pathCallIdx).toBeGreaterThanOrEqual(0);
    expect(activeCallIdx).toBeLessThan(pathCallIdx);
    expect(stub.stopNotebook).toHaveBeenCalled();
  });

  it('does not crash when electronAPI is undefined; hydration still updates state', async () => {
    clearElectronStub();
    mockGetConfig.mockImplementation(async (key) => {
      if (key === 'folderWatch.notebookPath') return '/notes';
      if (key === 'folderWatch.notebookWatchActive') return true;
      return undefined;
    });

    expect(() => renderHook(() => useNotebookWatcher())).not.toThrow();

    await waitFor(() => {
      expect(useImportQueueStore.getState().notebookWatchActive).toBe(true);
    });
  });
});
