/**
 * useJobProgress tests.
 *
 * The stall flag means "this job reported no progress change for 120s". The
 * trap pinned here: the hook outlives individual jobs (its host view never
 * unmounts), so the stall clock must start when a job becomes active, not
 * when the hook mounted or when the previous job ended. Otherwise every job
 * started after 2 idle minutes shows the stall warning from its first frame.
 */

import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useJobProgress } from './useJobProgress';
import { useAdminStatus } from './useAdminStatus';

vi.mock('./useAdminStatus', () => ({
  useAdminStatus: vi.fn(),
}));

const mockedUseAdminStatus = vi.mocked(useAdminStatus);

type Progress = { current: number; total: number; message: string; phase: string | null };

function setTracker(progress: Progress | null, startedAt: number | null = null) {
  mockedUseAdminStatus.mockReturnValue({
    status: {
      models: {
        job_tracker: {
          is_busy: progress !== null,
          progress,
          started_at: startedAt,
        },
      },
    } as never,
    loading: false,
    error: null,
    refresh: () => {},
  });
}

function advance(seconds: number) {
  act(() => {
    vi.advanceTimersByTime(seconds * 1000);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-01-01T00:00:00Z'));
  setTracker(null);
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe('useJobProgress stall flag', () => {
  it('does not flag a job that starts after the hook sat idle past the stall window', () => {
    const { result, rerender } = renderHook(({ active }) => useJobProgress(active), {
      initialProps: { active: false },
    });

    advance(600);
    rerender({ active: true });

    expect(result.current.stalled).toBe(false);
  });

  it('does not flag a second job that starts long after the previous one ended', () => {
    const { result, rerender } = renderHook(({ active }) => useJobProgress(active), {
      initialProps: { active: true },
    });
    setTracker({ current: 10, total: 100, message: '', phase: 'transcribing' });
    advance(5);

    setTracker(null);
    rerender({ active: false });
    advance(600);

    rerender({ active: true });

    expect(result.current.stalled).toBe(false);
  });

  it('flags an active job whose progress has not changed for over 120s', () => {
    const { result, rerender } = renderHook(({ active }) => useJobProgress(active), {
      initialProps: { active: false },
    });
    setTracker({ current: 10, total: 100, message: '', phase: 'transcribing' });
    rerender({ active: true });

    advance(119);
    expect(result.current.stalled).toBe(false);

    advance(3);
    expect(result.current.stalled).toBe(true);
  });

  it('resets the stall clock whenever progress changes', () => {
    const { result, rerender } = renderHook(({ active }) => useJobProgress(active), {
      initialProps: { active: false },
    });
    setTracker({ current: 10, total: 100, message: '', phase: 'transcribing' });
    rerender({ active: true });

    advance(100);
    setTracker({ current: 20, total: 100, message: '', phase: 'transcribing' });
    advance(100);

    expect(result.current.stalled).toBe(false);
  });

  it('never flags while inactive', () => {
    const { result } = renderHook(() => useJobProgress(false));

    advance(600);

    expect(result.current.stalled).toBe(false);
  });
});
