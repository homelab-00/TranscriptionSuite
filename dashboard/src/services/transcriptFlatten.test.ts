import { describe, it, expect } from 'vitest';
import { flattenSegmentsToText } from './transcriptFlatten';
import type { TranscriptionSegment } from '../api/types';

const seg = (text: string, extra: Partial<TranscriptionSegment> = {}): TranscriptionSegment => ({
  text,
  start: 0,
  end: 1,
  ...extra,
});

describe('flattenSegmentsToText', () => {
  it('returns "" for no segments', () => {
    expect(flattenSegmentsToText([])).toBe('');
  });

  it('joins plain segments one per line', () => {
    expect(flattenSegmentsToText([seg('Hello there.'), seg('General Kenobi.')])).toBe(
      'Hello there.\nGeneral Kenobi.',
    );
  });

  it('drops blank / whitespace-only segments', () => {
    expect(flattenSegmentsToText([seg('one'), seg('   '), seg(''), seg('two')])).toBe('one\ntwo');
  });

  it('trims leading/trailing whitespace per segment', () => {
    expect(flattenSegmentsToText([seg('  padded  '), seg('\ttabbed\n')])).toBe('padded\ntabbed');
  });

  it('ignores speaker labels (no prefix in MVP)', () => {
    const segments = [
      seg('First.', { speaker: 'SPEAKER_00' }),
      seg('Second.', { speaker: 'SPEAKER_01' }),
    ];
    expect(flattenSegmentsToText(segments)).toBe('First.\nSecond.');
  });

  it('flattens word-timestamped segments to their text only', () => {
    const segments = [
      seg('the quick', {
        words: [
          { word: 'the', start: 0, end: 0.2 },
          { word: 'quick', start: 0.2, end: 0.5 },
        ],
      }),
    ];
    expect(flattenSegmentsToText(segments)).toBe('the quick');
  });

  it('tolerates a missing text field defensively', () => {
    const malformed = { start: 0, end: 1 } as unknown as TranscriptionSegment;
    expect(flattenSegmentsToText([malformed, seg('ok')])).toBe('ok');
  });
});
