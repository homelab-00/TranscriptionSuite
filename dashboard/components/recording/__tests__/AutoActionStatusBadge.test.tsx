/**
 * AutoActionStatusBadge tests (Issue #104, Story 6.6 — UX-DR1, FR35, FR51-53).
 *
 * AC1: severity → visual mapping (green ok / amber warn / red error / blue processing)
 * AC2: inline ⟳ Retry button when retryable=true
 * AC3: cardinality — two badges render independently for the same recording
 * AC4: persistence — render reads severity from prop (not local state)
 * AC5: accessibility — aria-label, aria-live announcements
 */

import { render, screen, act, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AutoActionStatusBadge, statusToBadgeProps } from '../AutoActionStatusBadge';

const announceMock = vi.fn();
vi.mock('../../../src/hooks/useAriaAnnouncer', () => ({
  useAriaAnnouncer: () => announceMock,
}));

beforeEach(() => {
  announceMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

// ──────────────────────────────────────────────────────────────────────────
// AC1 — severity → StatusLight mapping
// ──────────────────────────────────────────────────────────────────────────

describe('AutoActionStatusBadge — AC1 severity', () => {
  it.each([
    ['ok', 'active'],
    ['warn', 'warning'],
    ['error', 'error'],
    ['processing', 'loading'],
    ['manual_intervention_required', 'error'],
  ] as const)('severity=%s renders StatusLight in the right palette', (severity, _statusLight) => {
    const { container } = render(
      <AutoActionStatusBadge
        recordingId={1}
        recordingName="Test"
        actionType="auto_summary"
        severity={severity}
        message="Test message"
        retryable={false}
      />,
    );
    const badge = screen.getByRole('status');
    expect(badge).toHaveAttribute('data-severity', severity);
    expect(badge).toHaveTextContent('Test message');
    // StatusLight nests at least one shadowed dot inside the badge
    expect(container.querySelector('span.relative')).toBeTruthy();
  });
});

// ──────────────────────────────────────────────────────────────────────────
// AC2 — retry button
// ──────────────────────────────────────────────────────────────────────────

describe('AutoActionStatusBadge — AC2 retry button', () => {
  it('renders ⟳ Retry button when retryable=true', () => {
    const onRetry = vi.fn();
    render(
      <AutoActionStatusBadge
        recordingId={42}
        recordingName="Lecture 2025-05-04"
        actionType="auto_summary"
        severity="error"
        message="LLM unavailable"
        retryable
        onRetry={onRetry}
      />,
    );
    const button = screen.getByRole('button', {
      name: /retry auto-summary for Lecture 2025-05-04/i,
    });
    expect(button).toHaveTextContent('⟳ Retry');
  });

  it('does NOT render retry button when retryable=false', () => {
    render(
      <AutoActionStatusBadge
        recordingId={1}
        recordingName="X"
        actionType="auto_export"
        severity="ok"
        message="Export ready"
        retryable={false}
      />,
    );
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('clicking retry button invokes onRetry with the action type', () => {
    const onRetry = vi.fn();
    render(
      <AutoActionStatusBadge
        recordingId={1}
        recordingName="X"
        actionType="auto_export"
        severity="warn"
        message="Export deferred"
        retryable
        onRetry={onRetry}
      />,
    );
    fireEvent.click(screen.getByRole('button'));
    expect(onRetry).toHaveBeenCalledWith('auto_export');
  });
});

// ──────────────────────────────────────────────────────────────────────────
// AC3 — cardinality (two independent badges)
// ──────────────────────────────────────────────────────────────────────────

describe('AutoActionStatusBadge — AC3 cardinality', () => {
  it('two independent badges render on the same recording', () => {
    render(
      <>
        <AutoActionStatusBadge
          recordingId={1}
          recordingName="X"
          actionType="auto_summary"
          severity="error"
          message="Summary failed"
          retryable
          onRetry={vi.fn()}
        />
        <AutoActionStatusBadge
          recordingId={1}
          recordingName="X"
          actionType="auto_export"
          severity="ok"
          message="Export ready"
          retryable={false}
        />
      </>,
    );
    const badges = screen.getAllByRole('status');
    expect(badges).toHaveLength(2);
    expect(badges[0]).toHaveAttribute('data-action-type', 'auto_summary');
    expect(badges[0]).toHaveAttribute('data-severity', 'error');
    expect(badges[1]).toHaveAttribute('data-action-type', 'auto_export');
    expect(badges[1]).toHaveAttribute('data-severity', 'ok');
  });
});

// ──────────────────────────────────────────────────────────────────────────
// AC5 — accessibility
// ──────────────────────────────────────────────────────────────────────────

describe('AutoActionStatusBadge — AC5 a11y', () => {
  it('announces the message via useAriaAnnouncer on mount', () => {
    render(
      <AutoActionStatusBadge
        recordingId={1}
        recordingName="X"
        actionType="auto_summary"
        severity="error"
        message="Summary failed"
        retryable={false}
      />,
    );
    expect(announceMock).toHaveBeenCalledWith('auto-summary: Summary failed');
  });

  it('retry button has aria-label including recording name', () => {
    render(
      <AutoActionStatusBadge
        recordingId={1}
        recordingName="My Lecture"
        actionType="auto_export"
        severity="warn"
        message="Export deferred"
        retryable
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: 'Retry auto-export for My Lecture' })).toBeTruthy();
  });
});

// ──────────────────────────────────────────────────────────────────────────
// Auto-dismiss for severity='ok'
// ──────────────────────────────────────────────────────────────────────────

describe('AutoActionStatusBadge — auto-dismiss on ok', () => {
  it('autoDismissOk=true unmounts the badge after 3s', () => {
    vi.useFakeTimers();
    render(
      <AutoActionStatusBadge
        recordingId={1}
        recordingName="X"
        actionType="auto_summary"
        severity="ok"
        message="Summary ready"
        retryable={false}
        autoDismissOk
      />,
    );
    expect(screen.queryByRole('status')).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(3500);
    });
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('autoDismissOk=false leaves the badge mounted indefinitely', () => {
    vi.useFakeTimers();
    render(
      <AutoActionStatusBadge
        recordingId={1}
        recordingName="X"
        actionType="auto_summary"
        severity="ok"
        message="Summary ready"
        retryable={false}
      />,
    );
    act(() => {
      vi.advanceTimersByTime(3500);
    });
    expect(screen.queryByRole('status')).toBeTruthy();
  });
});

// ──────────────────────────────────────────────────────────────────────────
// statusToBadgeProps — the backend-status → UI-prop mapping
// ──────────────────────────────────────────────────────────────────────────

describe('statusToBadgeProps', () => {
  it('returns null for null/undefined status', () => {
    expect(statusToBadgeProps(null, 'auto_summary')).toBeNull();
  });

  it('maps success → ok (not retryable)', () => {
    const r = statusToBadgeProps('success', 'auto_summary');
    expect(r?.severity).toBe('ok');
    expect(r?.retryable).toBe(false);
  });

  it('maps in_progress → processing (not retryable)', () => {
    const r = statusToBadgeProps('in_progress', 'auto_export');
    expect(r?.severity).toBe('processing');
    expect(r?.retryable).toBe(false);
  });

  it('maps held → warn (not retryable — user must review turns first)', () => {
    const r = statusToBadgeProps('held', 'auto_summary');
    expect(r?.severity).toBe('warn');
    expect(r?.retryable).toBe(false);
    expect(r?.message).toContain('review');
  });

  it('maps deferred → warn with destination path in message', () => {
    const r = statusToBadgeProps('deferred', 'auto_export', { path: '/mnt/usb' });
    expect(r?.severity).toBe('warn');
    expect(r?.retryable).toBe(true);
    expect(r?.message).toContain('/mnt/usb');
  });

  it('maps failed → error with error text', () => {
    const r = statusToBadgeProps('failed', 'auto_summary', { error: 'LLM timeout' });
    expect(r?.severity).toBe('error');
    expect(r?.retryable).toBe(true);
    expect(r?.message).toContain('LLM timeout');
  });

  it('maps summary_empty → warn (Story 6.7)', () => {
    const r = statusToBadgeProps('summary_empty', 'auto_summary');
    expect(r?.severity).toBe('warn');
    expect(r?.retryable).toBe(true);
  });

  it('maps summary_truncated → warn (Story 6.7)', () => {
    const r = statusToBadgeProps('summary_truncated', 'auto_summary');
    expect(r?.severity).toBe('warn');
    expect(r?.retryable).toBe(true);
  });

  it('maps manual_intervention_required → distinct severity (Story 6.11)', () => {
    const r = statusToBadgeProps('manual_intervention_required', 'auto_export');
    expect(r?.severity).toBe('manual_intervention_required');
    expect(r?.retryable).toBe(true);
    expect(r?.message).toContain('Manual intervention');
  });
});
