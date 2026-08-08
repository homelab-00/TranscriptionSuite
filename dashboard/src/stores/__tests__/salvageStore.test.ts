/**
 * salvageStore tests (GH-239 follow-up).
 *
 * The store coordinates three parties: useTranscription/SessionView request
 * immediate checks and record a user-requested drop; useSalvageProgress
 * consumes the drop marker and stamps lastCompletedAt when a salvage ends;
 * SessionView refreshes the recovery banner on that stamp.
 */

import { beforeEach, describe, expect, it } from 'vitest';

import { useSalvageStore } from '../salvageStore';

beforeEach(() => {
  useSalvageStore.setState({ checkNonce: 0, dropRequestedJobId: null, lastCompletedAt: null });
});

describe('salvageStore', () => {
  it('requestCheck bumps the nonce', () => {
    useSalvageStore.getState().requestCheck();
    useSalvageStore.getState().requestCheck();
    expect(useSalvageStore.getState().checkNonce).toBe(2);
  });

  it('markDropRequested / clearDropRequested round-trip', () => {
    useSalvageStore.getState().markDropRequested('job-1');
    expect(useSalvageStore.getState().dropRequestedJobId).toBe('job-1');
    useSalvageStore.getState().clearDropRequested();
    expect(useSalvageStore.getState().dropRequestedJobId).toBeNull();
  });

  it('markSalvageEnded stamps lastCompletedAt', () => {
    expect(useSalvageStore.getState().lastCompletedAt).toBeNull();
    useSalvageStore.getState().markSalvageEnded();
    expect(useSalvageStore.getState().lastCompletedAt).not.toBeNull();
  });
});
