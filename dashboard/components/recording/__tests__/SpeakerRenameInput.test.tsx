/**
 * SpeakerRenameInput tests (Issue #104, Story 4.3).
 *
 * Covers:
 *   - AC1: click + Enter commits rename; Esc cancels
 *   - AC1: blur commits (treated as soft-Enter — matches title rename UX)
 *   - AC3: aria-label on input + chip
 *   - AC3: trim-only — alias_name preserved verbatim otherwise (R-EL3)
 *   - Trimmed-empty rename is dropped (clear-by-blank)
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SpeakerRenameInput } from '../SpeakerRenameInput';

// useAriaAnnouncer reads from a Zustand store — stub it here so the
// test doesn't depend on the live region setup.
vi.mock('../../../src/hooks/useAriaAnnouncer', () => ({
  useAriaAnnouncer: () => vi.fn(),
}));

describe('SpeakerRenameInput — AC1 commit/cancel', () => {
  it('renders chip with currentLabel when not editing', () => {
    render(
      <SpeakerRenameInput speakerId="SPEAKER_00" currentLabel="Speaker 1" onCommit={vi.fn()} />,
    );
    expect(
      screen.getByRole('button', { name: /Rename speaker label for SPEAKER_00/ }),
    ).toHaveTextContent('Speaker 1');
  });

  it('switches to input on click and commits on Enter', () => {
    const onCommit = vi.fn();
    render(
      <SpeakerRenameInput speakerId="SPEAKER_00" currentLabel="Speaker 1" onCommit={onCommit} />,
    );
    fireEvent.click(screen.getByRole('button'));
    const input = screen.getByLabelText(/Speaker label for SPEAKER_00/);
    fireEvent.change(input, { target: { value: 'Elena' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onCommit).toHaveBeenCalledWith('Elena');
  });

  it('cancels on Esc — onCommit is NOT called', () => {
    const onCommit = vi.fn();
    render(
      <SpeakerRenameInput speakerId="SPEAKER_00" currentLabel="Speaker 1" onCommit={onCommit} />,
    );
    fireEvent.click(screen.getByRole('button'));
    const input = screen.getByLabelText(/Speaker label for SPEAKER_00/);
    fireEvent.change(input, { target: { value: 'Elena' } });
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(onCommit).not.toHaveBeenCalled();
    expect(screen.getByRole('button')).toHaveTextContent('Speaker 1');
  });

  it('blur commits the rename', () => {
    const onCommit = vi.fn();
    render(
      <SpeakerRenameInput speakerId="SPEAKER_00" currentLabel="Speaker 1" onCommit={onCommit} />,
    );
    fireEvent.click(screen.getByRole('button'));
    const input = screen.getByLabelText(/Speaker label for SPEAKER_00/);
    fireEvent.change(input, { target: { value: 'Elena' } });
    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledWith('Elena');
  });
});

describe('SpeakerRenameInput — AC3 accessibility + verbatim', () => {
  it('preserves Unicode in alias name (no normalization)', () => {
    const onCommit = vi.fn();
    render(
      <SpeakerRenameInput speakerId="SPEAKER_00" currentLabel="Speaker 1" onCommit={onCommit} />,
    );
    fireEvent.click(screen.getByRole('button'));
    const input = screen.getByLabelText(/Speaker label for SPEAKER_00/);
    fireEvent.change(input, { target: { value: 'Dr. María José García-López' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onCommit).toHaveBeenCalledWith('Dr. María José García-López');
  });

  it('trims surrounding whitespace before commit', () => {
    const onCommit = vi.fn();
    render(
      <SpeakerRenameInput speakerId="SPEAKER_00" currentLabel="Speaker 1" onCommit={onCommit} />,
    );
    fireEvent.click(screen.getByRole('button'));
    const input = screen.getByLabelText(/Speaker label for SPEAKER_00/);
    fireEvent.change(input, { target: { value: '   Elena   ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onCommit).toHaveBeenCalledWith('Elena');
  });

  it('does NOT call onCommit when committed value is unchanged', () => {
    const onCommit = vi.fn();
    render(
      <SpeakerRenameInput speakerId="SPEAKER_00" currentLabel="Speaker 1" onCommit={onCommit} />,
    );
    fireEvent.click(screen.getByRole('button'));
    const input = screen.getByLabelText(/Speaker label for SPEAKER_00/);
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('does NOT call onCommit when trimmed value is empty', () => {
    const onCommit = vi.fn();
    render(
      <SpeakerRenameInput speakerId="SPEAKER_00" currentLabel="Speaker 1" onCommit={onCommit} />,
    );
    fireEvent.click(screen.getByRole('button'));
    const input = screen.getByLabelText(/Speaker label for SPEAKER_00/);
    fireEvent.change(input, { target: { value: '   ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('disables editing when editable=false', () => {
    render(
      <SpeakerRenameInput
        speakerId="SPEAKER_00"
        currentLabel="Speaker 1"
        onCommit={vi.fn()}
        editable={false}
      />,
    );
    const button = screen.getByRole('button');
    expect(button).toBeDisabled();
  });
});
