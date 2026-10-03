// @vitest-environment node

/**
 * GH-318 - image pulls and the host-side GGML fetch reported into the
 * DownloadHub, so the download bar shows them, can cancel them, and records
 * how they ended.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createHash } from 'crypto';
import { EventEmitter } from 'events';
import * as fs from 'fs';
import fsDefault from 'fs';
import * as http from 'http';
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

/** The running item with this id, else the one that ended last. */
const hubItem = (id: string): DownloadItem | undefined => {
  // snapshot() lists running items first, then ended ones in the order they ended.
  const matches = downloadHub.snapshot().filter((i) => i.id === id);
  return matches.find((i) => i.status === 'active') ?? matches[matches.length - 1];
};

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

  it('turns docker layer lines into layer-fraction progress, across chunk boundaries', async () => {
    const { proc, finish } = controllableSpawn();
    const pull = dockerManager.pullImage('v-layers');
    await settle();

    proc.stdout.emit(
      'data',
      Buffer.from(
        'aaaaaaaaaaaa: Pulling fs layer\nbbbbbbbbbbbb: Pulling fs layer\naaaaaaaaaaaa: Download comp',
      ),
    );
    proc.stdout.emit('data', Buffer.from('lete\n'));

    expect(hubItem('server-image:v-layers')).toMatchObject({
      status: 'active',
      percent: 50,
      detail: '1 of 2 layers',
    });

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

  it('reports podman blob lines, which arrive on stderr, as an indeterminate detail', async () => {
    const { proc, finish } = controllableSpawn();
    const pull = dockerManager.pullSidecarImage();
    await settle();

    proc.stderr.emit(
      'data',
      Buffer.from(
        'Trying to pull ghcr.io/x/y:latest...\nCopying blob sha256:aaaa1111\nCopying blob sha256:bbbb2222\n',
      ),
    );

    const item = hubItem('sidecar-image');
    expect(item?.detail).toBe('Copying 2 layers');
    expect(item?.percent).toBeUndefined();

    finish(0);
    await pull;
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

describe('ensureVulkanSidecarImage (pull before compose up)', () => {
  it('pulls the sidecar image when the Vulkan profile starts without it', async () => {
    const pull = vi.fn(async () => '');

    await dockerManager.ensureVulkanSidecarImage('vulkan', {
      hasImage: async () => false,
      pull,
    });

    expect(pull).toHaveBeenCalledTimes(1);
  });

  it('does not pull when the image is already there', async () => {
    const pull = vi.fn(async () => '');

    await dockerManager.ensureVulkanSidecarImage('vulkan', { hasImage: async () => true, pull });

    expect(pull).not.toHaveBeenCalled();
  });

  it('leaves every other profile alone', async () => {
    const hasImage = vi.fn(async () => false);
    const pull = vi.fn(async () => '');

    for (const profile of ['gpu', 'cpu', 'vulkan-wsl2', 'metal'] as const) {
      await dockerManager.ensureVulkanSidecarImage(profile, { hasImage, pull });
    }

    expect(hasImage).not.toHaveBeenCalled();
    expect(pull).not.toHaveBeenCalled();
  });

  it('fails the start with the pull error instead of letting compose time out on it', async () => {
    await expect(
      dockerManager.ensureVulkanSidecarImage('vulkan', {
        hasImage: async () => false,
        pull: async () => {
          throw new Error('manifest unknown');
        },
      }),
    ).rejects.toThrow('manifest unknown');
  });
});

describe('image pull through the Engine API', () => {
  let dir = '';
  let socketPath = '';
  let server: http.Server | null = null;
  let hits = 0;

  function serveEngine(handler: http.RequestListener): Promise<void> {
    return new Promise((resolve) => {
      server = http.createServer((req, res) => {
        hits += 1;
        handler(req, res);
      });
      server.listen(socketPath, resolve);
    });
  }

  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-dm-engine-'));
    socketPath = path.join(dir, 'docker.sock');
    hits = 0;
    dockerManager.configureEnginePull({
      enabled: true,
      resolveEndpoint: async () => ({ socketPath }),
    });
  });

  afterEach(async () => {
    dockerManager.configureEnginePull({ enabled: false });
    if (server) {
      server.closeAllConnections();
      await new Promise<void>((resolve) => server?.close(() => resolve()));
      server = null;
    }
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it('pulls without the CLI and reports the bytes the daemon streams', async () => {
    let finishStream: () => void = () => {};
    await serveEngine((_req, res) => {
      res.writeHead(200);
      res.write('{"status":"Pulling fs layer","progressDetail":{},"id":"aaaaaaaaaaaa"}\r\n');
      res.write(
        '{"status":"Downloading","progressDetail":{"current":1000,"total":4000},"id":"aaaaaaaaaaaa"}\r\n',
      );
      finishStream = () => res.end('{"status":"Status: Downloaded newer image"}\r\n');
    });
    vi.mocked(spawn).mockReset();

    const pull = dockerManager.pullImage('v-api');
    await vi.waitFor(() =>
      expect(hubItem('server-image:v-api')).toMatchObject({ bytesDone: 1000, percent: 25 }),
    );

    finishStream();
    await pull;
    expect(hubItem('server-image:v-api')?.status).toBe('complete');
    expect(spawn).not.toHaveBeenCalled();
  });

  it('falls back to the CLI when the Engine API pull fails', async () => {
    await serveEngine((_req, res) => {
      res.writeHead(200);
      res.end('{"errorDetail":{"message":"unauthorized"},"error":"unauthorized"}\r\n');
    });
    const { finish } = controllableSpawn();

    const pull = dockerManager.pullImage('v-fallback');
    await vi.waitFor(() => expect(spawn).toHaveBeenCalled());
    finish(0);
    await pull;

    expect(hits).toBe(1);
    expect(hubItem('server-image:v-fallback')?.status).toBe('complete');
  });

  it('cancels an Engine API pull by hanging up', async () => {
    await serveEngine((_req, res) => {
      res.writeHead(200);
      res.write('{"status":"Pulling fs layer","progressDetail":{},"id":"aaaaaaaaaaaa"}\r\n');
      // Never ends.
    });
    vi.mocked(spawn).mockReset();

    const pull = dockerManager.pullImage('v-api-cancel');
    await vi.waitFor(() => expect(hits).toBe(1));
    await settle();
    expect(dockerManager.isPulling()).toBe(true);
    expect(downloadHub.cancel('server-image:v-api-cancel')).toBe(true);

    await expect(pull).rejects.toThrow('Pull cancelled.');
    expect(hubItem('server-image:v-api-cancel')?.status).toBe('cancelled');
    expect(spawn).not.toHaveBeenCalled();
    expect(dockerManager.isPulling()).toBe(false);
  });

  it('pulls the sidecar image through the Engine API too', async () => {
    let seenUrl = '';
    await serveEngine((req, res) => {
      seenUrl = req.url ?? '';
      res.writeHead(200);
      res.end('{"status":"Status: Image is up to date"}\r\n');
    });
    vi.mocked(spawn).mockReset();

    await dockerManager.pullSidecarImage();

    expect(seenUrl).toContain('/images/create?fromImage=');
    expect(spawn).not.toHaveBeenCalled();
    expect(hubItem('sidecar-image')?.status).toBe('complete');
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

describe('downloadWhisperServerExe download tracking', () => {
  const exeBytes = Buffer.from('MZ-whisper-server-payload');
  const goodDigest = `sha256:${createHash('sha256').update(exeBytes).digest('hex')}`;

  function stubRegistry(digest: string): void {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/token')) {
          return { ok: true, status: 200, json: async () => ({ token: 't' }) };
        }
        if (url.includes('/manifests/')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              layers: [
                {
                  digest,
                  mediaType: 'application/vnd.microsoft.portable-executable',
                  size: exeBytes.length,
                },
              ],
            }),
          };
        }
        return {
          ok: true,
          status: 200,
          headers: { get: () => String(exeBytes.length) },
          body: new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(new Uint8Array(exeBytes.subarray(0, 5)));
              controller.enqueue(new Uint8Array(exeBytes.subarray(5)));
              controller.close();
            },
          }),
        };
      }),
    );
  }

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('reports the bytes of the verified download and completes', async () => {
    stubRegistry(goodDigest);

    await dockerManager.downloadWhisperServerExe();

    expect(hubItem('whisper-server')).toMatchObject({
      kind: 'whisper-server',
      status: 'complete',
      bytesDone: exeBytes.length,
      bytesTotal: exeBytes.length,
    });
  });

  it('fails the item and leaves no executable when the content hash does not match', async () => {
    stubRegistry(`sha256:${'0'.repeat(64)}`);

    await expect(dockerManager.downloadWhisperServerExe()).rejects.toThrow(/integrity check/);

    expect(hubItem('whisper-server')?.status).toBe('error');
    const leftovers = fs
      .readdirSync(userDataRoot, { recursive: true })
      .filter((f) => String(f).endsWith('.tmp'));
    expect(leftovers).toEqual([]);
  });
});
