// @vitest-environment node

/**
 * GH-318 - image pulls and the host-side GGML fetch reported into the
 * DownloadHub, so the download bar shows them, can cancel them, and records
 * how they ended.
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { EventEmitter } from 'events';
import * as fs from 'fs';
import fsDefault from 'fs';
import * as path from 'path';
import * as os from 'os';

const userDataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-dm-downloads-test-'));

const netRequest = vi.fn();

vi.mock('electron', () => ({
  app: {
    isPackaged: false,
    getPath: (_name: string) => userDataRoot,
    setPath: vi.fn(),
  },
  net: { request: (...args: unknown[]) => netRequest(...args) },
}));

vi.mock('electron-store', () => ({
  default: class MockStore {
    get() {
      return undefined;
    }
    set() {}
  },
}));

vi.mock('../containerRuntime.js', () => ({
  getRuntimeBin: vi.fn(async () => '/usr/bin/docker'),
  getContainerRuntime: vi.fn(async () => ({ kind: 'docker', displayName: 'Docker' })),
  getDetectionResult: vi.fn(() => null),
  resetDetection: vi.fn(),
  resolveRootlessSocket: vi.fn(() => null),
  getSocketPaths: vi.fn(() => ({ docker: '/var/run/docker.sock', podman: null })),
  getRuntimePathAdditions: vi.fn(() => []),
}));

vi.mock('child_process', async () => {
  const actual = await vi.importActual<typeof import('child_process')>('child_process');
  return {
    ...actual,
    spawn: vi.fn(),
  };
});

import { spawn } from 'child_process';
import { dockerManager } from '../dockerManager.js';
import { downloadHub, type DownloadItem } from '../downloadHub.js';

interface FakeChildProcess extends EventEmitter {
  stdout: EventEmitter;
  stderr: EventEmitter;
  kill: ReturnType<typeof vi.fn>;
}

/** A pull process the test finishes by hand. */
function controllableSpawn(): {
  proc: FakeChildProcess;
  finish: (code: number | null, stderr?: string) => void;
} {
  const proc = new EventEmitter() as FakeChildProcess;
  proc.stdout = new EventEmitter();
  proc.stderr = new EventEmitter();
  let closed = false;
  const finish = (code: number | null, stderr?: string) => {
    if (closed) return;
    closed = true;
    if (stderr) proc.stderr.emit('data', Buffer.from(stderr));
    proc.emit('close', code);
  };
  proc.kill = vi.fn(() => {
    queueMicrotask(() => finish(null));
    return true;
  });
  vi.mocked(spawn).mockReset();
  vi.mocked(spawn).mockImplementation(() => proc as unknown as ReturnType<typeof spawn>);
  return { proc, finish };
}

const hubItem = (id: string): DownloadItem | undefined =>
  downloadHub
    .snapshot()
    .filter((i) => i.id === id)
    .sort((a, b) => b.startedAt - a.startedAt)[0];

/** Let the awaits inside pullImage (runtimeBin etc.) settle. */
async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('pullImage download tracking', () => {
  it('shows a cancellable server-image item while pulling and completes it', async () => {
    const { finish } = controllableSpawn();
    const pull = dockerManager.pullImage('v-ok');
    await settle();

    expect(hubItem('server-image:v-ok')).toMatchObject({
      kind: 'server-image',
      source: 'app',
      label: 'Server image (v-ok)',
      status: 'active',
      cancellable: true,
    });

    finish(0);
    await pull;
    expect(hubItem('server-image:v-ok')?.status).toBe('complete');
  });

  it('lets a caller that raises its own failure toast silence the one from the bar', async () => {
    const { finish } = controllableSpawn();
    const pull = dockerManager.pullImage('v-quiet', { errorToast: false });
    await settle();

    expect(hubItem('server-image:v-quiet')?.errorToast).toBe(false);

    finish(0);
    await pull;
  });

  it('fails the item with the friendly message, not the raw stderr', async () => {
    const { finish } = controllableSpawn();
    const pull = dockerManager.pullImage('v-auth');
    await settle();
    finish(1, 'unauthorized: authentication required');

    await expect(pull).rejects.toThrow();
    const item = hubItem('server-image:v-auth');
    expect(item?.status).toBe('error');
    expect(item?.error).not.toMatch(/unauthorized: authentication required/);
    expect(item?.error).toBeTruthy();
  });

  it('cancels the pull when the hub asks, and records it as cancelled', async () => {
    controllableSpawn();
    const pull = dockerManager.pullImage('v-cancel');
    await settle();

    expect(downloadHub.cancel('server-image:v-cancel')).toBe(true);

    await expect(pull).rejects.toThrow('Pull cancelled.');
    expect(hubItem('server-image:v-cancel')).toMatchObject({
      status: 'cancelled',
      detail: 'Cancelled by user',
    });
  });
});

describe('pullSidecarImage download tracking', () => {
  it('completes a sidecar-image item on success', async () => {
    const { finish } = controllableSpawn();
    const pull = dockerManager.pullSidecarImage();
    await settle();

    expect(hubItem('sidecar-image')).toMatchObject({
      kind: 'sidecar-image',
      status: 'active',
      cancellable: true,
    });

    finish(0);
    await pull;
    expect(hubItem('sidecar-image')?.status).toBe('complete');
  });

  it('fails the item when the pull exits non-zero', async () => {
    const { finish } = controllableSpawn();
    const pull = dockerManager.pullSidecarImage();
    await settle();
    finish(1, 'manifest unknown');

    await expect(pull).rejects.toThrow('manifest unknown');
    expect(hubItem('sidecar-image')).toMatchObject({ status: 'error', error: 'manifest unknown' });
  });

  it('records a user cancel as cancelled, not as a failure', async () => {
    controllableSpawn();
    const pull = dockerManager.pullSidecarImage();
    await settle();

    expect(downloadHub.cancel('sidecar-image')).toBe(true);

    await expect(pull).rejects.toThrow();
    expect(hubItem('sidecar-image')?.status).toBe('cancelled');
  });
});

describe('downloadGgmlModelToHost download tracking', () => {
  function fakeNetResponse(statusCode: number, contentLength?: number) {
    const request = new EventEmitter() as EventEmitter & { end: () => void };
    const response = new EventEmitter() as EventEmitter & {
      statusCode: number;
      headers: Record<string, string>;
    };
    response.statusCode = statusCode;
    response.headers =
      contentLength !== undefined ? { 'content-length': String(contentLength) } : {};
    request.end = () => queueMicrotask(() => request.emit('response', response));
    netRequest.mockReturnValue(request);
    return response;
  }

  it('reports bytes while downloading and completes the item', async () => {
    const response = fakeNetResponse(200, 8);
    const download = dockerManager.downloadGgmlModelToHost('ggml-tiny.bin');
    // The request is issued after a dynamic import; wait for it, then for the
    // response handler to attach its data listener.
    await vi.waitFor(() => expect(netRequest).toHaveBeenCalled());
    await settle();

    response.emit('data', Buffer.from('abcd'));
    response.emit('data', Buffer.from('efgh'));

    expect(hubItem('ggml-download-ggml-tiny.bin')).toMatchObject({
      kind: 'ggml-model',
      label: 'ggml-tiny.bin',
      status: 'active',
      bytesDone: 8,
      bytesTotal: 8,
    });

    response.emit('end');
    await download;
    expect(hubItem('ggml-download-ggml-tiny.bin')?.status).toBe('complete');
  });

  it('fails the item when the finished file cannot be moved into place', async () => {
    // e.g. antivirus briefly locking the freshly written file. The item must
    // not stay "downloading" forever.
    const response = fakeNetResponse(200, 4);
    const rename = vi.spyOn(fsDefault, 'renameSync').mockImplementation(() => {
      throw new Error('EBUSY: resource busy or locked');
    });
    try {
      const download = dockerManager.downloadGgmlModelToHost('ggml-locked.bin');
      await vi.waitFor(() => expect(netRequest).toHaveBeenCalled());
      await settle();
      response.emit('data', Buffer.from('abcd'));
      response.emit('end');

      await expect(download).rejects.toThrow(/EBUSY/);
      expect(hubItem('ggml-download-ggml-locked.bin')).toMatchObject({ status: 'error' });
    } finally {
      rename.mockRestore();
    }
  });

  it('fails the item on an HTTP error', async () => {
    fakeNetResponse(404);

    await expect(dockerManager.downloadGgmlModelToHost('ggml-base.bin')).rejects.toThrow(
      /HTTP 404/,
    );
    expect(hubItem('ggml-download-ggml-base.bin')?.status).toBe('error');
  });
});
