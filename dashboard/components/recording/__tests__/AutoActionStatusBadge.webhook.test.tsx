/**
 * AutoActionStatusBadge — webhook action type (Issue #104, Sprint 5, Story 7.7).
 *
 * Sprint 4 covers AC1–AC5 against ``auto_summary``/``auto_export``;
 * Sprint 5 extends ``AutoActionType`` with ``webhook`` and adds two
 * webhook-specific status strings (``in_flight``, ``failed`` carrying
 * delivery error) plus the retry-enabled ``manual_intervention_required``
 * surface that mirrors the auto-actions escalation policy.
 *
 * These tests assert ONLY the webhook-specific deltas; the underlying
 * primitives are exercised by ``AutoActionStatusBadge.test.tsx``.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AutoActionStatusBadge, statusToBadgeProps } from '../AutoActionStatusBadge';

vi.mock('../../../src/hooks/useAriaAnnouncer', () => ({
  useAriaAnnouncer: () => () => {},
}));

// ──────────────────────────────────────────────────────────────────────────
// statusToBadgeProps — webhook status mapping
// ──────────────────────────────────────────────────────────────────────────

describe('statusToBadgeProps — action_type=webhook', () => {
  it('returns null when status is null (no webhook ever fired)', () => {
    expect(statusToBadgeProps(null, 'webhook')).toBeNull();
  });

  it('maps "success" to ok severity', () => {
    const props = statusToBadgeProps('success', 'webhook');
    expect(props).toEqual({
      severity: 'ok',
      message: 'Webhook delivered',
      retryable: false,
    });
  });

  it('maps "in_flight" to processing severity (mid-call)', () => {
    const props = statusToBadgeProps('in_flight', 'webhook');
    expect(props?.severity).toBe('processing');
    expect(props?.retryable).toBe(false);
    expect(props?.message).toContain('in flight');
  });

  it('maps "pending" to processing severity (queued, not yet fired)', () => {
    const props = statusToBadgeProps('pending', 'webhook');
    expect(props?.severity).toBe('processing');
    expect(props?.retryable).toBe(false);
  });

  it('maps "failed" to error severity with retryable=true and the error message', () => {
    const props = statusToBadgeProps('failed', 'webhook', { error: 'http_500' });
    expect(props?.severity).toBe('error');
    expect(props?.retryable).toBe(true);
    expect(props?.message).toContain('http_500');
    // Webhook uses the "delivery failed" verb specifically (vs "failed" for
    // the auto-actions which run locally).
    expect(props?.message).toContain('delivery failed');
  });

  it('maps "failed" without an error to a generic message', () => {
    const props = statusToBadgeProps('failed', 'webhook');
    expect(props?.message).toBe('Webhook delivery failed');
  });

  it('maps "manual_intervention_required" to retryable error', () => {
    const props = statusToBadgeProps('manual_intervention_required', 'webhook');
    expect(props?.severity).toBe('manual_intervention_required');
    expect(props?.retryable).toBe(true);
    expect(props?.message).toContain('Manual intervention');
  });
});

// ──────────────────────────────────────────────────────────────────────────
// Render — retry button targets webhook action_type
// ──────────────────────────────────────────────────────────────────────────

describe('AutoActionStatusBadge — webhook render', () => {
  it('renders ⟳ Retry button when status is failed', () => {
    const onRetry = vi.fn();
    render(
      <AutoActionStatusBadge
        recordingId={42}
        recordingName="My Note"
        actionType="webhook"
        severity="error"
        message="Webhook delivery failed: http_500"
        retryable
        onRetry={onRetry}
      />,
    );
    const retry = screen.getByRole('button', {
      name: /retry webhook for my note/i,
    });
    fireEvent.click(retry);
    expect(onRetry).toHaveBeenCalledWith('webhook');
  });

  it('does NOT render retry button while in_flight (mid-call)', () => {
    render(
      <AutoActionStatusBadge
        recordingId={42}
        recordingName="My Note"
        actionType="webhook"
        severity="processing"
        message="Webhook delivery in flight…"
        retryable={false}
      />,
    );
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('renders manual_intervention_required severity with retry button', () => {
    const onRetry = vi.fn();
    render(
      <AutoActionStatusBadge
        recordingId={42}
        recordingName="My Note"
        actionType="webhook"
        severity="manual_intervention_required"
        message="Manual intervention required — automatic retry exhausted"
        retryable
        onRetry={onRetry}
      />,
    );
    const badge = screen.getByRole('status');
    expect(badge).toHaveAttribute('data-action-type', 'webhook');
    expect(badge).toHaveAttribute('data-severity', 'manual_intervention_required');
    expect(screen.getByRole('button', { name: /retry webhook for my note/i })).toBeTruthy();
  });
});
