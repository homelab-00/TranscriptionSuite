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
  it.each([['session'], ['notebook']] as const)(
    'asks chokidar to hold `add` until the file size has been stable (%s watcher)',
    async (type) => {
      if (type === 'session') {
        await manager.startSessionWatcher(watchDir);
      } else {
        await manager.startNotebookWatcher(watchDir);
      }

      expect(mockWatch).toHaveBeenCalledTimes(1);
      expect(watchers[0].options).toMatchObject({
        depth: 0,
        ignoreInitial: true,
        awaitWriteFinish: { stabilityThreshold: 5_000, pollInterval: 500 },
      });
    },
  );

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

describe('ledger - recorded only after the renderer confirms the import (GH-311 problem 2)', () => {
  it('does not write the ledger when a file is merely dispatched', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));

    await detect(watchers[0], file);

    expect(sentPayloads('watcher:filesDetected')).toHaveLength(1);
    expect(fs.existsSync(ledgerPath('session'))).toBe(false);
  });

  it("records the fingerprint on 'imported' and skips identical content afterwards", async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], file);

    manager.reportImportOutcome({ type: 'session', path: file, outcome: 'imported' });
    expect(readLedger('session')).toHaveLength(1);

    const copy = writeFile('a-copy.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], copy);

    expect(sentPayloads('watcher:filesDetected')).toHaveLength(1);
    expect(sentPayloads('watcher:fileSkipped')).toEqual([
      { type: 'session', path: copy, reason: 'already-imported' },
    ]);
  });

  it.each(['failed', 'dropped'] as const)(
    "forgets the file on '%s' so putting it back imports it again",
    async (outcome) => {
      await manager.startNotebookWatcher(watchDir);
      const file = writeFile('chunk_00.wav', Buffer.alloc(4096, 2));
      await detect(watchers[0], file);

      manager.reportImportOutcome({ type: 'notebook', path: file, outcome });
      expect(fs.existsSync(ledgerPath('notebook'))).toBe(false);

      const again = writeFile('chunk_00-again.wav', Buffer.alloc(4096, 2));
      await detect(watchers[0], again);

      expect(sentPayloads('watcher:filesDetected')).toHaveLength(2);
      expect(sentPayloads('watcher:fileSkipped')).toEqual([]);
    },
  );

  it('skips identical content while the first copy is still in flight', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], file);

    const copy = writeFile('b.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], copy);

    expect(sentPayloads('watcher:filesDetected')).toHaveLength(1);
    expect(sentPayloads('watcher:fileSkipped')).toEqual([
      { type: 'session', path: copy, reason: 'already-queued' },
    ]);
  });

  it("records a retried job's success even though it is no longer in flight", async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], file);

    manager.reportImportOutcome({ type: 'session', path: file, outcome: 'failed' });
    manager.reportImportOutcome({ type: 'session', path: file, outcome: 'imported' });

    expect(readLedger('session')).toHaveLength(1);
  });

  it('forgets files that were batched but never dispatched when the watcher stops', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));
    watchers[0].emit('add', file);
    await vi.advanceTimersByTimeAsync(0);
    await manager.stopSessionWatcher(); // before the batch window elapses

    await manager.startSessionWatcher(watchDir);
    await detect(watchers[1], file);

    expect(sentPayloads('watcher:filesDetected')).toHaveLength(1);
    expect(sentPayloads('watcher:fileSkipped')).toEqual([]);
  });
});

describe('ledger - loading and clearing', () => {
  it('drops stale in-memory fingerprints when the ledger file is missing on restart', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], file);
    manager.reportImportOutcome({ type: 'session', path: file, outcome: 'imported' });
    expect(readLedger('session')).toHaveLength(1);

    fs.rmSync(ledgerPath('session'));
    await manager.stopSessionWatcher();
    await manager.startSessionWatcher(watchDir);

    const copy = writeFile('a-copy.wav', Buffer.alloc(4096, 1));
    await detect(watchers[1], copy);

    expect(sentPayloads('watcher:filesDetected')).toHaveLength(2);
  });

  it('clearSessionLedger empties the ledger file and allows the file to be imported again', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], file);
    manager.reportImportOutcome({ type: 'session', path: file, outcome: 'imported' });

    manager.clearSessionLedger();
    expect(readLedger('session')).toEqual([]);

    const copy = writeFile('a-copy.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], copy);

    expect(sentPayloads('watcher:filesDetected')).toHaveLength(2);
  });

  it('releases dispatched but unacknowledged files when the watcher restarts (renderer reload)', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], file);

    await manager.stopSessionWatcher();
    await manager.startSessionWatcher(watchDir);
    const copy = writeFile('a-copy.wav', Buffer.alloc(4096, 1));
    await detect(watchers[1], copy);

    expect(sentPayloads('watcher:filesDetected')).toHaveLength(2);
    expect(sentPayloads('watcher:fileSkipped')).toEqual([]);

    // A late acknowledgement for the first file is still recorded.
    manager.reportImportOutcome({ type: 'session', path: file, outcome: 'imported' });
    expect(readLedger('session')).toHaveLength(1);
  });

  it('clearSessionLedger also releases files that are still in flight', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], file);

    manager.clearSessionLedger();
    const copy = writeFile('a-copy.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], copy);

    expect(sentPayloads('watcher:filesDetected')).toHaveLength(2);
    expect(sentPayloads('watcher:fileSkipped')).toEqual([]);
  });

  it('clearNotebookLedger also releases files that are still in flight', async () => {
    await manager.startNotebookWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], file);

    manager.clearNotebookLedger();
    const copy = writeFile('a-copy.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], copy);

    expect(sentPayloads('watcher:filesDetected')).toHaveLength(2);
    expect(sentPayloads('watcher:fileSkipped')).toEqual([]);
  });

  it('honors an existing ledger after an app restart', async () => {
    await manager.startSessionWatcher(watchDir);
    const file = writeFile('a.wav', Buffer.alloc(4096, 1));
    await detect(watchers[0], file);
    manager.reportImportOutcome({ type: 'session', path: file, outcome: 'imported' });
    expect(readLedger('session')).toHaveLength(1);

    await manager.destroyAll();
    manager = new WatcherManager(
      () => ({ webContents: { send }, isDestroyed: () => false }) as never,
    );

    await manager.startSessionWatcher(watchDir);
    const copy = writeFile('a-copy.wav', Buffer.alloc(4096, 1));
    await detect(watchers[watchers.length - 1], copy);

    expect(sentPayloads('watcher:fileSkipped')).toEqual([
      { type: 'session', path: copy, reason: 'already-imported' },
    ]);
    expect(sentPayloads('watcher:filesDetected')).toHaveLength(1);
  });
});
