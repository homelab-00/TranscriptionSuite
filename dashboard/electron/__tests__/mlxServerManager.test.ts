// @vitest-environment node

/**
 * P2-PLAT-003 — MLX server manager lifecycle
 *
 * Tests the MLXServerManager class: initial state, safe stop when already
 * stopped, log accumulation, and status transitions via mocked child_process.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { EventEmitter } from 'events';

// ── Hoisted mocks ──────────────────────────────────────────────────────────

const { mockSpawn, mockExistsSync, mockMkdirSync, mockSymlinkSync } = vi.hoisted(() => ({
  mockSpawn: vi.fn(),
  mockExistsSync: vi.fn().mockReturnValue(false),
  mockMkdirSync: vi.fn(),
  mockSymlinkSync: vi.fn(),
}));

vi.mock('child_process', () => ({
  spawn: mockSpawn,
}));

vi.mock('fs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('fs')>();
  return {
    ...actual,
    default: {
      ...actual,
      existsSync: mockExistsSync,
      mkdirSync: mockMkdirSync,
      symlinkSync: mockSymlinkSync,
    },
    existsSync: mockExistsSync,
    mkdirSync: mockMkdirSync,
    symlinkSync: mockSymlinkSync,
  };
});

vi.mock('electron', () => ({
  app: {
    getAppPath: () => '/mock/dashboard',
    getPath: (name: string) => `/mock/${name}`,
  },
  BrowserWindow: class {
    webContents = { send: vi.fn() };
    isDestroyed() {
      return false;
    }
  },
}));

import { MLXServerManager } from '../mlxServerManager.js';

// ── Helpers ────────────────────────────────────────────────────────────────

function makeChildProcess() {
  const child = new EventEmitter() as EventEmitter & {
    stdout: EventEmitter;
    stderr: EventEmitter;
    kill: ReturnType<typeof vi.fn>;
    pid: number;
  };
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.kill = vi.fn();
  child.pid = 12345;
  return child;
}

function makeMockWindow() {
  const send = vi.fn();
  return {
    webContents: { send },
    isDestroyed: () => false,
    send,
  };
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe('[P2] MLXServerManager', () => {
  let manager: MLXServerManager;
  let mockWindow: ReturnType<typeof makeMockWindow>;

  beforeEach(() => {
    vi.clearAllMocks();
    mockWindow = makeMockWindow();
    manager = new MLXServerManager(() => mockWindow as any);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('has initial status of "stopped"', () => {
    expect(manager.getStatus()).toBe('stopped');
  });

  it('returns empty logs initially', () => {
    expect(manager.getLogs()).toEqual([]);
  });

  it('stop() when already stopped is safe and sets status to stopped', async () => {
    expect(manager.getStatus()).toBe('stopped');
    await expect(manager.stop()).resolves.toBeUndefined();
    expect(manager.getStatus()).toBe('stopped');
  });

  it('transitions to "starting" on start() and "running" when startup complete', async () => {
    // Make the uvicorn binary exist at the dev path
    mockExistsSync.mockImplementation((p: string) => {
      if (typeof p === 'string' && p.includes('uvicorn')) return true;
      if (typeof p === 'string' && p.includes('python3')) return true;
      // server symlink check
      if (typeof p === 'string' && p.endsWith('/server')) return true;
      return false;
    });

    const child = makeChildProcess();
    mockSpawn.mockReturnValue(child);

    const startPromise = manager.start({ port: 8000 });

    // Manager should be in 'starting' state
    expect(manager.getStatus()).toBe('starting');

    // Simulate uvicorn stderr readiness message
    child.stderr.emit('data', Buffer.from('Application startup complete\n'));

    await startPromise;

    expect(manager.getStatus()).toBe('running');
    expect(mockWindow.send).toHaveBeenCalledWith('mlx:statusChanged', 'starting');
    expect(mockWindow.send).toHaveBeenCalledWith('mlx:statusChanged', 'running');
  });

  it('transitions to "error" on unexpected process exit', async () => {
    mockExistsSync.mockImplementation((p: string) => {
      if (
        typeof p === 'string' &&
        (p.includes('uvicorn') || p.includes('python3') || p.endsWith('/server'))
      )
        return true;
      return false;
    });

    const child = makeChildProcess();
    mockSpawn.mockReturnValue(child);

    await manager.start({ port: 8000 });
    // Simulate unexpected exit (not via stop())
    child.emit('exit', 1, null);

    expect(manager.getStatus()).toBe('error');

    // Logs should contain the exit message
    const logs = manager.getLogs();
    expect(logs.some((l: string) => l.includes('exited with code 1'))).toBe(true);
  });
});
