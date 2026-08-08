/**
 * useSalvageProgress tests (GH-239 follow-up).
 *
 * The monitor mirrors an in-progress salvage (from GET /api/status) into the
 * notification center and resolves the outcome when it ends. Critical trap
 * pinned here: completion must be confirmed via /recent, NEVER via
 * GET /result/{id} - a 200 there marks the job delivered and removes it from
 * the recovery banner.
 */

import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useSalvageProgress, waitForJobSlotFree, ACTIVE_POLL_MS } from './useSalvageProgress';
import { useNotificationsStore } from '../stores/notificationsStore';
import { useSalvageStore } from '../stores/salvageStore';
import { apiClient } from '../api/client';
import { jobTrackerFromServerStatus } from '../api/types';

vi.mock('../api/client', () => ({
  apiClient: {
    getStatus: vi.fn(),
    fetchRecentUndelivered: vi.fn(),
    fetchTranscriptionResult: vi.fn(),
  },
}));

const mockedApi = vi.mocked(apiClient);

const SALVAGE = { job_id: 'salv-full', client_name: 'laptop', started_at: 1 };

function statusWith(salvage: unknown, extra: Record<string, unknown> = {}) {
  return {
    models: {
      job_tracker: {
        is_busy: salvage !== null,
        active_user: 'laptop',
        active_job_id: 'salv-ful',
        cancellation_requested: false,
        progress: null,
        started_at: null,
        result: null,
        salvage,
        ...extra,
      },
    },
  } as never;
}

async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

function salvageNotification() {
  return useNotificationsStore.getState().notifications.find((n) => n.id === 'salvage-salv-full');
}

beforeEach(() => {
  vi.useFakeTimers();
  useNotificationsStore.setState({ notifications: [] });
  useSalvageStore.setState({ checkNonce: 0, dropRequestedJobId: null, lastCompletedAt: null });
  mockedApi.getStatus.mockResolvedValue(statusWith(null));
  mockedApi.fetchRecentUndelivered.mockResolvedValue({ ok: true, json: async () => [] } as never);
  mockedApi.fetchTranscriptionResult.mockResolvedValue({
    status: 404,
    json: async () => ({}),
  } as never);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('jobTrackerFromServerStatus', () => {
  it('digs the tracker out of the models blob', () => {
    expect(jobTrackerFromServerStatus(statusWith(SALVAGE))?.salvage).toEqual(SALVAGE);
    expect(jobTrackerFromServerStatus(null)).toBeUndefined();
    expect(jobTrackerFromServerStatus({} as never)).toBeUndefined();
  });
});

describe('useSalvageProgress', () => {
  it('mirrors an active salvage into the notification center with percent progress', async () => {
    mockedApi.getStatus.mockResolvedValue(
      statusWith(SALVAGE, {
        progress: { current: 30, total: 60, message: '', phase: 'transcribing' },
      }),
    );
    renderHook(() => useSalvageProgress());
    await flush();

    const n = salvageNotification();
    expect(n?.status).toBe('active');
    expect(n?.category).toBe('transcription');
    expect(n?.progress).toBe(50);
    expect(n?.detail).toContain('laptop');
  });

  it('renders a dropped salvage as stopped without probing the result endpoints', async () => {
    mockedApi.getStatus
      .mockResolvedValueOnce(statusWith(SALVAGE))
      .mockResolvedValue(statusWith(null));
    useSalvageStore.getState().markDropRequested('salv-full');
    renderHook(() => useSalvageProgress());
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS);
    });

    const n = salvageNotification();
    expect(n?.status).toBe('complete');
    expect(n?.title).toBe('Recovery stopped');
    expect(mockedApi.fetchRecentUndelivered).not.toHaveBeenCalled();
    expect(mockedApi.fetchTranscriptionResult).not.toHaveBeenCalled();
    expect(useSalvageStore.getState().dropRequestedJobId).toBeNull();
    expect(useSalvageStore.getState().lastCompletedAt).not.toBeNull();
  });

  it('confirms completion via /recent and never touches /result (mark_delivered trap)', async () => {
    mockedApi.getStatus
      .mockResolvedValueOnce(statusWith(SALVAGE))
      .mockResolvedValue(statusWith(null));
    mockedApi.fetchRecentUndelivered.mockResolvedValue({
      ok: true,
      json: async () => [{ job_id: 'salv-full', completed_at: 'x', text_preview: 'hi' }],
    } as never);
    renderHook(() => useSalvageProgress());
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS);
    });

    const n = salvageNotification();
    expect(n?.status).toBe('complete');
    expect(n?.title).toBe('Recording recovered');
    expect(mockedApi.fetchTranscriptionResult).not.toHaveBeenCalled();
    expect(useSalvageStore.getState().lastCompletedAt).not.toBeNull();
  });

  it('reports a failed salvage with the server reason (410 detail)', async () => {
    mockedApi.getStatus
      .mockResolvedValueOnce(statusWith(SALVAGE))
      .mockResolvedValue(statusWith(null));
    mockedApi.fetchTranscriptionResult.mockResolvedValue({
      status: 410,
      json: async () => ({ detail: 'CUDA out of memory' }),
    } as never);
    renderHook(() => useSalvageProgress());
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS);
    });

    const n = salvageNotification();
    expect(n?.status).toBe('error');
    expect(n?.error).toBe('CUDA out of memory');
  });

  it('requestCheck triggers an immediate poll', async () => {
    renderHook(() => useSalvageProgress());
    await flush();
    const calls = mockedApi.getStatus.mock.calls.length;

    act(() => {
      useSalvageStore.getState().requestCheck();
    });
    await flush();

    expect(mockedApi.getStatus.mock.calls.length).toBeGreaterThan(calls);
  });
});

describe('waitForJobSlotFree', () => {
  it('resolves true immediately when the tracker is free', async () => {
    mockedApi.getStatus.mockResolvedValue(statusWith(null));
    await expect(waitForJobSlotFree(5_000, 1_000)).resolves.toBe(true);
  });

  it('gives up after the deadline while busy', async () => {
    mockedApi.getStatus.mockResolvedValue(statusWith(SALVAGE));
    const pending = waitForJobSlotFree(3_000, 1_000);
    await vi.advanceTimersByTimeAsync(4_000);
    await expect(pending).resolves.toBe(false);
  });
});
