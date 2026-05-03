/**
 * ariaAnnouncerStore tests (Issue #104, Story 1.8 AC1).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useAriaAnnouncerStore } from '../ariaAnnouncerStore';

beforeEach(() => {
  vi.useFakeTimers();
  useAriaAnnouncerStore.setState({ politeMessage: '', assertiveMessage: '' });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('ariaAnnouncerStore', () => {
  it('writes a polite message to the polite region', () => {
    useAriaAnnouncerStore.getState().announce('Saved', 'polite');
    expect(useAriaAnnouncerStore.getState().politeMessage).toBe('Saved');
    expect(useAriaAnnouncerStore.getState().assertiveMessage).toBe('');
  });

  it('writes an assertive message to the assertive region', () => {
    useAriaAnnouncerStore.getState().announce('Failed', 'assertive');
    expect(useAriaAnnouncerStore.getState().assertiveMessage).toBe('Failed');
    expect(useAriaAnnouncerStore.getState().politeMessage).toBe('');
  });

  it('clears the polite region after the 5s coalescence window', () => {
    useAriaAnnouncerStore.getState().announce('Hello', 'polite');
    expect(useAriaAnnouncerStore.getState().politeMessage).toBe('Hello');
    vi.advanceTimersByTime(5_000);
    expect(useAriaAnnouncerStore.getState().politeMessage).toBe('');
  });

  it('clears the assertive region after the 5s coalescence window', () => {
    useAriaAnnouncerStore.getState().announce('Critical', 'assertive');
    vi.advanceTimersByTime(5_000);
    expect(useAriaAnnouncerStore.getState().assertiveMessage).toBe('');
  });

  it('keeps a newer message intact when an older clear-timer fires', () => {
    useAriaAnnouncerStore.getState().announce('First', 'polite');
    vi.advanceTimersByTime(2_000);
    useAriaAnnouncerStore.getState().announce('Second', 'polite');
    // Original 5s timer for "First" fires now (3s remaining), but the message
    // is "Second" — clear-guard should detect mismatch and leave it alone.
    vi.advanceTimersByTime(3_000);
    expect(useAriaAnnouncerStore.getState().politeMessage).toBe('Second');
  });
});
