/**
 * DedupChoiceContainer integration test
 * (Issue #104, Sprint 2 carve-out — Item 4).
 *
 * Asserts:
 *   - Container renders nothing when the store has no pending decision.
 *   - Container renders the modal when the store has a pending decision.
 *   - Clicking a button resolves the store's request promise.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { DedupChoiceContainer } from '../DedupChoiceContainer';
import { useDedupChoiceStore } from '../../../src/stores/dedupChoiceStore';

import type { DedupMatch } from '../../../src/api/types';

const sampleMatch: DedupMatch = {
  recording_id: 'job-abc',
  name: 'Sample lecture',
  created_at: '2026-04-15T10:30:00Z',
};

afterEach(() => {
  useDedupChoiceStore.getState().resolveChoice('cancel');
});

describe('DedupChoiceContainer', () => {
  it('renders no modal when nothing is pending', () => {
    render(<DedupChoiceContainer />);
    // The Headless UI Dialog renders to a portal only when open=true; with
    // pendingMatches null, both buttons must be absent from the DOM.
    expect(screen.queryByRole('button', { name: 'Use existing recording' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Create new recording entry' })).toBeNull();
  });

  it('renders the modal when a decision is pending', async () => {
    render(<DedupChoiceContainer />);
    void useDedupChoiceStore.getState().requestChoice([sampleMatch]);
    // findByRole waits for the next render after the store update
    expect(
      await screen.findByRole('button', { name: 'Use existing recording' }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Sample lecture/)).toBeInTheDocument();
  });

  it("clicking 'Use existing' resolves the request promise", async () => {
    render(<DedupChoiceContainer />);
    const promise = useDedupChoiceStore.getState().requestChoice([sampleMatch]);
    fireEvent.click(await screen.findByRole('button', { name: 'Use existing recording' }));
    await expect(promise).resolves.toBe('use_existing');
  });

  it("clicking 'Create new' resolves the request promise", async () => {
    render(<DedupChoiceContainer />);
    const promise = useDedupChoiceStore.getState().requestChoice([sampleMatch]);
    fireEvent.click(await screen.findByRole('button', { name: 'Create new recording entry' }));
    await expect(promise).resolves.toBe('create_new');
  });
});
