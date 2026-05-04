/**
 * PersistentInfoBanner — persistent amber/blue banner with optional CTA.
 *
 * Issue #104, Story 5.7 (UX-DR2). Mirrors `QueuePausedBanner` styling so
 * the visual language is consistent. Used by AudioNoteModal to surface
 * the "Review uncertain turns" prompt when a recording has low-confidence
 * diarization (banner_visible() predicate from the ADR-009 lifecycle).
 *
 * Persistence semantics:
 *   - Banner does NOT auto-dismiss on time, navigation, or app restart
 *     (R-EL19, R-EL20, NFR23). The parent decides when to render it
 *     based on the lifecycle state.
 *   - The banner fires an ARIA-live announcement on mount (FR52) so
 *     screen-reader users hear "Transcription complete. N of M turn
 *     boundaries flagged low-confidence" when the recording opens.
 */

import { useEffect } from 'react';
import { useAriaAnnouncer } from '../../src/hooks/useAriaAnnouncer';

interface Props {
  message: string;
  ctaLabel?: string;
  onCta?: () => void;
  /** Severity controls colour — `warning` is amber, `info` is blue. */
  severity?: 'warning' | 'info';
  /**
   * One-shot ARIA-live announcement fired when the banner mounts.
   * Skipped when undefined; updates when the value changes.
   */
  ariaAnnouncement?: string;
}

export function PersistentInfoBanner({
  message,
  ctaLabel,
  onCta,
  severity = 'warning',
  ariaAnnouncement,
}: Props) {
  const announce = useAriaAnnouncer();
  useEffect(() => {
    if (ariaAnnouncement) announce(ariaAnnouncement);
  }, [ariaAnnouncement, announce]);

  const palette =
    severity === 'warning'
      ? 'border-amber-400/30 bg-amber-400/10 text-amber-400'
      : 'border-blue-400/30 bg-blue-400/10 text-blue-300';
  const ctaPalette =
    severity === 'warning'
      ? 'bg-amber-400/20 text-amber-300 hover:bg-amber-400/30'
      : 'bg-blue-400/20 text-blue-200 hover:bg-blue-400/30';

  return (
    <div
      role="status"
      className={`flex items-center justify-between gap-3 border px-4 py-2 text-sm ${palette}`}
    >
      <span>{message}</span>
      {ctaLabel && onCta && (
        <button
          type="button"
          onClick={onCta}
          className={`rounded px-3 py-1 text-xs font-medium transition-colors ${ctaPalette}`}
        >
          {ctaLabel}
        </button>
      )}
    </div>
  );
}
