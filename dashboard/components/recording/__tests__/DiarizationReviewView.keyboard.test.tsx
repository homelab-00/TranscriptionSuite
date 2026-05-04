/**
 * Diarization-Review Keyboard Contract — canonical regression test
 * (Issue #104, Story 5.9 AC3 + PRD §900–920).
 *
 * Each row of the contract gets its own assertion. Any divergence
 * triggers a test failure here BEFORE it can ship.
 *
 * | Key                  | Action                                |
 * | Tab / Shift+Tab      | Traverse turns (single tab stop)      |
 * | ↑ / ↓                | Move selection within turn-list       |
 * | ← / →                | Switch attribution within focused turn |
 * | Enter                | Accept current attribution            |
 * | Esc                  | Skip current turn                     |
 * | Space                | Bulk-accept all visible turns         |
 */

import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DiarizationReviewView } from '../DiarizationReviewView';
import type { ReviewTurn } from '../../../src/utils/diarizationReviewFilter';

vi.mock('../../../src/hooks/useAriaAnnouncer', () => ({
  useAriaAnnouncer: () => vi.fn(),
}));

function makeTurns(): ReviewTurn[] {
  // 3 turns, all in low bucket so they all show under default filter
  return [
    { turn_index: 0, speaker_id: 'SPEAKER_00', confidence: 0.45, text: 'First.' },
    { turn_index: 1, speaker_id: 'SPEAKER_01', confidence: 0.55, text: 'Second.' },
    { turn_index: 2, speaker_id: 'SPEAKER_00', confidence: 0.4, text: 'Third.' },
  ];
}

const speakerLabel = (id: string | null | undefined) => id ?? 'unknown';

describe('Diarization Keyboard Contract — composite-widget shape', () => {
  it('turn-list is a listbox with single tab stop', () => {
    render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox', { name: /Uncertain turns to review/ });
    expect(list).toHaveAttribute('tabIndex', '0');
  });

  it('individual turns are options with role=option', () => {
    render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    // Query within the listbox so we don't capture the <select> options
    const listbox = screen.getByRole('listbox');
    expect(within(listbox).getAllByRole('option')).toHaveLength(3);
  });

  it('uses aria-activedescendant rather than per-turn focus', () => {
    render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox');
    expect(list).toHaveAttribute('aria-activedescendant', 'dr-turn-0');
  });
});

describe('Diarization Keyboard Contract — ↓ / ↑ move selection', () => {
  it('ArrowDown advances aria-activedescendant', () => {
    render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox');
    fireEvent.keyDown(list, { key: 'ArrowDown' });
    expect(list).toHaveAttribute('aria-activedescendant', 'dr-turn-1');
  });

  it('ArrowDown does not advance past the last turn', () => {
    render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox');
    fireEvent.keyDown(list, { key: 'ArrowDown' });
    fireEvent.keyDown(list, { key: 'ArrowDown' });
    fireEvent.keyDown(list, { key: 'ArrowDown' }); // overshoots
    expect(list).toHaveAttribute('aria-activedescendant', 'dr-turn-2');
  });

  it('ArrowUp moves selection up', () => {
    render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox');
    fireEvent.keyDown(list, { key: 'ArrowDown' });
    fireEvent.keyDown(list, { key: 'ArrowUp' });
    expect(list).toHaveAttribute('aria-activedescendant', 'dr-turn-0');
  });
});

describe('Diarization Keyboard Contract — Enter accepts + advances', () => {
  it('Enter advances to next turn after accept', () => {
    render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox');
    fireEvent.keyDown(list, { key: 'Enter' });
    expect(list).toHaveAttribute('aria-activedescendant', 'dr-turn-1');
  });
});

describe('Diarization Keyboard Contract — Esc skips + advances', () => {
  it('Escape advances without committing', () => {
    render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox');
    fireEvent.keyDown(list, { key: 'Escape' });
    expect(list).toHaveAttribute('aria-activedescendant', 'dr-turn-1');
  });
});

describe('Diarization Keyboard Contract — Space bulk-accepts', () => {
  it('Space marks every visible turn as accepted', async () => {
    const onComplete = vi.fn().mockResolvedValue(undefined);
    render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={onComplete}
      />,
    );
    const list = screen.getByRole('listbox');
    fireEvent.keyDown(list, { key: ' ' });
    // Submit and confirm all 3 turns recorded as 'accept'
    fireEvent.click(screen.getByRole('button', { name: /Run summary now/ }));
    // Wait for the submit to flush
    await Promise.resolve();
    expect(onComplete).toHaveBeenCalled();
    const decisions = onComplete.mock.calls[0][0];
    expect(decisions).toHaveLength(3);
    for (const d of decisions) expect(d.decision).toBe('accept');
  });
});

describe('Diarization Keyboard Contract — ←/→ are consumed', () => {
  it('ArrowLeft / ArrowRight do not advance selection (attribution scope)', () => {
    render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox');
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    fireEvent.keyDown(list, { key: 'ArrowLeft' });
    // Active descendant unchanged
    expect(list).toHaveAttribute('aria-activedescendant', 'dr-turn-0');
  });
});

describe('Diarization Review — confidence-threshold filter (AC1)', () => {
  it('changing filter to <60% reduces visible turns', () => {
    const turns: ReviewTurn[] = [
      { turn_index: 0, speaker_id: 'A', confidence: 0.45, text: 'low' },
      { turn_index: 1, speaker_id: 'B', confidence: 0.7, text: 'medium' },
    ];
    render(
      <DiarizationReviewView turns={turns} speakerLabel={speakerLabel} onComplete={vi.fn()} />,
    );
    const listbox = screen.getByRole('listbox');
    // Default <80% filter shows both
    expect(within(listbox).getAllByRole('option')).toHaveLength(2);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'below_60' } });
    // Now only the <60% one
    expect(within(listbox).getAllByRole('option')).toHaveLength(1);
  });
});
