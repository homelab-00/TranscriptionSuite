/**
 * Reliable clipboard write for Wayland.
 *
 * Electron's clipboard.writeText() performs wl_data_device.set_selection, which
 * the compositor only honors when the window holds a valid input-event serial —
 * i.e. when it is focused. When the dashboard is UNFOCUSED (e.g. the user copied
 * something in another app mid-recording and stopped via a global hotkey without
 * refocusing the window), Chromium's Ozone Wayland backend has no serial and the
 * write is SILENTLY DROPPED. Critically, clipboard.readText() still returns the
 * just-written text from Chromium's in-process cache, so a write→readback
 * self-check cannot detect the failure (verified on KDE Plasma 6 / Ozone Wayland).
 *
 * Therefore, on Wayland we prefer `wl-copy`, which sets the selection
 * focus-independently via the ext-data-control protocol, and we confirm the
 * result against the REAL clipboard via `wl-paste` — an independent channel that
 * does not share Chromium's cache. Electron's native write is kept only as a
 * fallback for systems without wl-clipboard installed.
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

/** Whether the "wl-clipboard not installed" degraded-mode warning was emitted. */
let degradedWaylandWarningEmitted = false;

// ─── Helpers ───────────────────────────────────────────────────────────────

const VERIFY_RETRY_DELAY_MS = 60;

/** Poll interval while confirming the real clipboard via wl-paste. */
const WL_PASTE_POLL_INTERVAL_MS = 30;

/**
 * Time budget for confirming a write landed on the real clipboard. wl-copy
 * acquires the selection slightly after the child is spawned, so we poll rather
 * than read once.
 */
const CLIPBOARD_CONFIRM_BUDGET_MS = 400;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Read clipboard text safely.
 * clipboard.readText() is synchronous in Electron's main process, so it
 * cannot be meaningfully wrapped in a Promise.race timeout. We wrap it in
 * a try/catch to gracefully handle any exceptions from the Ozone backend.
 *
 * NOTE: this reads through Chromium and shares its in-process cache, so it
 * must NOT be used to verify a write succeeded on Wayland — use wl-paste.
 */
function readClipboardSafe(): string | null {
  try {
    return clipboard.readText();
  } catch {
    return null;
  }
}

/**
 * Read the REAL system clipboard via wl-paste — an independent channel that
 * does not share Chromium's clipboard cache. Returns the clipboard text, or
 * null when wl-paste is unavailable / cannot read (so we cannot verify).
 */
async function readViaWlPaste(): Promise<string | null> {
  try {
    const { stdout } = await execFileAsync('wl-paste', ['--no-newline'], { timeout: 2000 });
    return stdout;
  } catch (err: unknown) {
    // wl-paste exits non-zero on an empty clipboard ("Nothing is copied") but
    // still yields stdout=''. Treat a present stdout as the value; ENOENT /
    // timeout (no stdout) means we cannot read independently.
    const e = err as { stdout?: unknown };
    if (typeof e.stdout === 'string') return e.stdout;
    return null;
  }
}

/**
 * Confirm the real system clipboard holds `text`, polling wl-paste until it
 * matches or the budget elapses. Returns:
 *   true  — confirmed on the real clipboard
 *   false — wl-paste worked but never showed `text` within the budget
 *   null  — wl-paste is unavailable (cannot verify independently)
 */
async function confirmClipboard(
  text: string,
  budgetMs = CLIPBOARD_CONFIRM_BUDGET_MS,
): Promise<boolean | null> {
  const deadline = Date.now() + budgetMs;
  let everRead = false;
  for (;;) {
    const real = await readViaWlPaste();
    if (real !== null) {
      everRead = true;
      if (real === text) return true;
    }
    if (Date.now() >= deadline) return everRead ? false : null;
    await sleep(WL_PASTE_POLL_INTERVAL_MS);
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
 * On Wayland: wl-copy (focus-independent) → confirm via wl-paste → Electron
 * fallback only when wl-clipboard is absent.
 * On other platforms: direct clipboard.writeText() (no overhead).
 */
export async function reliableWriteText(text: string): Promise<void> {
  if (process.platform !== 'linux' || !isWayland()) {
    clipboard.writeText(text);
    return;
  }

  // ── Primary path: wl-copy (works whether or not the window is focused) ──
  if (await hasWlCopy()) {
    writeViaWlCopy(text);
    const confirmed = await confirmClipboard(text);
    // true = verified on the real clipboard; null = wl-paste unavailable, so we
    // cannot verify but trust wl-copy. Only fall through on an explicit false.
    if (confirmed !== false) return;
    console.warn(
      '[Clipboard] Wayland: wl-copy write could not be confirmed on the real ' +
        'clipboard; falling back to Electron native write.',
    );
  } else if (!degradedWaylandWarningEmitted) {
    degradedWaylandWarningEmitted = true;
    console.warn(
      '[Clipboard] Wayland: wl-clipboard is not installed. Clipboard writes may ' +
        'silently fail when the window is unfocused. Install wl-clipboard for ' +
        'reliable clipboard support (e.g. sudo pacman -S wl-clipboard / ' +
        'sudo apt install wl-clipboard).',
    );
  }

  // ── Fallback: Electron native write (reliable only when window is focused) ──
  clipboard.writeText(text);
  if (readClipboardSafe() === text) return;
  await sleep(VERIFY_RETRY_DELAY_MS);
  clipboard.writeText(text);
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
  degradedWaylandWarningEmitted = false;
}
