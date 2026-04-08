// @vitest-environment node

/**
 * Tests for clipboardWayland.ts — reliable clipboard write on Wayland.
 *
 * Mocks Electron's clipboard, child_process (spawn/execFile), and the
 * isWayland() helper to test the verify-retry-fallback logic without
 * requiring a running Wayland session.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── Hoisted mocks ──────────────────────────────────────────────────────────

const { mockClipboard, mockIsWayland, mockSpawn, mockExecFile } = vi.hoisted(() => {
  const stdinWrite = vi.fn();
  const stdinEnd = vi.fn();
  const stdinOn = vi.fn();
  const onHandler = vi.fn();
  const killFn = vi.fn();

  return {
    mockClipboard: {
      readText: vi.fn().mockReturnValue(''),
      writeText: vi.fn(),
    },
    mockIsWayland: vi.fn().mockReturnValue(true),
    mockSpawn: vi.fn().mockReturnValue({
      stdin: { write: stdinWrite, end: stdinEnd, on: stdinOn },
      on: onHandler,
      kill: killFn,
    }),
    mockExecFile: vi.fn(),
  };
});

vi.mock('electron', () => ({
  clipboard: mockClipboard,
}));

vi.mock('child_process', () => ({
  spawn: mockSpawn,
  execFile: mockExecFile,
}));

vi.mock('../shortcutManager.js', () => ({
  isWayland: mockIsWayland,
}));

import { reliableWriteText, _resetClipboardState } from '../clipboardWayland.js';

// ── Helpers ────────────────────────────────────────────────────────────────

/** Make `which wl-copy` succeed. */
function setWlCopyAvailable() {
  mockExecFile.mockImplementation(
    (_cmd: string, _args: string[], optsOrCb: unknown, maybeCb?: unknown) => {
      const cb = typeof optsOrCb === 'function' ? optsOrCb : maybeCb;
      if (typeof cb === 'function') {
        (cb as (err: Error | null, result?: { stdout: string }) => void)(null, {
          stdout: '/usr/bin/wl-copy',
        });
      }
    },
  );
}

/** Make `which wl-copy` fail. */
function setWlCopyMissing() {
  mockExecFile.mockImplementation(
    (_cmd: string, _args: string[], optsOrCb: unknown, maybeCb?: unknown) => {
      const cb = typeof optsOrCb === 'function' ? optsOrCb : maybeCb;
      if (typeof cb === 'function') {
        (cb as (err: Error | null) => void)(new Error('not found'));
      }
    },
  );
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe('reliableWriteText', () => {
  beforeEach(() => {
    _resetClipboardState();
    vi.clearAllMocks();
    // Default: Wayland, Linux
    mockIsWayland.mockReturnValue(true);
    Object.defineProperty(process, 'platform', { value: 'linux', configurable: true });
  });

  afterEach(() => {
    _resetClipboardState();
    Object.defineProperty(process, 'platform', { value: 'linux', configurable: true });
  });

  it('uses clipboard.writeText directly on non-Wayland (passthrough)', async () => {
    mockIsWayland.mockReturnValue(false);

    await reliableWriteText('hello');

    expect(mockClipboard.writeText).toHaveBeenCalledWith('hello');
    expect(mockClipboard.writeText).toHaveBeenCalledTimes(1);
    expect(mockSpawn).not.toHaveBeenCalled();
  });

  it('uses clipboard.writeText directly on non-Linux platform', async () => {
    Object.defineProperty(process, 'platform', { value: 'darwin', configurable: true });

    await reliableWriteText('hello');

    expect(mockClipboard.writeText).toHaveBeenCalledWith('hello');
    expect(mockClipboard.writeText).toHaveBeenCalledTimes(1);
    expect(mockSpawn).not.toHaveBeenCalled();
  });

  it('returns immediately when first write verifies (happy path)', async () => {
    mockClipboard.readText.mockReturnValue('transcription result');

    await reliableWriteText('transcription result');

    expect(mockClipboard.writeText).toHaveBeenCalledTimes(1);
    expect(mockClipboard.writeText).toHaveBeenCalledWith('transcription result');
    expect(mockSpawn).not.toHaveBeenCalled();
  });

  it('retries once when first verification fails, succeeds on retry', async () => {
    // First readText returns wrong value (write was dropped), second returns correct
    mockClipboard.readText.mockReturnValueOnce('stale clipboard').mockReturnValueOnce('my text');

    await reliableWriteText('my text');

    expect(mockClipboard.writeText).toHaveBeenCalledTimes(2);
    expect(mockSpawn).not.toHaveBeenCalled();
  });

  it('falls back to wl-copy when both Electron writes fail verification', async () => {
    mockClipboard.readText.mockReturnValue('stale');
    setWlCopyAvailable();

    await reliableWriteText('important text');

    expect(mockClipboard.writeText).toHaveBeenCalledTimes(2);
    expect(mockSpawn).toHaveBeenCalledWith('wl-copy', [], {
      stdio: ['pipe', 'ignore', 'ignore'],
    });
    const spawnResult = mockSpawn.mock.results[0].value;
    expect(spawnResult.stdin.write).toHaveBeenCalledWith('important text');
    expect(spawnResult.stdin.end).toHaveBeenCalled();
  });

  it('logs warning when wl-copy is not installed and verification fails', async () => {
    mockClipboard.readText.mockReturnValue('stale');
    setWlCopyMissing();
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    await reliableWriteText('text');

    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('wl-copy is not installed'));
    expect(mockSpawn).not.toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it('kills previous wl-copy child before spawning new one', async () => {
    mockClipboard.readText.mockReturnValue('stale');
    setWlCopyAvailable();

    // First write — spawns wl-copy
    await reliableWriteText('first');
    const firstChild = mockSpawn.mock.results[0].value;

    // Second write — should kill first child
    await reliableWriteText('second');

    expect(firstChild.kill).toHaveBeenCalled();
    expect(mockSpawn).toHaveBeenCalledTimes(2);
  });
});
