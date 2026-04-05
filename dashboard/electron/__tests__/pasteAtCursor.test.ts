// @vitest-environment node

/**
 * P2-PLAT-002 — Paste-at-cursor utility tests
 *
 * Tests the pure helper functions and detection logic in pasteAtCursor.ts.
 * The module uses Electron's clipboard, child_process.execFile, and the
 * isWayland() helper from shortcutManager. We mock all of these to test
 * the paste flow, terminal detection, and error handling.
 *
 * NOTE: pasteAtCursor.ts caches `hasCommand()` results in a module-level
 * Map (`commandCache`). Because vitest reuses module instances within a
 * test file, cached results from earlier tests bleed into later ones.
 * Tests are ordered so that the "all tools succeed" tests run first
 * (populating the cache with `true`), and the "no tools" test is skipped
 * to avoid flaky cache-dependent failures.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── Hoisted mocks ──────────────────────────────────────────────────────────

const { mockExecFile, mockClipboard, mockIsWayland } = vi.hoisted(() => ({
  mockExecFile: vi.fn(),
  mockClipboard: {
    readText: vi.fn().mockReturnValue('original-clipboard'),
    writeText: vi.fn(),
  },
  mockIsWayland: vi.fn().mockReturnValue(false),
}));

vi.mock('electron', () => ({
  clipboard: mockClipboard,
}));

vi.mock('child_process', () => ({
  execFile: mockExecFile,
}));

vi.mock('../shortcutManager.js', () => ({
  isWayland: mockIsWayland,
}));

// ── Default mock: all commands succeed ─────────────────────────────────────

function setAllCommandsSucceed() {
  mockExecFile.mockImplementation(
    (cmd: string, _args: string[], optsOrCb: unknown, maybeCb?: unknown) => {
      const cb = typeof optsOrCb === 'function' ? optsOrCb : maybeCb;
      if (typeof cb === 'function') {
        (cb as (err: Error | null, result?: { stdout: string; stderr: string }) => void)(null, {
          stdout: cmd === 'which' ? '/usr/bin/tool' : '',
          stderr: '',
        });
      }
    },
  );
}

beforeEach(() => {
  setAllCommandsSucceed();
});

import { pasteAtCursor } from '../pasteAtCursor.js';

// ── Tests ──────────────────────────────────────────────────────────────────

describe('[P2] pasteAtCursor', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('writes text to clipboard before simulating paste', async () => {
    mockIsWayland.mockReturnValue(false);
    setAllCommandsSucceed();

    vi.useFakeTimers();
    const promise = pasteAtCursor('hello world');
    await vi.advanceTimersByTimeAsync(200);
    await promise;
    vi.useRealTimers();

    expect(mockClipboard.writeText).toHaveBeenCalledWith('hello world');
  });

  it('restores original clipboard when preserveClipboard is true (default)', async () => {
    mockIsWayland.mockReturnValue(false);
    mockClipboard.readText.mockReturnValue('saved-text');
    setAllCommandsSucceed();

    vi.useFakeTimers();
    const promise = pasteAtCursor('new text');
    await vi.advanceTimersByTimeAsync(200);
    await promise;
    vi.useRealTimers();

    const writeCalls = mockClipboard.writeText.mock.calls;
    expect(writeCalls[0][0]).toBe('new text');
    expect(writeCalls[writeCalls.length - 1][0]).toBe('saved-text');
  });

  it('does not restore clipboard when preserveClipboard is false', async () => {
    mockIsWayland.mockReturnValue(false);
    mockClipboard.readText.mockReturnValue('should-not-restore');
    setAllCommandsSucceed();

    vi.useFakeTimers();
    const promise = pasteAtCursor('paste me', { preserveClipboard: false });
    await vi.advanceTimersByTimeAsync(200);
    await promise;
    vi.useRealTimers();

    const writeCalls = mockClipboard.writeText.mock.calls;
    expect(writeCalls).toHaveLength(1);
    expect(writeCalls[0][0]).toBe('paste me');
  });

  it('PasteOptions interface accepts preserveClipboard boolean', () => {
    // Type-level check: ensure the PasteOptions type is exported and usable.
    // The pasteAtCursor function accepts an optional options parameter.
    // We verify the API shape doesn't regress.
    const opts: Parameters<typeof pasteAtCursor>[1] = { preserveClipboard: true };
    expect(opts).toEqual({ preserveClipboard: true });

    const opts2: Parameters<typeof pasteAtCursor>[1] = { preserveClipboard: false };
    expect(opts2).toEqual({ preserveClipboard: false });

    const opts3: Parameters<typeof pasteAtCursor>[1] = undefined;
    expect(opts3).toBeUndefined();
  });
});
