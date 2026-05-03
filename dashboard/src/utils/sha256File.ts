/**
 * sha256File — compute the SHA-256 hex digest of a File via the Web Crypto API
 * (Issue #104, Story 2.4 — dedup-check helper).
 *
 * Returns the same hex digest as the server-side `sha256_streaming` for the
 * SAME bytes. Both hash the raw file content; same file → same digest →
 * dedup-check returns matches.
 *
 * Memory: this implementation buffers the full File via `arrayBuffer()`. For
 * a 1 GB import, that's a 1 GB allocation. Acceptable for typical recordings;
 * a follow-up sprint can add a streaming variant via FileReader chunks if
 * users hit memory pressure on multi-GB imports.
 */

function bytesToHex(buf: ArrayBuffer): string {
  const view = new Uint8Array(buf);
  const hex: string[] = new Array(view.length);
  for (let i = 0; i < view.length; i++) {
    hex[i] = view[i].toString(16).padStart(2, '0');
  }
  return hex.join('');
}

export async function sha256File(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  const digest = await crypto.subtle.digest('SHA-256', buf);
  return bytesToHex(digest);
}
