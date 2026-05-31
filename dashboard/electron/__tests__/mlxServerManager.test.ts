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
  mockApp,
} = vi.hoisted(() => ({
  mockSpawn: vi.fn(),
  mockExistsSync: vi.fn().mockReturnValue(false),
  mockMkdirSync: vi.fn(),
  mockSymlinkSync: vi.fn(),
  mockCopyFileSync: vi.fn(),
  mockWriteFileSync: vi.fn(),
  // Mutable so individual tests can flip packaged-vs-dev and override getVersion().
  mockApp: { isPackaged: false, getVersion: (): string => '1.3.5' },
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
    get isPackaged() {
      return mockApp.isPackaged;
    },
    getVersion: () => mockApp.getVersion(),
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

// ── GH #124 — actionable diagnostics when the uvicorn binary is missing ─────
//
// The resolution logic is correct; a miss is almost always environmental (wrong/thin
// DMG or a lost venv). These tests lock the three message branches and assert the
// diagnostic reaches the log ring/sink BEFORE start() throws (symptom 3: empty logs).

describe('[GH #124] MLXServerManager uvicorn-missing diagnostics', () => {
  const proc = process as unknown as { resourcesPath?: string; arch: string };
  const originalResourcesPath = proc.resourcesPath;
  const originalArch = proc.arch;
  let mockWindow: ReturnType<typeof makeMockWindow>;

  beforeEach(() => {
    vi.clearAllMocks();
    mockWindow = makeMockWindow();
    mockApp.isPackaged = false;
    mockApp.getVersion = () => '1.3.5';
    // Default the packaged cases to Apple Silicon — the platform these messages target.
    // process.arch is writable:false but configurable:true, so redefine rather than assign.
    Object.defineProperty(process, 'arch', { value: 'arm64', configurable: true });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    proc.resourcesPath = originalResourcesPath;
    Object.defineProperty(process, 'arch', { value: originalArch, configurable: true });
  });

  it('thin DMG (packaged arm64, no Resources/backend): names the -metal.dmg and logs the checked path before throwing', async () => {
    mockApp.isPackaged = true;
    proc.resourcesPath = '/mock/Resources';
    // Nothing exists: no uvicorn candidate, and Resources/backend is absent.
    mockExistsSync.mockReturnValue(false);

    const manager = new MLXServerManager(() => mockWindow as never);
    await expect(manager.start({ port: 8000 })).rejects.toThrow(/dashboard-only build/);

    const logs = manager.getLogs();
    expect(logs.some((l: string) => l.includes('dashboard-only build'))).toBe(true);
    expect(
      logs.some((l: string) => l.includes('TranscriptionSuite-1.3.5-arm64-mac-metal.dmg')),
    ).toBe(true);
    // Probed-path evidence (I/O matrix) must reach the log.
    expect(
      logs.some((l: string) => l.includes('/mock/Resources/backend') && l.includes('not found')),
    ).toBe(true);
    expect(manager.getStatus()).toBe('error');
    expect(mockWindow.send).toHaveBeenCalledWith('mlx:statusChanged', 'error');
  });

  it('thin DMG on Intel (x64): directs to Docker/remote, NOT an arm64-only metal DMG', async () => {
    mockApp.isPackaged = true;
    proc.resourcesPath = '/mock/Resources';
    Object.defineProperty(process, 'arch', { value: 'x64', configurable: true });
    mockExistsSync.mockReturnValue(false);

    const manager = new MLXServerManager(() => mockWindow as never);
    await expect(manager.start({ port: 8000 })).rejects.toThrow(/not available on Intel/i);

    const logs = manager.getLogs();
    expect(logs.some((l: string) => l.includes('Intel'))).toBe(true);
    expect(logs.some((l: string) => l.includes('Docker'))).toBe(true);
    // Must NOT misdirect Intel users to the Apple-Silicon-only metal DMG.
    expect(logs.some((l: string) => l.includes('arm64-mac-metal.dmg'))).toBe(false);
  });

  it('corrupted bundle (packaged, Resources/backend exists, uvicorn missing): env incomplete; probed list excludes the dev path', async () => {
    mockApp.isPackaged = true;
    proc.resourcesPath = '/mock/Resources';
    // Resources/backend exists, but no uvicorn binary anywhere. Match the EXACT
    // backend dir, not a suffix, so the assertion documents the precise path.
    mockExistsSync.mockImplementation((p: string) => {
      if (typeof p !== 'string') return false;
      if (p.includes('uvicorn')) return false;
      return p === '/mock/Resources/backend';
    });

    const manager = new MLXServerManager(() => mockWindow as never);
    await expect(manager.start({ port: 8000 })).rejects.toThrow(/environment is incomplete/);

    const logs = manager.getLogs();
    expect(logs.some((l: string) => l.includes('environment is incomplete'))).toBe(true);
    expect(logs.some((l: string) => l.includes('-arm64-mac-metal.dmg'))).toBe(true);
    // Probed list is shown and contains the packaged candidate…
    expect(logs.some((l: string) => l.includes('Probed:'))).toBe(true);
    expect(logs.some((l: string) => l.includes('/mock/Resources/backend/.venv/bin/uvicorn'))).toBe(
      true,
    );
    // …but NOT the meaningless dev candidate path.
    expect(logs.some((l: string) => l.includes('/dashboard/../server/backend'))).toBe(false);
  });

  it('development (not packaged, venv not built): keeps the uv sync hint and logs status before throwing', async () => {
    mockApp.isPackaged = false;
    mockExistsSync.mockReturnValue(false);

    const manager = new MLXServerManager(() => mockWindow as never);
    await expect(manager.start({ port: 8000 })).rejects.toThrow(/uv sync --extra mlx/);

    const logs = manager.getLogs();
    expect(logs.some((l: string) => l.includes('uv sync --extra mlx'))).toBe(true);
    expect(manager.getStatus()).toBe('error');
    expect(mockWindow.send).toHaveBeenCalledWith('mlx:statusChanged', 'error');
  });

  it('throws only the single-line headline (multi-line probed detail stays in the log)', async () => {
    mockApp.isPackaged = true;
    proc.resourcesPath = '/mock/Resources';
    mockExistsSync.mockReturnValue(false);

    const manager = new MLXServerManager(() => mockWindow as never);
    await manager.start({ port: 8000 }).then(
      () => {
        throw new Error('expected start() to reject');
      },
      (err: Error) => {
        expect(err.message).not.toContain('\n');
        expect(err.message).toContain('dashboard-only build');
        expect(err.message).not.toContain('Checked:');
      },
    );
  });

  it('survives app.getVersion() throwing on a damaged bundle (still actionable, still logged)', async () => {
    mockApp.isPackaged = true;
    proc.resourcesPath = '/mock/Resources';
    mockApp.getVersion = () => {
      throw new Error('Info.plist unreadable');
    };
    mockExistsSync.mockReturnValue(false);

    const manager = new MLXServerManager(() => mockWindow as never);
    // The getVersion failure must NOT replace the actionable diagnostic (symptom 3 guard).
    await expect(manager.start({ port: 8000 })).rejects.toThrow(/dashboard-only build/);
    const logs = manager.getLogs();
    expect(logs.some((l: string) => l.includes('-arm64-mac-metal.dmg'))).toBe(true);
  });

  it('routes the diagnostic through an injected sink before throwing', async () => {
    mockApp.isPackaged = true;
    proc.resourcesPath = '/mock/Resources';
    mockExistsSync.mockReturnValue(false);

    const sinkAppend = vi.fn();
    const manager = new MLXServerManager(() => mockWindow as never, {
      append: sinkAppend as (line: string) => void,
      flush: vi.fn() as () => void,
    });

    await expect(manager.start({ port: 8000 })).rejects.toThrow(/dashboard-only build/);

    const appended: string[] = sinkAppend.mock.calls.map((c) => c[0] as string);
    expect(appended.some((l) => l.includes('dashboard-only build'))).toBe(true);
  });
});
