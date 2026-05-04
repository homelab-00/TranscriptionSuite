/**
 * useDiarizationConfidence — fetches per-turn confidence (Issue #104, Story 5.5).
 *
 * Mirrors `useRecordingAliases` in style. Returns a Map keyed on
 * `turn_index` for O(1) lookup during transcript rendering.
 */

import { useCallback, useEffect, useState } from 'react';
import { apiClient } from '../api/client';

export interface TurnConfidence {
  turn_index: number;
  speaker_id: string | null;
  confidence: number;
}

export interface ConfidenceState {
  /** Map keyed by turn_index → confidence value. Empty when no data. */
  byTurn: Map<number, number>;
  /** Raw list (for callers that need the full payload). */
  turns: TurnConfidence[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

interface ConfidenceResponse {
  recording_id: number;
  turns: TurnConfidence[];
}

export function useDiarizationConfidence(recordingId: number | null): ConfidenceState {
  const [turns, setTurns] = useState<TurnConfidence[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    if (recordingId === null || !Number.isFinite(recordingId) || recordingId <= 0) {
      setTurns([]);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const resp: ConfidenceResponse =
        await apiClient.getRecordingDiarizationConfidence(recordingId);
      setTurns(resp.turns ?? []);
    } catch (err) {
      // Non-fatal: missing confidence is rendered as "no chip" (Story 5.5
      // graceful fallback). We don't surface a user-visible error.
      setTurns([]);
      setError(err instanceof Error ? err.message : 'Failed to load confidence');
    } finally {
      setLoading(false);
    }
  }, [recordingId]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  const byTurn = new Map(turns.map((t) => [t.turn_index, t.confidence] as const));
  return { byTurn, turns, loading, error, refresh: fetch };
}
