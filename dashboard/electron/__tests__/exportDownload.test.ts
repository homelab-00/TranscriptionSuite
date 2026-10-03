// @vitest-environment node

/**
 * GH-318 - a recording saved to disk is a download too (server to file),
 * and shows in the download bar with a Cancel that removes the partial file.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { DownloadHub, type DownloadItem } from '../downloadHub.js';
import { downloadToFileTracked } from '../exportDownload.js';
import type { DownloadToFileOptions, DownloadToFileResult } from '../downloadToFile.js';

let hub: DownloadHub;

const only = (): DownloadItem => {
  const items = hub.snapshot();
  expect(items).toHaveLength(1);
  return items[0];
};

beforeEach(() => {
  hub = new DownloadHub({ now: () => 1_000 });
});

describe('downloadToFileTracked', () => {
  it('shows the export as a cancellable download named after the file', async () => {
    let midway: DownloadItem | undefined;
    const download = async (opts: DownloadToFileOptions): Promise<DownloadToFileResult> => {
      opts.onProgress?.(0, 400);
      opts.onProgress?.(100, 400);
      midway = hub.snapshot()[0];
      return { ok: true, bytes: 400 };
    };

    const result = await downloadToFileTracked(
      hub,
      { url: 'http://server/audio/job-1', filePath: '/home/me/Music/recording.wav' },
      download,
    );

    expect(result).toEqual({ ok: true, bytes: 400 });
    expect(midway).toMatchObject({
      kind: 'export',
      label: 'recording.wav',
      status: 'active',
      bytesDone: 100,
      bytesTotal: 400,
      cancellable: true,
      // The Session view raises its own toast with the server's reason.
      errorToast: false,
    });
    expect(only().status).toBe('complete');
  });

  it('never opens a download for a request the server refuses', async () => {
    const download = async (): Promise<DownloadToFileResult> => ({
      ok: false,
      error: 'Download failed: HTTP 410',
      status: 410,
      body: '{"detail":"never preserved"}',
    });

    const result = await downloadToFileTracked(
      hub,
      { url: 'http://server/audio/job-1', filePath: '/tmp/recording.wav' },
      download,
    );

    expect(result).toMatchObject({ ok: false, status: 410 });
    expect(hub.snapshot()).toHaveLength(0);
  });

  it('fails the item when the stream dies after bytes started flowing', async () => {
    const download = async (opts: DownloadToFileOptions): Promise<DownloadToFileResult> => {
      opts.onProgress?.(10, 400);
      return { ok: false, error: 'Error: connection reset' };
    };

    await downloadToFileTracked(
      hub,
      { url: 'http://server/audio/job-1', filePath: '/tmp/recording.wav' },
      download,
    );

    expect(only()).toMatchObject({ status: 'error', error: 'Error: connection reset' });
  });

  it('aborts the download when the bar cancels it, and records a cancel', async () => {
    const download = (opts: DownloadToFileOptions): Promise<DownloadToFileResult> =>
      new Promise((resolve) => {
        opts.onProgress?.(10, 400);
        opts.signal?.addEventListener('abort', () =>
          resolve({ ok: false, error: 'cancelled', cancelled: true }),
        );
      });

    const pending = downloadToFileTracked(
      hub,
      { url: 'http://server/audio/job-1', filePath: '/tmp/recording.wav' },
      download,
    );
    const id = only().id;
    expect(hub.cancel(id)).toBe(true);

    expect(await pending).toMatchObject({ ok: false, cancelled: true });
    expect(only().status).toBe('cancelled');
  });

  it('gives two exports of the same file separate items', async () => {
    const download = vi.fn(async (opts: DownloadToFileOptions): Promise<DownloadToFileResult> => {
      opts.onProgress?.(0, 4);
      return { ok: true, bytes: 4 };
    });
    const opts = { url: 'http://server/audio/job-1', filePath: '/tmp/recording.wav' };

    await downloadToFileTracked(hub, opts, download);
    await downloadToFileTracked(hub, opts, download);

    expect(new Set(hub.snapshot().map((i) => i.id)).size).toBe(2);
  });
});
