import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { apiClient } from '../api/client';
import { logClientEvent } from './clientDebugLog';
import { TranscriptionSocket } from './websocket';

vi.mock('./clientDebugLog', () => ({
  logClientEvent: vi.fn(),
}));

// WebSocket install-gate mirror: when apiClient.isBaseUrlConfigured() is false
// (pre-sync or blank-remote baseUrl), connect() and reconnect() must
// short-circuit before `new WebSocket(...)` — fire onError with the stable
// 'remote-host-not-configured' reason and transition state to 'error'.
// Spec: _bmad-output/implementation-artifacts/spec-in-app-update-renderer-network-paths-install-gate.md

describe('TranscriptionSocket.connect — remote-host-not-configured short-circuit', () => {
  let wsCalls: string[];
  let FakeWebSocket: unknown;

  beforeEach(() => {
    // Minimal WebSocket stub: class form so `new WebSocket(url)` works.
    // Tracks construction calls in `wsCalls` and exposes the handful of
    // members TranscriptionSocket's connect/disconnect paths touch.
    wsCalls = [];
    FakeWebSocket = class {
      readyState = 0;
      binaryType = '';
      onopen: unknown = null;
      onmessage: unknown = null;
      onerror: unknown = null;
      onclose: unknown = null;
      static OPEN = 1;
      static CONNECTING = 0;
      constructor(url: string) {
        wsCalls.push(url);
      }
      send = vi.fn();
      close = vi.fn();
    };
    vi.stubGlobal('WebSocket', FakeWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('fires onError("remote-host-not-configured") and transitions to error when apiClient is not configured', () => {
    vi.spyOn(apiClient, 'isBaseUrlConfigured').mockReturnValue(false);

    const onError = vi.fn();
    const onStateChange = vi.fn();
    const socket = new TranscriptionSocket('/ws', { onError, onStateChange });

    socket.connect();

    expect(onError).toHaveBeenCalledWith('remote-host-not-configured');
    expect(socket.connectionState).toBe('error');
    expect(wsCalls).toHaveLength(0);
  });

  it('does NOT short-circuit when apiClient is configured — WebSocket is constructed', () => {
    vi.spyOn(apiClient, 'isBaseUrlConfigured').mockReturnValue(true);
    vi.spyOn(apiClient, 'getBaseUrl').mockReturnValue('http://localhost:9786');

    const onError = vi.fn();
    const socket = new TranscriptionSocket('/ws', { onError });

    socket.connect();

    expect(wsCalls).toEqual(['ws://localhost:9786/ws']);
    expect(onError).not.toHaveBeenCalledWith('remote-host-not-configured');
    socket.disconnect();
  });

  it('rewrites https:// to wss:// when apiClient reports an https base URL', () => {
    vi.spyOn(apiClient, 'isBaseUrlConfigured').mockReturnValue(true);
    vi.spyOn(apiClient, 'getBaseUrl').mockReturnValue('https://foo.ts.net:9786');

    const socket = new TranscriptionSocket('/ws/live', {});
    socket.connect();

    expect(wsCalls).toEqual(['wss://foo.ts.net:9786/ws/live']);
    socket.disconnect();
  });

  it('doReconnect short-circuits the same way when apiClient loses its configuration mid-session', async () => {
    // Simulate the reconnect path by (a) connecting successfully, then (b)
    // closing the socket (which triggers scheduleReconnect → doReconnect),
    // then (c) observing that doReconnect fires onError + sets state=error
    // + does NOT construct a second WebSocket when isBaseUrlConfigured
    // flips to false between attempts.
    const configuredSpy = vi.spyOn(apiClient, 'isBaseUrlConfigured').mockReturnValue(true);
    vi.spyOn(apiClient, 'getBaseUrl').mockReturnValue('http://localhost:9786');
    vi.useFakeTimers();
    const onError = vi.fn();
    const socket = new TranscriptionSocket(
      '/ws',
      { onError },
      { initialDelayMs: 10, maxDelayMs: 10, backoffMultiplier: 1, enabled: true, maxAttempts: 5 },
    );
    try {
      socket.connect();
      expect(wsCalls).toHaveLength(1);
      // Flip configured to false, simulate onclose to drive doReconnect path.
      configuredSpy.mockReturnValue(false);
      // Access the internal socket instance's onclose to trigger reconnect logic.
      const wsInstance = (socket as unknown as { ws: { onclose: (ev: CloseEvent) => void } }).ws;
      wsInstance.onclose({ code: 1006, reason: 'network drop' } as CloseEvent);
      // Advance past the reconnect delay.
      await vi.advanceTimersByTimeAsync(20);
      expect(onError).toHaveBeenCalledWith('remote-host-not-configured');
      expect(socket.connectionState).toBe('error');
      // Exactly one WebSocket constructed — the one from the initial connect.
      // doReconnect short-circuited before constructing a second.
      expect(wsCalls).toHaveLength(1);
    } finally {
      vi.useRealTimers();
      socket.disconnect();
    }
  });
});

// TranscriptionSocket.handleConfigChanged — branches for apiClient.onConfigChanged events.
// Spec: _bmad-output/implementation-artifacts/spec-config-changed-rearm-hardening.md
describe('TranscriptionSocket.handleConfigChanged', () => {
  let wsCalls: string[];
  let FakeWebSocket: unknown;

  beforeEach(() => {
    wsCalls = [];
    FakeWebSocket = class {
      readyState = 0;
      binaryType = '';
      onopen: unknown = null;
      onmessage: unknown = null;
      onerror: unknown = null;
      onclose: unknown = null;
      static OPEN = 1;
      static CONNECTING = 0;
      constructor(url: string) {
        wsCalls.push(url);
      }
      send = vi.fn();
      close = vi.fn();
    };
    vi.stubGlobal('WebSocket', FakeWebSocket);
    vi.mocked(logClientEvent).mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('error + configured → calls connect() (existing rearm, regression guard)', () => {
    vi.spyOn(apiClient, 'isBaseUrlConfigured').mockReturnValue(true);
    vi.spyOn(apiClient, 'getBaseUrl').mockReturnValue('http://localhost:9786');

    const socket = new TranscriptionSocket('/ws', {});
    // Force an error state without going through a failed connect (keeps intentionalDisconnect=false).
    (socket as unknown as { state: string }).state = 'error';

    socket.handleConfigChanged(true);

    expect(wsCalls).toEqual(['ws://localhost:9786/ws']);
    socket.disconnect();
  });

  it('error + gate closed → no connect() (double-gate holds)', () => {
    vi.spyOn(apiClient, 'isBaseUrlConfigured').mockReturnValue(false);

    const socket = new TranscriptionSocket('/ws', {});
    (socket as unknown as { state: string }).state = 'error';

    socket.handleConfigChanged(false);

    expect(wsCalls).toHaveLength(0);
  });

  it('disconnected + pending reconnect timer + configured → cancels timer, fires doReconnect now (EC-3)', async () => {
    // Set up an initial connect so onclose drives scheduleReconnect,
    // then emit onclose, then emit config-changed BEFORE the backoff fires.
    vi.useFakeTimers();
    const configuredSpy = vi.spyOn(apiClient, 'isBaseUrlConfigured').mockReturnValue(true);
    vi.spyOn(apiClient, 'getBaseUrl').mockReturnValue('http://old-host:9786');

    const socket = new TranscriptionSocket(
      '/ws',
      {},
      {
        initialDelayMs: 30_000,
        maxDelayMs: 30_000,
        backoffMultiplier: 1,
        enabled: true,
        maxAttempts: 5,
      },
    );
    try {
      socket.connect();
      expect(wsCalls).toEqual(['ws://old-host:9786/ws']);

      // Simulate onclose → schedules a 30s reconnect timer.
      const wsInstance = (socket as unknown as { ws: { onclose: (ev: CloseEvent) => void } }).ws;
      wsInstance.onclose({ code: 1006, reason: 'network drop' } as CloseEvent);

      // State is now 'disconnected' with reconnectTimer armed.
      expect(socket.connectionState).toBe('disconnected');

      // Flip to new host (what Settings save would do), emit config-changed.
      vi.mocked(apiClient.getBaseUrl).mockReturnValue('http://new-host:9786');
      configuredSpy.mockReturnValue(true);

      socket.handleConfigChanged(true);

      // Second WebSocket constructed immediately against NEW host — no wait for backoff.
      expect(wsCalls).toEqual(['ws://old-host:9786/ws', 'ws://new-host:9786/ws']);

      // Advance past the original 30s backoff: the old timer must have been cancelled,
      // so NO third WebSocket is constructed.
      await vi.advanceTimersByTimeAsync(35_000);
      expect(wsCalls).toHaveLength(2);
    } finally {
      vi.useRealTimers();
      socket.disconnect();
    }
  });

  it('disconnected + pending timer + gate closed → no-op (backoff left running)', async () => {
    vi.useFakeTimers();
    const configuredSpy = vi.spyOn(apiClient, 'isBaseUrlConfigured').mockReturnValue(true);
    vi.spyOn(apiClient, 'getBaseUrl').mockReturnValue('http://localhost:9786');

    const socket = new TranscriptionSocket(
      '/ws',
      {},
      {
        initialDelayMs: 30_000,
        maxDelayMs: 30_000,
        backoffMultiplier: 1,
        enabled: true,
        maxAttempts: 5,
      },
    );
    try {
      socket.connect();
      const wsInstance = (socket as unknown as { ws: { onclose: (ev: CloseEvent) => void } }).ws;
      wsInstance.onclose({ code: 1006, reason: 'drop' } as CloseEvent);

      // Gate flips closed as part of the sync that just fired — exactly what
      // would happen when the hook forwards `configured=false`.
      configuredSpy.mockReturnValue(false);
      socket.handleConfigChanged(false);

      // No immediate second WebSocket — the pending backoff timer is not cancelled.
      expect(wsCalls).toHaveLength(1);

      // Advance past the backoff: doReconnect fires but short-circuits on the
      // gate-closed check in getWsUrl, so still no second WebSocket.
      await vi.advanceTimersByTimeAsync(35_000);
      expect(wsCalls).toHaveLength(1);
    } finally {
      vi.useRealTimers();
      socket.disconnect();
    }
  });

  it('active session with URL mismatch → emits a single warning breadcrumb naming both URLs (EC-2)', () => {
    vi.spyOn(apiClient, 'isBaseUrlConfigured').mockReturnValue(true);
    vi.spyOn(apiClient, 'getBaseUrl').mockReturnValue('http://old-host:9786');

    const socket = new TranscriptionSocket('/ws', {});
    socket.connect();
    // Promote to an active state without driving the full handshake.
    (socket as unknown as { state: string }).state = 'ready';

    vi.mocked(logClientEvent).mockClear();
    vi.mocked(apiClient.getBaseUrl).mockReturnValue('http://new-host:9786');

    socket.handleConfigChanged(true);

    const warnCalls = vi.mocked(logClientEvent).mock.calls.filter((c) => c[2] === 'warning');
    expect(warnCalls).toHaveLength(1);
    expect(warnCalls[0][1]).toContain('ws://old-host:9786/ws');
    expect(warnCalls[0][1]).toContain('ws://new-host:9786/ws');

    // Live socket is untouched — no second WebSocket.
    expect(wsCalls).toHaveLength(1);

    socket.disconnect();
  });

  it('active session with URL mismatch → invokes onHostMismatch with old + new URLs (EC-6 drain+retarget)', () => {
    vi.spyOn(apiClient, 'isBaseUrlConfigured').mockReturnValue(true);
    vi.spyOn(apiClient, 'getBaseUrl').mockReturnValue('http://old-host:9786');

    const onHostMismatch = vi.fn();
    const socket = new TranscriptionSocket('/ws', { onHostMismatch });
    socket.connect();
    (socket as unknown as { state: string }).state = 'ready';

    vi.mocked(apiClient.getBaseUrl).mockReturnValue('http://new-host:9786');

    socket.handleConfigChanged(true);

    expect(onHostMismatch).toHaveBeenCalledTimes(1);
    expect(onHostMismatch).toHaveBeenCalledWith('ws://old-host:9786/ws', 'ws://new-host:9786/ws');

    socket.disconnect();
  });

  it('onHostMismatch throwing does not prevent the warning log or crash the dispatch', () => {
    vi.spyOn(apiClient, 'isBaseUrlConfigured').mockReturnValue(true);
    vi.spyOn(apiClient, 'getBaseUrl').mockReturnValue('http://old-host:9786');

    const onHostMismatch = vi.fn(() => {
      throw new Error('consumer bug');
    });
    const socket = new TranscriptionSocket('/ws', { onHostMismatch });
    socket.connect();
    (socket as unknown as { state: string }).state = 'ready';

    vi.mocked(logClientEvent).mockClear();
    vi.mocked(apiClient.getBaseUrl).mockReturnValue('http://new-host:9786');

    expect(() => socket.handleConfigChanged(true)).not.toThrow();

    // One warning breadcrumb + one error breadcrumb for the throwing callback.
    const warnCalls = vi.mocked(logClientEvent).mock.calls.filter((c) => c[2] === 'warning');
    const errorCalls = vi
      .mocked(logClientEvent)
      .mock.calls.filter((c) => c[2] === 'error' && String(c[1]).includes('onHostMismatch'));
    expect(warnCalls).toHaveLength(1);
    expect(errorCalls).toHaveLength(1);

    socket.disconnect();
  });

  it('active session with URL match → silent no-op', () => {
    vi.spyOn(apiClient, 'isBaseUrlConfigured').mockReturnValue(true);
    vi.spyOn(apiClient, 'getBaseUrl').mockReturnValue('http://localhost:9786');

    const socket = new TranscriptionSocket('/ws', {});
    socket.connect();
    (socket as unknown as { state: string }).state = 'ready';

    vi.mocked(logClientEvent).mockClear();

    socket.handleConfigChanged(true);

    const warnCalls = vi.mocked(logClientEvent).mock.calls.filter((c) => c[2] === 'warning');
    expect(warnCalls).toHaveLength(0);
    expect(wsCalls).toHaveLength(1);

    socket.disconnect();
  });

  it('intentionalDisconnect suppresses all branches', () => {
    vi.spyOn(apiClient, 'isBaseUrlConfigured').mockReturnValue(true);
    vi.spyOn(apiClient, 'getBaseUrl').mockReturnValue('http://localhost:9786');

    const socket = new TranscriptionSocket('/ws', {});
    socket.connect();
    socket.disconnect(); // flips intentionalDisconnect=true and state=disconnected

    // Force the scenarios that would otherwise fire branches.
    (socket as unknown as { state: string }).state = 'error';
    vi.mocked(logClientEvent).mockClear();
    const callsBefore = wsCalls.length;

    socket.handleConfigChanged(true);

    expect(wsCalls).toHaveLength(callsBefore);
    const warnCalls = vi.mocked(logClientEvent).mock.calls.filter((c) => c[2] === 'warning');
    expect(warnCalls).toHaveLength(0);
  });

  it('idle socket never connected → silent no-op', () => {
    vi.spyOn(apiClient, 'isBaseUrlConfigured').mockReturnValue(true);
    vi.spyOn(apiClient, 'getBaseUrl').mockReturnValue('http://localhost:9786');

    const socket = new TranscriptionSocket('/ws', {});
    // Fresh socket: state=disconnected, reconnectTimer=null, connectedUrl=null.

    vi.mocked(logClientEvent).mockClear();

    socket.handleConfigChanged(true);

    expect(wsCalls).toHaveLength(0);
    const warnCalls = vi.mocked(logClientEvent).mock.calls.filter((c) => c[2] === 'warning');
    expect(warnCalls).toHaveLength(0);
  });
});
