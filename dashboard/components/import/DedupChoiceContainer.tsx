/**
 * Top-level mount for the DedupPromptModal (Issue #104, Sprint 2 Item 4).
 *
 * Subscribes to `useDedupChoiceStore` and renders the modal whenever a
 * pending decision exists. The modal is presentational — this container
 * is the only place that knows how to resolve the store's promise.
 *
 * The store guarantees at most one pending decision (see its docstring),
 * so we always render the first match and defer multi-match UX to a
 * future iteration if it becomes a real user concern.
 */

import { useDedupChoiceStore } from '../../src/stores/dedupChoiceStore';
import { DedupPromptModal } from './DedupPromptModal';

export function DedupChoiceContainer() {
  const pendingMatches = useDedupChoiceStore((s) => s.pendingMatches);
  const resolveChoice = useDedupChoiceStore((s) => s.resolveChoice);

  const open = pendingMatches !== null && pendingMatches.length > 0;
  const firstMatch = open ? pendingMatches[0] : null;

  return <DedupPromptModal open={open} match={firstMatch} onChoice={resolveChoice} />;
}
