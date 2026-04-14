import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { apiClient } from '../api/client';
import { TranscriptionSocket } from './websocket';

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
