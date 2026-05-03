/**
 * AriaLiveRegion — visually-hidden ARIA-live regions mounted at the app
 * root (Issue #104, Story 1.8 AC1).
 *
 * Two regions per WAI-ARIA convention: one polite, one assertive. The
 * `sr-only` Tailwind utility class hides them from sighted users while
 * keeping them in the accessibility tree.
 *
 * Mount once near the top of the React tree (in App.tsx). Components
 * announce via `useAriaAnnouncer()` rather than rendering their own
 * regions.
 */

import React from 'react';

import { useAriaAnnouncerStore } from '../src/stores/ariaAnnouncerStore';

export const AriaLiveRegion: React.FC = () => {
  const polite = useAriaAnnouncerStore((s) => s.politeMessage);
  const assertive = useAriaAnnouncerStore((s) => s.assertiveMessage);
  return (
    <>
      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {polite}
      </div>
      <div role="status" aria-live="assertive" aria-atomic="true" className="sr-only">
        {assertive}
      </div>
    </>
  );
};
