/**
 * useDiarizationReview — ADR-009 lifecycle state for a recording
 * (Issue #104, Stories 5.7 / 5.9).
 *
 * Exposes:
 *   - `state.status` — 'pending' | 'in_review' | 'completed' | 'released' | null
 *   - `openReview()` — POST action='open' (pending → in_review)
 *   - `completeReview(reviewedTurns)` — POST action='complete' with payload
 */

import { useCallback, useEffect, useState } from 'react';
import { apiClient } from '../api/client';

export type ReviewStatus = 'pending' | 'in_review' | 'completed' | 'released' | null;

export interface ReviewState {
  recording_id: number;
  status: ReviewStatus;
  reviewed_turns_json: string | null;
}

export interface UseDiarizationReviewState {
  state: ReviewState | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
  openReview: () => Promise<ReviewState | null>;
  completeReview: (
    reviewedTurns: ReadonlyArray<{
      turn_index: number;
      decision: string;
      speaker_id?: string | null;
    }>,
  ) => Promise<ReviewState | null>;
  /** Convenience: should we render the persistent banner? */
  bannerVisible: boolean;
}

export function useDiarizationReview(recordingId: number | null): UseDiarizationReviewState {
  const [state, setState] = useState<ReviewState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    if (recordingId === null || !Number.isFinite(recordingId) || recordingId <= 0) {
      setState(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const resp = await apiClient.getDiarizationReview(recordingId);
      setState(resp);
    } catch (err) {
      setState(null);
      setError(err instanceof Error ? err.message : 'Failed to load review state');
    } finally {
      setLoading(false);
    }
  }, [recordingId]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  const openReview = useCallback(async (): Promise<ReviewState | null> => {
    if (recordingId === null) return null;
    const resp = await apiClient.submitDiarizationReview(recordingId, { action: 'open' });
    setState(resp);
    return resp;
  }, [recordingId]);

  const completeReview = useCallback(
    async (
      reviewedTurns: ReadonlyArray<{
        turn_index: number;
        decision: string;
        speaker_id?: string | null;
      }>,
    ): Promise<ReviewState | null> => {
      if (recordingId === null) return null;
      const resp = await apiClient.submitDiarizationReview(recordingId, {
        action: 'complete',
        reviewed_turns: [...reviewedTurns],
      });
      setState(resp);
      return resp;
    },
    [recordingId],
  );

  const bannerVisible =
    state !== null && (state.status === 'pending' || state.status === 'in_review');

  return { state, loading, error, refresh: fetch, openReview, completeReview, bannerVisible };
}
