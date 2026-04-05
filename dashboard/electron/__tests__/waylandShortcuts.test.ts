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

import { describe, it, expect } from 'vitest';
import {
  electronToXdg,
  xdgToElectron,
  isPortalConnected,
  destroyWaylandShortcuts,
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
