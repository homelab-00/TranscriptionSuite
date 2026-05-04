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
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DiarizationReviewView } from '../DiarizationReviewView';
import type { ReviewTurn } from '../../../src/utils/diarizationReviewFilter';

const { mockToastSuccess } = vi.hoisted(() => ({ mockToastSuccess: vi.fn() }));

vi.mock('../../../src/hooks/useAriaAnnouncer', () => ({
  useAriaAnnouncer: () => vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
  },
}));

beforeEach(() => {
  mockToastSuccess.mockReset();
});

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

// ──────────────────────────────────────────────────────────────────────────
// Sprint 4 deferred-work no. 4 — ←/→ cycle attribution within focused turn
// ──────────────────────────────────────────────────────────────────────────

function makeTurnsWithAlternatives(): ReviewTurn[] {
  // Three speakers; turn 0's alternatives are SPEAKER_01 then SPEAKER_02 in
  // first-appearance order.
  return [
    {
      turn_index: 0,
      speaker_id: 'SPEAKER_00',
      confidence: 0.45,
      text: 'First.',
      alternative_speakers: ['SPEAKER_01', 'SPEAKER_02'],
    },
    {
      turn_index: 1,
      speaker_id: 'SPEAKER_01',
      confidence: 0.55,
      text: 'Second.',
      alternative_speakers: ['SPEAKER_00', 'SPEAKER_02'],
    },
    {
      turn_index: 2,
      speaker_id: 'SPEAKER_02',
      confidence: 0.4,
      text: 'Third.',
      alternative_speakers: ['SPEAKER_00', 'SPEAKER_01'],
    },
  ];
}

describe('Diarization Keyboard Contract — ←/→ cycle attribution (Sprint 4 no. 4)', () => {
  it('ArrowRight cycles displayed speaker through alternative_speakers', () => {
    render(
      <DiarizationReviewView
        turns={makeTurnsWithAlternatives()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox');
    const turn0 = document.getElementById('dr-turn-0')!;
    expect(turn0.textContent).toContain('SPEAKER_00');

    fireEvent.keyDown(list, { key: 'ArrowRight' });
    expect(turn0.textContent).toContain('SPEAKER_01');

    fireEvent.keyDown(list, { key: 'ArrowRight' });
    expect(turn0.textContent).toContain('SPEAKER_02');
  });

  it('ArrowRight does NOT change aria-activedescendant (regression of existing contract)', () => {
    render(
      <DiarizationReviewView
        turns={makeTurnsWithAlternatives()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox');
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    expect(list).toHaveAttribute('aria-activedescendant', 'dr-turn-0');
  });

  it('ArrowRight clamps at the last alternative (does not wrap)', () => {
    render(
      <DiarizationReviewView
        turns={makeTurnsWithAlternatives()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox');
    const turn0 = document.getElementById('dr-turn-0')!;
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    fireEvent.keyDown(list, { key: 'ArrowRight' }); // overshoot
    fireEvent.keyDown(list, { key: 'ArrowRight' }); // overshoot more
    expect(turn0.textContent).toContain('SPEAKER_02');
  });

  it('ArrowLeft cycles back through alternatives toward original', () => {
    render(
      <DiarizationReviewView
        turns={makeTurnsWithAlternatives()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox');
    const turn0 = document.getElementById('dr-turn-0')!;
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    expect(turn0.textContent).toContain('SPEAKER_02');

    fireEvent.keyDown(list, { key: 'ArrowLeft' });
    expect(turn0.textContent).toContain('SPEAKER_01');

    fireEvent.keyDown(list, { key: 'ArrowLeft' });
    expect(turn0.textContent).toContain('SPEAKER_00'); // back to original

    // Further ← clamps; original stays.
    fireEvent.keyDown(list, { key: 'ArrowLeft' });
    expect(turn0.textContent).toContain('SPEAKER_00');
  });

  it('Enter after cycling persists the chosen speaker_id in the decision', async () => {
    const onComplete = vi.fn().mockResolvedValue(undefined);
    render(
      <DiarizationReviewView
        turns={makeTurnsWithAlternatives()}
        speakerLabel={speakerLabel}
        onComplete={onComplete}
      />,
    );
    const list = screen.getByRole('listbox');
    // Cycle turn 0 to SPEAKER_02 (two →s) then Enter → accept with cycled speaker.
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    fireEvent.keyDown(list, { key: 'Enter' });

    fireEvent.click(screen.getByRole('button', { name: /Run summary now/ }));
    await Promise.resolve();
    expect(onComplete).toHaveBeenCalled();
    const decisions = onComplete.mock.calls[0][0];
    const turn0Decision = decisions.find(
      (d: { turn_index: number; decision: string; speaker_id: string }) => d.turn_index === 0,
    );
    expect(turn0Decision.decision).toBe('accept');
    expect(turn0Decision.speaker_id).toBe('SPEAKER_02');
  });

  it("cycling resets per-turn (turn 1 starts at its original speaker, not turn 0's cycle)", () => {
    render(
      <DiarizationReviewView
        turns={makeTurnsWithAlternatives()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox');
    const turn1 = document.getElementById('dr-turn-1')!;
    // Cycle turn 0
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    // Move down to turn 1 — its display is unaffected
    fireEvent.keyDown(list, { key: 'ArrowDown' });
    expect(turn1.textContent).toContain('SPEAKER_01'); // turn 1's original
  });

  it('on a single-speaker recording (no alternatives), ←/→ are no-ops', () => {
    const turns: ReviewTurn[] = [
      {
        turn_index: 0,
        speaker_id: 'SPEAKER_00',
        confidence: 0.4,
        text: 'Solo.',
        alternative_speakers: [],
      },
    ];
    render(
      <DiarizationReviewView turns={turns} speakerLabel={speakerLabel} onComplete={vi.fn()} />,
    );
    const list = screen.getByRole('listbox');
    const turn0 = document.getElementById('dr-turn-0')!;
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    expect(turn0.textContent).toContain('SPEAKER_00');
    expect(list).toHaveAttribute('aria-activedescendant', 'dr-turn-0');
  });
});

describe('Diarization Keyboard Contract — Ctrl+Z undoes the most recent bulk-accept', () => {
  it('Ctrl+Z reverts decisions to pre-bulk-accept state and toasts', async () => {
    const onComplete = vi.fn().mockResolvedValue(undefined);
    render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={onComplete}
      />,
    );
    const list = screen.getByRole('listbox');
    // Skip the first turn before bulk-accept: only turn 0 has a 'skip' decision.
    fireEvent.keyDown(list, { key: 'Escape' });
    // Bulk-accept overwrites all 3 visible turns to 'accept'.
    fireEvent.keyDown(list, { key: ' ' });
    // Undo: reverts to the state before bulk-accept (only turn 0 'skip').
    fireEvent.keyDown(list, { key: 'z', ctrlKey: true });

    fireEvent.click(screen.getByRole('button', { name: /Run summary now/ }));
    await Promise.resolve();
    expect(onComplete).toHaveBeenCalled();
    const decisions = onComplete.mock.calls[0][0];
    // Turn 0 retains 'skip'; turns 1 and 2 fall back to default-fill 'accept'.
    expect(decisions.find((d: { turn_index: number }) => d.turn_index === 0).decision).toBe('skip');
    expect(mockToastSuccess).toHaveBeenCalledTimes(1);
  });

  it('Cmd+Z (metaKey) is treated identically to Ctrl+Z', () => {
    render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox');
    fireEvent.keyDown(list, { key: ' ' }); // bulk-accept
    fireEvent.keyDown(list, { key: 'z', metaKey: true }); // undo
    expect(mockToastSuccess).toHaveBeenCalledTimes(1);
  });

  it('Ctrl+Z is a no-op when the undo stack is empty (no toast)', () => {
    render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox');
    fireEvent.keyDown(list, { key: 'z', ctrlKey: true });
    expect(mockToastSuccess).not.toHaveBeenCalled();
  });

  it('Ctrl+Z only pops one bulk-accept at a time', async () => {
    const onComplete = vi.fn().mockResolvedValue(undefined);
    render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={onComplete}
      />,
    );
    const list = screen.getByRole('listbox');
    // First bulk-accept (snapshot A: empty)
    fireEvent.keyDown(list, { key: ' ' });
    // Skip turn 0 (after first bulk-accept committed turn 0 to 'accept')
    fireEvent.keyDown(list, { key: 'Escape' });
    // Second bulk-accept (snapshot B: {0:'skip', 1:'accept', 2:'accept'})
    fireEvent.keyDown(list, { key: ' ' });
    // One undo — should pop snapshot B, restoring {0:'skip', 1:'accept', 2:'accept'}.
    fireEvent.keyDown(list, { key: 'z', ctrlKey: true });

    fireEvent.click(screen.getByRole('button', { name: /Run summary now/ }));
    await Promise.resolve();
    const decisions = onComplete.mock.calls[0][0];
    const byTurn: Record<number, string> = Object.fromEntries(
      decisions.map((d: { turn_index: number; decision: string }) => [d.turn_index, d.decision]),
    );
    expect(byTurn[0]).toBe('skip');
    expect(byTurn[1]).toBe('accept');
    expect(byTurn[2]).toBe('accept');
  });

  it('Ctrl+Shift+Z is reserved for future redo and does NOT undo', () => {
    render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox');
    fireEvent.keyDown(list, { key: ' ' });
    fireEvent.keyDown(list, { key: 'z', ctrlKey: true, shiftKey: true });
    expect(mockToastSuccess).not.toHaveBeenCalled();
  });

  it('clicking "Mark all visible" button (not Space) also pushes onto the stack', () => {
    render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    fireEvent.click(
      screen.getByRole('button', { name: /Mark all visible turns as auto-accept best guess/ }),
    );
    fireEvent.keyDown(screen.getByRole('listbox'), { key: 'z', ctrlKey: true });
    expect(mockToastSuccess).toHaveBeenCalledTimes(1);
  });

  it('Ctrl+Z works from the wrapper even when listbox is not focused', () => {
    const { container } = render(
      <DiarizationReviewView
        turns={makeTurns()}
        speakerLabel={speakerLabel}
        onComplete={vi.fn()}
      />,
    );
    const list = screen.getByRole('listbox');
    fireEvent.keyDown(list, { key: ' ' });
    // Fire keydown on the outer wrapper (root child of container) — simulates
    // the user being focused on the submit button or filter dropdown.
    const wrapper = container.firstChild as HTMLElement;
    fireEvent.keyDown(wrapper, { key: 'z', ctrlKey: true });
    expect(mockToastSuccess).toHaveBeenCalledTimes(1);
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
