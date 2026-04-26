// @vitest-environment node

/**
 * Issue #103 — `pullImage` transient-network resilience.
 *
 * Covers the new `classifyPullError` pure helper and the retry loop layered
 * on top of `dockerManager.pullImage`. The Windows v1.3.3 reporter saw a
 * single `httpReadSeeker: failed open: ... EOF` and was stranded with raw
 * Go-style stderr in the Server view. These tests lock in:
 *   1) the EOF stderr classifies as `transient` + `retriable: true`,
 *   2) the retry loop fires only on transient errors (auth/not-found short-
 *      circuit on attempt 1),
 *   3) `cancelPull()` interrupts mid-backoff cleanly,
 *   4) the final user-facing error is the friendly one-sentence message —
 *      never the raw `httpReadSeeker` text.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { EventEmitter } from 'events';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

const userDataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-pull-retry-test-'));

vi.mock('electron', () => ({
  app: {
    isPackaged: false,
    getPath: (_name: string) => userDataRoot,
    setPath: vi.fn(),
  },
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
}));

vi.mock('child_process', async () => {
  const actual = await vi.importActual<typeof import('child_process')>('child_process');
  return {
    ...actual,
    spawn: vi.fn(),
  };
});

import { spawn } from 'child_process';
import { dockerManager, classifyPullError } from '../dockerManager.js';

type FakeProcOpts = {
  code: number | null;
  stderr?: string;
  stdout?: string;
};

interface FakeChildProcess extends EventEmitter {
  stdout: EventEmitter;
  stderr: EventEmitter;
  kill: ReturnType<typeof vi.fn>;
  __fired?: boolean;
}

function makeFakeProc(opts: FakeProcOpts): FakeChildProcess {
  const proc = new EventEmitter() as FakeChildProcess;
  proc.stdout = new EventEmitter();
  proc.stderr = new EventEmitter();
  proc.kill = vi.fn(() => {
    // Mimic SIGTERM: emit close with null code if not already closed.
    if (!proc.__fired) {
      proc.__fired = true;
      queueMicrotask(() => proc.emit('close', null));
    }
    return true;
  });
  // Asynchronously emit the configured outcome.
  queueMicrotask(() => {
    if (proc.__fired) return;
    proc.__fired = true;
    if (opts.stdout) proc.stdout.emit('data', Buffer.from(opts.stdout));
    if (opts.stderr) proc.stderr.emit('data', Buffer.from(opts.stderr));
    proc.emit('close', opts.code);
  });
  return proc;
}

function queueSpawnResults(results: FakeProcOpts[]): FakeChildProcess[] {
  const created: FakeChildProcess[] = [];
  const spawnMock = vi.mocked(spawn);
  spawnMock.mockReset();
  let i = 0;
  spawnMock.mockImplementation((..._args: unknown[]) => {
    const opts = results[i] ?? results[results.length - 1];
    i += 1;
    const proc = makeFakeProc(opts);
    created.push(proc);
    return proc as unknown as ReturnType<typeof spawn>;
  });
  return created;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

// ─────────────────────────────────────────────────────────────────────────────

describe('[P1] Issue #103 — classifyPullError (pure)', () => {
  it('classifies the v1.3.3 reporter EOF stderr as transient + retriable', () => {
    const v133Stderr =
      'failed to copy: httpReadSeeker: failed open: failed to do request: ' +
      'Get "https://ghcr.io/v2/homelab-00/transcriptionsuite-server/manifests/' +
      'sha256:f2cd7df17e7aef6b3de01fbc22865f73a836001c2f8305aafe09b1f47c2ca4ba": EOF';
    const result = classifyPullError(v133Stderr, 1);
    expect(result.kind).toBe('transient');
    expect(result.retriable).toBe(true);
    expect(result.friendly).toMatch(/network connection interrupted/i);
    // Friendly must NOT leak the raw Go-style stderr.
    expect(result.friendly).not.toMatch(/httpReadSeeker/i);
  });

  it('classifies "unauthorized" as auth (no retry) — wins over transient signals in mixed stderr', () => {
    const mixed = 'unauthorized: authentication required ... eof while reading';
    const result = classifyPullError(mixed, 1);
    expect(result.kind).toBe('auth');
    expect(result.retriable).toBe(false);
  });

  it('classifies "manifest unknown" as not_found (no retry)', () => {
    const result = classifyPullError('manifest unknown', 1);
    expect(result.kind).toBe('not_found');
    expect(result.retriable).toBe(false);
    expect(result.friendly).toMatch(/not found/i);
  });

  it('classifies "no space left on device" as disk_full (no retry)', () => {
    const result = classifyPullError('write /var/lib/docker: no space left on device', 1);
    expect(result.kind).toBe('disk_full');
    expect(result.retriable).toBe(false);
    expect(result.friendly).toMatch(/disk space/i);
  });

  it('classifies "connection reset" as transient', () => {
    const result = classifyPullError('Get "...": read tcp 1.2.3.4: connection reset by peer', 1);
    expect(result.kind).toBe('transient');
    expect(result.retriable).toBe(true);
  });

  it('classifies DNS "no such host" as transient — must NOT collide with not_found', () => {
    // Regression: an earlier draft had `'no such'` in NOT_FOUND_PULL_SIGNALS,
    // which mis-classified `"dial tcp: lookup ghcr.io: no such host"` (a real
    // DNS-failure transient) as a permanent error and skipped the retry.
    const result = classifyPullError(
      'Error response from daemon: dial tcp: lookup ghcr.io: no such host',
      1,
    );
    expect(result.kind).toBe('transient');
    expect(result.retriable).toBe(true);
  });

  it('classifies null exit code with no signal as transient (process died unexpectedly)', () => {
    const result = classifyPullError('', null);
    expect(result.kind).toBe('transient');
    expect(result.retriable).toBe(true);
  });

  it('classifies non-zero exit with empty/unmatched stderr as unknown (no retry)', () => {
    const result = classifyPullError('something exotic and unmatched', 137);
    expect(result.kind).toBe('unknown');
    expect(result.retriable).toBe(false);
    expect(result.friendly).toContain('137');
  });

  it('returns cancelled when cancelled flag is set, regardless of stderr', () => {
    const result = classifyPullError('eof connection reset whatever', null, true);
    expect(result.kind).toBe('cancelled');
    expect(result.retriable).toBe(false);
    expect(result.friendly).toBe('Pull cancelled.');
  });
});

// ─────────────────────────────────────────────────────────────────────────────

describe('[P1] Issue #103 — pullImage retry loop', () => {
  it('happy path: pull succeeds on attempt 1 — single spawn, resolves with stdout', async () => {
    queueSpawnResults([{ code: 0, stdout: 'Status: Image is up to date' }]);
    const result = await dockerManager.pullImage('v1.3.3');
    expect(result).toContain('up to date');
    expect(vi.mocked(spawn)).toHaveBeenCalledTimes(1);
  });

  it('retries once on transient EOF, then resolves on attempt 2', async () => {
    queueSpawnResults([
      { code: 1, stderr: 'httpReadSeeker: failed open: ... EOF' },
      { code: 0, stdout: 'pulled' },
    ]);
    const promise = dockerManager.pullImage('v1.3.3');
    // Drive the 2s backoff
    await vi.advanceTimersByTimeAsync(2000);
    const result = await promise;
    expect(result).toBe('pulled');
    expect(vi.mocked(spawn)).toHaveBeenCalledTimes(2);
  });

  it('exhausts all 3 attempts on persistent transient errors, rejects with friendly message', async () => {
    queueSpawnResults([
      { code: 1, stderr: 'EOF' },
      { code: 1, stderr: 'EOF' },
      { code: 1, stderr: 'EOF' },
    ]);
    const promise = dockerManager.pullImage('v1.3.3');
    // Catch rejection eagerly so the unhandled-rejection guard doesn't fire
    // while we advance the fake clock.
    const settled = promise.catch((e: Error) => e);
    await vi.advanceTimersByTimeAsync(2000); // first backoff
    await vi.advanceTimersByTimeAsync(5000); // second backoff
    const err = (await settled) as Error;
    expect(err).toBeInstanceOf(Error);
    expect(err.message).toMatch(/network connection interrupted/i);
    expect(err.message).not.toMatch(/httpReadSeeker/i);
    expect(vi.mocked(spawn)).toHaveBeenCalledTimes(3);
  });

  it('does not retry on auth — single spawn, rejects with friendly auth message', async () => {
    queueSpawnResults([{ code: 1, stderr: 'unauthorized: authentication required' }]);
    await expect(dockerManager.pullImage('v1.3.3')).rejects.toThrow(/registry rejected/i);
    expect(vi.mocked(spawn)).toHaveBeenCalledTimes(1);
  });

  it('does not retry on not_found — single spawn', async () => {
    queueSpawnResults([{ code: 1, stderr: 'manifest unknown' }]);
    await expect(dockerManager.pullImage('v9.9.9')).rejects.toThrow(/not found/i);
    expect(vi.mocked(spawn)).toHaveBeenCalledTimes(1);
  });

  it('cancelled mid-backoff: timer cleared, no further spawns, rejects with "Pull cancelled."', async () => {
    queueSpawnResults([
      { code: 1, stderr: 'EOF' }, // attempt 1 fails transient
      { code: 0, stdout: 'should-not-reach' }, // would succeed on attempt 2 — must not run
    ]);
    const promise = dockerManager.pullImage('v1.3.3');
    const settled = promise.catch((e: Error) => e);
    // Let attempt 1 fail and the loop enter the 2s backoff
    await vi.advanceTimersByTimeAsync(0);
    // Fire cancel during the backoff
    dockerManager.cancelPull();
    const err = (await settled) as Error;
    expect(err.message).toBe('Pull cancelled.');
    expect(vi.mocked(spawn)).toHaveBeenCalledTimes(1);
  });
});
