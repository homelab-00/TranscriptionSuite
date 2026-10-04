// @vitest-environment node

/**
 * GH-318 - pulling an image through the Docker Engine API, which (unlike the
 * CLI without a TTY) streams byte progress per layer.
 *
 * The transport is exercised against a real HTTP server on a unix socket, so
 * the request shape, the streamed JSON framing and the abort path are all
 * the real thing.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs';
import * as http from 'http';
import * as os from 'os';
import * as path from 'path';
import {
  parseEngineHost,
  pingEngine,
  pullViaEngine,
  splitImageReference,
  type EnginePullMessage,
} from '../enginePull.js';

let dir = '';
let socketPath = '';
let server: http.Server | null = null;
let requests: Array<{ method?: string; url?: string }> = [];

function serve(handler: http.RequestListener): Promise<void> {
  return new Promise((resolve) => {
    server = http.createServer((req, res) => {
      requests.push({ method: req.method, url: req.url });
      handler(req, res);
    });
    server.listen(socketPath, resolve);
  });
}

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-engine-pull-'));
  socketPath = path.join(dir, 'docker.sock');
  requests = [];
});

afterEach(async () => {
  if (server) {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server?.close(() => resolve()));
    server = null;
  }
  fs.rmSync(dir, { recursive: true, force: true });
});

describe('parseEngineHost', () => {
  it('reads a unix socket endpoint', () => {
    expect(parseEngineHost('unix:///var/run/docker.sock')).toEqual({
      socketPath: '/var/run/docker.sock',
    });
  });

  it('reads the Docker Desktop named pipe', () => {
    expect(parseEngineHost('npipe:////./pipe/docker_engine')).toEqual({
      socketPath: '\\\\.\\pipe\\docker_engine',
    });
  });

  it('gives up on endpoints it cannot reach as a local socket', () => {
    expect(parseEngineHost('tcp://10.0.0.5:2375')).toBeNull();
    expect(parseEngineHost('ssh://user@host')).toBeNull();
    expect(parseEngineHost('')).toBeNull();
    expect(parseEngineHost(undefined)).toBeNull();
  });
});

describe('splitImageReference', () => {
  it('splits repository and tag at the last colon after the last slash', () => {
    expect(splitImageReference('ghcr.io/homelab-00/whisper-cpp-linux:latest')).toEqual({
      repo: 'ghcr.io/homelab-00/whisper-cpp-linux',
      tag: 'latest',
    });
  });

  it('keeps a registry port out of the tag', () => {
    expect(splitImageReference('localhost:5000/app')).toEqual({
      repo: 'localhost:5000/app',
      tag: 'latest',
    });
  });
});

describe('pingEngine', () => {
  it('is true when the daemon answers', async () => {
    await serve((_req, res) => res.end('OK'));

    expect(await pingEngine({ socketPath })).toBe(true);
    expect(requests[0]).toEqual({ method: 'GET', url: '/_ping' });
  });

  it('is false when nothing listens on the socket', async () => {
    expect(await pingEngine({ socketPath })).toBe(false);
  });
});

describe('pullViaEngine', () => {
  it('requests the image and streams the progress messages', async () => {
    await serve((_req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.write('{"status":"Pulling fs layer","progressDetail":{},"id":"aaaaaaaaaaaa"}\r\n');
      // A message split across two chunks must still arrive whole.
      res.write('{"status":"Downloading","progressDetail":{"current":10,');
      res.write('"total":40},"id":"aaaaaaaaaaaa"}\r\n');
      res.end('{"status":"Status: Downloaded newer image for x:1"}\r\n');
    });
    const messages: EnginePullMessage[] = [];

    const result = await pullViaEngine(
      { socketPath },
      { repo: 'ghcr.io/org/app', tag: 'v1' },
      (m) => messages.push(m),
      new AbortController().signal,
    );

    expect(result).toEqual({ ok: true });
    expect(requests[0]).toEqual({
      method: 'POST',
      url: '/images/create?fromImage=ghcr.io%2Forg%2Fapp&tag=v1',
    });
    expect(messages.map((m) => m.status)).toEqual([
      'Pulling fs layer',
      'Downloading',
      'Status: Downloaded newer image for x:1',
    ]);
    expect(messages[1].progressDetail).toEqual({ current: 10, total: 40 });
  });

  it('fails with the daemon error reported inside the stream', async () => {
    await serve((_req, res) => {
      res.writeHead(200);
      res.end('{"errorDetail":{"message":"manifest unknown"},"error":"manifest unknown"}\r\n');
    });

    const result = await pullViaEngine(
      { socketPath },
      { repo: 'x', tag: 'missing' },
      () => {},
      new AbortController().signal,
    );

    expect(result).toEqual({ ok: false, error: 'manifest unknown' });
  });

  it('fails with the message of a non-200 answer', async () => {
    await serve((_req, res) => {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end('{"message":"pull access denied"}');
    });

    const result = await pullViaEngine(
      { socketPath },
      { repo: 'x', tag: 'v' },
      () => {},
      new AbortController().signal,
    );

    expect(result).toEqual({ ok: false, error: 'pull access denied' });
  });

  it('fails cleanly when the socket is unreachable', async () => {
    const result = await pullViaEngine(
      { socketPath },
      { repo: 'x', tag: 'v' },
      () => {},
      new AbortController().signal,
    );

    expect(result.ok).toBe(false);
  });

  it('stops and reports a cancel when aborted mid-pull', async () => {
    let closedByClient = false;
    await serve((_req, res) => {
      res.writeHead(200);
      res.write('{"status":"Pulling fs layer","progressDetail":{},"id":"aaaaaaaaaaaa"}\r\n');
      res.on('close', () => {
        closedByClient = true;
      });
      // Never ends: the client has to hang up.
    });
    const controller = new AbortController();
    const messages: EnginePullMessage[] = [];

    const pending = pullViaEngine(
      { socketPath },
      { repo: 'x', tag: 'v' },
      (m) => {
        messages.push(m);
        controller.abort();
      },
      controller.signal,
    );

    expect(await pending).toEqual({ ok: false, error: 'cancelled', cancelled: true });
    expect(messages).toHaveLength(1);
    // The daemon cancels a pull when its client disconnects.
    await vi.waitFor(() => expect(closedByClient).toBe(true));
  });

  it('survives a message handler that throws', async () => {
    await serve((_req, res) => {
      res.writeHead(200);
      res.end('{"status":"Pulling fs layer","id":"aaaaaaaaaaaa"}\r\n');
    });

    const result = await pullViaEngine(
      { socketPath },
      { repo: 'x', tag: 'v' },
      () => {
        throw new Error('aggregator bug');
      },
      new AbortController().signal,
    );

    expect(result).toEqual({ ok: true });
  });
});
