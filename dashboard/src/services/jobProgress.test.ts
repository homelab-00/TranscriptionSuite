import { describe, expect, it } from 'vitest';
import { describeJobProgress, formatClock } from './jobProgress';

describe('formatClock', () => {
  it('formats mm:ss under an hour', () => {
    expect(formatClock(760)).toBe('12:40');
  });

  it('formats h:mm:ss over an hour', () => {
    expect(formatClock(3725)).toBe('1:02:05');
  });

  it('clamps negatives to zero', () => {
    expect(formatClock(-5)).toBe('0:00');
  });
});

describe('describeJobProgress (GH-211)', () => {
  const now = 1_000_000;

  it('loading_model phase', () => {
    expect(
      describeJobProgress(
        { current: 0, total: 0, message: '', phase: 'loading_model' },
        now - 5,
        now,
      ),
    ).toBe('Loading model...');
  });

  it('transcribing with duration progress shows position, percent, elapsed and ETA', () => {
    const label = describeJobProgress(
      { current: 760, total: 2295, message: '', phase: 'transcribing' },
      now - 120,
      now,
    );
    expect(label).toBe('Transcribing 12:40 / 38:15 (33%, elapsed 2:00, ETA 4:02)');
  });

  it('transcribing_diarizing uses the combined verb', () => {
    const label = describeJobProgress(
      { current: 760, total: 2295, message: '', phase: 'transcribing_diarizing' },
      now - 120,
      now,
    );
    expect(label).toContain('Transcribing + identifying speakers 12:40 / 38:15');
  });

  it('diarizing shows phase + elapsed, never a percentage', () => {
    const label = describeJobProgress(
      { current: 2295, total: 2295, message: '', phase: 'diarizing' },
      now - 300,
      now,
    );
    expect(label).toContain('Identifying speakers');
    expect(label).toContain('elapsed 5:00');
    expect(label).not.toContain('%');
  });

  it('omits the ETA during the first seconds of a phase', () => {
    const label = describeJobProgress(
      { current: 10, total: 100, message: '', phase: 'transcribing' },
      now - 3,
      now,
    );
    expect(label).not.toMatch(/ETA/);
  });

  it('progress without a phase but with totals renders a generic position', () => {
    expect(
      describeJobProgress({ current: 30, total: 300, message: '', phase: null }, now - 60, now),
    ).toBe('Processing 0:30 / 5:00 (elapsed 1:00)');
  });

  it('no phase, no totals -> generic Processing with elapsed', () => {
    expect(
      describeJobProgress({ current: 0, total: 0, message: '', phase: null }, now - 60, now),
    ).toBe('Processing... (elapsed 1:00)');
  });

  it('null progress and null startedAt -> plain Processing...', () => {
    expect(describeJobProgress(null, null, now)).toBe('Processing...');
  });
});
