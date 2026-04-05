/**
 * P2-HOOK-007 — useDocker container state transitions
 *
 * Tests the useDocker hook with mocked window.electronAPI.docker IPC methods.
 * Verifies initial state, loading transitions, container status reflection,
 * runtime kind population, and error handling.
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── Helpers ────────────────────────────────────────────────────────────────

function makeDockerAPI(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    available: vi.fn().mockResolvedValue(true),
    getDetectionGuidance: vi.fn().mockResolvedValue(null),
    getComposeAvailable: vi.fn().mockResolvedValue(true),
    getRuntimeKind: vi.fn().mockResolvedValue('Docker'),
    listImages: vi.fn().mockResolvedValue([]),
    getContainerStatus: vi.fn().mockResolvedValue({
      exists: false,
      running: false,
      status: 'unknown',
    }),
    getVolumes: vi.fn().mockResolvedValue([]),
    pullImage: vi.fn().mockResolvedValue(undefined),
    cancelPull: vi.fn().mockResolvedValue(undefined),
    hasSidecarImage: vi.fn().mockResolvedValue(false),
    pullSidecarImage: vi.fn().mockResolvedValue(undefined),
    cancelSidecarPull: vi.fn().mockResolvedValue(undefined),
    removeImage: vi.fn().mockResolvedValue(undefined),
    startContainer: vi.fn().mockResolvedValue(undefined),
    stopContainer: vi.fn().mockResolvedValue(undefined),
    removeContainer: vi.fn().mockResolvedValue(undefined),
    removeVolume: vi.fn().mockResolvedValue(undefined),
    retryDetection: vi.fn().mockResolvedValue(true),
    startLogStream: vi.fn(),
    stopLogStream: vi.fn(),
    onLogLine: vi.fn().mockReturnValue(vi.fn()),
    ...overrides,
  };
}

// ── Tests ──────────────────────────────────────────────────────────────────

import { useDocker } from '../useDocker';

describe('[P2] useDocker', () => {
  let originalElectronAPI: unknown;

  beforeEach(() => {
    originalElectronAPI = (window as any).electronAPI;
  });

  afterEach(() => {
    (window as any).electronAPI = originalElectronAPI;
    vi.restoreAllMocks();
  });

  it('returns available=false when docker.available() returns false', async () => {
    const dockerApi = makeDockerAPI({ available: vi.fn().mockResolvedValue(false) });
    (window as any).electronAPI = { docker: dockerApi };

    const { result } = renderHook(() => useDocker());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.available).toBe(false);
  });

  it('returns loading=true initially then loading=false after detection', async () => {
    const dockerApi = makeDockerAPI();
    (window as any).electronAPI = { docker: dockerApi };

    const { result } = renderHook(() => useDocker());

    // Initially loading
    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.available).toBe(true);
  });

  it('container status reflects IPC response', async () => {
    const dockerApi = makeDockerAPI({
      getContainerStatus: vi.fn().mockResolvedValue({
        exists: true,
        running: true,
        status: 'running',
        health: 'healthy',
      }),
    });
    (window as any).electronAPI = { docker: dockerApi };

    const { result } = renderHook(() => useDocker());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.container).toEqual({
      exists: true,
      running: true,
      status: 'running',
      health: 'healthy',
    });
  });

  it('runtimeKind is populated from detection', async () => {
    const dockerApi = makeDockerAPI({
      getRuntimeKind: vi.fn().mockResolvedValue('Podman'),
    });
    (window as any).electronAPI = { docker: dockerApi };

    const { result } = renderHook(() => useDocker());

    await waitFor(() => {
      expect(result.current.runtimeKind).toBe('Podman');
    });
  });

  it('sets operationError on IPC failure during pullImage', async () => {
    const dockerApi = makeDockerAPI({
      pullImage: vi.fn().mockRejectedValue(new Error('Network timeout')),
    });
    (window as any).electronAPI = { docker: dockerApi };

    const { result } = renderHook(() => useDocker());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    // Trigger pullImage and let it fail
    await act(async () => {
      await result.current.pullImage('latest');
    });

    expect(result.current.operationError).toBe('Network timeout');
  });
});
