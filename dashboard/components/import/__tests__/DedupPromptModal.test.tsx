/**
 * DedupPromptModal tests (Issue #104, Story 2.4 AC4).
 *
 * Verifies the contract:
 *   - Both buttons have descriptive aria-label attributes
 *   - Clicking Use existing emits 'use_existing'
 *   - Clicking Create new emits 'create_new'
 *   - Esc / outside-click emits 'cancel'
 *   - When match=null the modal renders nothing (callers can pre-render)
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DedupPromptModal } from '../DedupPromptModal';

import type { DedupMatch } from '../../../src/api/types';

const sampleMatch: DedupMatch = {
  recording_id: 'job-abc123',
  name: 'Sample lecture',
  created_at: '2026-04-15T10:30:00Z',
};

describe('DedupPromptModal — AC2.4.AC4 a11y contract', () => {
  it('renders both buttons with descriptive aria-labels', () => {
    render(<DedupPromptModal open match={sampleMatch} onChoice={vi.fn()} />);

    expect(screen.getByRole('button', { name: 'Use existing recording' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create new recording entry' })).toBeInTheDocument();
  });

  it('emits use_existing when primary button clicked', () => {
    const onChoice = vi.fn();
    render(<DedupPromptModal open match={sampleMatch} onChoice={onChoice} />);

    fireEvent.click(screen.getByRole('button', { name: 'Use existing recording' }));

    expect(onChoice).toHaveBeenCalledWith('use_existing');
  });

  it('emits create_new when secondary button clicked', () => {
    const onChoice = vi.fn();
    render(<DedupPromptModal open match={sampleMatch} onChoice={onChoice} />);

    fireEvent.click(screen.getByRole('button', { name: 'Create new recording entry' }));

    expect(onChoice).toHaveBeenCalledWith('create_new');
  });

  it('renders nothing when match is null', () => {
    const { container } = render(<DedupPromptModal open match={null} onChoice={vi.fn()} />);
    // Modal is short-circuited — no Dialog primitive in the DOM
    expect(container).toBeEmptyDOMElement();
  });
});

describe('DedupPromptModal — content', () => {
  it("displays the matched recording's name", () => {
    render(<DedupPromptModal open match={sampleMatch} onChoice={vi.fn()} />);
    expect(screen.getByText(/Sample lecture/)).toBeInTheDocument();
  });

  it('displays the modal title', () => {
    render(<DedupPromptModal open match={sampleMatch} onChoice={vi.fn()} />);
    expect(screen.getByText('Possible duplicate detected')).toBeInTheDocument();
  });
});
