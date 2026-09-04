/**
 * downloadToFile - stream an HTTP download straight to disk in the main process.
 *
 * The renderer's `file:writeText` channel takes a JS string and is not binary
 * safe, so audio needs its own path. More importantly the bytes must never
 * cross the IPC bridge: a supported 5-hour recording is roughly 576 MB at
 * 16 kHz mono 16-bit, and buffering that into the renderer to structured-clone
 * it would spike memory twice over or exceed the message limit outright.
 * Piping the response body into a write stream here keeps renderer memory flat
 * regardless of recording length.
 *
 * Lives in its own module rather than inline in main.ts so the cleanup rule
 * below is testable, which matters: this function deletes files.
 */

import fs from 'fs';
import path from 'path';
import { Readable } from 'stream';
import { pipeline } from 'stream/promises';
import type { ReadableStream as NodeWebReadableStream } from 'stream/web';

export interface DownloadToFileOptions {
  url: string;
  headers?: Record<string, string>;
  filePath: string;
}

export type DownloadToFileResult =
  | { ok: true; bytes?: number }
  | { ok: false; error: string; status?: number; body?: string };

/** Cap on the error body relayed to the renderer. */
export const MAX_ERROR_BODY_CHARS = 2000;

/**
 * Fetch `url` and write the response body to `filePath`.
 *
 * Never throws: always resolves to the result union, so the renderer never has
 * to try/catch an IPC rejection.
 *
 * On a non-ok response the destination is left untouched and the server's own
 * body is relayed back, because the audio endpoint answers 410 with a distinct
 * `detail` per reason (never preserved / lost with /tmp / deleted) and that
 * distinction is the whole answer for the user.
 */
export async function downloadToFile(opts: DownloadToFileOptions): Promise<DownloadToFileResult> {
  // Everything, path.resolve included, sits inside the try: it throws
  // ERR_INVALID_ARG_TYPE for a non-string filePath, and callers are promised
  // this never rejects.
  let resolved = '';
  // Flipped only once the write stream exists, i.e. once this function has
  // actually created or truncated the destination. The cleanup below keys off
  // it. Unlinking unconditionally would delete a pre-existing file the user
  // picked in the save dialog even when the download never wrote a byte to it,
  // which is exactly the kind of silent loss this feature exists to prevent.
  let destinationOpened = false;
  try {
    resolved = path.resolve(opts.filePath);
    const res = await fetch(opts.url, { headers: opts.headers });
    if (!res.ok) {
      let body = '';
      try {
        body = (await res.text()).slice(0, MAX_ERROR_BODY_CHARS);
      } catch {
        body = '';
      }
      return { ok: false, error: `Download failed: HTTP ${res.status}`, status: res.status, body };
    }
    if (!res.body) {
      return { ok: false, error: 'Download failed: response had no body', status: res.status };
    }
    // The DOM lib's ReadableStream and node:stream/web's are structurally
    // distinct to TypeScript even though fetch hands back the same object at
    // runtime, so the cast is the documented bridge between them.
    const source = Readable.fromWeb(res.body as unknown as NodeWebReadableStream<Uint8Array>);
    destinationOpened = true;
    await pipeline(source, fs.createWriteStream(resolved));
    let bytes: number | undefined;
    try {
      bytes = (await fs.promises.stat(resolved)).size;
    } catch {
      bytes = undefined;
    }
    return bytes === undefined ? { ok: true } : { ok: true, bytes };
  } catch (err) {
    // Best-effort cleanup so a half-written file is never left behind looking
    // valid. Scoped to a file this call actually opened, and errors from the
    // unlink itself are swallowed.
    if (destinationOpened && resolved) {
      try {
        await fs.promises.unlink(resolved);
      } catch {
        // Nothing to clean up, or the path is not ours to remove.
      }
    }
    return { ok: false, error: String(err) };
  }
}
