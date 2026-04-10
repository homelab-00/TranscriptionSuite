/**
 * Reliable clipboard write for Wayland.
 *
 * Electron's clipboard.writeText() silently drops writes when Chromium's
 * Ozone Wayland backend lacks a valid input event serial (the focused-window
 * requirement of wl_data_device.set_selection). This module adds a
 * write-verify-retry loop and falls back to wl-copy when Electron fails.
 *
 * On non-Wayland platforms the native clipboard.writeText() is used directly.
 *
 * Adapted from espanso's wl-copy handling (https://github.com/espanso/espanso/pull/2654)
 */

import { clipboard } from 'electron';
import { spawn, execFile } from 'child_process';
import { promisify } from 'util';
import type { ChildProcess } from 'child_process';
import { isWayland } from './shortcutManager.js';

const execFileAsync = promisify(execFile);

// ─── Module State ──────────────────────────────────────────────────────────

/** The long-lived wl-copy child process that maintains clipboard ownership. */
let wlCopyChild: ChildProcess | null = null;

/** Cached result of wl-copy availability probe. */
let wlCopyAvailable: boolean | null = null;

/** Timestamp of last negative probe — allows re-check after TTL. */
let wlCopyNegativeProbeAt = 0;

/** Re-probe interval for negative results (60 seconds). */
const WL_COPY_NEGATIVE_TTL_MS = 60_000;

// ─── Helpers ───────────────────────────────────────────────────────────────

const VERIFY_RETRY_DELAY_MS = 60;

/**
 * Read clipboard text safely.
 * clipboard.readText() is synchronous in Electron's main process, so it
 * cannot be meaningfully wrapped in a Promise.race timeout. We wrap it in
 * a try/catch to gracefully handle any exceptions from the Ozone backend.
 */
function readClipboardSafe(): string | null {
  try {
    return clipboard.readText();
  } catch {
    return null;
  }
}

/** Check whether `wl-copy` is available on the system (cached with TTL on negatives). */
async function hasWlCopy(): Promise<boolean> {
  if (wlCopyAvailable === true) return true;
  if (wlCopyAvailable === false && Date.now() - wlCopyNegativeProbeAt < WL_COPY_NEGATIVE_TTL_MS) {
    return false;
  }
  try {
    // Probe the command directly instead of relying on `which`, which may not
    // be on PATH in Electron's sanitized environment.
    await execFileAsync('wl-copy', ['--version']);
    wlCopyAvailable = true;
  } catch (err: unknown) {
    const code = (err as NodeJS.ErrnoException).code;
    if (code === 'ENOENT' || code === 'EACCES') {
      wlCopyAvailable = false;
      wlCopyNegativeProbeAt = Date.now();
    } else {
      // Command exists but --version flag not understood — still available
      wlCopyAvailable = true;
    }
  }
  return wlCopyAvailable;
}

/** Kill the previous wl-copy child if it's still running. */
function killPreviousWlCopy(): void {
  if (wlCopyChild !== null) {
    wlCopyChild.kill();
    wlCopyChild = null;
  }
}

/**
 * Write text to the Wayland clipboard via wl-copy.
 * The child process is kept alive to maintain clipboard ownership
 * (Wayland requires the source process to serve paste requests).
 */
function writeViaWlCopy(text: string): void {
  killPreviousWlCopy();

  const child = spawn('wl-copy', [], {
    stdio: ['pipe', 'ignore', 'ignore'],
  });

  // Guard against spawn failures (ENOENT if wl-copy disappears after the
  // `which` check, or EPIPE if the child exits before we finish writing).
  child.on('error', (err) => {
    console.warn('[Clipboard] wl-copy process error:', err.message);
    if (wlCopyChild === child) wlCopyChild = null;
  });
  child.stdin!.on('error', () => {
    // Swallow EPIPE — wl-copy may have already exited.
  });

  child.stdin!.write(text);
  child.stdin!.end();

  // Keep reference alive — do NOT kill. Wayland clipboard ownership
  // requires the source process to remain running.
  wlCopyChild = child;

  child.on('exit', () => {
    if (wlCopyChild === child) {
      wlCopyChild = null;
    }
  });
}

// ─── Public API ────────────────────────────────────────────────────────────

/**
 * Write text to the clipboard reliably.
 *
 * On Wayland: write → verify → retry once → fall back to wl-copy.
 * On other platforms: direct clipboard.writeText() (no overhead).
 */
export async function reliableWriteText(text: string): Promise<void> {
  if (process.platform !== 'linux' || !isWayland()) {
    clipboard.writeText(text);
    return;
  }

  // ── Attempt 1: Electron native write ──────────────────────────────────
  clipboard.writeText(text);

  const readback1 = readClipboardSafe();
  if (readback1 === text) return;

  // ── Attempt 2: Retry after short delay ────────────────────────────────
  await new Promise((resolve) => setTimeout(resolve, VERIFY_RETRY_DELAY_MS));
  clipboard.writeText(text);

  const readback2 = readClipboardSafe();
  if (readback2 === text) {
    console.info('[Clipboard] Wayland: retry succeeded');
    return;
  }

  // ── Attempt 3: wl-copy fallback ───────────────────────────────────────
  if (await hasWlCopy()) {
    console.info('[Clipboard] Wayland: falling back to wl-copy');
    writeViaWlCopy(text);
    return;
  }

  console.warn(
    '[Clipboard] Wayland: clipboard write could not be verified and wl-copy is not installed. ' +
      'Install the wl-clipboard package for reliable clipboard support ' +
      '(e.g. sudo pacman -S wl-clipboard / sudo apt install wl-clipboard).',
  );
}

/**
 * Clean up module state. Call on app quit to kill any lingering wl-copy child.
 */
export function cleanupClipboard(): void {
  killPreviousWlCopy();
}

/** @internal Test-only — reset module state for test isolation. */
export function _resetClipboardState(): void {
  killPreviousWlCopy();
  wlCopyAvailable = null;
  wlCopyNegativeProbeAt = 0;
}
