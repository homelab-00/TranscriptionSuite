/**
 * checksumVerifier — streaming SHA-256 comparator for downloaded update
 * binaries. The expected digest comes from the per-release `manifest.json`
 * persisted by M4's CompatGuard under `updates.lastManifest`.
 *
 * Streaming hash (no whole-file read) keeps peak memory bounded on AppImages
 * measured in hundreds of MB.
 */

import { createHash } from 'crypto';
import { createReadStream } from 'fs';

export interface VerifyChecksumResult {
  ok: boolean;
  reason?: 'mismatch' | 'file-missing' | 'read-error';
  actual?: string;
  message?: string;
}

export async function verifyChecksum(
  filePath: string,
  expectedSha256: string,
): Promise<VerifyChecksumResult> {
  const expected = expectedSha256.toLowerCase();

  return new Promise<VerifyChecksumResult>((resolve) => {
    const hash = createHash('sha256');
    const stream = createReadStream(filePath);

    stream.on('data', (chunk) => hash.update(chunk));

    stream.on('error', (err: NodeJS.ErrnoException) => {
      const reason = err.code === 'ENOENT' ? 'file-missing' : 'read-error';
      resolve({ ok: false, reason, message: err.message });
    });

    stream.on('end', () => {
      const actual = hash.digest('hex').toLowerCase();
      if (actual === expected) {
        resolve({ ok: true });
      } else {
        resolve({ ok: false, reason: 'mismatch', actual });
      }
    });
  });
}
