// @vitest-environment node

/**
 * P1-DOCK-002 — Container runtime detection: Docker vs Podman
 *
 * Tests that detectRuntime() correctly identifies the available container
 * runtime, handles partial availability (binary found but daemon not running),
 * and returns actionable guidance when no runtime is found.
 *
 * 3 primary detection scenarios + edge cases for compose/socket/override.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ─── Hoisted Mocks ─────────────────────────────────────────────────────────

const { mockExecFile, mockConnect, mockExistsSync } = vi.hoisted(() => ({
  mockExecFile: vi.fn(),
  mockConnect: vi.fn(),
  mockExistsSync: vi.fn(),
}));

vi.mock('child_process', () => ({
  execFile: mockExecFile,
}));

vi.mock('net', () => ({
  default: { connect: (...args: unknown[]) => mockConnect(...args) },
  connect: (...args: unknown[]) => mockConnect(...args),
}));

// Partial fs mock — only override existsSync for socket probing.
vi.mock('fs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('fs')>();
  return {
    ...actual,
    default: { ...actual, existsSync: mockExistsSync },
    existsSync: mockExistsSync,
  };
});

// ─── Import after mocks ────────────────────────────────────────────────────

import { detectRuntime, resetDetection } from '../containerRuntime.js';

// ─── Helpers ────────────────────────────────────────────────────────────────

const originalPlatform = process.platform;
const originalEnv = { ...process.env };

function setPlatform(platform: string): void {
  Object.defineProperty(process, 'platform', { value: platform, writable: true });
}

/**
 * Configure mockExecFile to succeed or fail for specific command+args combos.
 * Keys are `"bin arg1"` strings (prefix-matched); values are stdout or Error.
 */
function setExecResponses(responses: Record<string, string | Error>): void {
  mockExecFile.mockImplementation(
    (cmd: string, args: string[], _opts: unknown, callback?: Function) => {
      const key = `${cmd} ${args.join(' ')}`;
      const matched = Object.entries(responses).find(([k]) => key.startsWith(k));

      if (matched && !(matched[1] instanceof Error)) {
        if (callback) callback(null, { stdout: matched[1] });
        return;
      }

      const err = matched?.[1] instanceof Error ? matched[1] : new Error(`ENOENT: ${key}`);
      if (callback) callback(err, { stdout: '' });
    },
  );
}

/** Make mockConnect simulate a successful or failed socket connection. */
function setSocketResult(succeeds: boolean): void {
  mockConnect.mockImplementation(() => {
    const handlers: Record<string, Function> = {};
    const sock = {
      on: (event: string, cb: Function) => {
        handlers[event] = cb;
        return sock;
      },
      destroy: vi.fn(),
    };
    setTimeout(() => {
      if (succeeds && handlers['connect']) handlers['connect']();
      else if (!succeeds && handlers['error']) handlers['error'](new Error('refused'));
    }, 0);
    return sock;
  });
}

beforeEach(() => {
  resetDetection();
  vi.clearAllMocks();
  // Default: socket files exist and connections succeed
  mockExistsSync.mockReturnValue(true);
  setSocketResult(true);
  delete process.env.CONTAINER_RUNTIME;
  delete process.env.DOCKER_HOST;
  delete process.env.CONTAINER_HOST;
});

afterEach(() => {
  Object.defineProperty(process, 'platform', { value: originalPlatform, writable: true });
  process.env = { ...originalEnv };
});

// ─── P1-DOCK-002: Container Runtime Detection ──────────────────────────────

describe('[P1] detectRuntime', () => {
  // ── Scenario 1: Docker available ──────────────────────────────────────

  it('detects Docker when daemon is running', async () => {
    setExecResponses({
      'docker version': '24.0.7',
      'docker compose version': 'Docker Compose v2.24.0',
    });

    const result = await detectRuntime();

    expect(result.runtime).not.toBeNull();
    expect(result.runtime!.kind).toBe('docker');
    expect(result.runtime!.bin).toBe('docker');
    expect(result.runtime!.displayName).toBe('Docker');
    expect(result.binaryFoundButNotRunning).toBe(false);
    expect(result.composeAvailable).toBe(true);
  });

  it('Docker running but compose missing: runtime set, guidance provided', async () => {
    setExecResponses({
      'docker version': '24.0.7',
    });

    const result = await detectRuntime();

    expect(result.runtime).not.toBeNull();
    expect(result.runtime!.kind).toBe('docker');
    expect(result.composeAvailable).toBe(false);
    expect(result.guidance).toContain('Compose');
  });

  // ── Scenario 2: Podman available ──────────────────────────────────────

  it('detects Podman when running with live socket', async () => {
    setPlatform('linux');
    setExecResponses({
      'podman version': '4.9.3',
      'podman compose version': 'podman-compose 1.0.6',
    });

    const result = await detectRuntime();

    expect(result.runtime).not.toBeNull();
    expect(result.runtime!.kind).toBe('podman');
    expect(result.runtime!.bin).toBe('podman');
    expect(result.runtime!.displayName).toBe('Podman');
    expect(result.composeAvailable).toBe(true);
  });

  // ── Scenario 3: Neither available ─────────────────────────────────────

  it('returns null runtime when nothing is installed', async () => {
    setExecResponses({});

    const result = await detectRuntime();

    expect(result.runtime).toBeNull();
    expect(result.binaryFoundButNotRunning).toBe(false);
    expect(result.binaryFound).toBeNull();
  });

  // ── Edge cases ────────────────────────────────────────────────────────

  it('binary found but daemon not running: sets binaryFoundButNotRunning', async () => {
    setExecResponses({
      'docker --version': 'Docker version 24.0.7, build afdd53b',
    });

    const result = await detectRuntime();

    expect(result.runtime).toBeNull();
    expect(result.binaryFoundButNotRunning).toBe(true);
    expect(result.binaryFound).toBe('docker');
  });

  it('CONTAINER_RUNTIME env override forces detection', async () => {
    process.env.CONTAINER_RUNTIME = 'docker';
    setExecResponses({
      'docker version': '24.0.7',
      'docker compose version': 'v2',
    });

    const result = await detectRuntime();

    expect(result.runtime).not.toBeNull();
    expect(result.runtime!.kind).toBe('docker');
  });

  it('Podman socket dead on Linux: returns guidance, no runtime', async () => {
    setPlatform('linux');
    // Socket file exists but connection fails
    mockExistsSync.mockReturnValue(true);
    setSocketResult(false);
    setExecResponses({
      'podman version': '4.9.3',
    });

    const result = await detectRuntime();

    expect(result.runtime).toBeNull();
    expect(result.socketDead).toBe(true);
    expect(result.guidance).toContain('socket');
  });

  it('resetDetection() clears cache so next call re-probes', async () => {
    setExecResponses({
      'docker version': '24.0.7',
      'docker compose version': 'v2',
    });

    const first = await detectRuntime();
    expect(first.runtime).not.toBeNull();
    expect(first.runtime!.kind).toBe('docker');

    // Reset cache then wipe mock → re-detection finds nothing
    resetDetection();
    setExecResponses({});
    const second = await detectRuntime();
    expect(second.runtime).toBeNull();
  });
});
