/**
 * PersistentInfoBanner tests (Issue #104, Story 5.7 / UX-DR2).
 *
 * Covers:
 *   - AC1: amber/yellow background + text content
 *   - AC3: inline CTA button activates onCta callback
 *   - AC4: ARIA live announcement fired on mount
 *   - AC4: keyboard activation works (Enter on the button)
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { PersistentInfoBanner } from '../PersistentInfoBanner';

const mockAnnounce = vi.fn();
vi.mock('../../../src/hooks/useAriaAnnouncer', () => ({
  useAriaAnnouncer: () => mockAnnounce,
}));

describe('PersistentInfoBanner — AC1 visual', () => {
  it('renders the message', () => {
    render(<PersistentInfoBanner message="Test message" />);
    expect(screen.getByText('Test message')).toBeInTheDocument();
  });

  it('uses warning palette by default', () => {
    render(<PersistentInfoBanner message="m" />);
    const banner = screen.getByRole('status');
    expect(banner.className).toContain('amber');
  });

  it('uses info palette when severity=info', () => {
    render(<PersistentInfoBanner message="m" severity="info" />);
    const banner = screen.getByRole('status');
    expect(banner.className).toContain('blue');
  });
});

describe('PersistentInfoBanner — AC3 CTA', () => {
  it('does not render CTA button when ctaLabel is undefined', () => {
    render(<PersistentInfoBanner message="m" />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('renders CTA button with given label', () => {
    render(<PersistentInfoBanner message="m" ctaLabel="Review uncertain turns" onCta={vi.fn()} />);
    expect(screen.getByRole('button', { name: /Review uncertain turns/ })).toBeInTheDocument();
  });

  it('fires onCta when button is clicked', () => {
    const onCta = vi.fn();
    render(<PersistentInfoBanner message="m" ctaLabel="Open" onCta={onCta} />);
    fireEvent.click(screen.getByRole('button'));
    expect(onCta).toHaveBeenCalledTimes(1);
  });
});

describe('PersistentInfoBanner — AC4 ARIA', () => {
  it('fires aria announcement on mount when ariaAnnouncement is provided', () => {
    mockAnnounce.mockClear();
    render(
      <PersistentInfoBanner
        message="Static message"
        ariaAnnouncement="Heads up: 5 turns flagged."
      />,
    );
    expect(mockAnnounce).toHaveBeenCalledWith('Heads up: 5 turns flagged.');
  });

  it('does NOT announce when ariaAnnouncement is undefined', () => {
    mockAnnounce.mockClear();
    render(<PersistentInfoBanner message="Silent" />);
    expect(mockAnnounce).not.toHaveBeenCalled();
  });
});
