/**
 * resultPolling - the shared way a transcript reaches the UI when the socket
 * that ordered it is gone.
 *
 * Two call sites used to own unequal copies of this loop. The weaker one is
 * what stranded a completed transcript in the database with nothing on screen
 * pointing at it, so the behaviours below are the ones that must not regress:
 * a wall-clock budget rather than an attempt count, a separate budget for
 * network failures, per-invocation cancellation, and a delivery throw that is
 * never mistaken for "not ready yet".
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { apiClient } from '../api/client';
import {
  pollForTranscriptionResult,
  toTranscriptionResult,
  POLL_INTERVAL_MS,
  POLL_BUDGET_MS,
  MAX_NETWORK_ERRORS,
  type PollFailure,
} from './resultPolling';

vi.mock('../api/client', () => ({
  apiClient: { fetchTranscriptionResult: vi.fn() },
}));

const fetchResult = apiClient.fetchTranscriptionResult as unknown as ReturnType<typeof vi.fn>;

/** Fixed epoch so the wall-clock budget is exercised without the real clock. */
const EPOCH = new Date('2026-09-04T16:00:00.000Z').getTime();

function ready(result: unknown) {
  return { status: 200, json: async () => ({ result }) };
}

describe('toTranscriptionResult', () => {
  it('maps every field the durability endpoint sends', () => {
    expect(
      toTranscriptionResult({
        text: 'hello',
        words: [{ word: 'hello', start: 0, end: 1 }],
        language: 'el',
        duration: 12.5,
        partial: true,
        partial_reason: 'sidecar died',
        num_speakers: 3,
        diarization: { requested: true, performed: false, reason: 'missing', remedy: 'install' },
      }),
    ).toEqual({
      text: 'hello',
      words: [{ word: 'hello', start: 0, end: 1 }],
      language: 'el',
      duration: 12.5,
      partial: true,
      partialReason: 'sidecar died',
      numSpeakers: 3,
      diarization: { requested: true, performed: false, reason: 'missing', remedy: 'install' },
    });
  });

  it('produces a usable result from an empty or absent payload', () => {
    expect(toTranscriptionResult(undefined)).toEqual({
      text: '',
      words: [],
      language: undefined,
      duration: undefined,
      partial: false,
      partialReason: null,
      numSpeakers: 0,
      diarization: undefined,
    });
  });
});

describe('pollForTranscriptionResult', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    vi.setSystemTime(new Date(EPOCH));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('delivers on the first attempt when the result is already there', async () => {
    fetchResult.mockResolvedValue(ready({ text: 'done', words: [], num_speakers: 2 }));
    const onResult = vi.fn();
    const onFailure = vi.fn();

    pollForTranscriptionResult({ jobId: 'job-1', onResult, onFailure });
    await vi.advanceTimersByTimeAsync(0);

    expect(fetchResult).toHaveBeenCalledWith('job-1');
    expect(onResult).toHaveBeenCalledWith(
      expect.objectContaining({ text: 'done', numSpeakers: 2 }),
      'job-1',
    );
    expect(onFailure).not.toHaveBeenCalled();
  });

  it('keeps polling on 202 and stops the moment the result lands', async () => {
    fetchResult
      .mockResolvedValueOnce({ status: 202, json: async () => ({}) })
      .mockResolvedValueOnce({ status: 202, json: async () => ({}) })
      .mockResolvedValue(ready({ text: 'finally', words: [] }));
    const onResult = vi.fn();

    pollForTranscriptionResult({ jobId: 'job-1', onResult, onFailure: vi.fn() });
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3);

    expect(onResult).toHaveBeenCalledTimes(1);
    const callsAtDelivery = fetchResult.mock.calls.length;
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5);
    expect(fetchResult.mock.calls.length).toBe(callsAtDelivery);
  });

  it('reports a 410 as a server-side failure and carries the reason back', async () => {
    fetchResult.mockResolvedValue({
      status: 410,
      json: async () => ({}),
      text: async () => JSON.stringify({ detail: 'Audio file has been deleted' }),
    });
    const onFailure = vi.fn();

    pollForTranscriptionResult({ jobId: 'job-1', onResult: vi.fn(), onFailure });
    await vi.advanceTimersByTimeAsync(0);

    expect(onFailure).toHaveBeenCalledTimes(1);
    const failure = onFailure.mock.calls[0][0] as PollFailure;
    expect(failure.kind).toBe('failed');
    expect(failure.status).toBe(410);
    expect(failure.body).toContain('Audio file has been deleted');
  });

  it('reports an unexpected status as unavailable rather than idling forever', async () => {
    fetchResult.mockResolvedValue({ status: 404, json: async () => ({}) });
    const onFailure = vi.fn();

    pollForTranscriptionResult({ jobId: 'job-1', onResult: vi.fn(), onFailure });
    await vi.advanceTimersByTimeAsync(0);

    expect(onFailure).toHaveBeenCalledWith(expect.objectContaining({ kind: 'unavailable' }));
  });

  // The count-based cap it replaced ignored request latency, so it always gave
  // up sooner than it claimed to. This budget is real elapsed time.
  it('gives up on wall-clock time, not on a count of attempts', async () => {
    fetchResult.mockResolvedValue({ status: 202, json: async () => ({}) });
    const onFailure = vi.fn();

    pollForTranscriptionResult({ jobId: 'job-1', onResult: vi.fn(), onFailure });
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 40);

    // Well past the old hundred-attempt idea of five minutes, still going.
    expect(onFailure).not.toHaveBeenCalled();
    expect(fetchResult.mock.calls.length).toBeGreaterThan(11);

    vi.setSystemTime(new Date(EPOCH + POLL_BUDGET_MS + 1000));
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);

    expect(onFailure).toHaveBeenCalledWith(expect.objectContaining({ kind: 'timeout' }));
  });

  // An unreachable server will not produce a result no matter how long we wait,
  // so network failures must not inherit the long transcription budget.
  it('keeps a separate, much smaller budget for network failures', async () => {
    fetchResult.mockRejectedValue(new Error('ECONNREFUSED'));
    const onFailure = vi.fn();

    pollForTranscriptionResult({ jobId: 'job-1', onResult: vi.fn(), onFailure });
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * (MAX_NETWORK_ERRORS - 1));
    expect(onFailure).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3);
    expect(onFailure).toHaveBeenCalledWith(expect.objectContaining({ kind: 'network' }));
    expect(fetchResult.mock.calls.length).toBe(MAX_NETWORK_ERRORS + 1);
  });

  it('abandons silently once isStale turns true', async () => {
    fetchResult.mockResolvedValue({ status: 202, json: async () => ({}) });
    const onResult = vi.fn();
    const onFailure = vi.fn();
    let stale = false;

    pollForTranscriptionResult({
      jobId: 'job-1',
      onResult,
      onFailure,
      isStale: () => stale,
    });
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    const before = fetchResult.mock.calls.length;

    stale = true;
    fetchResult.mockResolvedValue(ready({ text: 'not ours any more', words: [] }));
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5);

    expect(fetchResult.mock.calls.length).toBe(before);
    expect(onResult).not.toHaveBeenCalled();
    expect(onFailure).not.toHaveBeenCalled();
  });

  it('cancel stops its own chain and leaves every other one running', async () => {
    fetchResult.mockResolvedValue({ status: 202, json: async () => ({}) });
    const firstResult = vi.fn();
    const secondResult = vi.fn();

    const first = pollForTranscriptionResult({
      jobId: 'job-1',
      onResult: firstResult,
      onFailure: vi.fn(),
    });
    const second = pollForTranscriptionResult({
      jobId: 'job-2',
      onResult: secondResult,
      onFailure: vi.fn(),
    });
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);

    first.cancel();
    fetchResult.mockResolvedValue(ready({ text: 'second one wins', words: [] }));
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2);

    expect(firstResult).not.toHaveBeenCalled();
    expect(secondResult).toHaveBeenCalledWith(
      expect.objectContaining({ text: 'second one wins' }),
      'job-2',
    );
  });

  // The old shape put the delivery inside the same try as the fetch, so a
  // throw here read as "not ready yet": the loop ran on forever and the caller
  // never learned it had failed.
  it('routes a throw from the delivery handler to onDeliveryError and stops', async () => {
    fetchResult.mockResolvedValue(ready({ text: 'done', words: [] }));
    const onDeliveryError = vi.fn();
    const onFailure = vi.fn();

    pollForTranscriptionResult({
      jobId: 'job-1',
      onResult: () => {
        throw new Error('render blew up');
      },
      onFailure,
      onDeliveryError,
    });
    await vi.advanceTimersByTimeAsync(0);
    const callsAfterThrow = fetchResult.mock.calls.length;
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5);

    expect(onDeliveryError).toHaveBeenCalledTimes(1);
    expect(onFailure).not.toHaveBeenCalled();
    expect(fetchResult.mock.calls.length).toBe(callsAfterThrow);
  });
});
