import { describe, it, expect } from 'vitest';
import { computeMatches, replaceCurrent, replaceAll } from './findReplaceEngine';

const CI = { caseSensitive: false };
const CS = { caseSensitive: true };

describe('computeMatches', () => {
  it('returns [] for an empty query', () => {
    expect(computeMatches('abc', '', CI)).toEqual([]);
  });

  it('returns [] for a whitespace-only query', () => {
    expect(computeMatches('a b c', '   ', CI)).toEqual([]);
  });

  it('returns [] when there is no match', () => {
    expect(computeMatches('hello world', 'xyz', CI)).toEqual([]);
  });

  it('finds a single match with correct half-open offsets', () => {
    expect(computeMatches('hello world', 'world', CS)).toEqual([{ start: 6, end: 11 }]);
  });

  it('finds multiple matches left-to-right', () => {
    expect(computeMatches('a a a', 'a', CS)).toEqual([
      { start: 0, end: 1 },
      { start: 2, end: 3 },
      { start: 4, end: 5 },
    ]);
  });

  it('does not produce overlapping matches', () => {
    // "aa" in "aaaa" → [0,2] and [2,4], NOT [1,3]
    expect(computeMatches('aaaa', 'aa', CS)).toEqual([
      { start: 0, end: 2 },
      { start: 2, end: 4 },
    ]);
  });

  it('respects case-sensitivity', () => {
    expect(computeMatches('Foo foo', 'foo', CS)).toEqual([{ start: 4, end: 7 }]);
  });

  it('matches case-insensitively while indexing the original text', () => {
    expect(computeMatches('Foo foo', 'foo', CI)).toEqual([
      { start: 0, end: 3 },
      { start: 4, end: 7 },
    ]);
  });

  it('handles Greek text (length-preserving lowercasing)', () => {
    // 'Α' lowercases to 'α' as a single code unit, so offsets stay aligned.
    expect(computeMatches('Αλφα αλφα', 'αλφα', CI)).toEqual([
      { start: 0, end: 4 },
      { start: 5, end: 9 },
    ]);
  });
});

describe('replaceCurrent', () => {
  it('replaces only the given match and returns a new string', () => {
    const text = 'hello world';
    const [match] = computeMatches(text, 'world', CS);
    expect(replaceCurrent(text, match, 'there')).toBe('hello there');
  });

  it('does not mutate the input string', () => {
    const text = 'abc';
    replaceCurrent(text, { start: 0, end: 1 }, 'X');
    expect(text).toBe('abc');
  });

  it('supports replacement longer or shorter than the match', () => {
    expect(replaceCurrent('a_b', { start: 1, end: 2 }, '---')).toBe('a---b');
    expect(replaceCurrent('a---b', { start: 1, end: 4 }, '_')).toBe('a_b');
  });
});

describe('replaceAll', () => {
  it('replaces every match and reports the count', () => {
    expect(replaceAll('a a a', 'a', 'b', CS)).toEqual({ text: 'b b b', count: 3 });
  });

  it('is a no-op for an empty query', () => {
    expect(replaceAll('a a a', '', 'b', CI)).toEqual({ text: 'a a a', count: 0 });
  });

  it('is a no-op when there are no matches', () => {
    expect(replaceAll('hello', 'z', 'b', CI)).toEqual({ text: 'hello', count: 0 });
  });

  it('preserves surrounding original casing on case-insensitive replace', () => {
    // Both "Foo" and "foo" are replaced; the space between is preserved.
    expect(replaceAll('Foo foo', 'foo', 'bar', CI)).toEqual({ text: 'bar bar', count: 2 });
  });

  it('handles overlapping-substring patterns without double counting', () => {
    expect(replaceAll('aaaa', 'aa', 'b', CS)).toEqual({ text: 'bb', count: 2 });
  });

  it('supports deletion via empty replacement', () => {
    expect(replaceAll('a-b-c', '-', '', CS)).toEqual({ text: 'abc', count: 2 });
  });
});
