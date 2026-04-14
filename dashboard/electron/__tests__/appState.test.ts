// @vitest-environment node

/**
 * appState — isAppIdle() predicate + InstallGate orchestrator tests.
 *
 * Drives each I/O matrix row from
 *   _bmad-output/implementation-artifacts/spec-in-app-update-m3-safety-gate.md
 * via stubbed `fetch` responses and a fake electron-store.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type Store from 'electron-store';

import {
  createAppState,
  getServerUrl,
  InstallGate,
  isServerUrlConfigured,
  type IdleResult,
} from '../appState.js';

// ─── Fake electron-store ────────────────────────────────────────────────

type AnyStore = Store<any>;

function makeStore(overrides: Record<string, unknown> = {}): AnyStore {
  const defaults: Record<string, unknown> = {
    'connection.useRemote': false,
    'connection.remoteProfile': 'tailscale',
    'connection.remoteHost': '',
    'connection.lanHost': '',
    'connection.localHost': 'localhost',
    'connection.port': 9786,
    'connection.useHttps': false,
    'connection.authToken': '',
    'server.host': 'localhost',
    'server.port': 9786,
    'server.https': false,
  };
  const data = { ...defaults, ...overrides };
  return {
    get: vi.fn((key: string) => data[key]),
  } as unknown as AnyStore;
}

function makeResponse(body: unknown, init: { ok?: boolean; status?: number } = {}): Response {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: async () => body,
  } as unknown as Response;
}

// ─── isAppIdle ──────────────────────────────────────────────────────────

describe('isAppIdle', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns {idle:true} when job_tracker.is_busy is false', async () => {
    fetchMock.mockResolvedValueOnce(
      makeResponse({ models: { job_tracker: { is_busy: false, active_user: null } } }),
    );
    const { isAppIdle } = createAppState(makeStore());
    const result = await isAppIdle();
    expect(result).toEqual({ idle: true });
  });

  it('returns busy with active_user suffix when is_busy is true', async () => {
    fetchMock.mockResolvedValueOnce(
      makeResponse({
        models: { job_tracker: { is_busy: true, active_user: 'test-client' } },
      }),
    );
    const { isAppIdle } = createAppState(makeStore());
    const result = await isAppIdle();
    expect(result).toEqual({
      idle: false,
      reason: 'active transcription (test-client)',
    });
  });

  it('returns busy without suffix when active_user is null', async () => {
    fetchMock.mockResolvedValueOnce(
      makeResponse({ models: { job_tracker: { is_busy: true, active_user: null } } }),
    );
    const { isAppIdle } = createAppState(makeStore());
    const result = await isAppIdle();
    expect(result).toEqual({ idle: false, reason: 'active transcription' });
  });

  it('returns server-unreachable when HTTP status is not ok', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({}, { ok: false, status: 503 }));
    const { isAppIdle } = createAppState(makeStore());
    const result = await isAppIdle();
    expect(result).toEqual({ idle: false, reason: 'server-unreachable' });
  });

  it('returns auth-error when HTTP status is 401', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({}, { ok: false, status: 401 }));
    const { isAppIdle } = createAppState(makeStore());
    const result = await isAppIdle();
    expect(result).toEqual({ idle: false, reason: 'auth-error' });
  });

  it('returns auth-error when HTTP status is 403', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({}, { ok: false, status: 403 }));
    const { isAppIdle } = createAppState(makeStore());
    const result = await isAppIdle();
    expect(result).toEqual({ idle: false, reason: 'auth-error' });
  });

  it('returns server-unreachable when fetch throws (network error)', async () => {
    fetchMock.mockRejectedValueOnce(new Error('ECONNREFUSED'));
    const { isAppIdle } = createAppState(makeStore());
    const result = await isAppIdle();
    expect(result).toEqual({ idle: false, reason: 'server-unreachable' });
  });

  it('returns server-unreachable when AbortSignal.timeout fires', async () => {
    fetchMock.mockRejectedValueOnce(Object.assign(new Error('timeout'), { name: 'TimeoutError' }));
    const { isAppIdle } = createAppState(makeStore());
    const result = await isAppIdle(50);
    expect(result).toEqual({ idle: false, reason: 'server-unreachable' });
  });

  it('returns {idle:false, reason:"unknown"} when job_tracker is missing', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({ models: {} }));
    const { isAppIdle } = createAppState(makeStore());
    const result = await isAppIdle();
    expect(result).toEqual({ idle: false, reason: 'unknown' });
  });

  it('returns unknown when is_busy is not a boolean', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({ models: { job_tracker: { is_busy: 'yes' } } }));
    const { isAppIdle } = createAppState(makeStore());
    const result = await isAppIdle();
    expect(result).toEqual({ idle: false, reason: 'unknown' });
  });

  it('sends Authorization header when connection.authToken is set', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({ models: { job_tracker: { is_busy: false } } }));
    const store = makeStore({ 'connection.authToken': 'sekrit' });
    const { isAppIdle } = createAppState(store);
    await isAppIdle();
    const callArgs = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = callArgs.headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer sekrit');
  });

  it('omits Authorization header when no token is stored', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({ models: { job_tracker: { is_busy: false } } }));
    const { isAppIdle } = createAppState(makeStore());
    await isAppIdle();
    const callArgs = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = callArgs.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it('builds the URL from connection.* keys when useRemote is false', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({ models: { job_tracker: { is_busy: false } } }));
    const store = makeStore({
      'connection.localHost': '10.0.0.5',
      'connection.port': 8080,
      'connection.useHttps': true,
    });
    const { isAppIdle } = createAppState(store);
    await isAppIdle();
    expect(fetchMock.mock.calls[0][0]).toBe('https://10.0.0.5:8080/api/admin/status');
  });

  it('picks remoteHost when useRemote=true and remoteProfile=tailscale', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({ models: { job_tracker: { is_busy: false } } }));
    const store = makeStore({
      'connection.useRemote': true,
      'connection.remoteProfile': 'tailscale',
      'connection.remoteHost': 'tailnet-host',
    });
    const { isAppIdle } = createAppState(store);
    await isAppIdle();
    expect(fetchMock.mock.calls[0][0]).toBe('http://tailnet-host:9786/api/admin/status');
  });

  it('picks lanHost when useRemote=true and remoteProfile=lan', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({ models: { job_tracker: { is_busy: false } } }));
    const store = makeStore({
      'connection.useRemote': true,
      'connection.remoteProfile': 'lan',
      'connection.lanHost': '192.168.1.42',
    });
    const { isAppIdle } = createAppState(store);
    await isAppIdle();
    expect(fetchMock.mock.calls[0][0]).toBe('http://192.168.1.42:9786/api/admin/status');
  });
});

// ─── isServerUrlConfigured ──────────────────────────────────────────────

describe('isServerUrlConfigured', () => {
  it('returns true for local mode regardless of blank remote fields', () => {
    expect(
      isServerUrlConfigured(
        makeStore({
          'connection.useRemote': false,
          'connection.remoteHost': '',
          'connection.lanHost': '',
        }),
      ),
    ).toBe(true);
  });

  it('returns false for Tailscale remote with blank remoteHost', () => {
    expect(
      isServerUrlConfigured(
        makeStore({
          'connection.useRemote': true,
          'connection.remoteProfile': 'tailscale',
          'connection.remoteHost': '',
        }),
      ),
    ).toBe(false);
  });

  it('returns false for LAN remote with blank lanHost', () => {
    expect(
      isServerUrlConfigured(
        makeStore({
          'connection.useRemote': true,
          'connection.remoteProfile': 'lan',
          'connection.lanHost': '',
        }),
      ),
    ).toBe(false);
  });

  it('treats whitespace-only host as blank (trim-aware)', () => {
    expect(
      isServerUrlConfigured(
        makeStore({
          'connection.useRemote': true,
          'connection.remoteProfile': 'tailscale',
          'connection.remoteHost': '   ',
        }),
      ),
    ).toBe(false);
  });

  it('returns true for configured Tailscale remote', () => {
    expect(
      isServerUrlConfigured(
        makeStore({
          'connection.useRemote': true,
          'connection.remoteProfile': 'tailscale',
          'connection.remoteHost': 'host.ts.net',
        }),
      ),
    ).toBe(true);
  });

  it('returns true for configured LAN remote', () => {
    expect(
      isServerUrlConfigured(
        makeStore({
          'connection.useRemote': true,
          'connection.remoteProfile': 'lan',
          'connection.lanHost': '192.168.1.42',
        }),
      ),
    ).toBe(true);
  });
});

// ─── getServerUrl — no-localhost-coercion regression lock ──────────────

describe('getServerUrl — blank-remote non-coercion', () => {
  it('does NOT coerce blank Tailscale remote to localhost', () => {
    // Locks the invariant: removing the `|| 'localhost'` fallback is the
    // entire point of the predicate-first design. If a future refactor
    // reintroduces the fallback, this test catches it before the deadlock
    // defect it enables can re-ship.
    const url = getServerUrl(
      makeStore({
        'connection.useRemote': true,
        'connection.remoteProfile': 'tailscale',
        'connection.remoteHost': '',
      }),
    );
    expect(url).not.toContain('localhost');
    expect(url).toBe('http://:9786');
  });

  it('does NOT coerce blank LAN remote to localhost', () => {
    const url = getServerUrl(
      makeStore({
        'connection.useRemote': true,
        'connection.remoteProfile': 'lan',
        'connection.lanHost': '',
      }),
    );
    expect(url).not.toContain('localhost');
    expect(url).toBe('http://:9786');
  });
});

// ─── isAppIdle short-circuit on misconfigured remote ────────────────────

describe('isAppIdle — remote-host-not-configured short-circuit', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns remote-host-not-configured without invoking fetch (Tailscale blank)', async () => {
    const { isAppIdle } = createAppState(
      makeStore({
        'connection.useRemote': true,
        'connection.remoteProfile': 'tailscale',
        'connection.remoteHost': '',
      }),
    );
    const result = await isAppIdle();
    expect(result).toEqual({ idle: false, reason: 'remote-host-not-configured' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('returns remote-host-not-configured without invoking fetch (LAN blank)', async () => {
    const { isAppIdle } = createAppState(
      makeStore({
        'connection.useRemote': true,
        'connection.remoteProfile': 'lan',
        'connection.lanHost': '',
      }),
    );
    const result = await isAppIdle();
    expect(result).toEqual({ idle: false, reason: 'remote-host-not-configured' });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ─── InstallGate ────────────────────────────────────────────────────────

describe('InstallGate', () => {
  const IDLE: IdleResult = { idle: true };
  const BUSY: IdleResult = { idle: false, reason: 'active transcription (tester)' };

  let idleCheck: ReturnType<typeof vi.fn<() => Promise<IdleResult>>>;
  let onReady: ReturnType<typeof vi.fn<() => void>>;
  let doInstall: ReturnType<typeof vi.fn<() => Promise<{ ok: boolean; reason?: string }>>>;

  beforeEach(() => {
    idleCheck = vi.fn<() => Promise<IdleResult>>();
    onReady = vi.fn<() => void>();
    doInstall = vi.fn<() => Promise<{ ok: boolean; reason?: string }>>();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('calls doInstall immediately when idle', async () => {
    idleCheck.mockResolvedValue(IDLE);
    doInstall.mockResolvedValue({ ok: true });
    const gate = new InstallGate({ idleCheck, onReady, doInstall, pollMs: 30_000 });

    const result = await gate.requestInstall();

    expect(doInstall).toHaveBeenCalledTimes(1);
    expect(result).toEqual({ ok: true });
    expect(gate.isPending()).toBe(false);
  });

  it('defers when busy and returns deferred-until-idle with reason detail', async () => {
    idleCheck.mockResolvedValue(BUSY);
    const gate = new InstallGate({ idleCheck, onReady, doInstall, pollMs: 30_000 });

    const result = await gate.requestInstall();

    expect(doInstall).not.toHaveBeenCalled();
    expect(result).toEqual({
      ok: false,
      reason: 'deferred-until-idle',
      detail: 'active transcription (tester)',
    });
    expect(gate.isPending()).toBe(true);

    gate.destroy();
  });

  it('propagates remote-host-not-configured as detail on deferred-until-idle', async () => {
    // Verifies the new diagnostic reason surfaces through the same
    // channel the renderer already consumes — no new IPC shape required.
    idleCheck.mockResolvedValue({
      idle: false,
      reason: 'remote-host-not-configured',
    });
    const gate = new InstallGate({ idleCheck, onReady, doInstall, pollMs: 30_000 });

    const result = await gate.requestInstall();

    expect(doInstall).not.toHaveBeenCalled();
    expect(result).toEqual({
      ok: false,
      reason: 'deferred-until-idle',
      detail: 'remote-host-not-configured',
    });
    expect(gate.isPending()).toBe(true);

    gate.destroy();
  });

  it('returns already-deferred on a second request while pending', async () => {
    idleCheck.mockResolvedValue(BUSY);
    const gate = new InstallGate({ idleCheck, onReady, doInstall, pollMs: 30_000 });

    await gate.requestInstall();
    const second = await gate.requestInstall();

    expect(second).toEqual({ ok: false, reason: 'already-deferred' });
    // idleCheck called only once — no fresh check for the re-request.
    expect(idleCheck).toHaveBeenCalledTimes(1);
    gate.destroy();
  });

  it('serializes concurrent requestInstall calls — second returns already-deferred during the first idleCheck await', async () => {
    // Without serialization, two concurrent callers both slip past the
    // this.pending null-check and orphan setInterval timers.
    let resolveFirst!: (v: IdleResult) => void;
    const firstCheck = new Promise<IdleResult>((r) => {
      resolveFirst = r;
    });
    idleCheck.mockReturnValueOnce(firstCheck).mockResolvedValue(BUSY);
    const gate = new InstallGate({ idleCheck, onReady, doInstall, pollMs: 30_000 });

    const firstCall = gate.requestInstall();
    const secondCall = gate.requestInstall();

    // Second call should resolve synchronously with already-deferred.
    expect(await secondCall).toEqual({ ok: false, reason: 'already-deferred' });
    // idleCheck must not have been invoked a second time.
    expect(idleCheck).toHaveBeenCalledTimes(1);

    resolveFirst(BUSY);
    await firstCall;
    expect(gate.isPending()).toBe(true);
    gate.destroy();
  });

  it('returns {ok:false, reason:"destroyed"} when destroy fires during the initial idleCheck', async () => {
    let resolveCheck!: (v: IdleResult) => void;
    idleCheck.mockReturnValueOnce(
      new Promise<IdleResult>((r) => {
        resolveCheck = r;
      }),
    );
    const gate = new InstallGate({ idleCheck, onReady, doInstall, pollMs: 30_000 });

    const pending = gate.requestInstall();
    gate.destroy();
    resolveCheck(BUSY);
    const result = await pending;

    expect(result).toEqual({ ok: false, reason: 'destroyed' });
    expect(gate.isPending()).toBe(false);
  });

  it('fires onReady and clears pending when the poll tick sees idle', async () => {
    idleCheck.mockResolvedValueOnce(BUSY); // initial request → defer
    const gate = new InstallGate({ idleCheck, onReady, doInstall, pollMs: 30_000 });
    await gate.requestInstall();
    expect(gate.isPending()).toBe(true);

    // Next idleCheck returns idle; advance timer past poll interval.
    idleCheck.mockResolvedValueOnce(IDLE);
    await vi.advanceTimersByTimeAsync(30_000);

    expect(onReady).toHaveBeenCalledTimes(1);
    expect(gate.isPending()).toBe(false);
  });

  it('does NOT fire onReady when the poll tick still sees busy', async () => {
    idleCheck.mockResolvedValue(BUSY);
    const gate = new InstallGate({ idleCheck, onReady, doInstall, pollMs: 30_000 });
    await gate.requestInstall();

    await vi.advanceTimersByTimeAsync(30_000);

    expect(onReady).not.toHaveBeenCalled();
    expect(gate.isPending()).toBe(true);

    gate.destroy();
  });

  it('cancelPending stops the poll and clears state', async () => {
    idleCheck.mockResolvedValue(BUSY);
    const gate = new InstallGate({ idleCheck, onReady, doInstall, pollMs: 30_000 });
    await gate.requestInstall();
    expect(gate.isPending()).toBe(true);

    const result = gate.cancelPending();

    expect(result).toEqual({ ok: true });
    expect(gate.isPending()).toBe(false);

    // Advancing the timer after cancel should NOT trigger another idleCheck.
    idleCheck.mockClear();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(idleCheck).not.toHaveBeenCalled();
  });

  it('cancelPending is idempotent when not pending', () => {
    const gate = new InstallGate({ idleCheck, onReady, doInstall });
    const result = gate.cancelPending();
    expect(result).toEqual({ ok: true });
  });

  it('destroy cancels in-flight poll and prevents onReady from firing', async () => {
    let resolveIdle!: (v: IdleResult) => void;
    const idleDuringTick = new Promise<IdleResult>((r) => {
      resolveIdle = r;
    });
    idleCheck.mockResolvedValueOnce(BUSY).mockReturnValueOnce(idleDuringTick);
    const gate = new InstallGate({ idleCheck, onReady, doInstall, pollMs: 30_000 });
    await gate.requestInstall();

    // Kick off the tick's async idleCheck.
    vi.advanceTimersByTime(30_000);

    // Destroy while the tick's idleCheck is still pending.
    gate.destroy();
    // Now resolve the in-flight idleCheck — onReady must NOT fire post-destroy.
    resolveIdle({ idle: true });
    await Promise.resolve();
    await Promise.resolve();

    expect(onReady).not.toHaveBeenCalled();
    expect(gate.isPending()).toBe(false);
  });
});
