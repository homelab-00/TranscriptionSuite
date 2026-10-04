// @vitest-environment node

/**
 * downloadToFile - streaming an HTTP download straight to disk.
 *
 * This function deletes files, so the cleanup rule is the point of the suite:
 * a partial write it created must be removed, and a pre-existing file it never
 * opened must be left exactly as it was. The user reaches this code by picking
 * a path in a save dialog, so "the destination already exists" is the normal
 * case, not the exotic one.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync, readFileSync, existsSync } from 'fs';
import { tmpdir } from 'os';
import path from 'path';
import { Readable } from 'stream';

import { downloadToFile, MAX_ERROR_BODY_CHARS } from '../downloadToFile.js';

/** A minimal stand-in for the parts of Response this module reads. */
function okResponse(body: Buffer | NodeJS.ReadableStream, contentLength?: number) {
  const stream = Buffer.isBuffer(body) ? Readable.from([body]) : body;
  return {
    ok: true,
    status: 200,
    headers: {
      get: (name: string) =>
        name.toLowerCase() === 'content-length' && contentLength !== undefined
          ? String(contentLength)
          : null,
    },
    body: Readable.toWeb(stream as Readable),
  };
}

function errorResponse(status: number, text: string) {
  return {
    ok: false,
    status,
    body: null,
    text: async () => text,
  };
}

describe('downloadToFile', () => {
  let dir: string;
  let target: string;

  beforeEach(() => {
    dir = mkdtempSync(path.join(tmpdir(), 'download-to-file-'));
    target = path.join(dir, 'recording.wav');
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    rmSync(dir, { recursive: true, force: true });
  });

  it('writes the response body to the chosen path and reports its size', async () => {
    const payload = Buffer.from('RIFF____WAVEfmt this is the recording');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okResponse(payload)));

    const result = await downloadToFile({ url: 'http://server/audio/job-1', filePath: target });

    expect(result).toEqual({ ok: true, bytes: payload.length });
    expect(readFileSync(target).equals(payload)).toBe(true);
  });

  it('passes the caller headers through, so the token never rides in the URL', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okResponse(Buffer.from('x')));
    vi.stubGlobal('fetch', fetchMock);

    await downloadToFile({
      url: 'http://server/audio/job-1',
      headers: { Authorization: 'Bearer secret' },
      filePath: target,
    });

    expect(fetchMock).toHaveBeenCalledWith('http://server/audio/job-1', {
      headers: { Authorization: 'Bearer secret' },
    });
  });

  // The 410 body distinguishes never-preserved from lost-on-restart from
  // already-deleted. Relaying it verbatim is the whole point of carrying it.
  it('relays the server own message on a non-ok response', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          errorResponse(410, JSON.stringify({ detail: 'Audio file has been deleted' })),
        ),
    );

    const result = await downloadToFile({ url: 'http://server/audio/job-1', filePath: target });

    expect(result).toMatchObject({ ok: false, status: 410 });
    expect((result as { body: string }).body).toContain('Audio file has been deleted');
  });

  it('caps a runaway error body instead of relaying all of it', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(errorResponse(500, 'x'.repeat(MAX_ERROR_BODY_CHARS * 3))),
    );

    const result = await downloadToFile({ url: 'http://server/audio/job-1', filePath: target });

    expect((result as { body: string }).body).toHaveLength(MAX_ERROR_BODY_CHARS);
  });

  // The save dialog hands back a path the user confirmed overwriting, so an
  // existing file is normal. A failure before this code opens anything must
  // leave that file alone: deleting it would destroy data the download never
  // even attempted to replace.
  it('leaves a pre-existing file untouched when the request itself fails', async () => {
    const precious = Buffer.from('the users existing recording');
    writeFileSync(target, precious);
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED')));

    const result = await downloadToFile({ url: 'http://server/audio/job-1', filePath: target });

    expect(result).toMatchObject({ ok: false });
    expect(existsSync(target)).toBe(true);
    expect(readFileSync(target).equals(precious)).toBe(true);
  });

  it('leaves a pre-existing file untouched when the server refuses', async () => {
    const precious = Buffer.from('the users existing recording');
    writeFileSync(target, precious);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(errorResponse(410, 'gone')));

    await downloadToFile({ url: 'http://server/audio/job-1', filePath: target });

    expect(readFileSync(target).equals(precious)).toBe(true);
  });

  // The mirror image: once the write has begun, a truncated file IS this
  // function's doing and must not be left behind looking like a valid WAV.
  it('removes the half-written file when the stream dies mid-download', async () => {
    const dying = new Readable({
      read() {
        this.push(Buffer.from('RIFF____WAVE'));
        this.destroy(new Error('connection reset'));
      },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okResponse(dying)));

    const result = await downloadToFile({ url: 'http://server/audio/job-1', filePath: target });

    expect(result).toMatchObject({ ok: false });
    expect(existsSync(target)).toBe(false);
  });

  it('reports progress against the declared size as the bytes are written', async () => {
    const chunks = [Buffer.from('RIFF'), Buffer.from('____'), Buffer.from('WAVE')];
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okResponse(Readable.from(chunks), 12)));
    const seen: Array<[number, number | undefined]> = [];

    const result = await downloadToFile({
      url: 'http://server/audio/job-1',
      filePath: target,
      onProgress: (done, total) => seen.push([done, total]),
    });

    expect(result).toEqual({ ok: true, bytes: 12 });
    // Announced once before any byte, so the caller knows the total up front.
    expect(seen[0]).toEqual([0, 12]);
    expect(seen[seen.length - 1]).toEqual([12, 12]);
  });

  it('reports an unknown total when the server sends no Content-Length', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okResponse(Buffer.from('abcd'))));
    const seen: Array<[number, number | undefined]> = [];

    await downloadToFile({
      url: 'http://server/audio/job-1',
      filePath: target,
      onProgress: (done, total) => seen.push([done, total]),
    });

    expect(seen[seen.length - 1]).toEqual([4, undefined]);
  });

  it('never reports progress for a refused download', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(errorResponse(410, '{"detail":"gone"}')));
    const onProgress = vi.fn();

    await downloadToFile({ url: 'http://server/audio/job-1', filePath: target, onProgress });

    expect(onProgress).not.toHaveBeenCalled();
  });

  it('removes the half-written file and reports a cancel when aborted mid-download', async () => {
    const controller = new AbortController();
    // A web stream that never ends: the download can only stop by being aborted.
    const endless = new ReadableStream<Uint8Array>({
      pull(streamController) {
        streamController.enqueue(new Uint8Array(Buffer.from('RIFF____WAVE')));
      },
    });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => null },
        body: endless,
      }),
    );

    const result = await downloadToFile({
      url: 'http://server/audio/job-1',
      filePath: target,
      signal: controller.signal,
      onProgress: (done) => {
        if (done > 0) controller.abort();
      },
    });

    expect(result).toMatchObject({ ok: false, cancelled: true });
    expect(existsSync(target)).toBe(false);
  });

  it('passes the abort signal to the request itself', async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockResolvedValue(okResponse(Buffer.from('x')));
    vi.stubGlobal('fetch', fetchMock);

    await downloadToFile({
      url: 'http://server/audio/job-1',
      filePath: target,
      signal: controller.signal,
    });

    expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal);
  });

  it('survives a progress callback that throws', async () => {
    const payload = Buffer.from('RIFF____WAVE');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okResponse(payload)));

    const result = await downloadToFile({
      url: 'http://server/audio/job-1',
      filePath: target,
      onProgress: () => {
        throw new Error('bar bug');
      },
    });

    expect(result).toEqual({ ok: true, bytes: payload.length });
  });

  it('keeps a pre-existing file intact when the stream dies mid-download', async () => {
    // The user picked "Replace" in the save dialog. A failed download must
    // not cost them the file they already had.
    writeFileSync(target, 'the recording I already saved');
    const dying = new Readable({
      read() {
        this.push(Buffer.from('RIFF____WAVE'));
        this.destroy(new Error('connection reset'));
      },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okResponse(dying)));

    const result = await downloadToFile({ url: 'http://server/audio/job-1', filePath: target });

    expect(result).toMatchObject({ ok: false });
    expect(readFileSync(target, 'utf-8')).toBe('the recording I already saved');
    expect(existsSync(`${target}.part`)).toBe(false);
  });

  it('keeps a pre-existing file intact when the download is cancelled', async () => {
    writeFileSync(target, 'the recording I already saved');
    const controller = new AbortController();
    const endless = new ReadableStream<Uint8Array>({
      pull(streamController) {
        streamController.enqueue(new Uint8Array(Buffer.from('RIFF____WAVE')));
      },
    });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => null },
        body: endless,
      }),
    );

    const result = await downloadToFile({
      url: 'http://server/audio/job-1',
      filePath: target,
      signal: controller.signal,
      onProgress: (done) => {
        if (done > 0) controller.abort();
      },
    });

    expect(result).toMatchObject({ ok: false, cancelled: true });
    expect(readFileSync(target, 'utf-8')).toBe('the recording I already saved');
    expect(existsSync(`${target}.part`)).toBe(false);
  });

  it('replaces a pre-existing file only once the download is complete', async () => {
    writeFileSync(target, 'old');
    const payload = Buffer.from('RIFF____WAVEfmt new recording');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okResponse(payload)));

    const result = await downloadToFile({ url: 'http://server/audio/job-1', filePath: target });

    expect(result).toEqual({ ok: true, bytes: payload.length });
    expect(readFileSync(target).equals(payload)).toBe(true);
    expect(existsSync(`${target}.part`)).toBe(false);
  });

  it('reports a response with no body instead of writing an empty file', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, body: null }));

    const result = await downloadToFile({ url: 'http://server/audio/job-1', filePath: target });

    expect(result).toMatchObject({ ok: false, status: 200 });
    expect(existsSync(target)).toBe(false);
  });

  // The renderer is promised this never rejects, and its tsconfig has no
  // strictNullChecks, so a null path from a cancelled dialog type-checks fine.
  it('resolves rather than rejects when the path is not a string', async () => {
    vi.stubGlobal('fetch', vi.fn());

    const result = await downloadToFile({
      url: 'http://server/audio/job-1',
      filePath: null as unknown as string,
    });

    expect(result).toMatchObject({ ok: false });
    expect((result as { error: string }).error).toContain('ERR_INVALID_ARG_TYPE');
  });
});
