/**
 * useAriaAnnouncer — hook that lets any component push a screen-reader
 * announcement (Issue #104, Story 1.8 AC1).
 *
 * Wraps `useAriaAnnouncerStore.announce()` with a stable callback identity
 * so consumers can pass it to effects without retrigger.
 *
 * Usage:
 *   const announce = useAriaAnnouncer();
 *   announce('Transcription complete');                           // polite
 *   announce('Network connection lost', { politeness: 'assertive' });
 */

import { useCallback } from 'react';

import { useAriaAnnouncerStore, type AriaPoliteness } from '../stores/ariaAnnouncerStore';

interface AnnounceOptions {
  politeness?: AriaPoliteness;
}

export function useAriaAnnouncer(): (message: string, opts?: AnnounceOptions) => void {
  const announce = useAriaAnnouncerStore((s) => s.announce);
  return useCallback(
    (message: string, opts?: AnnounceOptions) => announce(message, opts?.politeness ?? 'polite'),
    [announce],
  );
}
