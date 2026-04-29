import { describe, it, expect } from 'vitest';
import { deriveStatus } from './useServerStatus';
import type { ServerStatus } from '../api/client';

// Helper to build a minimal checkConnection result
function makeResult(overrides: {
  reachable?: boolean;
  ready?: boolean;
  status?: Partial<ServerStatus> | null;
  error?: string | null;
}) {
  return {
    reachable: overrides.reachable ?? true,
    ready: overrides.ready ?? false,
    status: (overrides.status === undefined ? {} : overrides.status) as ServerStatus | null,
    error: overrides.error ?? null,
  };
}

describe('deriveStatus', () => {
  it('returns loading state when result is undefined', () => {
    const info = deriveStatus(undefined);

    expect(info.serverStatus).toBe('loading');
    expect(info.ready).toBe(false);
    expect(info.gpuError).toBeNull();
  });

  it('returns inactive when server is not reachable', () => {
    const info = deriveStatus(makeResult({ reachable: false }));

    expect(info.serverStatus).toBe('inactive');
    expect(info.reachable).toBe(false);
    expect(info.ready).toBe(false);
    expect(info.gpuError).toBeNull();
  });

  it('returns error state when gpu_error is present', () => {
    const info = deriveStatus(
      makeResult({
        reachable: true,
        ready: false,
        status: {
          gpu_error: 'CUDA unknown error (999)',
          gpu_error_action: 'Restart your computer to reset the GPU driver.',
        },
      }),
    );

    expect(info.serverStatus).toBe('error');
    expect(info.ready).toBe(false);
    expect(info.gpuError).toBe('CUDA unknown error (999)');
    expect(info.serverLabel).toBe('Restart your computer to reset the GPU driver.');
  });

  it('uses fallback label when gpu_error_action is absent', () => {
    const info = deriveStatus(
      makeResult({
        reachable: true,
        ready: false,
        status: { gpu_error: 'CUDA error' },
      }),
    );

    expect(info.serverStatus).toBe('error');
    expect(info.serverLabel).toContain('GPU unavailable');
  });

  it('surfaces gpu_error_recovery_hint when backend included it (error-999 path)', () => {
    const HINT =
      'GPU init failed with error 999 (CUDA unknown). Run scripts/diagnose-gpu.sh on the host for details.';
    const info = deriveStatus(
      makeResult({
        reachable: true,
        ready: false,
        status: {
          gpu_error: 'CUDA unknown error (999)',
          gpu_error_action: 'Restart your computer to reset the GPU driver.',
          gpu_error_recovery_hint: HINT,
        },
      }),
    );

    expect(info.gpuError).toBe('CUDA unknown error (999)');
    expect(info.gpuErrorRecoveryHint).toBe(HINT);
  });

  it('returns null gpuErrorRecoveryHint when backend omitted it (non-999 path)', () => {
    const info = deriveStatus(
      makeResult({
        reachable: true,
        ready: false,
        status: {
          gpu_error: 'Some other CUDA error',
        },
      }),
    );

    expect(info.gpuError).toBe('Some other CUDA error');
    expect(info.gpuErrorRecoveryHint).toBeNull();
  });

  it('returns null gpuErrorRecoveryHint when there is no gpu_error', () => {
    const info = deriveStatus(makeResult({ reachable: true, ready: true, status: {} }));

    expect(info.gpuError).toBeNull();
    expect(info.gpuErrorRecoveryHint).toBeNull();
  });

  it('returns error state when gpu_error present even if ready is true', () => {
    // In practice this shouldn't happen (GPU failed → model can't load),
    // but gpu_error must always take priority over the ready flag.
    const info = deriveStatus(
      makeResult({
        reachable: true,
        ready: true,
        status: { gpu_error: 'CUDA error', ready: true },
      }),
    );

    expect(info.serverStatus).toBe('error');
    expect(info.ready).toBe(false);
  });

  it('returns warning when not ready and no gpu_error', () => {
    const info = deriveStatus(makeResult({ reachable: true, ready: false, status: {} }));

    expect(info.serverStatus).toBe('warning');
    expect(info.serverLabel).toBe('Models loading…');
    expect(info.gpuError).toBeNull();
  });

  it('returns active when server is ready and no gpu_error', () => {
    const info = deriveStatus(makeResult({ reachable: true, ready: true, status: {} }));

    expect(info.serverStatus).toBe('active');
    expect(info.ready).toBe(true);
    expect(info.gpuError).toBeNull();
    expect(info.serverLabel).toBe('Server ready');
  });
});
