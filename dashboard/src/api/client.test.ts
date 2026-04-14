import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { apiClient } from './client';

// Renderer-side install-gate mirror: when useRemote=true with a blank active-
// profile host, checkConnection must return `'remote-host-not-configured'`
// before dispatching any probe (IPC or fetch). Uses the Electron bridge
// config.get stub so isServerUrlConfigured() reads seeded values.

type ConfigSeed = Record<string, unknown>;

function installElectronBridge(seed: ConfigSeed, probeConnection: ReturnType<typeof vi.fn>) {
  (window as any).electronAPI = {
    server: { probeConnection },
    config: {
      get: vi.fn(async (key: string) => seed[key]),
      set: vi.fn(),
    },
  };
}

describe('APIClient.checkConnection — remote-host-not-configured short-circuit', () => {
  let probeConnection: ReturnType<typeof vi.fn>;
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    delete (window as any).electronAPI;
    probeConnection = vi.fn();
    fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
  });

  afterEach(() => {
    // Prevent singleton apiClient state and global stubs from leaking into
    // unrelated test files: fetch stub, window.electronAPI, and any mock
    // call histories on probeConnection / config.get must be cleared.
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete (window as any).electronAPI;
  });

  it('returns {error: "remote-host-not-configured"} when useRemote=true with blank Tailscale host', async () => {
    installElectronBridge(
      {
        'connection.useRemote': true,
        'connection.remoteProfile': 'tailscale',
        'connection.remoteHost': '',
      },
      probeConnection,
    );

    const result = await apiClient.checkConnection();

    expect(result).toEqual({
      reachable: false,
      ready: false,
      status: null,
      error: 'remote-host-not-configured',
    });
    expect(probeConnection).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('short-circuits without probing when useRemote=true with blank LAN host (whitespace)', async () => {
    installElectronBridge(
      {
        'connection.useRemote': true,
        'connection.remoteProfile': 'lan',
        'connection.lanHost': '   ',
      },
      probeConnection,
    );

    const result = await apiClient.checkConnection();

    expect(result.error).toBe('remote-host-not-configured');
    expect(result.reachable).toBe(false);
    expect(result.ready).toBe(false);
    expect(result.status).toBeNull();
    expect(probeConnection).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('does NOT short-circuit in local mode — probe path is entered and result.error is null', async () => {
    installElectronBridge({ 'connection.useRemote': false }, probeConnection);
    probeConnection.mockResolvedValue({
      ok: true,
      httpStatus: 200,
      body: JSON.stringify({
        server: { ready: true, healthy: true },
      }),
    });

    const result = await apiClient.checkConnection();

    expect(probeConnection).toHaveBeenCalledTimes(1);
    expect(result.error).toBeNull();
    expect(result.error).not.toBe('remote-host-not-configured');
  });

  it('does NOT short-circuit when useRemote=true with configured Tailscale host', async () => {
    installElectronBridge(
      {
        'connection.useRemote': true,
        'connection.remoteProfile': 'tailscale',
        'connection.remoteHost': 'foo.ts.net',
      },
      probeConnection,
    );
    probeConnection.mockResolvedValue({
      ok: true,
      httpStatus: 200,
      body: JSON.stringify({ server: { ready: true, healthy: true } }),
    });

    const result = await apiClient.checkConnection();

    expect(probeConnection).toHaveBeenCalledTimes(1);
    expect(result.error).toBeNull();
    expect(result.error).not.toBe('remote-host-not-configured');
  });
});
