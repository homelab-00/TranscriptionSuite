/**
 * updateManager — focused tests for the release-notes sanitizer.
 *
 * The function is the only new logic added to updateManager.ts in M5;
 * UpdateManager's GitHub/GHCR network paths and notification dedup are
 * already exercised indirectly via the UpdateBanner suite.
 */
import { describe, expect, it } from 'vitest';

import { sanitizeReleaseBody } from '../updateManager';

const MAX = 50_000;

describe('sanitizeReleaseBody', () => {
  it('returns null for non-string input', () => {
    expect(sanitizeReleaseBody(undefined)).toBeNull();
    expect(sanitizeReleaseBody(null)).toBeNull();
    expect(sanitizeReleaseBody(42)).toBeNull();
    expect(sanitizeReleaseBody({ body: 'x' })).toBeNull();
  });

  it('returns null for whitespace-only input', () => {
    expect(sanitizeReleaseBody('')).toBeNull();
    expect(sanitizeReleaseBody('   ')).toBeNull();
    expect(sanitizeReleaseBody('\n\n\t')).toBeNull();
  });

  it('returns trimmed content for typical release bodies', () => {
    expect(sanitizeReleaseBody('  ## Changelog\n- fix X\n  ')).toBe('## Changelog\n- fix X');
  });

  it('passes through content under the cap unchanged', () => {
    const body = 'a'.repeat(MAX);
    expect(sanitizeReleaseBody(body)).toBe(body);
  });

  it('truncates content over the cap to exactly MAX code points', () => {
    const body = 'a'.repeat(MAX + 1000);
    const out = sanitizeReleaseBody(body);
    expect(out).not.toBeNull();
    expect(Array.from(out as string).length).toBe(MAX);
  });

  it('does NOT split a surrogate pair at the boundary (astral-safe truncation)', () => {
    // 😀 (U+1F600) occupies 2 UTF-16 units; plain slice at MAX would split
    // the pair if the boundary lands inside it. Construct a string where
    // the last codepoint before the cap is an emoji.
    const pad = 'a'.repeat(MAX - 1);
    const body = pad + '😀' + 'tail';
    const out = sanitizeReleaseBody(body);
    expect(out).not.toBeNull();
    // Last code point in the output must be a well-formed emoji — no lone
    // surrogate (which would show up as a replacement character or fail
    // `isWellFormed()` checks on modern engines).
    const codepoints = Array.from(out as string);
    expect(codepoints.length).toBe(MAX);
    expect(codepoints[codepoints.length - 1]).toBe('😀');
  });

  it('trims only leading/trailing whitespace, not internal', () => {
    expect(sanitizeReleaseBody('  line 1\nline 2  ')).toBe('line 1\nline 2');
  });
});
