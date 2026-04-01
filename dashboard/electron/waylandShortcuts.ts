/**
 * XDG GlobalShortcuts portal integration for Wayland via D-Bus.
 *
 * Bypasses Electron's globalShortcut.register() on Wayland to talk directly
 * to the XDG Desktop Portal, which lets us:
 *   - Set human-readable descriptions ("Start Recording", "Stop & Transcribe")
 *   - Set preferred_trigger from config values
 *   - Listen for Activated / ShortcutsChanged signals
 *   - Read back actual portal-assigned triggers via ListShortcuts
 *
 * Uses `@particle/dbus-next` (CJS-only) imported via createRequire since the project is ESM.
 */

import { createRequire } from 'module';
import type { BrowserWindow } from 'electron';

const require = createRequire(import.meta.url);

// ─── Types ──────────────────────────────────────────────────────────────────

interface ReadableStore {
  get(key: string): unknown;
}

interface PortalBinding {
  id: string;
  description: string;
  preferredTrigger: string;
  action: string;
}

export interface PortalShortcutInfo {
  id: string;
  trigger: string;
}

// ─── Format Conversion ──────────────────────────────────────────────────────

/**
 * Convert Electron accelerator format to XDG portal trigger format.
 * Electron: "Alt+Ctrl+Z"  →  XDG: "CTRL+ALT+z"
 *
 * XDG portal uses uppercase modifier names and lowercase key names,
 * with a canonical modifier order: SUPER, CTRL, ALT, SHIFT.
 */
export function electronToXdg(accelerator: string): string {
  if (!accelerator) return '';

  const parts = accelerator.split('+');
  const modifiers: string[] = [];
  let key = '';

  for (const part of parts) {
    const lower = part.toLowerCase().trim();
    switch (lower) {
      case 'ctrl':
      case 'control':
      case 'commandorcontrol':
        modifiers.push('CTRL');
        break;
      case 'alt':
      case 'option':
        modifiers.push('ALT');
        break;
      case 'shift':
        modifiers.push('SHIFT');
        break;
      case 'super':
      case 'meta':
      case 'command':
      case 'cmd':
        modifiers.push('SUPER');
        break;
      default:
        key = lower;
        break;
    }
  }

  // Canonical modifier order: SUPER, CTRL, ALT, SHIFT
  const order = ['SUPER', 'CTRL', 'ALT', 'SHIFT'];
  modifiers.sort((a, b) => order.indexOf(a) - order.indexOf(b));

  if (!key) return modifiers.join('+');
  return [...modifiers, key].join('+');
}

/**
 * Convert XDG portal trigger format to Electron accelerator format.
 * XDG: "CTRL+ALT+z"  →  Electron: "Ctrl+Alt+Z"
 */
export function xdgToElectron(trigger: string): string {
  if (!trigger) return '';

  const parts = trigger.split('+');
  const result: string[] = [];

  for (const part of parts) {
    const upper = part.toUpperCase().trim();
    switch (upper) {
      case 'CTRL':
      case 'CONTROL':
        result.push('Ctrl');
        break;
      case 'ALT':
        result.push('Alt');
        break;
      case 'SHIFT':
        result.push('Shift');
        break;
      case 'SUPER':
      case 'META':
        result.push('Super');
        break;
      default:
        // Key name — capitalize first letter for Electron format
        result.push(
          part.length === 1
            ? part.toUpperCase()
            : part.charAt(0).toUpperCase() + part.slice(1).toLowerCase(),
        );
        break;
    }
  }

  return result.join('+');
}

// ─── D-Bus Portal Client ────────────────────────────────────────────────────

// The shortcut definitions we register with the portal
const SHORTCUT_DEFS: Array<{ id: string; description: string; action: string }> = [
  { id: 'start-recording', description: 'Start Recording', action: 'start-recording' },
  { id: 'stop-transcribe', description: 'Stop & Transcribe', action: 'stop-recording' },
];

let bus: any = null;
let portalProxy: any = null;
let sessionPath: string | null = null;
let connected = false;
let activatedUnsubscribe: (() => void) | null = null;
let shortcutsChangedUnsubscribe: (() => void) | null = null;
let currentGetWindow: (() => BrowserWindow | null) | null = null;

// Unique token counter for portal request paths
let requestCounter = 0;

function getRequestToken(): string {
  return `transcriptionsuite_${process.pid}_${++requestCounter}`;
}

/**
 * Get the sender name formatted for D-Bus object paths.
 * D-Bus sender is like ":1.42" → "1_42"
 */
function senderToPath(sender: string): string {
  return sender.replace(/^:/, '').replace(/\./g, '_');
}

/**
 * Initialize the Wayland GlobalShortcuts portal session.
 *
 * Returns true if the portal session was created successfully.
 * Returns false on any failure (no portal, unsupported compositor, etc.)
 */
export async function initWaylandShortcuts(
  store: ReadableStore,
  getWindow: () => BrowserWindow | null,
): Promise<boolean> {
  if (process.platform !== 'linux') return false;

  currentGetWindow = getWindow;

  // Close any leftover bus from a previous failed init before opening a new one.
  if (bus) {
    try {
      bus.disconnect();
    } catch {
      // Ignore — stale reference.
    }
    bus = null;
  }

  try {
    const dbus = require('@particle/dbus-next');
    bus = dbus.sessionBus();

    // Get the portal proxy
    const portalObj = await bus.getProxyObject(
      'org.freedesktop.portal.Desktop',
      '/org/freedesktop/portal/desktop',
    );
    portalProxy = portalObj.getInterface('org.freedesktop.portal.GlobalShortcuts');
  } catch (err) {
    console.warn('[WaylandShortcuts] Failed to connect to D-Bus GlobalShortcuts portal:', err);
    cleanup(true);
    return false;
  }

  // Create a session
  try {
    const token = getRequestToken();
    const sessionToken = `session_${getRequestToken()}`;

    // Subscribe to the Response signal on the predicted request path BEFORE calling CreateSession
    const sender = senderToPath(bus.name);
    const requestPath = `/org/freedesktop/portal/desktop/request/${sender}/${token}`;

    const responsePromise = waitForResponse(requestPath);

    const dbus = require('@particle/dbus-next');
    const { Variant } = dbus;

    await portalProxy.CreateSession({
      handle_token: new Variant('s', token),
      session_handle_token: new Variant('s', sessionToken),
    });

    const response = await responsePromise;
    if (response.code !== 0) {
      console.warn(
        '[WaylandShortcuts] CreateSession was rejected by portal (code:',
        response.code,
        ')',
      );
      cleanup(true);
      return false;
    }

    sessionPath = response.results?.session_handle?.value ?? null;
    if (!sessionPath) {
      // Construct expected session path
      sessionPath = `/org/freedesktop/portal/desktop/session/${sender}/${sessionToken}`;
    }

    console.log('[WaylandShortcuts] Session created:', sessionPath);
  } catch (err) {
    console.warn('[WaylandShortcuts] Failed to create portal session:', err);
    cleanup(true);
    return false;
  }

  // Subscribe to signals
  try {
    subscribeToSignals();
  } catch (err) {
    console.warn('[WaylandShortcuts] Failed to subscribe to signals:', err);
    // Non-fatal — shortcuts may still work, just no live updates
  }

  // Bind shortcuts with current config values
  try {
    const success = await bindShortcutsFromStore(store);
    if (!success) {
      console.warn('[WaylandShortcuts] Initial BindShortcuts failed or was cancelled');
      // Non-fatal — session is still valid, user can rebind later
    }
  } catch (err) {
    console.warn('[WaylandShortcuts] Error during initial bind:', err);
  }

  connected = true;
  console.log('[WaylandShortcuts] Portal integration active');
  return true;
}

/**
 * Wait for a portal Response signal on the given request path.
 *
 * Uses the low-level D-Bus message interface (AddMatch + bus.on('message'))
 * instead of getProxyObject().  This avoids the introspection race condition
 * where the portal destroys the ephemeral Request object before dbus-next can
 * introspect it, resulting in "Interface org.freedesktop.portal.Request not
 * found".
 */
function waitForResponse(
  requestPath: string,
  timeoutMs = 30000,
): Promise<{ code: number; results: any }> {
  return new Promise((resolve, reject) => {
    const dbus = require('@particle/dbus-next');
    const Message = dbus.Message;

    const matchRule =
      `type='signal',` +
      `sender='org.freedesktop.portal.Desktop',` +
      `interface='org.freedesktop.portal.Request',` +
      `path='${requestPath}',` +
      `member='Response'`;

    let settled = false;
    let matchAdded = false;

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      removeResources();
      reject(new Error(`Portal response timeout on ${requestPath}`));
    }, timeoutMs);

    function onMessage(msg: any) {
      if (settled) return;
      if (
        msg.type === dbus.MessageType.SIGNAL &&
        msg.path === requestPath &&
        msg.interface === 'org.freedesktop.portal.Request' &&
        msg.member === 'Response'
      ) {
        settled = true;
        clearTimeout(timer);
        removeResources();
        const [code, results] = msg.body ?? [1, {}];
        resolve({ code, results });
      }
    }

    function removeResources() {
      bus.removeListener('message', onMessage);
      // Only send RemoveMatch if AddMatch completed — otherwise we'd
      // orphan the match rule if AddMatch finishes after this call.
      if (matchAdded) {
        try {
          const removeMsg = new Message({
            destination: 'org.freedesktop.DBus',
            path: '/org/freedesktop/DBus',
            interface: 'org.freedesktop.DBus',
            member: 'RemoveMatch',
            signature: 's',
            body: [matchRule],
          });
          bus.send(removeMsg);
        } catch {
          // Ignore — match may already be gone or bus disconnected.
        }
      }
    }

    // Register the listener BEFORE sending AddMatch so we can't miss the signal.
    bus.on('message', onMessage);

    const addMatchMsg = new Message({
      destination: 'org.freedesktop.DBus',
      path: '/org/freedesktop/DBus',
      interface: 'org.freedesktop.DBus',
      member: 'AddMatch',
      signature: 's',
      body: [matchRule],
    });

    bus.call(addMatchMsg).then(
      () => {
        matchAdded = true;
        // If already settled (timeout fired while AddMatch was in flight),
        // clean up the match rule now that we know it was registered.
        if (settled) {
          try {
            const removeMsg = new Message({
              destination: 'org.freedesktop.DBus',
              path: '/org/freedesktop/DBus',
              interface: 'org.freedesktop.DBus',
              member: 'RemoveMatch',
              signature: 's',
              body: [matchRule],
            });
            bus.send(removeMsg);
          } catch {
            // Ignore — bus may be closed.
          }
        }
      },
      (err: any) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        bus.removeListener('message', onMessage);
        reject(err);
      },
    );
  });
}

/**
 * Build the shortcuts array for BindShortcuts from store config.
 */
function buildBindings(store: ReadableStore): PortalBinding[] {
  const startAccelerator = (store.get('shortcuts.startRecording') as string) || 'Alt+Ctrl+Z';
  const stopAccelerator = (store.get('shortcuts.stopTranscribe') as string) || 'Alt+Ctrl+X';

  return [
    {
      id: SHORTCUT_DEFS[0].id,
      description: SHORTCUT_DEFS[0].description,
      preferredTrigger: electronToXdg(startAccelerator),
      action: SHORTCUT_DEFS[0].action,
    },
    {
      id: SHORTCUT_DEFS[1].id,
      description: SHORTCUT_DEFS[1].description,
      preferredTrigger: electronToXdg(stopAccelerator),
      action: SHORTCUT_DEFS[1].action,
    },
  ];
}

/**
 * Call BindShortcuts on the portal with current config values.
 */
async function bindShortcutsFromStore(store: ReadableStore): Promise<boolean> {
  if (!portalProxy || !sessionPath) return false;

  const dbus = require('@particle/dbus-next');
  const { Variant } = dbus;

  const bindings = buildBindings(store);

  // Build the shortcuts array: Array<(id, Dict<String,Variant>)>
  const shortcuts = bindings.map((b) => [
    b.id,
    {
      description: new Variant('s', b.description),
      preferred_trigger: new Variant('s', b.preferredTrigger),
    },
  ]);

  const token = getRequestToken();
  const sender = senderToPath(bus.name);
  const requestPath = `/org/freedesktop/portal/desktop/request/${sender}/${token}`;

  const responsePromise = waitForResponse(requestPath);

  try {
    await portalProxy.BindShortcuts(
      sessionPath,
      shortcuts,
      '', // parent_window
      {
        handle_token: new Variant('s', token),
      },
    );

    const response = await responsePromise;
    if (response.code === 0) {
      console.log('[WaylandShortcuts] Shortcuts bound successfully');
      return true;
    } else if (response.code === 1) {
      console.log('[WaylandShortcuts] User cancelled the portal shortcut dialog');
      return false;
    } else {
      console.warn('[WaylandShortcuts] BindShortcuts returned code:', response.code);
      return false;
    }
  } catch (err) {
    console.warn('[WaylandShortcuts] BindShortcuts call failed:', err);
    return false;
  }
}

/**
 * Subscribe to Activated and ShortcutsChanged signals on the portal.
 */
function subscribeToSignals(): void {
  if (!portalProxy) return;

  // Activated signal: (session_handle, shortcut_id, timestamp, options)
  const onActivated = (
    _sessionHandle: string,
    shortcutId: string,
    _timestamp: any,
    _options: any,
  ) => {
    const def = SHORTCUT_DEFS.find((d) => d.id === shortcutId);
    if (!def) {
      console.warn('[WaylandShortcuts] Unknown shortcut activated:', shortcutId);
      return;
    }

    console.log(`[WaylandShortcuts] Shortcut activated: ${shortcutId} → ${def.action}`);
    const win = currentGetWindow?.();
    if (win) {
      win.webContents.send('tray:action', def.action);
    }
  };

  // ShortcutsChanged signal: (session_handle, shortcuts)
  const onShortcutsChanged = (_sessionHandle: string, shortcuts: any) => {
    console.log('[WaylandShortcuts] Shortcuts changed by portal');
    const bindings = parsePortalShortcuts(shortcuts);
    const win = currentGetWindow?.();
    if (win) {
      win.webContents.send('shortcuts:portalChanged', bindings);
    }
  };

  portalProxy.on('Activated', onActivated);
  portalProxy.on('ShortcutsChanged', onShortcutsChanged);

  activatedUnsubscribe = () => portalProxy?.removeListener('Activated', onActivated);
  shortcutsChangedUnsubscribe = () =>
    portalProxy?.removeListener('ShortcutsChanged', onShortcutsChanged);
}

/**
 * Parse the portal shortcuts response into a simple array of {id, trigger}.
 */
function parsePortalShortcuts(shortcuts: any): PortalShortcutInfo[] {
  if (!Array.isArray(shortcuts)) return [];

  return shortcuts.map((entry: any) => {
    // Each entry is [id, dict] where dict has 'trigger_description' or 'preferred_trigger'
    const id = typeof entry[0] === 'string' ? entry[0] : '';
    const dict = entry[1] || {};

    // The portal may return 'trigger_description' with the actual bound trigger
    const triggerVariant = dict['trigger_description'] ?? dict['preferred_trigger'];
    const trigger = triggerVariant?.value ?? triggerVariant ?? '';

    return { id, trigger: typeof trigger === 'string' ? trigger : '' };
  });
}

/**
 * Read back the actual portal-assigned triggers via ListShortcuts.
 */
export async function listShortcuts(): Promise<PortalShortcutInfo[] | null> {
  if (!portalProxy || !sessionPath || !connected) return null;

  const dbus = require('@particle/dbus-next');
  const { Variant } = dbus;

  const token = getRequestToken();
  const sender = senderToPath(bus.name);
  const requestPath = `/org/freedesktop/portal/desktop/request/${sender}/${token}`;

  const responsePromise = waitForResponse(requestPath);

  try {
    await portalProxy.ListShortcuts(sessionPath, {
      handle_token: new Variant('s', token),
    });

    const response = await responsePromise;
    if (response.code !== 0) {
      console.warn('[WaylandShortcuts] ListShortcuts returned code:', response.code);
      return null;
    }

    const shortcuts = response.results?.shortcuts?.value ?? response.results?.shortcuts ?? [];
    return parsePortalShortcuts(shortcuts);
  } catch (err) {
    console.warn('[WaylandShortcuts] ListShortcuts failed:', err);
    return null;
  }
}

/**
 * Rebind shortcuts — called when config values change.
 * Triggers the portal dialog for the user to confirm/reassign.
 */
export async function rebindShortcuts(store: ReadableStore): Promise<boolean> {
  if (!connected) return false;
  return bindShortcutsFromStore(store);
}

/**
 * Whether the portal session is active and connected.
 */
export function isPortalConnected(): boolean {
  return connected;
}

/**
 * Clean up internal state.
 *
 * @param closeBus — also disconnect the D-Bus connection.  Pass `true` on
 *   error/teardown paths so orphaned connections don't degrade the session bus
 *   (which is shared with libnotify and other D-Bus clients).
 */
function cleanup(closeBus = false): void {
  activatedUnsubscribe?.();
  shortcutsChangedUnsubscribe?.();
  activatedUnsubscribe = null;
  shortcutsChangedUnsubscribe = null;
  portalProxy = null;
  sessionPath = null;
  connected = false;
  currentGetWindow = null;
  if (closeBus && bus) {
    try {
      bus.disconnect();
    } catch {
      // Best-effort — bus may already be closed or in a bad state.
    }
    bus = null;
  }
}

/**
 * Destroy the portal session and disconnect from D-Bus.
 */
export function destroyWaylandShortcuts(): void {
  cleanup(true);
  console.log('[WaylandShortcuts] Portal session destroyed');
}
