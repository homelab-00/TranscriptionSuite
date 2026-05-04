/**
 * Per-turn confidence chip (Issue #104, Story 5.5 — UX-DR3).
 *
 * Visual buckets:
 *   - high   (≥80%) → no chip rendered (zero visual noise)
 *   - medium (60–80%) → neutral chip ("medium")
 *   - low    (<60%)  → amber chip ("low")
 *
 * Tooltip shows exact percentage on hover. ARIA exposure:
 *   - aria-label="confidence: <bucket>"
 *   - role="status" so the chip is in the virtual buffer for screen readers
 *   - tooltip is the native title attribute (NVDA + JAWS read it on focus)
 *
 * The chip is rendered next to a speaker label — its CSS class set is part
 * of the UI contract (`dashboard/ui-contract/transcription-suite-ui.contract.yaml`).
 */

import { bucketFor } from '../../src/utils/confidenceBuckets';

interface Props {
  /** 0..1 confidence value. Negative or NaN is treated as low. */
  confidence: number;
  /** Optional override — defaults to "ml-2 inline-flex". */
  className?: string;
}

export function ConfidenceChip({ confidence, className }: Props) {
  // Defensive: NaN or out-of-range values fall through to "low" bucket.
  const safe = Number.isFinite(confidence) ? Math.max(0, Math.min(1, confidence)) : 0;
  const bucket = bucketFor(safe);
  if (bucket === 'high') return null;

  const palette =
    bucket === 'low'
      ? 'bg-amber-500/20 text-amber-200 border-amber-500/40'
      : 'bg-slate-500/20 text-slate-300 border-slate-500/40';
  const pct = Math.round(safe * 100);

  return (
    <span
      role="status"
      aria-label={`confidence: ${bucket}`}
      title={`confidence: ${pct}%`}
      data-bucket={bucket}
      className={`${className ?? 'ml-2 inline-flex'} items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${palette}`}
    >
      {bucket}
    </span>
  );
}
