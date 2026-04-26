// @vitest-environment node

/**
 * gh-86 #3 — MLX log sink unit tests.
 *
 * The sink owns the persist-and-deliver pipeline for mlx:logLine messages:
 *   - synchronous best-effort disk write on every append
 *   - buffer mode (initial) → FIFO buffer at MLX_EARLY_LOG_BUFFER_MAX
 *   - live mode (after flush) → direct webContents.send delivery
 *
 * Tests mock fs.appendFileSync and a fake BrowserWindow so the factory can
 * be exercised without spinning up Electron.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const { mockAppendFileSync } = vi.hoisted(() => ({
  mockAppendFileSync: vi.fn(),
}));

vi.mock('fs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('fs')>();
  return {
    ...actual,
    default: { ...actual, appendFileSync: mockAppendFileSync },
    appendFileSync: mockAppendFileSync,
  };
});

import { createMlxLogSink, MLX_EARLY_LOG_BUFFER_MAX } from '../mlxLogSink.js';

interface MockWindow {
  webContents: { send: ReturnType<typeof vi.fn> };
  isDestroyed: () => boolean;
}

function makeWindow(opts: { destroyed?: boolean; sendThrows?: boolean } = {}): MockWindow {
  const send = vi.fn(() => {
    if (opts.sendThrows) throw new Error('window torn down');
  });
  return {
    webContents: { send },
    isDestroyed: () => opts.destroyed ?? false,
  };
}

const LOG_PATH = '/mock/userData/logs/mlx-server.log';

describe('[P2] createMlxLogSink', () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.clearAllMocks();
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    warnSpy.mockRestore();
  });

  // ── Disk persistence ─────────────────────────────────────────────────────

  it('writes every appended line to disk synchronously', () => {
    const win = makeWindow();
    const sink = createMlxLogSink({
      getWindow: () => win as never,
      getLogFilePath: () => LOG_PATH,
    });

    sink.append('first line');
    sink.append('second line');

    expect(mockAppendFileSync).toHaveBeenCalledTimes(2);
    expect(mockAppendFileSync).toHaveBeenNthCalledWith(1, LOG_PATH, 'first line\n', 'utf-8');
    expect(mockAppendFileSync).toHaveBeenNthCalledWith(2, LOG_PATH, 'second line\n', 'utf-8');
  });

  it('survives fs.appendFileSync throwing and warns once per failure', () => {
    mockAppendFileSync.mockImplementation(() => {
      throw new Error('disk full');
    });
    const win = makeWindow();
    const sink = createMlxLogSink({
      getWindow: () => win as never,
      getLogFilePath: () => LOG_PATH,
    });

    expect(() => sink.append('boom')).not.toThrow();
    expect(warnSpy).toHaveBeenCalledWith('[MLX] Failed to persist log line:', expect.any(Error));
  });

  // ── Buffer mode (before flush) ───────────────────────────────────────────

  it('buffers lines and does NOT deliver via IPC before flush', () => {
    const win = makeWindow();
    const sink = createMlxLogSink({
      getWindow: () => win as never,
      getLogFilePath: () => LOG_PATH,
    });

    sink.append('a');
    sink.append('b');
    sink.append('c');

    expect(win.webContents.send).not.toHaveBeenCalled();
  });

  it('flush() drains the buffer via webContents.send in original order', () => {
    const win = makeWindow();
    const sink = createMlxLogSink({
      getWindow: () => win as never,
      getLogFilePath: () => LOG_PATH,
    });

    sink.append('a');
    sink.append('b');
    sink.append('c');
    sink.flush();

    expect(win.webContents.send).toHaveBeenCalledTimes(3);
    expect(win.webContents.send).toHaveBeenNthCalledWith(1, 'mlx:logLine', 'a');
    expect(win.webContents.send).toHaveBeenNthCalledWith(2, 'mlx:logLine', 'b');
    expect(win.webContents.send).toHaveBeenNthCalledWith(3, 'mlx:logLine', 'c');
  });

  it('flush() called twice is a no-op the second time', () => {
    const win = makeWindow();
    const sink = createMlxLogSink({
      getWindow: () => win as never,
      getLogFilePath: () => LOG_PATH,
    });

    sink.append('only');
    sink.flush();
    sink.flush();

    expect(win.webContents.send).toHaveBeenCalledTimes(1);
  });

  // ── Live mode (after flush) ──────────────────────────────────────────────

  it('after flush, append delivers directly via IPC and does NOT buffer', () => {
    const win = makeWindow();
    const sink = createMlxLogSink({
      getWindow: () => win as never,
      getLogFilePath: () => LOG_PATH,
    });

    sink.flush(); // empty flush → enter live mode immediately
    sink.append('live-1');
    sink.append('live-2');

    expect(win.webContents.send).toHaveBeenCalledTimes(2);
    expect(win.webContents.send).toHaveBeenNthCalledWith(1, 'mlx:logLine', 'live-1');
    expect(win.webContents.send).toHaveBeenNthCalledWith(2, 'mlx:logLine', 'live-2');
  });

  // ── FIFO eviction at cap ─────────────────────────────────────────────────

  it('FIFO-evicts oldest lines when the early buffer exceeds MLX_EARLY_LOG_BUFFER_MAX', () => {
    const win = makeWindow();
    const sink = createMlxLogSink({
      getWindow: () => win as never,
      getLogFilePath: () => LOG_PATH,
    });

    const total = MLX_EARLY_LOG_BUFFER_MAX + 50;
    for (let i = 0; i < total; i += 1) {
      sink.append(`line-${i}`);
    }
    sink.flush();

    // Disk write happened for every line — eviction is buffer-only.
    expect(mockAppendFileSync).toHaveBeenCalledTimes(total);
    // IPC only delivered the most recent MLX_EARLY_LOG_BUFFER_MAX lines.
    expect(win.webContents.send).toHaveBeenCalledTimes(MLX_EARLY_LOG_BUFFER_MAX);
    // First delivered line is line-50 (oldest 50 evicted), last is line-(total-1).
    expect(win.webContents.send).toHaveBeenNthCalledWith(1, 'mlx:logLine', 'line-50');
    expect(win.webContents.send).toHaveBeenLastCalledWith('mlx:logLine', `line-${total - 1}`);
  });

  // ── IPC delivery error handling ──────────────────────────────────────────

  it('survives webContents.send throwing during live mode', () => {
    const win = makeWindow({ sendThrows: true });
    const sink = createMlxLogSink({
      getWindow: () => win as never,
      getLogFilePath: () => LOG_PATH,
    });

    sink.flush(); // enter live mode
    expect(() => sink.append('broken')).not.toThrow();
  });

  it('skips IPC delivery when window is null', () => {
    const sink = createMlxLogSink({
      getWindow: () => null,
      getLogFilePath: () => LOG_PATH,
    });

    sink.append('a');
    sink.flush();

    // Disk write still happened, no crash.
    expect(mockAppendFileSync).toHaveBeenCalledTimes(1);
  });

  it('skips IPC delivery when window.isDestroyed() returns true', () => {
    const win = makeWindow({ destroyed: true });
    const sink = createMlxLogSink({
      getWindow: () => win as never,
      getLogFilePath: () => LOG_PATH,
    });

    sink.append('a');
    sink.flush();
    sink.append('b'); // live mode, but window destroyed

    expect(win.webContents.send).not.toHaveBeenCalled();
    expect(mockAppendFileSync).toHaveBeenCalledTimes(2);
  });
});
