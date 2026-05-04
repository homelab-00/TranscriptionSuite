/**
 * Per-turn confidence bucket math (Issue #104, Story 5.5 — UX-DR3).
 *
 * Mirrors `server/backend/core/diarization_confidence.py` constants. The
 * sync test in `server/backend/tests/test_confidence_buckets_sync.py`
 * reads this file and asserts the constants match the Python side.
 */

export const HIGH_CONFIDENCE_THRESHOLD = 0.8;
export const LOW_CONFIDENCE_THRESHOLD = 0.6;

export type Bucket = 'high' | 'medium' | 'low';

export function bucketFor(confidence: number): Bucket {
  if (confidence >= HIGH_CONFIDENCE_THRESHOLD) return 'high';
  if (confidence >= LOW_CONFIDENCE_THRESHOLD) return 'medium';
  return 'low';
}
