/**
 * Issue #104, Story 4.4 — alias substitution unit tests.
 */

import { describe, expect, it } from 'vitest';
import { buildSpeakerLabelMap, labelFor } from '../aliasSubstitution';

describe('buildSpeakerLabelMap', () => {
  it('returns empty map when there are no segments', () => {
    expect(buildSpeakerLabelMap([], {})).toEqual(new Map());
  });

  it('returns empty map when no segments have a speaker', () => {
    const segs = [{ speaker: null }, { speaker: undefined }, { speaker: '' }];
    expect(buildSpeakerLabelMap(segs, {})).toEqual(new Map());
  });

  it('assigns "Speaker N" by first-appearance order when no aliases exist', () => {
    const segs = [
      { speaker: 'SPEAKER_01' },
      { speaker: 'SPEAKER_00' },
      { speaker: 'SPEAKER_01' }, // duplicate — does not advance counter
      { speaker: 'SPEAKER_02' },
    ];
    expect(buildSpeakerLabelMap(segs, {})).toEqual(
      new Map([
        ['SPEAKER_01', 'Speaker 1'],
        ['SPEAKER_00', 'Speaker 2'],
        ['SPEAKER_02', 'Speaker 3'],
      ]),
    );
  });

  it('substitutes alias when present, falls back to "Speaker N" otherwise', () => {
    const segs = [{ speaker: 'SPEAKER_00' }, { speaker: 'SPEAKER_01' }, { speaker: 'SPEAKER_02' }];
    const aliases = {
      SPEAKER_00: 'Elena Vasquez',
      SPEAKER_02: 'Sami Patel',
    };
    expect(buildSpeakerLabelMap(segs, aliases)).toEqual(
      new Map([
        ['SPEAKER_00', 'Elena Vasquez'],
        ['SPEAKER_01', 'Speaker 1'],
        ['SPEAKER_02', 'Sami Patel'],
      ]),
    );
  });

  it('preserves alias_name verbatim — no normalization (R-EL3)', () => {
    const aliases = { SPEAKER_00: 'Dr. María José García-López' };
    const map = buildSpeakerLabelMap([{ speaker: 'SPEAKER_00' }], aliases);
    expect(map.get('SPEAKER_00')).toBe('Dr. María José García-López');
  });
});

describe('labelFor', () => {
  it('returns empty string for null/undefined raw', () => {
    const map = new Map<string, string>();
    expect(labelFor(null, map)).toBe('');
    expect(labelFor(undefined, map)).toBe('');
  });

  it('returns the mapped label when present', () => {
    const map = new Map([['SPEAKER_00', 'Elena']]);
    expect(labelFor('SPEAKER_00', map)).toBe('Elena');
  });

  it('falls back to the raw value when not in map (defensive)', () => {
    const map = new Map<string, string>();
    expect(labelFor('SPEAKER_99', map)).toBe('SPEAKER_99');
  });
});
