/**
 * A recording saved to disk, reported to the download bar (GH-318).
 *
 * Wraps downloadToFile: the item opens only once the server has accepted the
 * download and bytes are about to flow, so a refused request (the audio
 * endpoint answers 410 with a reason) never shows as a download. The Session
 * view keeps raising its own toast with the server's reason, so the item does
 * not raise a second one.
 */

import path from 'path';
import type { DownloadHandle, DownloadHub } from './downloadHub.js';
import {
  downloadToFile,
  type DownloadToFileOptions,
  type DownloadToFileResult,
} from './downloadToFile.js';

let exportSeq = 0;

export async function downloadToFileTracked(
  hub: DownloadHub,
  opts: DownloadToFileOptions,
  download: (opts: DownloadToFileOptions) => Promise<DownloadToFileResult> = downloadToFile,
): Promise<DownloadToFileResult> {
  const abort = new AbortController();
  exportSeq += 1;
  const id = `export:${exportSeq}`;
  let handle: DownloadHandle | undefined;

  const result = await download({
    ...opts,
    signal: abort.signal,
    onProgress: (bytesDone, bytesTotal) => {
      handle ??= hub.begin({
        id,
        kind: 'export',
        label: path.basename(String(opts.filePath)),
        cancel: () => abort.abort(),
        errorToast: false,
      });
      handle.update({ bytesDone, bytesTotal });
    },
  });

  if (handle) {
    if (result.ok === true) handle.complete();
    else if (result.cancelled) handle.cancel('Cancelled by user');
    else handle.fail(result.error);
  }
  return result;
}
