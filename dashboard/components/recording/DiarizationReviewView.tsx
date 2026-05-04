/**
 * DiarizationReviewView — focused review for low-confidence turns
 * (Issue #104, Story 5.9 + Diarization-Review Keyboard Contract).
 *
 * This component implements the WAI-ARIA Authoring Practices composite-
 * widget pattern (`role="listbox"` with `aria-activedescendant`):
 *
 *   - The turn-list is a SINGLE tab stop (Tab/Shift+Tab traverse
 *     elements OUTSIDE the list).
 *   - Inside the list, ↑/↓ move the selection without changing tab order.
 *   - ←/→ cycle attribution within the focused turn.
 *   - Enter accepts the current attribution, advances to next.
 *   - Esc skips the current turn, advances to next.
 *   - Space bulk-accepts every visible turn (respects active filter).
 *
 * Tab order in the surrounding view (Story 5.9 AC3):
 *   review-banner → confidence-filter → turn-list → bulk-action → "Run summary now"
 *
 * Cross-references: PRD §900–920 (canonical keyboard contract),
 * FR54 (turn announcement), FR51 (keyboard operability), R-EL15.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAriaAnnouncer } from '../../src/hooks/useAriaAnnouncer';
import {
  filterLowConfidence,
  type FilterMode,
  type ReviewTurn,
} from '../../src/utils/diarizationReviewFilter';
import { bucketFor } from '../../src/utils/confidenceBuckets';

interface ReviewDecision {
  turn_index: number;
  decision: 'accept' | 'skip';
  speaker_id: string | null;
}

interface Props {
  /** All turns surfaced as candidates for review (already filtered to <80% by caller). */
  turns: ReadonlyArray<ReviewTurn>;
  /** Display label for each speaker_id (alias-aware). */
  speakerLabel: (speakerId: string | null | undefined) => string;
  /**
   * Submit handler. Called when user clicks "Run summary now".
   * Returns a promise so the button can show a loading state.
   */
  onComplete: (decisions: ReadonlyArray<ReviewDecision>) => Promise<void>;
  /** Optional cancel handler — closes the view without submitting. */
  onCancel?: () => void;
}

const FILTER_OPTIONS: { value: FilterMode; label: string }[] = [
  { value: 'bottom_5', label: 'bottom 5% confidence' },
  { value: 'below_60', label: '< 60%' },
  { value: 'below_80', label: '< 80%' },
  { value: 'all', label: 'all uncertain' },
];

export function DiarizationReviewView({ turns, speakerLabel, onComplete, onCancel }: Props) {
  const [filterMode, setFilterMode] = useState<FilterMode>('below_80');
  const [activeIndex, setActiveIndex] = useState(0);
  const [decisions, setDecisions] = useState<Map<number, ReviewDecision>>(new Map());
  const [submitting, setSubmitting] = useState(false);
  const announce = useAriaAnnouncer();
  const listRef = useRef<HTMLDivElement>(null);

  const visibleTurns = useMemo(() => filterLowConfidence(turns, filterMode), [turns, filterMode]);

  // Keep activeIndex within bounds when the filter changes
  useEffect(() => {
    if (activeIndex >= visibleTurns.length) {
      setActiveIndex(Math.max(0, visibleTurns.length - 1));
    }
  }, [visibleTurns.length, activeIndex]);

  const announceTurn = useCallback(
    (turn: ReviewTurn | undefined) => {
      if (!turn) return;
      const bucket = bucketFor(turn.confidence);
      announce(
        `${turn.text ?? ''} · current speaker: ${speakerLabel(turn.speaker_id)} · confidence: ${bucket}`,
      );
    },
    [announce, speakerLabel],
  );

  const moveSelection = useCallback(
    (delta: number) => {
      setActiveIndex((idx) => {
        const next = Math.max(0, Math.min(visibleTurns.length - 1, idx + delta));
        if (next !== idx) announceTurn(visibleTurns[next]);
        return next;
      });
    },
    [visibleTurns, announceTurn],
  );

  const recordDecision = useCallback(
    (decision: 'accept' | 'skip', advance: boolean) => {
      const turn = visibleTurns[activeIndex];
      if (!turn) return;
      setDecisions((prev) => {
        const next = new Map(prev);
        next.set(turn.turn_index, {
          turn_index: turn.turn_index,
          decision,
          speaker_id: turn.speaker_id,
        });
        return next;
      });
      if (advance) moveSelection(+1);
    },
    [activeIndex, visibleTurns, moveSelection],
  );

  const bulkAccept = useCallback(() => {
    setDecisions((prev) => {
      const next = new Map(prev);
      for (const t of visibleTurns) {
        next.set(t.turn_index, {
          turn_index: t.turn_index,
          decision: 'accept',
          speaker_id: t.speaker_id,
        });
      }
      return next;
    });
    announce(`Bulk-accepted ${visibleTurns.length} turns.`);
  }, [visibleTurns, announce]);

  const onListKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        moveSelection(+1);
        break;
      case 'ArrowUp':
        e.preventDefault();
        moveSelection(-1);
        break;
      case 'ArrowLeft':
      case 'ArrowRight':
        e.preventDefault();
        // Attribution cycling — placeholder for now (Sprint 4 will wire the
        // alternative-speaker list per turn). The contract requires the keys
        // be consumed (not bubble), so we preventDefault even when no-op.
        break;
      case 'Enter':
        e.preventDefault();
        recordDecision('accept', true);
        break;
      case 'Escape':
        e.preventDefault();
        recordDecision('skip', true);
        break;
      case ' ': {
        e.preventDefault();
        bulkAccept();
        break;
      }
      default:
        // bubble
        break;
    }
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      // Default decision for unreviewed visible turns: accept (matches the
      // bulk-accept default per AC2).
      const allDecisions: ReviewDecision[] = visibleTurns.map((t) => {
        const existing = decisions.get(t.turn_index);
        return (
          existing ?? {
            turn_index: t.turn_index,
            decision: 'accept',
            speaker_id: t.speaker_id,
          }
        );
      });
      await onComplete(allDecisions);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-4 rounded-lg border border-white/10 bg-black/30 p-4">
      <header className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-100">Review uncertain turns</h2>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="text-xs text-slate-400 hover:text-slate-200"
          >
            Cancel
          </button>
        )}
      </header>

      <div>
        <label className="text-xs text-slate-400">
          Show:
          <select
            value={filterMode}
            onChange={(e) => setFilterMode(e.target.value as FilterMode)}
            className="ml-2 rounded border border-white/10 bg-black/40 px-2 py-1 text-sm text-slate-200"
          >
            {FILTER_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div
        ref={listRef}
        role="listbox"
        aria-label="Uncertain turns to review"
        aria-activedescendant={
          visibleTurns[activeIndex] ? `dr-turn-${visibleTurns[activeIndex].turn_index}` : undefined
        }
        tabIndex={0}
        onKeyDown={onListKeyDown}
        onFocus={() => announceTurn(visibleTurns[activeIndex])}
        className="max-h-96 overflow-y-auto rounded border border-white/10 focus:ring-1 focus:ring-amber-400/40 focus:outline-none"
      >
        {visibleTurns.length === 0 ? (
          <div className="p-3 text-sm text-slate-500">No turns match this filter.</div>
        ) : (
          visibleTurns.map((t, i) => {
            const decision = decisions.get(t.turn_index);
            const decisionTag =
              decision?.decision === 'accept'
                ? 'accepted'
                : decision?.decision === 'skip'
                  ? 'skipped'
                  : null;
            return (
              <div
                key={t.turn_index}
                id={`dr-turn-${t.turn_index}`}
                role="option"
                aria-selected={i === activeIndex}
                aria-label={`${t.text ?? ''} · current speaker: ${speakerLabel(t.speaker_id)} · confidence: ${bucketFor(t.confidence)}`}
                onClick={() => setActiveIndex(i)}
                className={`cursor-pointer border-b border-white/5 px-3 py-2 text-sm last:border-b-0 ${
                  i === activeIndex ? 'bg-amber-400/10' : 'hover:bg-white/5'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-slate-200">{speakerLabel(t.speaker_id)}</span>
                  <span className="text-xs text-slate-400">
                    {Math.round(t.confidence * 100)}%
                    {decisionTag && (
                      <span className="ml-2 rounded bg-slate-500/20 px-1 py-0.5 text-[10px] uppercase">
                        {decisionTag}
                      </span>
                    )}
                  </span>
                </div>
                <div className="text-slate-300">{t.text}</div>
              </div>
            );
          })
        )}
      </div>

      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={bulkAccept}
          aria-label="Mark all visible turns as auto-accept best guess"
          className="rounded border border-white/10 px-3 py-1 text-xs text-slate-300 hover:bg-white/10"
        >
          Mark all visible as auto-accept best guess
        </button>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={submitting}
          className="rounded bg-amber-400/20 px-4 py-2 text-sm font-semibold text-amber-200 hover:bg-amber-400/30 disabled:opacity-50"
        >
          {submitting ? 'Submitting…' : 'Run summary now'}
        </button>
      </div>
    </div>
  );
}
