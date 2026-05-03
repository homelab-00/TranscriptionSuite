/**
 * Dedup-choice store (Issue #104, Sprint 2 carve-out — Item 4).
 *
 * Mediates between the import queue (which discovers duplicates from the
 * server's dedup_matches response) and the user-facing DedupPromptModal
 * (which renders the question and emits a choice). The queue calls
 * `requestChoice(matches)` and awaits the returned promise; the modal
 * resolves the promise via `resolveChoice(...)` when the user clicks.
 *
 * Invariants:
 *   - At most one pending decision at a time. A second `requestChoice`
 *     while one is pending replaces the prior request and resolves the
 *     prior promise with `'cancel'` (defensive: should not happen in
 *     practice because the queue serializes its own iterations, but if
 *     two unrelated callers race, the older request is treated as user-
 *     cancelled rather than orphaning its promise).
 *   - `resolveChoice` is a no-op when nothing is pending, so spurious
 *     calls (e.g. modal close after the queue already moved on) are safe.
 *   - The modal is purely presentational — it never calls back into the
 *     queue. The store IS the contract surface.
 */

import { create } from 'zustand';

import type { DedupChoice } from '../../components/import/DedupPromptModal';
import type { DedupMatch } from '../api/types';

interface DedupChoiceState {
  pendingMatches: DedupMatch[] | null;
  requestChoice: (matches: DedupMatch[]) => Promise<DedupChoice>;
  resolveChoice: (choice: DedupChoice) => void;
}

export const useDedupChoiceStore = create<DedupChoiceState>((set) => {
  // Resolver is module-scope (not React state) so resolving is synchronous
  // and never re-renders. The promise consumer (importQueueStore) doesn't
  // need React; it just awaits.
  let activeResolver: ((choice: DedupChoice) => void) | null = null;

  return {
    pendingMatches: null,

    requestChoice(matches) {
      // Defensive: if a prior request is unresolved, cancel it so its
      // awaiter does not leak. The new request supersedes.
      const prior = activeResolver;
      activeResolver = null;
      if (prior) prior('cancel');

      return new Promise<DedupChoice>((resolve) => {
        activeResolver = resolve;
        set({ pendingMatches: matches });
      });
    },

    resolveChoice(choice) {
      const resolver = activeResolver;
      if (!resolver) return; // no-op when nothing pending
      activeResolver = null;
      set({ pendingMatches: null });
      resolver(choice);
    },
  };
});
