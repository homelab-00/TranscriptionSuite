/**
 * Platform-specific paste-at-cursor implementation.
 *
 * Saves clipboard → writes text → simulates Ctrl+V → restores clipboard.
 *
 * Adapted from Handy (https://github.com/cjpais/handy)
 * Copyright 2025 CJ Pais — MIT License.
 */

import { clipboard } from 'electron';
import { execFile } from 'child_process';
import { promisify } from 'util';
import { isWayland } from './shortcutManager.js';
import { reliableWriteText } from './clipboardWayland.js';

const execFileAsync = promisify(execFile);

// ─── Tool Detection (cached per session) ────────────────────────────────────

const commandCache = new Map<string, boolean>();

/** @internal Test-only — clear the cached tool-detection results. */
export function _resetCommandCache(): void {
  commandCache.clear();
}

async function hasCommand(name: string): Promise<boolean> {
  const cached = commandCache.get(name);
  if (cached !== undefined) return cached;
  try {
    // Probe the command directly instead of relying on `which`, which may not
    // be on PATH in Electron's sanitized environment. ENOENT = not found;
    // any other error (bad flag, non-zero exit) still proves the binary exists.
    await execFileAsync(name, ['--version']);
    commandCache.set(name, true);
    return true;
  } catch (err: unknown) {
    const code = (err as NodeJS.ErrnoException).code;
    const found = code !== 'ENOENT' && code !== 'EACCES';
    commandCache.set(name, found);
    return found;
  }
}

// ─── Window Class Detection (Linux only) ────────────────────────────────────

/** Known terminal emulator window classes (case-insensitive). */
const TERMINAL_WINDOW_CLASSES = new Set([
  'konsole',
  'kitty',
  'alacritty',
  'foot',
  'wezterm',
  'gnome-terminal-server',
  'xterm',
  'tilix',
  'terminator',
  'xfce4-terminal',
  'mate-terminal',
  'sakura',
  'st',
  'urxvt',
  'lxterminal',
]);

/** Window classes where paste should be skipped (file managers, shells, etc.). */
const PASTE_SKIP_WINDOW_CLASSES = new Set([
  'org.kde.dolphin',
  'org.gnome.nautilus',
  'pcmanfm',
  'thunar',
  'nemo',
  'caja',
  'org.kde.plasmashell',
]);

function isTerminalWindow(windowClass: string | null): boolean {
  return windowClass != null && TERMINAL_WINDOW_CLASSES.has(windowClass.toLowerCase());
}

function isPasteSkipWindow(windowClass: string | null): boolean {
  return windowClass != null && PASTE_SKIP_WINDOW_CLASSES.has(windowClass.toLowerCase());
}

/**
 * Detect the active window's class name on Linux.
 * Returns null when detection is not supported or fails.
 */
async function getActiveWindowClass(): Promise<string | null> {
  if (isWayland()) {
    // KDE Wayland: query KWin D-Bus for the active window resource class.
    try {
      const { stdout } = await execFileAsync('gdbus', [
        'call',
        '--session',
        '--dest',
        'org.kde.KWin',
        '--object-path',
        '/KWin',
        '--method',
        'org.kde.KWin.activeWindow',
      ]);
      // Output is a GVariant string like: ('konsole',)
      const match = stdout.match(/'([^']+)'/);
      if (match) return match[1];
    } catch {
      // Non-KDE compositor or KWin D-Bus not available — fall back to null.
    }
    return null;
  } else {
    // X11: xdotool returns the WM_CLASS name for the active window.
    try {
      const { stdout } = await execFileAsync('xdotool', ['getactivewindow', 'getwindowclassname']);
      return stdout.trim() || null;
    } catch {
      return null;
    }
  }
}

// ─── Keystroke Simulation ───────────────────────────────────────────────────

async function simulatePasteLinuxWayland(): Promise<void> {
  const windowClass = await getActiveWindowClass();

  if (isPasteSkipWindow(windowClass)) {
    throw new Error(
      'Paste skipped — active window does not accept text input. Text has been copied to clipboard.',
    );
  }

  const isTerminal = isTerminalWindow(windowClass);

  // Wayland fallback chain: wtype → dotool → ydotool
  // Each tool is tried at runtime — a tool may be installed but fail if the
  // compositor doesn't support its required protocol (e.g. wtype needs
  // zwp_virtual_keyboard_v1, which KWin/KDE does not expose).
  if (await hasCommand('wtype')) {
    try {
      if (isTerminal) {
        await execFileAsync('wtype', [
          '-M',
          'ctrl',
          '-M',
          'shift',
          'v',
          '-m',
          'shift',
          '-m',
          'ctrl',
        ]);
      } else {
        await execFileAsync('wtype', ['-M', 'ctrl', 'v', '-m', 'ctrl']);
      }
      return;
    } catch {
      // fall through to next tool
    }
  }
  if (await hasCommand('dotool')) {
    try {
      await execFileAsync('dotool', ['key', isTerminal ? 'ctrl+shift+v' : 'ctrl+v']);
      return;
    } catch {
      // fall through to next tool
    }
  }
  if (await hasCommand('ydotool')) {
    try {
      if (isTerminal) {
        // Ctrl+Shift+V raw keycodes
        await execFileAsync('ydotool', ['key', '29:1', '42:1', '47:1', '47:0', '42:0', '29:0']);
      } else {
        await execFileAsync('ydotool', ['key', '29:1', '47:1', '47:0', '29:0']);
      }
      return;
    } catch {
      // fall through to next tool
    }
  }
  // Last resort: xdotool works for XWayland apps even in a Wayland session
  // (e.g. KDE Plasma, where many apps still run via XWayland).
  if (await hasCommand('xdotool')) {
    await execFileAsync('xdotool', [
      'key',
      '--clearmodifiers',
      isTerminal ? 'ctrl+shift+v' : 'ctrl+v',
    ]);
    return;
  }
  throw new Error(
    'No keystroke simulation tool found for Wayland. Install wtype, dotool, or ydotool. ' +
      'Text has been copied to clipboard — paste manually with Ctrl+V.',
  );
}

async function simulatePasteLinuxX11(): Promise<void> {
  const windowClass = await getActiveWindowClass();

  if (isPasteSkipWindow(windowClass)) {
    throw new Error(
      'Paste skipped — active window does not accept text input. Text has been copied to clipboard.',
    );
  }

  const isTerminal = isTerminalWindow(windowClass);

  // X11 fallback chain: xdotool → ydotool
  if (await hasCommand('xdotool')) {
    await execFileAsync('xdotool', [
      'key',
      '--clearmodifiers',
      isTerminal ? 'ctrl+shift+v' : 'ctrl+v',
    ]);
    return;
  }
  if (await hasCommand('ydotool')) {
    if (isTerminal) {
      await execFileAsync('ydotool', ['key', '29:1', '42:1', '47:1', '47:0', '42:0', '29:0']);
    } else {
      await execFileAsync('ydotool', ['key', '29:1', '47:1', '47:0', '29:0']);
    }
    return;
  }
  throw new Error(
    'No keystroke simulation tool found for X11. Install xdotool or ydotool. ' +
      'Text has been copied to clipboard — paste manually with Ctrl+V.',
  );
}

async function simulatePasteMacOS(): Promise<void> {
  let stderr = '';
  try {
    const result = await Promise.race([
      execFileAsync('osascript', [
        '-e',
        'tell application "System Events" to keystroke "v" using command down',
      ]),
      new Promise<never>((_, reject) =>
        setTimeout(
          () =>
            reject(
              new Error('osascript timed out — grant Accessibility access in System Settings'),
            ),
          3000,
        ),
      ),
    ]);
    stderr = (result as { stderr: string }).stderr ?? '';
  } catch (err) {
    throw err; // timeout or exec failure
  }
  if (stderr.toLowerCase().includes('not allowed assistive access')) {
    throw new Error(
      'macOS Accessibility permission denied. Grant access to TranscriptionSuite in ' +
        'System Settings → Privacy & Security → Accessibility.',
    );
  }
}

async function simulatePasteWindows(): Promise<void> {
  // mshta runs inline VBScript and starts ~5-10x faster than PowerShell,
  // reducing the window in which focus can change before Ctrl+V fires.
  try {
    await execFileAsync(
      'mshta',
      ['vbscript:Execute("CreateObject(\"WScript.Shell\").SendKeys \"^v\":close")'],
      { timeout: 3000 },
    );
    return;
  } catch {
    // fall through to PowerShell
  }
  // Fallback: explicit powershell.exe (Windows PowerShell 5.1, not pwsh/PS7).
  // PS7 cannot reliably load System.Windows.Forms.
  await execFileAsync(
    'powershell.exe',
    [
      '-NoProfile',
      '-Command',
      'Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait("^v")',
    ],
    { timeout: 5000 },
  );
}

async function simulatePaste(): Promise<void> {
  switch (process.platform) {
    case 'linux':
      if (isWayland()) {
        await simulatePasteLinuxWayland();
      } else {
        await simulatePasteLinuxX11();
      }
      break;
    case 'darwin':
      await simulatePasteMacOS();
      break;
    case 'win32':
      await simulatePasteWindows();
      break;
    default:
      throw new Error(`Unsupported platform for paste-at-cursor: ${process.platform}`);
  }
}

// ─── Public API ─────────────────────────────────────────────────────────────

export interface PasteOptions {
  /**
   * If true, save the clipboard before pasting and restore it afterward.
   * If false, the pasted text remains in the clipboard (useful when the caller
   * wants the text to stay in the clipboard, e.g. autoCopy + pasteAtCursor).
   * @default true
   */
  preserveClipboard?: boolean;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Paste text at the current cursor position in the focused application.
 *
 * 1. Optionally save current clipboard
 * 2. Write text to clipboard
 * 3. Simulate paste keystroke (platform-specific)
 * 4. Optionally restore original clipboard
 */
export async function pasteAtCursor(text: string, options?: PasteOptions): Promise<void> {
  const preserve = options?.preserveClipboard ?? true;
  const originalClipboard = preserve ? clipboard.readText() : null;
  await reliableWriteText(text);
  try {
    await sleep(50);
    await simulatePaste();
    await sleep(100);
  } finally {
    if (preserve && originalClipboard !== null) {
      // Restore uses direct clipboard.writeText — the paste has already been
      // served, so reliability guarantees are not needed. Using reliableWriteText
      // here would kill the wl-copy child that may still be serving the paste.
      clipboard.writeText(originalClipboard);
    }
  }
}
