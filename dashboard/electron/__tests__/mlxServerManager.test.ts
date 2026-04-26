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

const {
  mockSpawn,
  mockExistsSync,
  mockMkdirSync,
  mockSymlinkSync,
  mockCopyFileSync,
  mockWriteFileSync,
} = vi.hoisted(() => ({
  mockSpawn: vi.fn(),
  mockExistsSync: vi.fn().mockReturnValue(false),
  mockMkdirSync: vi.fn(),
  mockSymlinkSync: vi.fn(),
  mockCopyFileSync: vi.fn(),
  mockWriteFileSync: vi.fn(),
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
      copyFileSync: mockCopyFileSync,
      writeFileSync: mockWriteFileSync,
    },
    existsSync: mockExistsSync,
    mkdirSync: mockMkdirSync,
    symlinkSync: mockSymlinkSync,
    copyFileSync: mockCopyFileSync,
    writeFileSync: mockWriteFileSync,
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

// ── gh-86 #3 — sink-injection coverage ────────────────────────────────────

describe('[P2] MLXServerManager with injected log sink', () => {
  let manager: MLXServerManager;
  let mockWindow: ReturnType<typeof makeMockWindow>;
  let sinkAppend: ReturnType<typeof vi.fn>;
  let sinkFlush: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    mockWindow = makeMockWindow();
    sinkAppend = vi.fn();
    sinkFlush = vi.fn();
    manager = new MLXServerManager(() => mockWindow as never, {
      append: sinkAppend as (line: string) => void,
      flush: sinkFlush as () => void,
    });
    mockExistsSync.mockImplementation((p: string) => {
      if (typeof p !== 'string') return false;
      return p.includes('uvicorn') || p.includes('python3') || p.endsWith('/server');
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('routes stdout lines to sink.append (not direct webContents.send)', async () => {
    const child = makeChildProcess();
    mockSpawn.mockReturnValue(child);

    await manager.start({ port: 8000 });
    child.stdout.emit('data', Buffer.from('hello world\n'));

    expect(sinkAppend).toHaveBeenCalledWith('hello world');
    // Direct mlx:logLine sends should NOT happen when a sink is injected.
    const logLineSends = mockWindow.send.mock.calls.filter((call) => call[0] === 'mlx:logLine');
    expect(logLineSends).toHaveLength(0);
  });

  it('routes stderr lines through the sink with the [stderr] prefix', async () => {
    const child = makeChildProcess();
    mockSpawn.mockReturnValue(child);

    await manager.start({ port: 8000 });
    child.stderr.emit('data', Buffer.from('boom\n'));

    expect(sinkAppend).toHaveBeenCalledWith('[stderr] boom');
  });

  it('routes internal manager messages (start, exit) through the sink', async () => {
    const child = makeChildProcess();
    mockSpawn.mockReturnValue(child);

    await manager.start({ port: 8000 });
    child.emit('exit', 1, null);

    // Pre-existing bug pre-gh-86 #3: these internal messages only hit the
    // in-memory ring and never reached the renderer. With sink injection they
    // now flow through the sink as well.
    const appendedLines: string[] = sinkAppend.mock.calls.map((call) => call[0] as string);
    expect(appendedLines.some((l) => l.includes('Starting uvicorn on port 8000'))).toBe(true);
    expect(appendedLines.some((l) => l.includes('exited with code 1'))).toBe(true);
  });

  it('still preserves the in-memory ring buffer alongside the sink', async () => {
    const child = makeChildProcess();
    mockSpawn.mockReturnValue(child);

    await manager.start({ port: 8000 });
    child.stdout.emit('data', Buffer.from('ring-line\n'));

    // Ring buffer is the source for getLogs(tail) and must keep working.
    expect(manager.getLogs()).toContain('ring-line');
    expect(sinkAppend).toHaveBeenCalledWith('ring-line');
  });
});
