import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { APIClient, apiClient, initApiClient } from './client';

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

  it('returns {error: "config-read-failed"} when isServerUrlConfigured throws (preload rejection)', async () => {
    // Restores the docstring's "Does not throw" contract. Preload IPC
    // rejection / QuotaExceededError on localStorage fallback must surface
    // as a stable error reason, not an unhandled rejection that crashes
    // useServerStatus / useAdminStatus polling loops.
    (window as any).electronAPI = {
      server: { probeConnection },
      config: {
        get: vi.fn(async () => {
          throw new Error('preload bridge rejected');
        }),
        set: vi.fn(),
      },
    };

    const result = await apiClient.checkConnection();

    expect(result).toEqual({
      reachable: false,
      ready: false,
      status: null,
      error: 'config-read-failed',
    });
    expect(probeConnection).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
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

// Network-path install-gate: all REST helpers, SSE generators, loadModelsStream,
// and derived-URL methods (getAudioUrl/getExportUrl) must gate on
// isBaseUrlConfigured() — which requires (a) syncFromConfig has run at least
// once AND (b) baseUrl parses with a non-empty hostname. Uses a fresh APIClient
// per test to avoid singleton synced-flag bleed.

describe('APIClient.isBaseUrlConfigured — sync predicate', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    delete (window as any).electronAPI;
    fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete (window as any).electronAPI;
  });

  it('returns false for a fresh client (synced=false) even with a parseable default URL', () => {
    const client = new APIClient();
    expect(client.isBaseUrlConfigured()).toBe(false);
  });

  it('returns true after syncFromConfig reads a configured local-mode URL', async () => {
    (window as any).electronAPI = {
      config: {
        get: vi.fn(async (key: string) => {
          const seed: Record<string, unknown> = {
            'connection.useRemote': false,
          };
          return seed[key];
        }),
        set: vi.fn(),
      },
    };
    const client = new APIClient();
    await client.syncFromConfig();
    expect(client.isBaseUrlConfigured()).toBe(true);
  });

  it('returns false after syncFromConfig yields a blank-remote baseUrl (http://:9786)', async () => {
    (window as any).electronAPI = {
      config: {
        get: vi.fn(async (key: string) => {
          const seed: Record<string, unknown> = {
            'connection.useRemote': true,
            'connection.remoteProfile': 'tailscale',
            'connection.remoteHost': '',
          };
          return seed[key];
        }),
        set: vi.fn(),
      },
    };
    const client = new APIClient();
    await client.syncFromConfig();
    expect(client.getBaseUrl()).toMatch(/^https?:\/\/:\d+$/);
    expect(client.isBaseUrlConfigured()).toBe(false);
  });
});

describe('APIClient REST helpers — remote-host-not-configured gate', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    delete (window as any).electronAPI;
    fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete (window as any).electronAPI;
  });

  it('throws APIError(0, "remote-host-not-configured") on a pre-sync REST call AND does not dispatch fetch', async () => {
    const client = new APIClient();
    // Probe via a public method that routes through the gated private `get`.
    await expect(client.getAdminStatus()).rejects.toMatchObject({
      name: 'APIError',
      status: 0,
      body: 'remote-host-not-configured',
      path: '/api/admin/status',
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('throws the stable error shape for each HTTP verb helper (pre-sync)', async () => {
    const client = new APIClient();
    // Assert the full shape (not just instanceof) so a regression where any
    // verb throws a different APIError (e.g. wrong body, wrong status, wrong
    // path) doesn't silently pass this test.
    const expectedBody = 'remote-host-not-configured';
    await expect(client.getAdminStatus()).rejects.toMatchObject({
      status: 0,
      body: expectedBody,
      path: '/api/admin/status',
    });
    await expect(client.loadModels()).rejects.toMatchObject({
      status: 0,
      body: expectedBody,
      path: '/api/admin/models/load',
    });
    await expect(client.updateDiarizationSettings({ parallel: true })).rejects.toMatchObject({
      status: 0,
      body: expectedBody,
      path: '/api/admin/diarization',
    });
    await expect(client.setRecordingSummary(1, 'x')).rejects.toMatchObject({
      status: 0,
      body: expectedBody,
      path: expect.stringMatching(/^\/api\/notebook\/recordings\/1\/summary/),
    });
    await expect(client.deleteRecording(1)).rejects.toMatchObject({
      status: 0,
      body: expectedBody,
      path: '/api/notebook/recordings/1',
    });
    const file = new File(['x'], 'x.wav', { type: 'audio/wav' });
    await expect(client.transcribeAudio(file)).rejects.toMatchObject({
      status: 0,
      body: expectedBody,
      path: '/api/transcribe/audio',
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('throws APIError on SSE generators pre-sync — generator rejects before fetch', async () => {
    const client = new APIClient();
    const gen = client.chat({ conversation_id: 1, user_message: 'hi' });
    await expect(gen.next()).rejects.toMatchObject({
      name: 'APIError',
      body: 'remote-host-not-configured',
      path: '/api/llm/chat',
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('loadModelsStream fires onError + NEVER constructs a WebSocket + returns a no-op cleanup', () => {
    const wsConstructor = vi.fn();
    vi.stubGlobal('WebSocket', wsConstructor);
    try {
      const client = new APIClient();
      const onError = vi.fn();
      const cleanup = client.loadModelsStream({ onError });
      expect(onError).toHaveBeenCalledWith('remote-host-not-configured');
      expect(wsConstructor).not.toHaveBeenCalled();
      // Cleanup must be callable without error even though no WS opened.
      expect(() => cleanup()).not.toThrow();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('throws on REST call after sync when baseUrl is blank-remote (http://:9786)', async () => {
    (window as any).electronAPI = {
      config: {
        get: vi.fn(async (key: string) => {
          const seed: Record<string, unknown> = {
            'connection.useRemote': true,
            'connection.remoteProfile': 'tailscale',
            'connection.remoteHost': '',
          };
          return seed[key];
        }),
        set: vi.fn(),
      },
    };
    const client = new APIClient();
    await client.syncFromConfig();
    await expect(client.getAdminStatus()).rejects.toMatchObject({
      body: 'remote-host-not-configured',
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('gates correctly on a good→blank sync transition: previously configured, then re-synced blank', async () => {
    // Seed 1: configured local mode, then sync again with blank-remote — synced
    // stays true but hostname-check rejects. Ensures both predicate clauses
    // (synced AND hostname) matter, not just `synced`.
    let phase: 'local' | 'blank' = 'local';
    (window as any).electronAPI = {
      config: {
        get: vi.fn(async (key: string) => {
          const local: Record<string, unknown> = { 'connection.useRemote': false };
          const blank: Record<string, unknown> = {
            'connection.useRemote': true,
            'connection.remoteProfile': 'tailscale',
            'connection.remoteHost': '',
          };
          return (phase === 'local' ? local : blank)[key];
        }),
        set: vi.fn(),
      },
    };
    const client = new APIClient();
    await client.syncFromConfig();
    expect(client.isBaseUrlConfigured()).toBe(true);
    phase = 'blank';
    await client.syncFromConfig();
    expect(client.isBaseUrlConfigured()).toBe(false);
    await expect(client.getAdminStatus()).rejects.toMatchObject({
      body: 'remote-host-not-configured',
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('allows REST calls after sync when baseUrl is configured', async () => {
    (window as any).electronAPI = {
      config: {
        get: vi.fn(async (key: string) => {
          const seed: Record<string, unknown> = {
            'connection.useRemote': false,
          };
          return seed[key];
        }),
        set: vi.fn(),
      },
    };
    fetchSpy.mockResolvedValue({
      ok: true,
      json: async () => ({ ready: true }),
    });
    const client = new APIClient();
    await client.syncFromConfig();
    await client.getAdminStatus();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/admin\/status$/),
      expect.any(Object),
    );
  });
});

describe('APIClient.getAudioUrl / getExportUrl — return null when not configured', () => {
  beforeEach(() => {
    delete (window as any).electronAPI;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete (window as any).electronAPI;
  });

  it('getAudioUrl returns null on a pre-sync client', () => {
    const client = new APIClient();
    expect(client.getAudioUrl(42)).toBeNull();
  });

  it('getExportUrl returns null on a pre-sync client', () => {
    const client = new APIClient();
    expect(client.getExportUrl(42, 'txt')).toBeNull();
  });

  it('getAudioUrl returns null after sync when baseUrl is blank-remote', async () => {
    (window as any).electronAPI = {
      config: {
        get: vi.fn(async (key: string) => {
          const seed: Record<string, unknown> = {
            'connection.useRemote': true,
            'connection.remoteProfile': 'tailscale',
            'connection.remoteHost': '',
          };
          return seed[key];
        }),
        set: vi.fn(),
      },
    };
    const client = new APIClient();
    await client.syncFromConfig();
    expect(client.getAudioUrl(42)).toBeNull();
    expect(client.getExportUrl(42, 'srt')).toBeNull();
  });

  it('getAudioUrl returns a string URL after sync with a configured host', async () => {
    (window as any).electronAPI = {
      config: {
        get: vi.fn(async (key: string) => {
          const seed: Record<string, unknown> = {
            'connection.useRemote': false,
          };
          return seed[key];
        }),
        set: vi.fn(),
      },
    };
    const client = new APIClient();
    await client.syncFromConfig();
    const url = client.getAudioUrl(42);
    expect(url).not.toBeNull();
    expect(url).toMatch(/\/api\/notebook\/recordings\/42\/audio/);
  });
});

// Install-gate hardening: syncFromConfig is now throw-safe (catches IPC
// rejection internally) and emits config-changed on BOTH success and
// failure paths so socket-rearm subscribers can re-check predicate state.
describe('APIClient.syncFromConfig — throw-safety + config-changed event', () => {
  beforeEach(() => {
    delete (window as any).electronAPI;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete (window as any).electronAPI;
  });

  it('does not throw when getServerBaseUrl rejects; leaves synced=false; logs warning', async () => {
    (window as any).electronAPI = {
      config: {
        get: vi.fn(async () => {
          throw new Error('preload bridge rejected');
        }),
        set: vi.fn(),
      },
    };
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const client = new APIClient();

    await expect(client.syncFromConfig()).resolves.toBeUndefined();

    expect(client.isBaseUrlConfigured()).toBe(false);
    expect(warnSpy).toHaveBeenCalledWith(
      '[APIClient] syncFromConfig failed:',
      expect.stringContaining('preload bridge rejected'),
    );
  });

  it('fires config-changed listeners exactly once per syncFromConfig success', async () => {
    (window as any).electronAPI = {
      config: {
        get: vi.fn(async (key: string) => {
          const seed: Record<string, unknown> = { 'connection.useRemote': false };
          return seed[key];
        }),
        set: vi.fn(),
      },
    };
    const client = new APIClient();
    const listener = vi.fn();
    client.onConfigChanged(listener);

    await client.syncFromConfig();

    expect(listener).toHaveBeenCalledTimes(1);
    expect(client.isBaseUrlConfigured()).toBe(true);
  });

  it('fires config-changed listeners exactly once even when the sync THROWS internally', async () => {
    // Critical for socket rearm: a failed sync still mutates state from
    // pre-sync (synced=false, gate closed) to post-sync-failed (synced still
    // false, gate still closed) — but more importantly, if the user retries
    // by saving Settings again, that next sync would not fire any event if
    // we only emitted on success. So emit on both paths and let subscribers
    // re-check predicate state.
    (window as any).electronAPI = {
      config: {
        get: vi.fn(async () => {
          throw new Error('IPC bridge unavailable');
        }),
        set: vi.fn(),
      },
    };
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const client = new APIClient();
    const listener = vi.fn();
    client.onConfigChanged(listener);

    await client.syncFromConfig();

    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('returns an unsubscribe function from onConfigChanged that detaches the listener', async () => {
    (window as any).electronAPI = {
      config: {
        get: vi.fn(async (key: string) => {
          const seed: Record<string, unknown> = { 'connection.useRemote': false };
          return seed[key];
        }),
        set: vi.fn(),
      },
    };
    const client = new APIClient();
    const listener = vi.fn();
    const unsub = client.onConfigChanged(listener);

    await client.syncFromConfig();
    expect(listener).toHaveBeenCalledTimes(1);

    unsub();
    await client.syncFromConfig();
    expect(listener).toHaveBeenCalledTimes(1); // not called again
  });

  it('a throwing listener does not break sibling listeners or the sync flow', async () => {
    (window as any).electronAPI = {
      config: {
        get: vi.fn(async (key: string) => {
          const seed: Record<string, unknown> = { 'connection.useRemote': false };
          return seed[key];
        }),
        set: vi.fn(),
      },
    };
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const client = new APIClient();
    const goodListener = vi.fn();
    client.onConfigChanged(() => {
      throw new Error('listener exploded');
    });
    client.onConfigChanged(goodListener);

    await expect(client.syncFromConfig()).resolves.toBeUndefined();

    expect(goodListener).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalledWith(
      '[APIClient] config-changed listener threw:',
      expect.stringContaining('listener exploded'),
    );
  });
});

// Bootstrap diagnostic: initApiClient logs a single warning when the
// post-sync gate predicate is false. Covers (a) useRemote=true + persisted
// blank host AND (b) sync threw internally.
describe('initApiClient — bootstrap diagnostic for unconfigured gate', () => {
  beforeEach(() => {
    delete (window as any).electronAPI;
    // Reset singleton state polluted by earlier test blocks. initApiClient
    // operates on the module-level apiClient whose `synced` flag carries over
    // between tests; without this the IPC-throw branch of this suite is
    // shadowed by a prior successful sync.
    (apiClient as any).synced = false;
    (apiClient as any).baseUrl = 'http://localhost:9786';
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete (window as any).electronAPI;
  });

  it('logs the bootstrap diagnostic when post-sync isBaseUrlConfigured is false (blank-remote persisted)', async () => {
    (window as any).electronAPI = {
      config: {
        get: vi.fn(async (key: string) => {
          const seed: Record<string, unknown> = {
            'connection.useRemote': true,
            'connection.remoteProfile': 'tailscale',
            'connection.remoteHost': '',
          };
          return seed[key];
        }),
        set: vi.fn(),
      },
    };
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    await initApiClient();

    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining('[APIClient] bootstrap: remote host not configured'),
    );
  });

  it('does NOT log the bootstrap diagnostic in healthy local mode', async () => {
    (window as any).electronAPI = {
      config: {
        get: vi.fn(async (key: string) => {
          const seed: Record<string, unknown> = { 'connection.useRemote': false };
          return seed[key];
        }),
        set: vi.fn(),
      },
    };
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    await initApiClient();

    const bootstrapWarnings = warnSpy.mock.calls.filter(
      (call) => typeof call[0] === 'string' && call[0].includes('[APIClient] bootstrap:'),
    );
    expect(bootstrapWarnings).toHaveLength(0);
  });

  it('logs the bootstrap diagnostic when syncFromConfig threw internally', async () => {
    (window as any).electronAPI = {
      config: {
        get: vi.fn(async () => {
          throw new Error('IPC unavailable at startup');
        }),
        set: vi.fn(),
      },
    };
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    await initApiClient();

    // Two warnings expected: the syncFromConfig failure log AND the bootstrap
    // diagnostic. The diagnostic must fire even on the IPC-throw branch.
    const bootstrapWarnings = warnSpy.mock.calls.filter(
      (call) => typeof call[0] === 'string' && call[0].includes('[APIClient] bootstrap:'),
    );
    expect(bootstrapWarnings).toHaveLength(1);
  });
});
