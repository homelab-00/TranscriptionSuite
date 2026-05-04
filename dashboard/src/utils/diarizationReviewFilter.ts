/**
 * Confidence-threshold filter for the diarization-review view
 * (Issue #104, Story 5.9 AC1).
 *
 * Mirror of `server/backend/core/diarization_review_filter.py`. The
 * dashboard does its own filtering rather than round-trip the server
 * for every dropdown change — one round-trip on view-open fetches all
 * uncertain turns, then filtering is local.
 */

export type FilterMode = 'bottom_5' | 'below_60' | 'below_80' | 'all';

export interface ReviewTurn {
  turn_index: number;
  speaker_id: string | null;
  confidence: number;
  text?: string;
  /**
   * Other speaker_ids in the recording (excluding this turn's current speaker),
   * in first-appearance order. Drives ←/→ attribution-cycling in
   * DiarizationReviewView (Issue #104, Sprint 4 deferred-work no. 4). Optional
   * because older serialized clients omit it; treat undefined as [].
   */
  alternative_speakers?: string[];
}

export function filterLowConfidence<T extends ReviewTurn>(
  turns: ReadonlyArray<T>,
  mode: FilterMode,
): T[] {
  if (mode === 'all') return turns.filter((t) => Number.isFinite(t.confidence));
  if (mode === 'below_60') return turns.filter((t) => t.confidence < 0.6);
  if (mode === 'below_80') return turns.filter((t) => t.confidence < 0.8);
  // bottom_5 — top 5% LOWEST confidence
  const sorted = [...turns].sort((a, b) => a.confidence - b.confidence);
  if (sorted.length === 0) return [];
  const k = Math.max(1, Math.ceil(sorted.length * 0.05));
  return sorted.slice(0, k);
}
