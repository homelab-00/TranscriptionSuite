/**
 * ARIA-live announcer store (Issue #104, Story 1.8).
 *
 * Centralised state for two `<div role="status" aria-live="...">` regions
 * mounted at app root by `<AriaLiveRegion />`. Components call
 * `useAriaAnnouncer()` (hook) instead of poking the DOM directly so
 * screen-reader announcements are testable via the store.
 *
 * Politeness levels follow WAI-ARIA conventions:
 *   - "polite"     — wait for current speech, deliver next idle slot
 *   - "assertive"  — interrupt, deliver immediately
 *
 * Each region clears itself 5 s after a write so an identical message
 * can re-announce (otherwise the same string would be coalesced and
 * silently dropped by the AT).
 */

import { create } from 'zustand';

export type AriaPoliteness = 'polite' | 'assertive';

const CLEAR_DELAY_MS = 5_000;

interface AriaAnnouncerState {
  politeMessage: string;
  assertiveMessage: string;
  /** internal — exposes a setter the hook re-exports */
  announce: (message: string, politeness: AriaPoliteness) => void;
}

export const useAriaAnnouncerStore = create<AriaAnnouncerState>((set) => ({
  politeMessage: '',
  assertiveMessage: '',
  announce: (message, politeness) => {
    if (politeness === 'assertive') {
      set({ assertiveMessage: message });
      setTimeout(() => {
        useAriaAnnouncerStore.setState((s) =>
          s.assertiveMessage === message ? { assertiveMessage: '' } : s,
        );
      }, CLEAR_DELAY_MS);
    } else {
      set({ politeMessage: message });
      setTimeout(() => {
        useAriaAnnouncerStore.setState((s) =>
          s.politeMessage === message ? { politeMessage: '' } : s,
        );
      }, CLEAR_DELAY_MS);
    }
  },
}));
