// @vitest-environment node

/**
 * sha256Lookup — manifest-to-downloaded-file hash resolution.
 *
 * Defends the verifier against multi-arch spoofing: when a future
 * manifest lists two `.AppImage` entries (x64 + arm64), the old
 * same-extension-first-match fallback would cross-validate the wrong
 * architecture. Ambiguous matches now fail-closed.
 */

import { describe, it, expect, vi } from 'vitest';
import { resolveExpectedSha256 } from '../sha256Lookup.js';

const HASH_X64 = 'a'.repeat(64);
const HASH_ARM64 = 'b'.repeat(64);
const HASH_WIN = 'c'.repeat(64);
const HASH_MAC = 'd'.repeat(64);

describe('resolveExpectedSha256', () => {
  it('returns hash on exact basename match', () => {
    const map = { 'TranscriptionSuite-1.3.3.AppImage': HASH_X64 };
    expect(resolveExpectedSha256(map, '/tmp/TranscriptionSuite-1.3.3.AppImage')).toBe(HASH_X64);
  });

  it('returns hash on single same-extension fallback (canonical vs versioned name)', () => {
    // v1 shape: manifest publishes canonical name; downloaded file
    // carries electron-builder's version-embedded artifactName.
    const map = { 'TranscriptionSuite.AppImage': HASH_X64 };
    expect(resolveExpectedSha256(map, '/tmp/TranscriptionSuite-1.3.3.AppImage')).toBe(HASH_X64);
  });

  it('returns null on zero matches', () => {
    const map = { 'TranscriptionSuite.dmg': HASH_MAC };
    expect(resolveExpectedSha256(map, '/tmp/TranscriptionSuite-1.3.3.AppImage')).toBeNull();
  });

  it('returns null and warns on ambiguous same-extension fallback (>1 matches)', () => {
    // The multi-arch spoofing seam: two .AppImage entries, downloaded
    // basename matches neither exactly. The old fallback would return
    // HASH_X64 (first insertion order) and cross-validate an arm64
    // binary against an x64 hash. The new behavior refuses to guess.
    const map = {
      'TranscriptionSuite-x64.AppImage': HASH_X64,
      'TranscriptionSuite-arm64.AppImage': HASH_ARM64,
    };
    const logger = { warn: vi.fn() };
    const result = resolveExpectedSha256(map, '/tmp/TranscriptionSuite-1.3.3.AppImage', logger);
    expect(result).toBeNull();
    expect(logger.warn).toHaveBeenCalledTimes(1);
    expect(logger.warn.mock.calls[0][0]).toContain('ambiguous fallback');
    expect(logger.warn.mock.calls[0][0]).toContain('.AppImage');
    // Second arg carries the structured context — pin its shape so a
    // future refactor that drops the object (or mangles candidates) is
    // caught by this test, not only by the message-substring check.
    expect(logger.warn.mock.calls[0][1]).toEqual({
      downloaded: 'TranscriptionSuite-1.3.3.AppImage',
      candidates: expect.arrayContaining([
        'TranscriptionSuite-x64.AppImage',
        'TranscriptionSuite-arm64.AppImage',
      ]),
    });
  });

  it('returns null without throwing when ambiguous and no logger supplied', () => {
    const map = {
      'TranscriptionSuite-x64.AppImage': HASH_X64,
      'TranscriptionSuite-arm64.AppImage': HASH_ARM64,
    };
    expect(() =>
      resolveExpectedSha256(map, '/tmp/TranscriptionSuite-1.3.3.AppImage'),
    ).not.toThrow();
    expect(resolveExpectedSha256(map, '/tmp/TranscriptionSuite-1.3.3.AppImage')).toBeNull();
  });

  it('prefers exact match even when ambiguity would otherwise apply', () => {
    // If the downloaded basename is literally one of the manifest keys,
    // the exact-match path wins — no ambiguity check runs.
    const map = {
      'TranscriptionSuite-x64.AppImage': HASH_X64,
      'TranscriptionSuite-arm64.AppImage': HASH_ARM64,
    };
    expect(resolveExpectedSha256(map, '/tmp/TranscriptionSuite-x64.AppImage')).toBe(HASH_X64);
    expect(resolveExpectedSha256(map, '/tmp/TranscriptionSuite-arm64.AppImage')).toBe(HASH_ARM64);
  });

  it('handles files with no extension (returns null, no crash)', () => {
    const map = { 'TranscriptionSuite.AppImage': HASH_X64 };
    expect(resolveExpectedSha256(map, '/tmp/TranscriptionSuite')).toBeNull();
  });

  it('does not cross-match different extensions', () => {
    const map = { 'TranscriptionSuite.dmg': HASH_MAC, 'TranscriptionSuite.exe': HASH_WIN };
    expect(resolveExpectedSha256(map, '/tmp/TranscriptionSuite-1.3.3.AppImage')).toBeNull();
  });
});
