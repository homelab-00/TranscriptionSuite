/**
 * Dedup-choice store tests (Issue #104, Sprint 2 carve-out — Item 4).
 *
 * Verifies the store-level contract used by importQueueStore <-> the
 * DedupChoiceContainer:
 *   - requestChoice returns a pending Promise
 *   - resolveChoice resolves it with the picked value
 *   - state clears after resolve
 *   - resolveChoice is a no-op when nothing is pending
 *   - requestChoice while one is pending cancels the prior request
 */

import { afterEach, describe, expect, it } from 'vitest';

import { useDedupChoiceStore } from '../dedupChoiceStore';

import type { DedupMatch } from '../../api/types';

const sampleMatch: DedupMatch = {
  recording_id: 'job-abc',
  name: 'Lecture A',
  created_at: '2026-04-15T10:30:00Z',
};

afterEach(() => {
  // Reset store state — drain any pending decision so tests don't leak.
  useDedupChoiceStore.getState().resolveChoice('cancel');
});

describe('useDedupChoiceStore', () => {
  it('starts with no pending matches', () => {
    expect(useDedupChoiceStore.getState().pendingMatches).toBeNull();
  });

  it('requestChoice sets pendingMatches and returns a Promise', () => {
    const promise = useDedupChoiceStore.getState().requestChoice([sampleMatch]);
    expect(useDedupChoiceStore.getState().pendingMatches).toEqual([sampleMatch]);
    expect(promise).toBeInstanceOf(Promise);
  });

  it('resolveChoice resolves the promise with the picked value', async () => {
    const promise = useDedupChoiceStore.getState().requestChoice([sampleMatch]);
    useDedupChoiceStore.getState().resolveChoice('use_existing');
    await expect(promise).resolves.toBe('use_existing');
  });

  it('resolveChoice clears pendingMatches', async () => {
    const promise = useDedupChoiceStore.getState().requestChoice([sampleMatch]);
    useDedupChoiceStore.getState().resolveChoice('create_new');
    await promise;
    expect(useDedupChoiceStore.getState().pendingMatches).toBeNull();
  });

  it('resolveChoice is a no-op when nothing is pending', () => {
    expect(() => useDedupChoiceStore.getState().resolveChoice('use_existing')).not.toThrow();
    expect(useDedupChoiceStore.getState().pendingMatches).toBeNull();
  });

  it('a second requestChoice cancels the prior one', async () => {
    const first = useDedupChoiceStore.getState().requestChoice([sampleMatch]);
    const second = useDedupChoiceStore
      .getState()
      .requestChoice([{ ...sampleMatch, recording_id: 'other' }]);
    // First should resolve to 'cancel' because it was superseded
    await expect(first).resolves.toBe('cancel');
    // Second is still pending; resolving it must work
    useDedupChoiceStore.getState().resolveChoice('create_new');
    await expect(second).resolves.toBe('create_new');
  });
});
