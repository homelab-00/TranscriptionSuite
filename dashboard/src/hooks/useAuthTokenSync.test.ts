import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';

import { useAuthTokenSync } from './useAuthTokenSync';

// ── Mocks ──────────────────────────────────────────────────────────────

vi.mock('../api/client', () => ({
  apiClient: {
    setAuthToken: vi.fn(),
    login: vi.fn(),
  },
}));

// extractAdminTokenFromDockerLogLine is NOT mocked — tests exercise the
// real parser (including ANSI-stripping) for fidelity.

import { apiClient } from '../api/client';

// ── Helpers ────────────────────────────────────────────────────────────

function makeElectronAPI(
  overrides: {
    getLogs?: (n: number) => Promise<string[]>;
    onLogLine?: (cb: (line: string) => void) => () => void;
    configGet?: (key: string) => Promise<unknown>;
    configSet?: (key: string, value: unknown) => Promise<void>;
    useRemote?: boolean;
  } = {},
) {
  return {
    docker: {
      getLogs: overrides.getLogs ?? vi.fn().mockResolvedValue([]),
      onLogLine: overrides.onLogLine ?? vi.fn().mockReturnValue(vi.fn()),
    },
    config: {
      get:
        overrides.configGet ??
        vi.fn(async (key: string) => {
          if (key === 'connection.useRemote') return overrides.useRemote ?? false;
          return '';
        }),
      set: overrides.configSet ?? vi.fn().mockResolvedValue(undefined),
    },
  };
}

function createWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
  return { wrapper, qc };
}

/** Flush microtasks so async init() inside useEffect can complete. */
async function flushEffects() {
  await act(async () => {
    // Yield to microtask queue repeatedly to let chained awaits resolve.
    for (let i = 0; i < 10; i++) {
      await new Promise((r) => setTimeout(r, 0));
    }
  });
}

// ── Tests ──────────────────────────────────────────────────────────────

describe('useAuthTokenSync', () => {
  let originalElectronAPI: unknown;

  beforeEach(() => {
    originalElectronAPI = (window as any).electronAPI;
    vi.clearAllMocks();
  });

  afterEach(() => {
    (window as any).electronAPI = originalElectronAPI;
    vi.restoreAllMocks();
  });

  // ── Non-Electron no-op ─────────────────────────────────────────────

  it('is a no-op when electronAPI is absent', () => {
    delete (window as any).electronAPI;
    const { wrapper } = createWrapper();

    const { unmount } = renderHook(() => useAuthTokenSync(false), { wrapper });

    expect(apiClient.setAuthToken).not.toHaveBeenCalled();
    unmount();
  });

  // ── Config seeding ─────────────────────────────────────────────────

  it('seeds token from persisted config on mount', async () => {
    const { wrapper, qc } = createWrapper();
    (window as any).electronAPI = makeElectronAPI({
      configGet: vi.fn(async (key: string) => {
        if (key === 'connection.authToken') return 'saved-token-123';
        if (key === 'connection.useRemote') return false;
        return '';
      }),
    });

    renderHook(() => useAuthTokenSync(false), { wrapper });
    await flushEffects();

    expect(qc.getQueryData(['authToken'])).toBe('saved-token-123');
  });

  // ── Docker log scanning ────────────────────────────────────────────

  it('detects token from Docker log scan on mount', async () => {
    const electronAPI = makeElectronAPI({
      getLogs: vi
        .fn()
        .mockResolvedValue(['some other log line', 'INFO:     Admin Token: abc-token-xyz']),
    });
    const { wrapper, qc } = createWrapper();
    (window as any).electronAPI = electronAPI;

    renderHook(() => useAuthTokenSync(false), { wrapper });
    await flushEffects();

    expect(qc.getQueryData(['authToken'])).toBe('abc-token-xyz');
    expect(apiClient.setAuthToken).toHaveBeenCalledWith('abc-token-xyz');
    // Token persisted to electron-store
    expect(electronAPI.config.set).toHaveBeenCalledWith('connection.authToken', 'abc-token-xyz');
  });

  it('detects token with ANSI escape codes in log line', async () => {
    const { wrapper, qc } = createWrapper();
    (window as any).electronAPI = makeElectronAPI({
      getLogs: vi
        .fn()
        .mockResolvedValue([
          '\u001b[32mINFO:\u001b[0m     Admin Token: \u001b[1mansi-token-456\u001b[0m',
        ]),
    });

    renderHook(() => useAuthTokenSync(false), { wrapper });
    await flushEffects();

    expect(qc.getQueryData(['authToken'])).toBe('ansi-token-456');
  });

  it('detects token from live log line subscription', async () => {
    let logCallback: ((line: string) => void) | undefined;
    const { wrapper, qc } = createWrapper();
    (window as any).electronAPI = makeElectronAPI({
      onLogLine: vi.fn((cb: (line: string) => void) => {
        logCallback = cb;
        return vi.fn();
      }),
    });

    renderHook(() => useAuthTokenSync(false), { wrapper });
    await flushEffects();

    // Simulate a live log line arriving
    expect(logCallback).toBeDefined();
    act(() => {
      logCallback!('INFO:     Admin Token: live-token-999');
    });

    expect(qc.getQueryData(['authToken'])).toBe('live-token-999');
    expect(apiClient.setAuthToken).toHaveBeenCalledWith('live-token-999');
  });

  // ── Remote mode guard ──────────────────────────────────────────────

  it('skips Docker log scanning in remote mode', async () => {
    const getLogs = vi.fn().mockResolvedValue([]);
    const onLogLine = vi.fn().mockReturnValue(vi.fn());
    const { wrapper } = createWrapper();
    (window as any).electronAPI = makeElectronAPI({
      useRemote: true,
      getLogs,
      onLogLine,
    });

    renderHook(() => useAuthTokenSync(false), { wrapper });
    await flushEffects();

    expect(getLogs).not.toHaveBeenCalled();
    expect(onLogLine).not.toHaveBeenCalled();
  });

  // ── Stale-token validation ─────────────────────────────────────────

  it('validates token when server becomes reachable and retains it on success', async () => {
    vi.mocked(apiClient.login).mockResolvedValue({ success: true });

    const { wrapper, qc } = createWrapper();
    (window as any).electronAPI = makeElectronAPI({
      configGet: vi.fn(async (key: string) => {
        if (key === 'connection.authToken') return 'cached-token';
        if (key === 'connection.useRemote') return false;
        return '';
      }),
    });

    // Mount with serverReachable=false, then re-render with true
    const { rerender } = renderHook(
      ({ reachable }: { reachable: boolean }) => useAuthTokenSync(reachable),
      { wrapper, initialProps: { reachable: false } },
    );
    await flushEffects();

    // Server becomes reachable — triggers second useEffect
    rerender({ reachable: true });
    await flushEffects();

    expect(apiClient.login).toHaveBeenCalledWith('cached-token');
    // Token should be retained (not cleared)
    expect(apiClient.setAuthToken).not.toHaveBeenCalledWith(null);
    expect(qc.getQueryData(['authToken'])).toBe('cached-token');
  });

  it('clears stale token when server rejects it', async () => {
    vi.mocked(apiClient.login).mockResolvedValue({ success: false });

    const electronAPI = makeElectronAPI({
      configGet: vi.fn(async (key: string) => {
        if (key === 'connection.authToken') return 'stale-token';
        if (key === 'connection.useRemote') return false;
        return '';
      }),
    });
    const { wrapper, qc } = createWrapper();
    (window as any).electronAPI = electronAPI;

    // Mount with server already reachable — init() validates inline
    renderHook(() => useAuthTokenSync(true), { wrapper });
    await flushEffects();

    // Token should be cleared everywhere
    await waitFor(() => {
      expect(apiClient.setAuthToken).toHaveBeenCalledWith(null);
    });
    expect(qc.getQueryData(['authToken'])).toBe('');
    // Token cleared in electron-store
    expect(electronAPI.config.set).toHaveBeenCalledWith('connection.authToken', '');
  });

  it('does not clear token on network error during validation', async () => {
    vi.mocked(apiClient.login).mockRejectedValue(new Error('Network error'));

    const { wrapper, qc } = createWrapper();
    (window as any).electronAPI = makeElectronAPI({
      configGet: vi.fn(async (key: string) => {
        if (key === 'connection.authToken') return 'good-token';
        if (key === 'connection.useRemote') return false;
        return '';
      }),
    });

    renderHook(() => useAuthTokenSync(true), { wrapper });
    await flushEffects();

    // Token should NOT be cleared — still set from config seed
    expect(qc.getQueryData(['authToken'])).toBe('good-token');
    expect(apiClient.setAuthToken).not.toHaveBeenCalledWith(null);
  });

  // ── Cleanup ────────────────────────────────────────────────────────

  it('cleans up subscription on unmount', async () => {
    const unsubscribe = vi.fn();
    const { wrapper } = createWrapper();
    (window as any).electronAPI = makeElectronAPI({
      onLogLine: vi.fn(() => unsubscribe),
    });

    const { unmount } = renderHook(() => useAuthTokenSync(false), { wrapper });
    await flushEffects();

    unmount();

    expect(unsubscribe).toHaveBeenCalled();
  });

  // ── Deduplication ──────────────────────────────────────────────────

  it('does not re-apply the same token from logs', async () => {
    const getLogs = vi.fn().mockResolvedValue(['Admin Token: same-token']);
    const { wrapper } = createWrapper();
    (window as any).electronAPI = makeElectronAPI({
      configGet: vi.fn(async (key: string) => {
        if (key === 'connection.authToken') return 'same-token';
        if (key === 'connection.useRemote') return false;
        return '';
      }),
      getLogs,
    });

    renderHook(() => useAuthTokenSync(false), { wrapper });
    await flushEffects();

    // Verify logs WERE scanned (proving dedup is the reason, not scan failure)
    expect(getLogs).toHaveBeenCalled();
    // setAuthToken should NOT be called because the log token matches
    // the already-seeded knownTokenRef from config
    expect(apiClient.setAuthToken).not.toHaveBeenCalled();
  });
});
