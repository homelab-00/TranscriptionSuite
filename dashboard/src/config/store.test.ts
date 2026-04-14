import { describe, it, expect, beforeEach, vi } from 'vitest';

import { DEFAULT_SERVER_PORT, getServerBaseUrl, isServerUrlConfigured } from './store';

// These tests route getConfig through the Electron `window.electronAPI.config.get`
// bridge — the production branch. Each test seeds a plain object that the bridge
// mock reads via key lookup, so unset keys return undefined (matching electron-
// store's missing-key behavior).

type ConfigSeed = Record<string, unknown>;

function installConfigBridge(seed: ConfigSeed): void {
  (window as any).electronAPI = {
    config: {
      get: vi.fn(async (key: string) => seed[key]),
      set: vi.fn(),
    },
  };
}

describe('isServerUrlConfigured', () => {
  beforeEach(() => {
    delete (window as any).electronAPI;
  });

  it('returns true when useRemote is unset (local mode default)', async () => {
    installConfigBridge({});
    expect(await isServerUrlConfigured()).toBe(true);
  });

  it('returns true when useRemote=false regardless of remote hosts', async () => {
    installConfigBridge({
      'connection.useRemote': false,
      'connection.remoteHost': '',
      'connection.lanHost': '',
    });
    expect(await isServerUrlConfigured()).toBe(true);
  });

  it('returns true when useRemote=true and Tailscale remoteHost is configured', async () => {
    installConfigBridge({
      'connection.useRemote': true,
      'connection.remoteProfile': 'tailscale',
      'connection.remoteHost': 'foo.ts.net',
    });
    expect(await isServerUrlConfigured()).toBe(true);
  });

  it('returns false when useRemote=true and Tailscale remoteHost is blank', async () => {
    installConfigBridge({
      'connection.useRemote': true,
      'connection.remoteProfile': 'tailscale',
      'connection.remoteHost': '',
    });
    expect(await isServerUrlConfigured()).toBe(false);
  });

  it('returns false when useRemote=true and Tailscale remoteHost is whitespace-only', async () => {
    installConfigBridge({
      'connection.useRemote': true,
      'connection.remoteProfile': 'tailscale',
      'connection.remoteHost': '   \t\n',
    });
    expect(await isServerUrlConfigured()).toBe(false);
  });

  it('returns false when useRemote=true and LAN lanHost is blank', async () => {
    installConfigBridge({
      'connection.useRemote': true,
      'connection.remoteProfile': 'lan',
      'connection.lanHost': '',
    });
    expect(await isServerUrlConfigured()).toBe(false);
  });

  it('reads the ACTIVE profile host — Tailscale blank + LAN configured → false when profile is Tailscale', async () => {
    installConfigBridge({
      'connection.useRemote': true,
      'connection.remoteProfile': 'tailscale',
      'connection.remoteHost': '',
      'connection.lanHost': '10.0.0.5',
    });
    expect(await isServerUrlConfigured()).toBe(false);
  });

  it('reads the ACTIVE profile host — LAN configured + Tailscale blank → true when profile is LAN', async () => {
    installConfigBridge({
      'connection.useRemote': true,
      'connection.remoteProfile': 'lan',
      'connection.remoteHost': '',
      'connection.lanHost': '10.0.0.5',
    });
    expect(await isServerUrlConfigured()).toBe(true);
  });

  it('defaults remoteProfile to tailscale when unset — configured remoteHost → true', async () => {
    installConfigBridge({
      'connection.useRemote': true,
      'connection.remoteHost': 'foo.ts.net',
    });
    expect(await isServerUrlConfigured()).toBe(true);
  });

  it('defaults remoteProfile to tailscale when unset — blank remoteHost + configured lanHost → false', async () => {
    installConfigBridge({
      'connection.useRemote': true,
      'connection.remoteHost': '',
      'connection.lanHost': '10.0.0.5',
    });
    expect(await isServerUrlConfigured()).toBe(false);
  });
});

describe('getServerBaseUrl — blank-remote non-coercion regression lock', () => {
  beforeEach(() => {
    delete (window as any).electronAPI;
  });

  it('returns http://:<port> (NOT http://localhost:<port>) when useRemote=true with blank Tailscale host', async () => {
    installConfigBridge({
      'connection.useRemote': true,
      'connection.remoteProfile': 'tailscale',
      'connection.remoteHost': '',
    });
    const url = await getServerBaseUrl();
    expect(url).toBe(`http://:${DEFAULT_SERVER_PORT}`);
    expect(url).not.toContain('localhost');
  });

  it('returns http://:<port> when useRemote=true with blank LAN host', async () => {
    installConfigBridge({
      'connection.useRemote': true,
      'connection.remoteProfile': 'lan',
      'connection.lanHost': '',
    });
    const url = await getServerBaseUrl();
    expect(url).toBe(`http://:${DEFAULT_SERVER_PORT}`);
    expect(url).not.toContain('localhost');
  });

  it('respects useHttps toggle for the blank-remote malformed URL', async () => {
    installConfigBridge({
      'connection.useRemote': true,
      'connection.useHttps': true,
      'connection.remoteProfile': 'tailscale',
      'connection.remoteHost': '',
    });
    const url = await getServerBaseUrl();
    expect(url).toBe(`https://:${DEFAULT_SERVER_PORT}`);
  });

  it('returns localhost URL in LOCAL mode (regression lock for happy path)', async () => {
    installConfigBridge({ 'connection.useRemote': false });
    const url = await getServerBaseUrl();
    expect(url).toBe(`http://localhost:${DEFAULT_SERVER_PORT}`);
  });

  it('returns configured Tailscale host URL when remoteHost is set', async () => {
    installConfigBridge({
      'connection.useRemote': true,
      'connection.useHttps': true,
      'connection.remoteProfile': 'tailscale',
      'connection.remoteHost': 'foo.ts.net',
    });
    const url = await getServerBaseUrl();
    expect(url).toBe(`https://foo.ts.net:${DEFAULT_SERVER_PORT}`);
  });
});
