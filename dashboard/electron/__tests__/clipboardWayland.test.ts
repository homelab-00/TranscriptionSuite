// @vitest-environment node

/**
 * Tests for clipboardWayland.ts — reliable clipboard write on Wayland.
 *
 * These tests model the REAL Wayland failure mode proven on KDE/Plasma:
 * when the Electron window is unfocused, clipboard.writeText() is silently
 * dropped at the wl_data_device.set_selection layer (no input-event serial),
 * yet clipboard.readText() still returns the just-written text from Chromium's
 * in-process cache. A readback self-check therefore CANNOT detect the failure.
 *
 * To capture this faithfully the mocks separate two pieces of state:
 *   - `realClipboard`  — the authoritative system clipboard (what wl-paste sees)
 *   - `chromiumCache`  — what Electron's clipboard.readText() returns
 * Electron's writeText updates the real clipboard ONLY when the (test) window
 * is "focused"; wl-copy updates it unconditionally (focus-independent).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── Mutable system model (driven per-test) ──────────────────────────────────

const state = vi.hoisted(() => ({
  realClipboard: '', // authoritative — returned by wl-paste
  chromiumCache: '', // returned by clipboard.readText()
  electronWriteReachesSystem: true, // false = window unfocused (masked write)
  wlCopyAvailable: true,
  wlPasteAvailable: true,
}));

const { mockClipboard, mockIsWayland, mockSpawn, mockExecFile } = vi.hoisted(() => ({
  mockClipboard: {
    readText: vi.fn(() => state.chromiumCache),
    writeText: vi.fn((t: string) => {
      state.chromiumCache = t;
      if (state.electronWriteReachesSystem) state.realClipboard = t;
    }),
  },
  mockIsWayland: vi.fn().mockReturnValue(true),
  // wl-copy: spawn a child that takes ownership of the real clipboard when
  // its stdin is closed (focus-independent, like ext-data-control).
  mockSpawn: vi.fn((_cmd: string) => {
    let buf = '';
    return {
      stdin: {
        write: vi.fn((t: string) => {
          buf = t;
        }),
        end: vi.fn(() => {
          state.realClipboard = buf;
        }),
        on: vi.fn(),
      },
      on: vi.fn(),
      kill: vi.fn(),
    };
  }),
  mockExecFile: vi.fn(),
}));

vi.mock('electron', () => ({ clipboard: mockClipboard }));
vi.mock('child_process', () => ({ spawn: mockSpawn, execFile: mockExecFile }));
vi.mock('../shortcutManager.js', () => ({ isWayland: mockIsWayland }));

import { reliableWriteText, reliableReadText, _resetClipboardState } from '../clipboardWayland.js';

// ── execFile mock: routes wl-copy --version (probe) and wl-paste (verify) ────

function enoent(): NodeJS.ErrnoException {
  const e = new Error('spawn ENOENT') as NodeJS.ErrnoException;
  e.code = 'ENOENT';
  return e;
}

function installExecFileRouter() {
  mockExecFile.mockImplementation(
    (cmd: string, args: string[], optsOrCb: unknown, maybeCb?: unknown) => {
      const cb = (typeof optsOrCb === 'function' ? optsOrCb : maybeCb) as
        | ((err: Error | null, result?: { stdout: string }) => void)
        | undefined;
      if (!cb) return;
      if (cmd === 'wl-copy') {
        return state.wlCopyAvailable ? cb(null, { stdout: 'wl-copy 1.0' }) : cb(enoent());
      }
      if (cmd === 'wl-paste') {
        return state.wlPasteAvailable ? cb(null, { stdout: state.realClipboard }) : cb(enoent());
      }
      return cb(null, { stdout: '' });
    },
  );
}

// ── Tests ───────────────────────────────────────────────────────────────────

describe('reliableWriteText', () => {
  beforeEach(() => {
    _resetClipboardState();
    vi.clearAllMocks();
    state.realClipboard = 'OLD-CLIPBOARD';
    state.chromiumCache = 'OLD-CLIPBOARD';
    state.electronWriteReachesSystem = true;
    state.wlCopyAvailable = true;
    state.wlPasteAvailable = true;
    mockIsWayland.mockReturnValue(true);
    installExecFileRouter();
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
    expect(mockSpawn).not.toHaveBeenCalled();
    expect(state.realClipboard).toBe('hello');
  });

  it('uses clipboard.writeText directly on non-Linux platform', async () => {
    Object.defineProperty(process, 'platform', { value: 'darwin', configurable: true });
    await reliableWriteText('hello');
    expect(mockClipboard.writeText).toHaveBeenCalledWith('hello');
    expect(mockSpawn).not.toHaveBeenCalled();
  });

  it('on Wayland, writes via wl-copy as the PRIMARY path (not Electron)', async () => {
    await reliableWriteText('transcription result');
    expect(mockSpawn).toHaveBeenCalledWith('wl-copy', [], {
      stdio: ['pipe', 'ignore', 'ignore'],
    });
    const child = mockSpawn.mock.results[0].value;
    expect(child.stdin.write).toHaveBeenCalledWith('transcription result');
    expect(state.realClipboard).toBe('transcription result');
  });

  // THE REGRESSION TEST for the reported bug.
  it('succeeds even when the window is UNFOCUSED and Electron readback lies (masked write)', async () => {
    // Window unfocused: Electron writeText is dropped at the system layer, but
    // clipboard.readText() would still echo the text (the lie that defeated the
    // old readback verify). wl-copy must be used and the REAL clipboard updated.
    state.electronWriteReachesSystem = false;

    await reliableWriteText('important transcription');

    expect(mockSpawn).toHaveBeenCalledTimes(1); // wl-copy used
    expect(state.realClipboard).toBe('important transcription'); // really landed
  });

  it('does not rely on clipboard.readText() to decide success when wl-copy exists', async () => {
    // Even if readText echoes (would have passed the old verify), wl-copy is used.
    state.chromiumCache = 'echoed-by-chromium';
    await reliableWriteText('echoed-by-chromium');
    expect(mockSpawn).toHaveBeenCalled();
  });

  it('kills the previous wl-copy child before spawning a new one', async () => {
    await reliableWriteText('first');
    const firstChild = mockSpawn.mock.results[0].value;
    await reliableWriteText('second');
    expect(firstChild.kill).toHaveBeenCalled();
    expect(mockSpawn).toHaveBeenCalledTimes(2);
    expect(state.realClipboard).toBe('second');
  });

  describe('when wl-clipboard is NOT installed', () => {
    beforeEach(() => {
      state.wlCopyAvailable = false;
      state.wlPasteAvailable = false;
    });

    it('falls back to Electron clipboard.writeText and succeeds when focused', async () => {
      state.electronWriteReachesSystem = true;
      await reliableWriteText('via electron');
      expect(mockClipboard.writeText).toHaveBeenCalledWith('via electron');
      expect(mockSpawn).not.toHaveBeenCalled();
      expect(state.realClipboard).toBe('via electron');
    });

    it('warns that wl-clipboard should be installed when the write cannot be verified', async () => {
      state.electronWriteReachesSystem = false; // unfocused, no wl-copy → unrecoverable
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      await reliableWriteText('cannot land');
      expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('wl-clipboard'));
      warnSpy.mockRestore();
    });
  });
});

describe('reliableReadText', () => {
  beforeEach(() => {
    _resetClipboardState();
    vi.clearAllMocks();
    state.realClipboard = 'REAL-VALUE';
    state.chromiumCache = 'STALE-CHROMIUM-CACHE';
    state.wlPasteAvailable = true;
    mockIsWayland.mockReturnValue(true);
    installExecFileRouter();
    Object.defineProperty(process, 'platform', { value: 'linux', configurable: true });
  });

  afterEach(() => {
    Object.defineProperty(process, 'platform', { value: 'linux', configurable: true });
  });

  it('reads the REAL clipboard via wl-paste on Wayland, not Chromium’s cache', async () => {
    // The whole point: Chromium readText() can be stale/lie when unfocused.
    expect(await reliableReadText()).toBe('REAL-VALUE');
  });

  it('falls back to clipboard.readText() when wl-paste is unavailable on Wayland', async () => {
    state.wlPasteAvailable = false;
    expect(await reliableReadText()).toBe('STALE-CHROMIUM-CACHE');
  });

  it('uses clipboard.readText() directly on non-Wayland', async () => {
    mockIsWayland.mockReturnValue(false);
    expect(await reliableReadText()).toBe('STALE-CHROMIUM-CACHE');
  });
});
