/**
 * resultPolling - the one way a finished transcript reaches the UI when the
 * WebSocket cannot carry it.
 *
 * Two paths need this and used to own separate, unequal copies of it: the
 * socket-drop recovery inside useTranscription, and the Retry button in
 * SessionView. The SessionView copy was the weaker one, and its weaknesses are
 * what stranded a completed transcript in the database with no way to reach it:
 * an attempt counter that undercounted real elapsed time, a shared cancel flag
 * that let two overlapping retries write into each other, and a try block wide
 * enough that a throw while DELIVERING the result read as "not ready yet",
 * so the loop ran on forever and the caller never cleared its in-flight flag.
 *
 * Everything here goes through apiClient so the request carries the absolute
 * base URL. A bare relative fetch resolves against the packaged renderer
 * file:// origin and never reaches the backend (GH-202).
 */

import { apiClient } from '../api/client';
import type { TranscriptionResult } from '../hooks/useTranscription';

/** Gap between attempts. */
export const POLL_INTERVAL_MS = 3000;

/**
 * How long to keep polling before giving up, as wall clock rather than a count
 * of attempts. An attempt count ignores request latency, so it always
 * undercounts the time actually spent. Sized for the slow case: the server has
 * to transcribe the whole recording before the result exists, so the wait
 * scales with the length of the recording, not with the round trip.
 */
export const POLL_BUDGET_MS = 15 * 60 * 1000;

/**
 * Network failures keep their own much smaller budget. An unreachable server
 * will not produce a result no matter how long we wait, so this must not
 * inherit the long transcription budget above.
 */
export const MAX_NETWORK_ERRORS = 10;

/**
 * Why a poll stopped without a transcript.
 *
 * - `failed`: the server says the job failed (HTTP 410). Terminal.
 * - `unavailable`: 404, or any status the endpoint is not documented to
 *   return. Terminal.
 * - `timeout`: still processing when the wall clock budget ran out. The result
 *   is NOT lost: it stays in the database and the recovery banner finds it.
 * - `network`: the request itself kept failing.
 */
export type PollFailureKind = 'failed' | 'unavailable' | 'timeout' | 'network';

export interface PollFailure {
  kind: PollFailureKind;
  /** Default wording, suitable for putting straight on screen. */
  message: string;
  /** HTTP status that produced it, when there was one. */
  status?: number;
  /**
   * Raw response body for the statuses that carry a reason. The 410 branch of
   * the result endpoint returns three distinct explanations, and the user needs
   * the specific one.
   */
  body?: string;
}

/** Cancel handle. One per invocation, so cancelling one never touches another. */
export interface PollHandle {
  cancel: () => void;
}

/**
 * The snake_case payload the durability endpoints return under `result`.
 * Declared rather than inlined so the mapping below cannot silently drop a
 * field when the server grows one.
 */
export interface RawTranscriptionResult {
  text?: string;
  words?: TranscriptionResult['words'];
  language?: string;
  duration?: number;
  partial?: boolean;
  partial_reason?: string | null;
  num_speakers?: number;
  diarization?: TranscriptionResult['diarization'];
}

/**
 * Map a persisted result onto the hook's shape.
 *
 * Single source of truth on purpose. Three call sites used to hand-map this and
 * two of them dropped fields: a retried job lost its speaker labels, and the
 * recovery banner rendered a PARTIAL transcript as if it were whole, with no
 * amber banner and no Retry affordance.
 */
export function toTranscriptionResult(
  raw: RawTranscriptionResult | null | undefined,
): TranscriptionResult {
  const r = raw ?? {};
  return {
    text: r.text ?? '',
    words: r.words ?? [],
    language: r.language,
    duration: r.duration,
    partial: r.partial ?? false,
    partialReason: r.partial_reason ?? null,
    numSpeakers: r.num_speakers ?? 0,
    diarization: r.diarization,
  };
}

export interface PollOptions {
  /** Job whose result to wait for. */
  jobId: string;
  /** Called once, with the mapped result, when the server returns 200. */
  onResult: (result: TranscriptionResult, jobId: string) => void;
  /** Called once when the poll stops without a transcript. */
  onFailure: (failure: PollFailure) => void;
  /**
   * Called when `onResult` itself throws. Without this the caller would be left
   * with its in-flight flag stuck on, which is exactly the bug that made a
   * Retry button say "Retrying..." forever.
   */
  onDeliveryError?: (err: unknown, jobId: string) => void;
  /**
   * Return true to abandon the poll silently. Used by the hook to drop a poll
   * whose session has been replaced by a newer one.
   */
  isStale?: () => boolean;
  intervalMs?: number;
  budgetMs?: number;
  maxNetworkErrors?: number;
}

/** What one attempt learned, before any state is written. */
type Envelope =
  | { kind: 'ready'; result: TranscriptionResult }
  | { kind: 'pending' }
  | { kind: 'gone'; status: number; body?: string }
  | { kind: 'missing'; status: number };

async function readBody(resp: Response): Promise<string | undefined> {
  try {
    return await resp.text();
  } catch {
    return undefined;
  }
}

/**
 * Poll the durability endpoint until the transcript arrives or the budget runs
 * out. The first attempt fires immediately; the returned handle cancels this
 * invocation and only this one.
 */
export function pollForTranscriptionResult(options: PollOptions): PollHandle {
  const {
    jobId,
    onResult,
    onFailure,
    onDeliveryError,
    isStale,
    intervalMs = POLL_INTERVAL_MS,
    budgetMs = POLL_BUDGET_MS,
    maxNetworkErrors = MAX_NETWORK_ERRORS,
  } = options;

  let cancelled = false;
  let networkErrors = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;

  // Read once rather than per attempt, so a machine that suspends mid poll
  // gives up on waking instead of polling on for another full budget.
  const deadline = Date.now() + budgetMs;

  const abandoned = (): boolean => cancelled || (isStale ? isStale() : false);

  const schedule = (): void => {
    timer = setTimeout(() => {
      void attempt();
    }, intervalMs);
  };

  const attempt = async (): Promise<void> => {
    if (abandoned()) return;

    // Deliberately narrow. Only the request and reading its body live in here.
    // Delivery happens below, outside the catch, because a throw while
    // delivering is not a "not ready yet" and must never be retried as one.
    let envelope: Envelope;
    try {
      const resp = await apiClient.fetchTranscriptionResult(jobId);
      if (abandoned()) return;
      if (resp.status === 200) {
        const data = await resp.json();
        envelope = { kind: 'ready', result: toTranscriptionResult(data?.result) };
      } else if (resp.status === 202) {
        envelope = { kind: 'pending' };
      } else if (resp.status === 410) {
        envelope = { kind: 'gone', status: resp.status, body: await readBody(resp) };
      } else {
        envelope = { kind: 'missing', status: resp.status };
      }
    } catch {
      if (abandoned()) return;
      networkErrors += 1;
      if (networkErrors <= maxNetworkErrors) {
        schedule();
        return;
      }
      onFailure({ kind: 'network', message: 'Could not retrieve transcription result' });
      return;
    }

    if (abandoned()) return;

    switch (envelope.kind) {
      case 'ready':
        try {
          onResult(envelope.result, jobId);
        } catch (err) {
          onDeliveryError?.(err, jobId);
        }
        return;
      case 'pending':
        if (Date.now() < deadline) {
          schedule();
          return;
        }
        onFailure({ kind: 'timeout', message: 'Transcription result unavailable', status: 202 });
        return;
      case 'gone':
        onFailure({
          kind: 'failed',
          message: 'Transcription failed on server',
          status: envelope.status,
          body: envelope.body,
        });
        return;
      default:
        onFailure({
          kind: 'unavailable',
          message: 'Transcription result unavailable',
          status: envelope.status,
        });
        return;
    }
  };

  void attempt();

  return {
    cancel: () => {
      cancelled = true;
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
    },
  };
}
