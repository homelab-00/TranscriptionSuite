/**
 * Global keyboard shortcut registration + Wayland detection + CLI arg handling.
 *
 * Adapted from Handy (https://github.com/cjpais/handy)
 * Copyright 2025 CJ Pais — MIT License.
 */

import { globalShortcut, type BrowserWindow } from 'electron';

/** Minimal store interface — accepts any electron-store instance. */
interface ReadableStore {
  get(key: string): unknown;
}

// ─── Environment Detection ──────────────────────────────────────────────────

export function isWayland(): boolean {
  return Boolean(process.env.WAYLAND_DISPLAY) || process.env.XDG_SESSION_TYPE === 'wayland';
}

export function isKdePlasma(): boolean {
  const desktop = (process.env.XDG_CURRENT_DESKTOP ?? '').toLowerCase();
  return desktop.includes('kde') || Boolean(process.env.KDE_SESSION_VERSION);
}

// ─── Shortcut Registration ──────────────────────────────────────────────────

const registeredAccelerators: string[] = [];

/**
 * Register global keyboard shortcuts from config.
 * On Wayland: skip registration and log guidance about CLI/signal alternatives.
 * On failure (key already taken by another app): log warning, don't crash.
 */
export function registerShortcuts(
  store: ReadableStore,
  getWindow: () => BrowserWindow | null,
): void {
  unregisterShortcuts();

  if (process.platform === 'linux' && isWayland()) {
    console.log(
      '[Shortcuts] Wayland detected — globalShortcut API not supported. ' +
        'Use CLI args (--start-recording / --stop-recording) or Unix signals ' +
        '(SIGUSR1 / SIGUSR2) instead.',
    );
    return;
  }

  const startAccelerator = (store.get('shortcuts.startRecording') as string) || 'Alt+Ctrl+R';
  const stopAccelerator = (store.get('shortcuts.stopTranscribe') as string) || 'Alt+Ctrl+S';

  const bindings: Array<{ accelerator: string; action: string }> = [
    { accelerator: startAccelerator, action: 'start-recording' },
    { accelerator: stopAccelerator, action: 'stop-recording' },
  ];

  for (const { accelerator, action } of bindings) {
    try {
      const success = globalShortcut.register(accelerator, () => {
        const win = getWindow();
        if (win) {
          win.webContents.send('tray:action', action);
        }
      });
      if (success) {
        registeredAccelerators.push(accelerator);
        console.log(`[Shortcuts] Registered ${accelerator} → ${action}`);
      } else {
        console.warn(
          `[Shortcuts] Failed to register ${accelerator} — key may be taken by another application.`,
        );
      }
    } catch (err) {
      console.warn(`[Shortcuts] Error registering ${accelerator}:`, err);
    }
  }
}

/**
 * Unregister all global shortcuts previously registered by this module.
 */
export function unregisterShortcuts(): void {
  for (const acc of registeredAccelerators) {
    try {
      globalShortcut.unregister(acc);
    } catch {
      // Best-effort
    }
  }
  registeredAccelerators.length = 0;
}

// ─── CLI Arg Forwarding ─────────────────────────────────────────────────────

/**
 * Parse `--start-recording` / `--stop-recording` from argv and send matching
 * `tray:action` IPC to the renderer.  Called from the `second-instance` event
 * so that a second `TranscriptionSuite --start-recording` invocation forwards
 * the action to the already-running first instance.
 */
export function handleCliAction(argv: string[], getWindow: () => BrowserWindow | null): void {
  const win = getWindow();
  if (!win) return;

  if (argv.includes('--start-recording')) {
    console.log('[Shortcuts] CLI arg: --start-recording');
    win.webContents.send('tray:action', 'start-recording');
  }
  if (argv.includes('--stop-recording')) {
    console.log('[Shortcuts] CLI arg: --stop-recording');
    win.webContents.send('tray:action', 'stop-recording');
  }
}
