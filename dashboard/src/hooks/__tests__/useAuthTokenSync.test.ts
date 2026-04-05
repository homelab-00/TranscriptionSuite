/**
 * P2-HOOK-008 — useAuthTokenSync edge cases
 *
 * Additional edge-case tests for the useAuthTokenSync hook.
 * The primary test suite lives at src/hooks/useAuthTokenSync.test.ts;
 * this file covers corner cases not covered there:
 *   - Non-Electron env with serverReachable=true (double no-op)
 *   - Remote mode skips Docker log scanning even when server is reachable
 *   - Stale token cleared when login returns success=false (mount variant)
 *   - Network error during validation retains token
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';

// ── Mocks ──────────────────────────────────────────────────────────────────

vi.mock('../../api/client', () => ({
  apiClient: {
    setAuthToken: vi.fn(),
    login: vi.fn(),
  },
}));

import { apiClient } from '../../api/client';
import { useAuthTokenSync } from '../useAuthTokenSync';

// ── Helpers ────────────────────────────────────────────────────────────────

function makeElectronAPI(
  overrides: {
    getLogs?: (n: number) => Promise<string[]>;
    onLogLine?: (cb: (line: string) => void) => () => void;
    configGet?: (key: string) => Promise<unknown>;
    configSet?: (key: string, value: unknown) => Promise<void>;
  } = {},
) {
  return {
    docker: {
      getLogs: overrides.getLogs ?? vi.fn().mockResolvedValue([]),
      onLogLine: overrides.onLogLine ?? vi.fn().mockReturnValue(vi.fn()),
    },
    config: {
      get: overrides.configGet ?? vi.fn(async () => ''),
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

async function flushEffects() {
  await act(async () => {
    for (let i = 0; i < 10; i++) {
      await new Promise((r) => setTimeout(r, 0));
    }
  });
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe('[P2] useAuthTokenSync edge cases', () => {
  let originalElectronAPI: unknown;

  beforeEach(() => {
    originalElectronAPI = (window as any).electronAPI;
    vi.clearAllMocks();
  });

  afterEach(() => {
    (window as any).electronAPI = originalElectronAPI;
    vi.restoreAllMocks();
  });

  it('non-Electron environment with serverReachable=true does not call login', async () => {
    delete (window as any).electronAPI;
    const { wrapper } = createWrapper();

    renderHook(() => useAuthTokenSync(true, false), { wrapper });
    await flushEffects();

    // No token means no login attempt, even with serverReachable=true
    expect(apiClient.login).not.toHaveBeenCalled();
    expect(apiClient.setAuthToken).not.toHaveBeenCalled();
  });

  it('remote mode skips Docker log scanning even when server is reachable', async () => {
    const getLogs = vi.fn().mockResolvedValue(['Admin Token: remote-test-token']);
    const onLogLine = vi.fn().mockReturnValue(vi.fn());
    const { wrapper } = createWrapper();
    (window as any).electronAPI = makeElectronAPI({
      getLogs,
      onLogLine,
    });

    renderHook(() => useAuthTokenSync(true, true), { wrapper });
    await flushEffects();

    // Docker log scanning should be completely skipped
    expect(getLogs).not.toHaveBeenCalled();
    expect(onLogLine).not.toHaveBeenCalled();
  });

  it('clears stale token on mount when server is reachable and login fails', async () => {
    vi.mocked(apiClient.login).mockResolvedValue({ success: false });

    const electronAPI = makeElectronAPI({
      configGet: vi.fn(async (key: string) => {
        if (key === 'connection.authToken') return 'stale-mount-token';
        return '';
      }),
    });
    const { wrapper, qc } = createWrapper();
    (window as any).electronAPI = electronAPI;

    // Server already reachable on mount — init() validates inline
    renderHook(() => useAuthTokenSync(true, false), { wrapper });
    await flushEffects();

    await waitFor(() => {
      expect(apiClient.setAuthToken).toHaveBeenCalledWith(null);
    });
    expect(qc.getQueryData(['authToken'])).toBe('');
    expect(electronAPI.config.set).toHaveBeenCalledWith('connection.authToken', '');
  });

  it('retains token when network error occurs during validation', async () => {
    vi.mocked(apiClient.login).mockRejectedValue(new Error('ECONNREFUSED'));

    const { wrapper, qc } = createWrapper();
    (window as any).electronAPI = makeElectronAPI({
      configGet: vi.fn(async (key: string) => {
        if (key === 'connection.authToken') return 'good-token-net-err';
        return '';
      }),
    });

    renderHook(() => useAuthTokenSync(true, false), { wrapper });
    await flushEffects();

    // Token should NOT be cleared — the error might be transient
    expect(qc.getQueryData(['authToken'])).toBe('good-token-net-err');
    expect(apiClient.setAuthToken).not.toHaveBeenCalledWith(null);
  });
});
