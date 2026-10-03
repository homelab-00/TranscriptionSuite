import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ProgressBar } from '../ProgressBar';

describe('ProgressBar', () => {
  it('exposes a determinate value to assistive tech', () => {
    render(<ProgressBar value={42} label="Model download" valueText="42%, 1.1 GB of 2.6 GB" />);
    const bar = screen.getByRole('progressbar', { name: 'Model download' });

    expect(bar).toHaveAttribute('aria-valuenow', '42');
    expect(bar).toHaveAttribute('aria-valuemin', '0');
    expect(bar).toHaveAttribute('aria-valuemax', '100');
    expect(bar).toHaveAttribute('aria-valuetext', '42%, 1.1 GB of 2.6 GB');
    expect((bar.firstElementChild as HTMLElement).style.width).toBe('42%');
  });

  it('renders an indeterminate bar without a value when the progress is unknown', () => {
    render(<ProgressBar value={null} label="Image pull" />);
    const bar = screen.getByRole('progressbar', { name: 'Image pull' });

    expect(bar).not.toHaveAttribute('aria-valuenow');
    expect((bar.firstElementChild as HTMLElement).style.width).toBe('');
  });

  it('treats NaN as indeterminate instead of rendering a broken width', () => {
    render(<ProgressBar value={Number.NaN} label="Update" />);

    expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow');
  });

  it('clamps out-of-range values', () => {
    const { rerender } = render(<ProgressBar value={140} label="x" />);
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100');

    rerender(<ProgressBar value={-5} label="x" />);
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0');
  });
});
