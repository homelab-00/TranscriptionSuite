/**
 * ConfidenceChip tests (Issue #104, Story 5.5 — UX-DR3).
 *
 * AC1: bucket rendering matches PRD visual spec
 *      high (≥80%): no chip; medium [60, 80): neutral; low (<60): amber
 * AC2: tooltip shows percentage
 * AC3: aria-label="confidence: <bucket>"
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ConfidenceChip } from '../ConfidenceChip';

describe('ConfidenceChip — AC1 buckets', () => {
  it('renders no chip for high-confidence (>=80%)', () => {
    const { container } = render(<ConfidenceChip confidence={0.9} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders no chip exactly at the high threshold', () => {
    const { container } = render(<ConfidenceChip confidence={0.8} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders neutral chip for medium [60, 80)', () => {
    render(<ConfidenceChip confidence={0.7} />);
    const chip = screen.getByRole('status');
    expect(chip).toHaveTextContent('medium');
    expect(chip).toHaveAttribute('data-bucket', 'medium');
  });

  it('renders amber chip for low (<60%)', () => {
    render(<ConfidenceChip confidence={0.45} />);
    const chip = screen.getByRole('status');
    expect(chip).toHaveTextContent('low');
    expect(chip).toHaveAttribute('data-bucket', 'low');
  });

  it('treats edge confidence=0 as low', () => {
    render(<ConfidenceChip confidence={0} />);
    expect(screen.getByRole('status')).toHaveAttribute('data-bucket', 'low');
  });
});

describe('ConfidenceChip — AC2 tooltip', () => {
  it('tooltip title shows exact percentage', () => {
    render(<ConfidenceChip confidence={0.67} />);
    const chip = screen.getByRole('status');
    expect(chip).toHaveAttribute('title', 'confidence: 67%');
  });

  it('rounds tooltip percentage to whole number', () => {
    render(<ConfidenceChip confidence={0.6789} />);
    const chip = screen.getByRole('status');
    expect(chip).toHaveAttribute('title', 'confidence: 68%');
  });
});

describe('ConfidenceChip — AC3 aria-label', () => {
  it('aria-label reads "confidence: medium" for medium bucket', () => {
    render(<ConfidenceChip confidence={0.7} />);
    expect(screen.getByLabelText('confidence: medium')).toBeInTheDocument();
  });

  it('aria-label reads "confidence: low" for low bucket', () => {
    render(<ConfidenceChip confidence={0.4} />);
    expect(screen.getByLabelText('confidence: low')).toBeInTheDocument();
  });
});

describe('ConfidenceChip — defensive', () => {
  it('treats NaN as low (no crash)', () => {
    render(<ConfidenceChip confidence={NaN} />);
    expect(screen.getByRole('status')).toHaveAttribute('data-bucket', 'low');
  });

  it('clamps values >1 (high bucket → no chip)', () => {
    const { container } = render(<ConfidenceChip confidence={1.5} />);
    expect(container.firstChild).toBeNull();
  });

  it('clamps negative values to low', () => {
    render(<ConfidenceChip confidence={-0.5} />);
    expect(screen.getByRole('status')).toHaveAttribute('data-bucket', 'low');
  });
});
