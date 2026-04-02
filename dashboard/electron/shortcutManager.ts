/**
 * Global keyboard shortcut registration + Wayland detection + CLI arg handling.
 *
 * Adapted from Handy (https://github.com/cjpais/handy)
 * Copyright 2025 CJ Pais — MIT License.
 */

import { globalShortcut, type BrowserWindow } from 'electron';
import {
  initWaylandShortcuts,
  destroyWaylandShortcuts,
  rebindShortcuts,
  listShortcuts,
  isPortalConnected,
  type PortalShortcutInfo,
} from './waylandShortcuts.js';

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
let waylandMode = false;

// ─── Serialization guard ───────────────────────────────────────────────────
// Concurrent registerShortcuts() calls (e.g. from rapid config:set events)
// are serialized: if a registration is already in-flight we store the latest
// args and re-run once the current call completes (last-write-wins).
let registrationInFlight = false;
let pendingRegistration: { store: ReadableStore; getWindow: () => BrowserWindow | null } | null =
  null;

/**
 * Register global keyboard shortcuts from config.
 * On Wayland: attempts registration via the GlobalShortcutsPortal feature
 * (works on KDE Plasma, Hyprland).  Falls back to CLI/signal guidance if
 * the compositor doesn't support the portal.
 * On failure (key already taken by another app): log warning, don't crash.
 *
 * Concurrent calls are coalesced: only one D-Bus session runs at a time.
 */
export async function registerShortcuts(
  store: ReadableStore,
  getWindow: () => BrowserWindow | null,
): Promise<void> {
  if (registrationInFlight) {
    // A registration is already running — just record that we need another pass.
    pendingRegistration = { store, getWindow };
    return;
  }

  registrationInFlight = true;
  try {
    await doRegisterShortcuts(store, getWindow);
  } finally {
    registrationInFlight = false;

    // If another call came in while we were running, drain it now.
    if (pendingRegistration) {
      const { store: nextStore, getWindow: nextGetWindow } = pendingRegistration;
      pendingRegistration = null;
      // Don't await — let the caller return immediately; the next pass
      // will serialize further concurrent calls via the same guard.
      registerShortcuts(nextStore, nextGetWindow).catch((err) =>
        console.warn('[Shortcuts] Deferred re-registration failed:', err),
      );
    }
  }
}

/**
 * Inner implementation of shortcut registration (no concurrency guard).
 */
async function doRegisterShortcuts(
  store: ReadableStore,
  getWindow: () => BrowserWindow | null,
): Promise<void> {
  unregisterShortcuts();

  const onWayland = process.platform === 'linux' && isWayland();

  // On Wayland: try D-Bus portal first for proper descriptions and readback
  if (onWayland) {
    try {
      const portalOk = await initWaylandShortcuts(store, getWindow);
      if (portalOk) {
        waylandMode = true;
        return;
      }
    } catch (err) {
      console.warn('[Shortcuts] Wayland portal init failed, falling back to globalShortcut:', err);
    }
  }

  // Standard Electron globalShortcut path (X11, macOS, Windows, or portal fallback)
  const startAccelerator = (store.get('shortcuts.startRecording') as string) || 'Alt+Ctrl+Z';
  const stopAccelerator = (store.get('shortcuts.stopTranscribe') as string) || 'Alt+Ctrl+X';

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

  if (onWayland && registeredAccelerators.length === 0) {
    console.log(
      '[Shortcuts] No shortcuts registered on Wayland. ' +
        'Your compositor may not support the XDG GlobalShortcuts portal ' +
        '(KDE Plasma and Hyprland are supported). Fallback: use CLI args ' +
        '(--start-recording / --stop-recording) or Unix signals (SIGUSR1 / SIGUSR2).',
    );
  }
}

/**
 * Unregister all global shortcuts previously registered by this module.
 */
export function unregisterShortcuts(): void {
  if (waylandMode) {
    destroyWaylandShortcuts();
    waylandMode = false;
    return;
  }
  for (const acc of registeredAccelerators) {
    try {
      globalShortcut.unregister(acc);
    } catch {
      // Best-effort
    }
  }
  registeredAccelerators.length = 0;
}

/**
 * Get portal-assigned shortcut bindings (Wayland portal mode only).
 * Returns null when not in portal mode.
 */
export async function getPortalShortcuts(): Promise<PortalShortcutInfo[] | null> {
  if (!waylandMode) return null;
  return listShortcuts();
}

/**
 * Rebind shortcuts through the portal (Wayland portal mode only).
 * Triggers the compositor's shortcut assignment dialog.
 */
export async function rebindPortalShortcuts(store: ReadableStore): Promise<boolean> {
  if (!waylandMode) return false;
  return rebindShortcuts(store);
}

/**
 * Whether the Wayland portal mode is currently active.
 */
export function isWaylandPortalActive(): boolean {
  return waylandMode && isPortalConnected();
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
