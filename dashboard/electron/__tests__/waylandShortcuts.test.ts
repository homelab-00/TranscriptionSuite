// @vitest-environment node

/**
 * P2-PLAT-001 — Wayland shortcut registration/unregistration
 *
 * Tests the pure format-conversion functions (electronToXdg, xdgToElectron)
 * and safe state-check helpers exported from waylandShortcuts.ts.
 *
 * D-Bus integration is NOT tested here — it requires a live session bus
 * and compositor portal, which jsdom/node cannot provide.
 */

import { describe, it, expect, vi } from 'vitest';
import {
  electronToXdg,
  xdgToElectron,
  isPortalConnected,
  destroyWaylandShortcuts,
  registerHostAppId,
  PORTAL_APP_ID,
} from '../waylandShortcuts.js';

// ── electronToXdg ───────────────────────────────────────────────────────────

describe('[P2] electronToXdg', () => {
  it('converts Electron accelerator to XDG format with canonical modifier order', () => {
    // Electron uses title-case modifiers, XDG uses uppercase modifiers + lowercase key
    expect(electronToXdg('Alt+Ctrl+Z')).toBe('CTRL+ALT+z');
  });

  it('handles CommandOrControl and Option aliases', () => {
    expect(electronToXdg('CommandOrControl+Option+S')).toBe('CTRL+ALT+s');
  });

  it('handles Super/Meta/Command modifiers', () => {
    expect(electronToXdg('Super+Shift+A')).toBe('SUPER+SHIFT+a');
    expect(electronToXdg('Meta+X')).toBe('SUPER+x');
    expect(electronToXdg('Cmd+Q')).toBe('SUPER+q');
  });

  it('returns empty string for empty input', () => {
    expect(electronToXdg('')).toBe('');
  });

  it('returns modifier-only string when no key is present', () => {
    expect(electronToXdg('Ctrl+Alt')).toBe('CTRL+ALT');
  });

  it('sorts modifiers into canonical order (SUPER, CTRL, ALT, SHIFT)', () => {
    // Input has reverse order — output should be canonical
    expect(electronToXdg('Shift+Alt+Ctrl+Super+K')).toBe('SUPER+CTRL+ALT+SHIFT+k');
  });
});

// ── xdgToElectron ───────────────────────────────────────────────────────────

describe('[P2] xdgToElectron', () => {
  it('converts XDG portal trigger to Electron accelerator format', () => {
    expect(xdgToElectron('CTRL+ALT+z')).toBe('Ctrl+Alt+Z');
  });

  it('capitalizes multi-character key names', () => {
    expect(xdgToElectron('CTRL+escape')).toBe('Ctrl+Escape');
    expect(xdgToElectron('ALT+space')).toBe('Alt+Space');
  });

  it('handles SUPER modifier', () => {
    expect(xdgToElectron('SUPER+SHIFT+a')).toBe('Super+Shift+A');
  });

  it('returns empty string for empty input', () => {
    expect(xdgToElectron('')).toBe('');
  });

  it('round-trips with electronToXdg', () => {
    const original = 'Ctrl+Alt+Z';
    const xdg = electronToXdg(original);
    const roundTripped = xdgToElectron(xdg);
    expect(roundTripped).toBe(original);
  });
});

// ── isPortalConnected ───────────────────────────────────────────────────────

describe('[P2] isPortalConnected', () => {
  it('returns false before init is called', () => {
    expect(isPortalConnected()).toBe(false);
  });
});

// ── destroyWaylandShortcuts ─────────────────────────────────────────────────

describe('[P2] destroyWaylandShortcuts', () => {
  it('can be called safely when not connected (no-op)', () => {
    // Should not throw even when there is no active session
    expect(() => destroyWaylandShortcuts()).not.toThrow();
    expect(isPortalConnected()).toBe(false);
  });
});

// ── registerHostAppId ───────────────────────────────────────────────────────
// Registers the app id with the XDG host portal Registry so GlobalShortcuts
// CreateSession passes the "An app id is required" frontend gate added in
// xdg-desktop-portal 1.21.0. Tested with a fake portal object — no live D-Bus.

describe('[P2] registerHostAppId', () => {
  it('uses a non-empty reverse-DNS app id', () => {
    expect(PORTAL_APP_ID).toBeTruthy();
    // Reverse-DNS: at least one dot, no leading dot (xdp_is_valid_app_id rules).
    expect(PORTAL_APP_ID).toMatch(/^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)+$/);
  });

  it('calls Registry.Register with the app id and an empty options dict', async () => {
    const registerSpy = vi.fn().mockResolvedValue(undefined);
    const fakePortalObj = {
      getInterface: (name: string) => {
        if (name === 'org.freedesktop.host.portal.Registry') {
          return { Register: registerSpy };
        }
        throw new Error(`unexpected interface requested: ${name}`);
      },
    };

    await registerHostAppId(fakePortalObj);

    expect(registerSpy).toHaveBeenCalledTimes(1);
    expect(registerSpy).toHaveBeenCalledWith(PORTAL_APP_ID, {});
  });

  it('does not throw when the Registry interface is absent (older portal < 1.19.4)', async () => {
    // dbus-next getInterface() throws synchronously when the interface was not
    // present in the introspection data.
    const fakePortalObj = {
      getInterface: () => {
        throw new Error("Interface 'org.freedesktop.host.portal.Registry' not found");
      },
    };

    await expect(registerHostAppId(fakePortalObj)).resolves.toBeUndefined();
  });

  it('swallows Register rejections (already registered / too late / unknown method)', async () => {
    for (const message of [
      'Connection already associated with an application ID',
      'Registered too late',
      'org.freedesktop.DBus.Error.UnknownMethod',
    ]) {
      const fakePortalObj = {
        getInterface: () => ({
          Register: vi.fn().mockRejectedValue(new Error(message)),
        }),
      };
      await expect(registerHostAppId(fakePortalObj)).resolves.toBeUndefined();
    }
  });
});
