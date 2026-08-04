/**
 * retroDiarize service (GH-279) — start + poll-until-done semantics.
 *
 * The service mirrors the import queue's poll-/api/admin/status loop, so the
 * tests pin the same completion contract: matching tracker result resolves,
 * an idle tracker with a foreign result means the job was lost, and transient
 * poll errors are retried.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const mockDiarizeRecording = vi.fn();
const mockGetAdminStatus = vi.fn();

vi.mock('../../api/client', () => ({
  apiClient: {
    diarizeRecording: (...args: unknown[]) => mockDiarizeRecording(...args),
    getAdminStatus: (...args: unknown[]) => mockGetAdminStatus(...args),
  },
}));

import { diarizeRecordingAndWait } from '../retroDiarize';

const JOB_ID = 'abc12345';

function adminStatus(jobTracker: Record<string, unknown>): Record<string, unknown> {
  return { status: 'ok', models: { job_tracker: jobTracker }, config: {} };
}

describe('diarizeRecordingAndWait', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockDiarizeRecording.mockReset().mockResolvedValue({ job_id: JOB_ID });
    mockGetAdminStatus.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('starts the job and resolves with the matching tracker result', async () => {
    mockGetAdminStatus
      .mockResolvedValueOnce(adminStatus({ is_busy: true, active_job_id: JOB_ID, result: null }))
      .mockResolvedValueOnce(
        adminStatus({
          is_busy: false,
          active_job_id: null,
          result: { job_id: JOB_ID, recording_id: 7, num_speakers: 2 },
        }),
      );

    const promise = diarizeRecordingAndWait(7);
    await vi.advanceTimersByTimeAsync(5000);
    await vi.advanceTimersByTimeAsync(5000);

    await expect(promise).resolves.toEqual({
      job_id: JOB_ID,
      recording_id: 7,
      num_speakers: 2,
    });
    expect(mockDiarizeRecording).toHaveBeenCalledWith(7);
  });

  it('resolves with the error-bearing result so the caller can branch', async () => {
    mockGetAdminStatus.mockResolvedValueOnce(
      adminStatus({
        is_busy: false,
        active_job_id: null,
        result: { job_id: JOB_ID, error: 'CUDA out of memory' },
      }),
    );

    const promise = diarizeRecordingAndWait(7);
    await vi.advanceTimersByTimeAsync(5000);

    await expect(promise).resolves.toEqual({ job_id: JOB_ID, error: 'CUDA out of memory' });
  });

  it('rejects when the tracker is idle with a foreign result (job lost)', async () => {
    mockGetAdminStatus.mockResolvedValueOnce(
      adminStatus({
        is_busy: false,
        active_job_id: null,
        result: { job_id: 'other999' },
      }),
    );

    const promise = diarizeRecordingAndWait(7);
    const assertion = expect(promise).rejects.toThrow(/job lost/);
    await vi.advanceTimersByTimeAsync(5000);
    await assertion;
  });

  it('retries after a transient poll error', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    mockGetAdminStatus.mockRejectedValueOnce(new Error('network hiccup')).mockResolvedValueOnce(
      adminStatus({
        is_busy: false,
        active_job_id: null,
        result: { job_id: JOB_ID, recording_id: 7 },
      }),
    );

    const promise = diarizeRecordingAndWait(7);
    await vi.advanceTimersByTimeAsync(5000);
    await vi.advanceTimersByTimeAsync(5000);

    await expect(promise).resolves.toEqual({ job_id: JOB_ID, recording_id: 7 });
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it('propagates a start failure without polling', async () => {
    mockDiarizeRecording.mockRejectedValueOnce(new Error('409: already diarized'));

    await expect(diarizeRecordingAndWait(7)).rejects.toThrow('409');
    expect(mockGetAdminStatus).not.toHaveBeenCalled();
  });
});
