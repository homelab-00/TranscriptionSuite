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

const execFileAsync = promisify(execFile);

// ─── Tool Detection (cached per session) ────────────────────────────────────

const commandCache = new Map<string, boolean>();

async function hasCommand(name: string): Promise<boolean> {
  const cached = commandCache.get(name);
  if (cached !== undefined) return cached;
  try {
    await execFileAsync('which', [name]);
    commandCache.set(name, true);
    return true;
  } catch {
    commandCache.set(name, false);
    return false;
  }
}

// ─── Keystroke Simulation ───────────────────────────────────────────────────

async function simulatePasteLinuxWayland(): Promise<void> {
  // Wayland fallback chain: wtype → dotool → ydotool
  // Each tool is tried at runtime — a tool may be installed but fail if the
  // compositor doesn't support its required protocol (e.g. wtype needs
  // zwp_virtual_keyboard_v1, which KWin/KDE does not expose).
  if (await hasCommand('wtype')) {
    try {
      await execFileAsync('wtype', ['-M', 'ctrl', 'v', '-m', 'ctrl']);
      return;
    } catch {
      // fall through to next tool
    }
  }
  if (await hasCommand('dotool')) {
    try {
      await execFileAsync('dotool', ['key', 'ctrl+v']);
      return;
    } catch {
      // fall through to next tool
    }
  }
  if (await hasCommand('ydotool')) {
    try {
      await execFileAsync('ydotool', ['key', '29:1', '47:1', '47:0', '29:0']);
      return;
    } catch {
      // fall through to next tool
    }
  }
  // Last resort: xdotool works for XWayland apps even in a Wayland session
  // (e.g. KDE Plasma, where many apps still run via XWayland).
  if (await hasCommand('xdotool')) {
    await execFileAsync('xdotool', ['key', '--clearmodifiers', 'ctrl+v']);
    return;
  }
  throw new Error(
    'No keystroke simulation tool found for Wayland. Install wtype, dotool, or ydotool. ' +
      'Text has been copied to clipboard — paste manually with Ctrl+V.',
  );
}

async function simulatePasteLinuxX11(): Promise<void> {
  // X11 fallback chain: xdotool → ydotool
  if (await hasCommand('xdotool')) {
    await execFileAsync('xdotool', ['key', '--clearmodifiers', 'ctrl+v']);
    return;
  }
  if (await hasCommand('ydotool')) {
    await execFileAsync('ydotool', ['key', '29:1', '47:1', '47:0', '29:0']);
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

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Paste text at the current cursor position in the focused application.
 *
 * 1. Save current clipboard
 * 2. Write text to clipboard
 * 3. Simulate paste keystroke (platform-specific)
 * 4. Restore original clipboard
 */
export async function pasteAtCursor(text: string): Promise<void> {
  const originalClipboard = clipboard.readText();
  clipboard.writeText(text);
  try {
    await sleep(50);
    await simulatePaste();
    await sleep(100);
  } finally {
    clipboard.writeText(originalClipboard);
  }
}
