// @vitest-environment node

/**
 * checksumVerifier — streaming sha256 tests per M6 I/O matrix.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import path from 'path';
import { createHash } from 'crypto';

import { verifyChecksum } from '../checksumVerifier.js';

describe('verifyChecksum', () => {
  let dir: string;

  beforeEach(() => {
    dir = mkdtempSync(path.join(tmpdir(), 'checksum-'));
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it('returns ok when the sha256 matches (lowercase)', async () => {
    const file = path.join(dir, 'bin.AppImage');
    const content = Buffer.from('hello world\n');
    writeFileSync(file, content);
    const expected = createHash('sha256').update(content).digest('hex');

    const result = await verifyChecksum(file, expected);

    expect(result).toEqual({ ok: true });
  });

  it('accepts an uppercase expected digest and still matches', async () => {
    const file = path.join(dir, 'bin.AppImage');
    const content = Buffer.from('mixed-case');
    writeFileSync(file, content);
    const expected = createHash('sha256').update(content).digest('hex').toUpperCase();

    const result = await verifyChecksum(file, expected);

    expect(result).toEqual({ ok: true });
  });

  it('returns mismatch with the actual digest when content differs', async () => {
    const file = path.join(dir, 'bin.AppImage');
    writeFileSync(file, Buffer.from('actual-content'));
    const bogus = 'a'.repeat(64);

    const result = await verifyChecksum(file, bogus);

    expect(result.ok).toBe(false);
    expect(result.reason).toBe('mismatch');
    expect(result.actual).toMatch(/^[a-f0-9]{64}$/);
    expect(result.actual).not.toBe(bogus);
  });

  it('returns file-missing when the path does not exist', async () => {
    const result = await verifyChecksum(path.join(dir, 'nope.AppImage'), 'a'.repeat(64));

    expect(result.ok).toBe(false);
    expect(result.reason).toBe('file-missing');
  });

  it('streams large inputs without reading whole file into memory', async () => {
    // Write a 10 MB file in chunks to assert the stream path works for large inputs.
    const file = path.join(dir, 'big.AppImage');
    const chunk = Buffer.alloc(1024 * 1024, 0x41); // 1 MB of 'A'
    const hash = createHash('sha256');
    writeFileSync(file, Buffer.alloc(0));
    const { appendFileSync } = await import('fs');
    for (let i = 0; i < 10; i++) {
      appendFileSync(file, chunk);
      hash.update(chunk);
    }
    const expected = hash.digest('hex');

    const result = await verifyChecksum(file, expected);

    expect(result).toEqual({ ok: true });
  });
});
