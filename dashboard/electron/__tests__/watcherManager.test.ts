// @vitest-environment node

/**
 * WatcherManager - GH-311 regression coverage.
 *
 * chokidar is mocked so tests emit `add` events directly; the watched folder
 * and the ledger are real files in a temp dir; xxhash-wasm is replaced by a
 * tiny deterministic hash so identical content yields identical fingerprints.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { EventEmitter } from 'events';
import fs from 'fs';
import os from 'os';
import path from 'path';

const { mockWatch, mockUserData } = vi.hoisted(() => ({
  mockWatch: vi.fn(),
  mockUserData: { dir: '' },
}));

vi.mock('chokidar', () => ({ watch: mockWatch }));

vi.mock('electron', () => ({
  app: { getPath: () => mockUserData.dir },
  BrowserWindow: class {},
}));

vi.mock('xxhash-wasm', () => ({
  default: async () => ({
    h64Raw: (bytes: Uint8Array) => {
      let h = 0n;
      for (const b of bytes) h = (h * 31n + BigInt(b)) & 0xffffffffffffffffn;
      return h;
    },
  }),
}));

import { WatcherManager } from '../watcherManager.js';

type FakeWatcher = EventEmitter & {
  close: ReturnType<typeof vi.fn>;
  options: Record<string, unknown>;
};

const BATCH_DELAY_MS = 3_000;

let tmpDir: string;
let watchDir: string;
let watchers: FakeWatcher[];
let send: ReturnType<typeof vi.fn>;
let manager: WatcherManager;

function ledgerPath(type: 'session' | 'notebook'): string {
  return path.join(mockUserData.dir, `watch-ledger-${type}.json`);
}

function readLedger(type: 'session' | 'notebook'): string[] {
  return JSON.parse(fs.readFileSync(ledgerPath(type), 'utf8')) as string[];
}

function writeFile(name: string, content: Buffer): string {
  const p = path.join(watchDir, name);
  fs.writeFileSync(p, content);
  return p;
}

/** Emit chokidar `add` for a path and let the batch window elapse. */
async function detect(watcher: FakeWatcher, filePath: string): Promise<void> {
  watcher.emit('add', filePath);
  await vi.advanceTimersByTimeAsync(0);
  await vi.advanceTimersByTimeAsync(BATCH_DELAY_MS);
}

function sentPayloads(channel: string): unknown[] {
  return send.mock.calls.filter((c) => c[0] === channel).map((c) => c[1]);
}

beforeEach(() => {
  vi.useFakeTimers();
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'watcher-gh311-'));
  mockUserData.dir = path.join(tmpDir, 'userData');
  watchDir = path.join(tmpDir, 'watch');
  fs.mkdirSync(mockUserData.dir);
  fs.mkdirSync(watchDir);
  watchers = [];
  mockWatch.mockReset();
  mockWatch.mockImplementation((_p: string, options: Record<string, unknown>) => {
    const w = Object.assign(new EventEmitter(), {
      close: vi.fn().mockResolvedValue(undefined),
      options,
    }) as FakeWatcher;
    watchers.push(w);
    return w;
  });
  send = vi.fn();
  manager = new WatcherManager(
    () => ({ webContents: { send }, isDestroyed: () => false }) as never,
  );
});

afterEach(async () => {
  await manager.destroyAll();
  vi.useRealTimers();
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

describe('readiness - waits for writes to finish (GH-311 problem 1)', () => {
  it('asks chokidar to hold `add` until the file size has been stable', async () => {
    await manager.startSessionWatcher(watchDir);

    expect(mockWatch).toHaveBeenCalledTimes(1);
    expect(watchers[0].options).toMatchObject({
      depth: 0,
      ignoreInitial: true,
      awaitWriteFinish: { stabilityThreshold: 5_000, pollInterval: 500 },
    });
  });

  it('dispatches a non-empty file after the batch window', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));

    await detect(watchers[0], file);

    expect(sentPayloads('watcher:filesDetected')).toEqual([
      expect.objectContaining({ type: 'session', files: [file], count: 1 }),
    ]);
  });

  it('reports an empty file as skipped instead of dropping it silently', async () => {
    await manager.startNotebookWatcher(watchDir);
    const file = writeFile('empty.wav', Buffer.alloc(0));

    await detect(watchers[0], file);

    expect(sentPayloads('watcher:filesDetected')).toEqual([]);
    expect(sentPayloads('watcher:fileSkipped')).toEqual([
      { type: 'notebook', path: file, reason: 'empty' },
    ]);
  });

  it('reports a file that vanished before it could be read as unreadable', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = path.join(watchDir, 'gone.wav');

    await detect(watchers[0], file);

    expect(sentPayloads('watcher:filesDetected')).toEqual([]);
    expect(sentPayloads('watcher:fileSkipped')).toEqual([
      { type: 'session', path: file, reason: 'unreadable' },
    ]);
  });
});
