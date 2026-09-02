import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';

import { useLiveMode } from './useLiveMode';
import { apiClient } from '../api/client';

// ── Mocks ──────────────────────────────────────────────────────────────

// Capture the latest TranscriptionSocket instance so tests can simulate
// server messages by calling lastSocketCbs.onMessage!({...}).
let lastSocket: {
  connect: Mock;
  disconnect: Mock;
  sendJSON: Mock;
  sendAudio: Mock;
  setAudioSampleRate: Mock;
  getState: Mock;
  handleConfigChanged: Mock;
};
let lastSocketCbs: {
  onMessage?: (msg: { type: string; data?: Record<string, unknown> }) => void;
  onError?: (err: string) => void;
  onClose?: (code: number, reason: string) => void;
  onHostMismatch?: (oldUrl: string, newUrl: string) => void;
};

vi.mock('../services/websocket', () => ({
  TranscriptionSocket: vi.fn().mockImplementation(function (_ep: string, cbs: any) {
    lastSocketCbs = cbs;
    lastSocket = {
      connect: vi.fn(),
      disconnect: vi.fn(),
      sendJSON: vi.fn(),
      sendAudio: vi.fn(),
      setAudioSampleRate: vi.fn(),
      getState: vi.fn().mockReturnValue('disconnected'),
      handleConfigChanged: vi.fn(),
    };
    return lastSocket;
  }),
}));

let lastCapture: {
  start: Mock;
  stop: Mock;
  mute: Mock;
  unmute: Mock;
  setGain: Mock;
  analyser: null;
  isCapturing: boolean;
};

vi.mock('../services/audioCapture', () => ({
  AudioCapture: vi.fn().mockImplementation(function () {
    lastCapture = {
      start: vi.fn().mockResolvedValue(undefined),
      stop: vi.fn(),
      mute: vi.fn(),
      unmute: vi.fn(),
      setGain: vi.fn(),
      analyser: null,
      isCapturing: false,
    };
    return lastCapture;
  }),
}));

// ── Helpers ────────────────────────────────────────────────────────────

/** Drive the hook through auth → state LISTENING → listening. */
async function driveToListening(
  result: { current: ReturnType<typeof useLiveMode> },
  // Capture gain is clamped to unity for a microphone session, so gain tests
  // have to say which source they are starting.
  options: Parameters<ReturnType<typeof useLiveMode>['start']>[0] = {},
) {
  act(() => {
    result.current.start(options);
  });
  act(() => {
    lastSocketCbs.onMessage!({ type: 'auth_ok' });
  });
  await act(async () => {
    lastSocketCbs.onMessage!({
      type: 'state',
      data: { state: 'LISTENING' },
    });
  });
}

// ── Tests ──────────────────────────────────────────────────────────────

describe('[P1] useLiveMode', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── P1-HOOK-004: State machine transitions ──────────────────────────

  describe('P1-HOOK-004: state machine transitions', () => {
    it('starts in idle state with empty sentences', () => {
      const { result } = renderHook(() => useLiveMode());

      expect(result.current.status).toBe('idle');
      expect(result.current.sentences).toEqual([]);
      expect(result.current.partial).toBe('');
      expect(result.current.error).toBeNull();
      expect(result.current.statusMessage).toBeNull();
    });

    it('transitions idle → connecting on start()', () => {
      const { result } = renderHook(() => useLiveMode());

      act(() => {
        result.current.start();
      });

      expect(result.current.status).toBe('connecting');
      expect(lastSocket.connect).toHaveBeenCalledTimes(1);
    });

    it('transitions connecting → starting on auth_ok and sends config', () => {
      const { result } = renderHook(() => useLiveMode());

      act(() => {
        result.current.start({ language: 'en', model: 'base' });
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });

      expect(result.current.status).toBe('starting');
      expect(lastSocket.sendJSON).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'start',
          data: expect.objectContaining({
            config: expect.objectContaining({
              language: 'en',
              model: 'base',
            }),
          }),
        }),
      );
    });

    it('transitions starting → listening on state LISTENING', async () => {
      const { result } = renderHook(() => useLiveMode());

      await driveToListening(result);

      expect(result.current.status).toBe('listening');
      expect(result.current.statusMessage).toBeNull();
      expect(lastCapture.start).toHaveBeenCalled();
    });

    it('transitions listening → idle on stop()', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      act(() => {
        result.current.stop();
      });

      expect(result.current.status).toBe('idle');
      expect(lastSocket.sendJSON).toHaveBeenCalledWith({ type: 'stop' });
      expect(lastSocket.disconnect).toHaveBeenCalled();
      expect(lastCapture.stop).toHaveBeenCalled();
    });

    it('transitions to error on error message', () => {
      const { result } = renderHook(() => useLiveMode());

      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onMessage!({
          type: 'error',
          data: { message: 'Engine crashed' },
        });
      });

      expect(result.current.status).toBe('error');
      expect(result.current.error).toBe('Engine crashed');
    });

    // GH-271: a terminal engine failure arrives as an out-of-band `state`
    // frame. The hook used to drop it, leaving the UI stuck in listening.
    it('transitions to error on state ERROR and tears down capture', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      act(() => {
        lastSocketCbs.onMessage!({ type: 'state', data: { state: 'ERROR' } });
      });

      expect(result.current.status).toBe('error');
      expect(result.current.error).toContain('engine reported an error');
      // An engine ERROR now arms an auto-reconnect, and the countdown is
      // reported through statusMessage so it cannot clobber the specific
      // reason held in `error`.
      expect(result.current.statusMessage).toContain('Reconnecting in');
      expect(lastCapture.stop).toHaveBeenCalled();
    });

    it('keeps the specific error message when an error frame precedes state ERROR', () => {
      const { result } = renderHook(() => useLiveMode());

      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onMessage!({
          type: 'error',
          data: { message: 'Failed to start Live Mode: CUDA out of memory' },
        });
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'state', data: { state: 'ERROR' } });
      });

      expect(result.current.status).toBe('error');
      expect(result.current.error).toBe('Failed to start Live Mode: CUDA out of memory');
    });

    it('reflects a backend-initiated recovery via state STARTING instead of staying silent', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      act(() => {
        lastSocketCbs.onMessage!({ type: 'state', data: { state: 'STARTING' } });
      });

      expect(result.current.status).toBe('starting');
      expect(result.current.statusMessage).toContain('Recovering');
    });

    it('retries instead of giving up when rejected because another session is still shutting down', () => {
      const { result } = renderHook(() => useLiveMode());

      act(() => {
        result.current.start();
      });
      act(() => {
        // Real dispatch order: TranscriptionSocket hands a server `error`
        // frame to onError FIRST and then forwards the same frame to
        // onMessage. Driving onMessage alone would hide the fact that
        // onError has already set `error` by the time the retry is armed.
        const message = 'Another Live Mode session is already active';
        lastSocketCbs.onError!(message);
        lastSocketCbs.onMessage!({ type: 'error', data: { message } });
      });

      // Retried through the reconnect budget, not treated as terminal. The
      // specific rejection stays in `error` (GH-271: the specific message
      // always wins) and the countdown rides along in statusMessage.
      expect(result.current.status).toBe('error');
      expect(result.current.error).toBe('Another Live Mode session is already active');
      expect(result.current.statusMessage).toContain('Reconnecting in');
    });

    it('keeps the pending retry visible when the server closes the socket after rejecting', () => {
      vi.useFakeTimers();
      try {
        const { result } = renderHook(() => useLiveMode());

        act(() => {
          result.current.start();
        });
        act(() => {
          const message = 'Another Live Mode session is already active';
          lastSocketCbs.onError!(message);
          lastSocketCbs.onMessage!({ type: 'error', data: { message } });
        });
        // The server closes the connection right after the rejection. That
        // close must not reset the UI to idle underneath the armed retry.
        act(() => {
          lastSocketCbs.onClose!(1000, 'session busy');
        });

        expect(result.current.status).toBe('error');
        expect(result.current.statusMessage).toContain('Reconnecting in');
      } finally {
        vi.useRealTimers();
      }
    });

    it('falls back to a terminal error once the session-busy rejection exhausts the retry budget', () => {
      // Fake timers: each retry schedules a real setTimeout via
      // scheduleReconnect, and this test fires the rejection repeatedly
      // without letting any of them run — real timers would otherwise leak
      // past this test and fire during a later one.
      vi.useFakeTimers();
      try {
        const { result } = renderHook(() => useLiveMode());

        act(() => {
          result.current.start();
        });
        // Each rejection must be allowed to run its scheduled retry before
        // the next one arrives: while a retry is still armed, further
        // rejections are deliberately ignored rather than burning an attempt
        // (the socket's own auto-reconnect can fire several in a row).
        for (let i = 0; i < 6; i++) {
          act(() => {
            const message = 'Another Live Mode session is already active';
            lastSocketCbs.onError!(message);
            lastSocketCbs.onMessage!({ type: 'error', data: { message } });
          });
          act(() => {
            vi.advanceTimersByTime(6000);
          });
        }

        expect(result.current.status).toBe('error');
        expect(result.current.error).toBe('Another Live Mode session is already active');
      } finally {
        vi.useRealTimers();
      }
    });

    it('transitions to error on socket error callback', () => {
      const { result } = renderHook(() => useLiveMode());

      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onError!('Connection failed');
      });

      expect(result.current.status).toBe('error');
      expect(result.current.error).toBe('Connection failed');
    });

    it('updates statusMessage during model loading', () => {
      const { result } = renderHook(() => useLiveMode());

      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      act(() => {
        lastSocketCbs.onMessage!({
          type: 'status',
          data: { message: 'Loading live model…' },
        });
      });

      expect(result.current.statusMessage).toBe('Loading live model…');
    });

    it('returns to idle on socket close', () => {
      const { result } = renderHook(() => useLiveMode());

      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onClose!(1000, 'Normal');
      });

      expect(result.current.status).toBe('idle');
    });
  });

  // ── P1-HOOK-005: Unmount during model swap ──────────────────────────

  describe('P1-HOOK-005: unmount during model swap', () => {
    it('disconnects socket on unmount during starting state', () => {
      const { result, unmount } = renderHook(() => useLiveMode());

      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      expect(result.current.status).toBe('starting');

      lastSocket.disconnect.mockClear();

      unmount();

      // Cleanup is unconditional in useLiveMode — always disconnects
      expect(lastSocket.disconnect).toHaveBeenCalledTimes(1);
    });

    it('stops capture and disconnects on unmount during listening', async () => {
      const { result, unmount } = renderHook(() => useLiveMode());
      await driveToListening(result);

      lastCapture.stop.mockClear();
      lastSocket.disconnect.mockClear();

      unmount();

      expect(lastCapture.stop).toHaveBeenCalledTimes(1);
      expect(lastSocket.disconnect).toHaveBeenCalledTimes(1);
    });

    it('no crash when capture is null during starting unmount', () => {
      // When status is 'starting', AudioCapture hasn't been created yet.
      // Cleanup calls captureRef.current?.stop() which is a no-op on null.
      const { result, unmount } = renderHook(() => useLiveMode());

      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });

      // Should not throw
      expect(() => unmount()).not.toThrow();
    });
  });

  // ── P1-HOOK-006: Sentence accumulation + partial buffering ──────────

  describe('P1-HOOK-006: sentence accumulation + partial buffering', () => {
    it('accumulates sentences in order', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      act(() => {
        lastSocketCbs.onMessage!({
          type: 'sentence',
          data: { text: 'First sentence.' },
        });
      });
      act(() => {
        lastSocketCbs.onMessage!({
          type: 'sentence',
          data: { text: 'Second sentence.' },
        });
      });
      act(() => {
        lastSocketCbs.onMessage!({
          type: 'sentence',
          data: { text: 'Third sentence.' },
        });
      });

      expect(result.current.sentences).toHaveLength(3);
      expect(result.current.sentences[0].text).toBe('First sentence.');
      expect(result.current.sentences[1].text).toBe('Second sentence.');
      expect(result.current.sentences[2].text).toBe('Third sentence.');
      // Each sentence has a timestamp
      expect(result.current.sentences[0].timestamp).toBeGreaterThan(0);
    });

    it('updates partial text as it arrives', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      act(() => {
        lastSocketCbs.onMessage!({
          type: 'partial',
          data: { text: 'Hel' },
        });
      });
      expect(result.current.partial).toBe('Hel');

      act(() => {
        lastSocketCbs.onMessage!({
          type: 'partial',
          data: { text: 'Hello wor' },
        });
      });
      expect(result.current.partial).toBe('Hello wor');
    });

    it('clears partial when a sentence completes', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      act(() => {
        lastSocketCbs.onMessage!({
          type: 'partial',
          data: { text: 'Hello world' },
        });
      });
      expect(result.current.partial).toBe('Hello world');

      act(() => {
        lastSocketCbs.onMessage!({
          type: 'sentence',
          data: { text: 'Hello world.' },
        });
      });
      expect(result.current.partial).toBe('');
      expect(result.current.sentences).toHaveLength(1);
      expect(result.current.sentences[0].text).toBe('Hello world.');
    });

    it('restores history from server', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      act(() => {
        lastSocketCbs.onMessage!({
          type: 'history',
          data: { sentences: ['Restored one.', 'Restored two.'] },
        });
      });

      expect(result.current.sentences).toHaveLength(2);
      expect(result.current.sentences[0].text).toBe('Restored one.');
      expect(result.current.sentences[1].text).toBe('Restored two.');
    });

    it('clearHistory empties sentences and partial', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      act(() => {
        lastSocketCbs.onMessage!({
          type: 'sentence',
          data: { text: 'Keep me.' },
        });
        lastSocketCbs.onMessage!({
          type: 'partial',
          data: { text: 'More coming' },
        });
      });

      expect(result.current.sentences).toHaveLength(1);
      expect(result.current.partial).toBe('More coming');

      act(() => {
        result.current.clearHistory();
      });

      expect(result.current.sentences).toEqual([]);
      expect(result.current.partial).toBe('');
      expect(lastSocket.sendJSON).toHaveBeenCalledWith({
        type: 'clear_history',
      });
    });

    it('getText returns concatenated sentence text', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      act(() => {
        lastSocketCbs.onMessage!({
          type: 'sentence',
          data: { text: 'Hello.' },
        });
        lastSocketCbs.onMessage!({
          type: 'sentence',
          data: { text: 'World.' },
        });
      });

      expect(result.current.getText()).toBe('Hello. World.');
    });

    it('start() clears previous sentences', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      act(() => {
        lastSocketCbs.onMessage!({
          type: 'sentence',
          data: { text: 'Old sentence.' },
        });
      });
      expect(result.current.sentences).toHaveLength(1);

      // Start a new session — sentences should reset
      act(() => {
        result.current.start();
      });

      expect(result.current.sentences).toEqual([]);
      expect(result.current.partial).toBe('');
    });
  });

  // ── Additional coverage ─────────────────────────────────────────────

  describe('supplementary', () => {
    it('toggleMute delegates to AudioCapture', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      act(() => {
        result.current.toggleMute();
      });
      expect(result.current.muted).toBe(true);
      expect(lastCapture.mute).toHaveBeenCalled();

      act(() => {
        result.current.toggleMute();
      });
      expect(result.current.muted).toBe(false);
      expect(lastCapture.unmute).toHaveBeenCalled();
    });

    it('history_cleared empties sentences via server command', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      act(() => {
        lastSocketCbs.onMessage!({
          type: 'sentence',
          data: { text: 'Existing.' },
        });
      });
      expect(result.current.sentences).toHaveLength(1);

      act(() => {
        lastSocketCbs.onMessage!({ type: 'history_cleared' });
      });

      expect(result.current.sentences).toEqual([]);
    });
  });

  // ── config-changed forwarding: the hook no longer branches on socket state
  //   itself — it just forwards `isBaseUrlConfigured()` to
  //   TranscriptionSocket.handleConfigChanged so the socket class can own the
  //   error-rearm / pending-backoff-shortcut / active-session-warn branches.
  //   Exhaustive per-branch coverage lives in src/services/websocket.test.ts.
  describe('config-changed forwarding to socket.handleConfigChanged', () => {
    beforeEach(() => {
      (window as any).electronAPI = {
        config: {
          get: vi.fn(async (key: string) => {
            const seed: Record<string, unknown> = { 'connection.useRemote': false };
            return seed[key];
          }),
          set: vi.fn(),
        },
      };
    });

    it('forwards configured=true after a successful sync', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      lastSocket.handleConfigChanged.mockClear();

      await act(async () => {
        await apiClient.syncFromConfig();
      });

      expect(lastSocket.handleConfigChanged).toHaveBeenCalledTimes(1);
      expect(lastSocket.handleConfigChanged).toHaveBeenCalledWith(true);
    });

    it('forwards configured=false when the sync threw and gate is closed', async () => {
      // Prove that the gate boolean forwarded to handleConfigChanged reflects
      // the post-sync predicate — not just "did the sync happen". IPC rejects
      // → synced stays false → hook forwards false → socket short-circuits.
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      lastSocket.handleConfigChanged.mockClear();

      (window as any).electronAPI = {
        config: {
          get: vi.fn(async () => {
            throw new Error('IPC down');
          }),
          set: vi.fn(),
        },
      };
      vi.spyOn(console, 'warn').mockImplementation(() => {});

      (apiClient as any).synced = false;

      await act(async () => {
        await apiClient.syncFromConfig();
      });

      expect(lastSocket.handleConfigChanged).toHaveBeenCalledWith(false);
      expect(lastSocket.handleConfigChanged).toHaveBeenCalledTimes(1);
    });

    it('does NOT throw when config-changed fires before any session has started (null socketRef)', async () => {
      const { result } = renderHook(() => useLiveMode());
      // No start() call — socketRef.current is null. The handler's optional
      // chain (`socketRef.current?.handleConfigChanged(...)`) must short-circuit
      // cleanly; if it didn't, the act() below would surface the throw.

      await act(async () => {
        await apiClient.syncFromConfig();
      });

      expect(result.current.status).toBe('idle');
    });
  });

  // EC-6 drain+retarget: the user changes the server host mid-session. The
  // socket class detects the URL mismatch and fires onHostMismatch; the hook
  // responds by flushing the old server's VAD buffer via `stop`, closing the
  // old socket, and reconnecting against the new URL with the same options.
  // The transcript state MUST survive the hop — the user expects continuity,
  // not a blank slate.
  describe('config-changed retarget (EC-6 drain+retarget)', () => {
    it('drains and reconnects when onHostMismatch fires, preserving sentences', async () => {
      const TranscriptionSocketMock = (await import('../services/websocket'))
        .TranscriptionSocket as unknown as Mock;

      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      // Accumulate a sentence so we can assert it survives the retarget.
      act(() => {
        lastSocketCbs.onMessage!({
          type: 'sentence',
          data: { text: 'Existing sentence.' },
        });
      });
      expect(result.current.sentences).toHaveLength(1);

      const socketConstructorCallsBefore = TranscriptionSocketMock.mock.calls.length;
      const oldSocketDisconnect = lastSocket.disconnect;
      const oldSocketSendJSON = lastSocket.sendJSON;
      const oldCaptureStop = lastCapture.stop;

      // Fire the host-mismatch callback synchronously; retarget is deferred to
      // a microtask so the current dispatch returns cleanly.
      await act(async () => {
        lastSocketCbs.onHostMismatch?.('ws://old-host:9786/ws/live', 'ws://new-host:9786/ws/live');
        // Flush the queueMicrotask via a microtask of our own.
        await Promise.resolve();
      });

      // Immediate drain side effects on the OLD session.
      expect(oldCaptureStop).toHaveBeenCalled();
      expect(oldSocketSendJSON).toHaveBeenCalledWith({ type: 'stop' });
      // Retarget microtask tore down the old socket and built a new one.
      expect(oldSocketDisconnect).toHaveBeenCalled();
      expect(TranscriptionSocketMock.mock.calls.length).toBe(socketConstructorCallsBefore + 1);
      expect(lastSocket.connect).toHaveBeenCalled();

      // Transcript state must carry across the hop.
      expect(result.current.sentences).toHaveLength(1);
      expect(result.current.sentences[0].text).toBe('Existing sentence.');
    });

    it('suppresses OLD socket onClose during the retarget microtask', async () => {
      // While the retarget flag is set (between onHostMismatch firing and the
      // queueMicrotask finally), an OLD socket onClose must not flip status to
      // 'idle'. Fire onClose BEFORE awaiting the microtask so the flag is
      // still true. In real code this race is guarded by disconnect() nulling
      // ws.onclose, but a synchronous mock onClose from test infra can reach
      // the hook before the microtask-finally clears the flag — the same
      // shape the guard is written for.
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      const oldOnClose = lastSocketCbs.onClose;

      act(() => {
        lastSocketCbs.onHostMismatch?.('ws://old-host:9786/ws/live', 'ws://new-host:9786/ws/live');
        // Fire onClose synchronously BEFORE the microtask runs — flag is true.
        oldOnClose?.(1000, 'Reconnecting');
      });

      // Status must NOT be 'idle' — the guard suppressed the reset.
      expect(result.current.status).not.toBe('idle');

      // Flush the microtask so the retarget completes cleanly.
      await act(async () => {
        await Promise.resolve();
      });
    });
  });

  // ── GH-230: capture teardown + system-audio pass-through ─────────────

  describe('GH-230: server STOPPED state and monitorSinkName', () => {
    it("'state' STOPPED stops the capture and clears the analyser", async () => {
      // Pre-fix the STOPPED branch only reset the status: the capture kept
      // streaming into a dead session and the Linux loopback module stayed
      // held (OS mic indicator lit forever).
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);
      expect(lastCapture.stop).not.toHaveBeenCalled();

      act(() => {
        lastSocketCbs.onMessage!({ type: 'state', data: { state: 'STOPPED' } });
      });

      expect(lastCapture.stop).toHaveBeenCalledTimes(1);
      expect(result.current.status).toBe('idle');
      expect(result.current.analyser).toBeNull();
    });

    it('passes systemAudio + monitorSinkName to AudioCapture.start on LISTENING', async () => {
      const { result } = renderHook(() => useLiveMode());
      act(() => {
        result.current.start({ systemAudio: true, monitorSinkName: 'alsa_output.sink' });
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      await act(async () => {
        lastSocketCbs.onMessage!({ type: 'state', data: { state: 'LISTENING' } });
      });

      expect(lastCapture.start).toHaveBeenCalledWith(
        expect.objectContaining({
          systemAudio: true,
          monitorSinkName: 'alsa_output.sink',
        }),
      );
    });
  });

  // ── Capture gain must cross the gap between start() and the instance ──
  //
  // Same shape as the longform hook: start() only opens the socket, and the
  // AudioCapture is constructed later, when the engine reports LISTENING. A
  // setGain() in between reached `captureRef.current?.setGain(...)` with
  // nothing behind it and was silently dropped.

  describe('capture gain reaches the AudioCapture built on LISTENING', () => {
    it('applies a gain set before start() to the capture instance', async () => {
      const { result } = renderHook(() => useLiveMode());

      act(() => {
        result.current.setGain(3);
      });
      await driveToListening(result, { systemAudio: true });

      expect(lastCapture.setGain).toHaveBeenCalledWith(3);
      // Before start(): start() reads the remembered gain when it builds the
      // gain node, so a later call would leave the opening audio at unity.
      expect(lastCapture.setGain.mock.invocationCallOrder[0]).toBeLessThan(
        lastCapture.start.mock.invocationCallOrder[0],
      );
    });

    it('remembers a gain set mid-session and re-applies it to the next capture', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result, { systemAudio: true });
      const firstCapture = lastCapture;

      act(() => {
        result.current.setGain(2.5);
      });
      expect(firstCapture.setGain).toHaveBeenCalledWith(2.5);

      act(() => {
        result.current.stop();
      });
      await driveToListening(result, { systemAudio: true });

      expect(lastCapture).not.toBe(firstCapture);
      expect(lastCapture.setGain).toHaveBeenCalledWith(2.5);
    });

    it('a microphone session rebuilt inside the hook still opens at unity', async () => {
      // The retarget hop and the auto-reconnect-on-ERROR re-enter start() from
      // inside this hook with the same startOptsRef, so SessionView never gets
      // to reset the gain for them. Meanwhile the Capture Gain slider forwards
      // here unconditionally and the Active Input Source buttons stay live
      // mid-session, so a mic session really can have a system gain remembered
      // against it. Without the clamp at the seed, the rebuilt microphone
      // capture would open amplified.
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result, { systemAudio: false });
      expect(lastCapture.setGain).toHaveBeenCalledWith(1);

      act(() => {
        result.current.setGain(4);
      });

      // Drive the construction site directly rather than the reconnect timer:
      // the LISTENING handler rebuilds whenever the previous capture is not
      // capturing, which is the same code path a retarget lands on.
      await act(async () => {
        lastSocketCbs.onMessage!({ type: 'state', data: { state: 'LISTENING' } });
      });

      expect(lastCapture.setGain).toHaveBeenCalledWith(1);
      expect(lastCapture.setGain).not.toHaveBeenCalledWith(4);
    });
  });

  // ── Mute must reach the AudioCapture built on LISTENING ──────────────
  //
  // Same lifetime gap as the capture gain: `muted` is React state here, while
  // the object that gates chunk delivery is the AudioCapture the engine's
  // LISTENING message builds. A mute landing before that existed reached
  // `captureRef.current?.mute()` with nothing behind it, so the session came
  // up unmuted - audio streaming and being transcribed while all three mute
  // buttons and the tray icon showed muted.
  //
  // This hook makes it worse than the longform one: the retarget hop and the
  // auto-reconnect-on-ERROR both destroy the capture and build a fresh,
  // unmuted replacement, and both deliberately preserve the mute state across
  // the hop - so the UI keeps promising a mute the new capture never got.
  //
  // The flag cannot be handed over before start() the way the gain is:
  // start() opens with a defensive stop() and stop() clears it.

  describe('mute reaches the AudioCapture built on LISTENING', () => {
    it('mutes the capture built after a mute pressed before LISTENING', async () => {
      const { result } = renderHook(() => useLiveMode());

      act(() => {
        result.current.start({});
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      // No AudioCapture yet - the engine has not reported LISTENING. The mute
      // buttons are live throughout this window.
      act(() => {
        result.current.toggleMute();
      });
      expect(result.current.muted).toBe(true);

      await act(async () => {
        lastSocketCbs.onMessage!({ type: 'state', data: { state: 'LISTENING' } });
      });

      expect(lastCapture.mute).toHaveBeenCalled();
      // AFTER start(), not before - the opposite of the gain. start()'s
      // defensive stop() clears the muted flag, so a mute handed over first
      // would be wiped before the graph was built.
      expect(lastCapture.mute.mock.invocationCallOrder[0]).toBeGreaterThan(
        lastCapture.start.mock.invocationCallOrder[0],
      );
    });

    it('keeps the capture muted across a retarget hop', async () => {
      // EC-6: the user changed hosts mid-session. start() is re-entered from
      // inside this hook with the retarget flag set, which deliberately keeps
      // the accumulated sentences and the mute - so the remembered flag has to
      // survive it too, and the capture the new host builds has to honour it.
      // The auto-reconnect-on-ERROR takes the same path.
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      act(() => {
        result.current.toggleMute();
      });
      const firstCapture = lastCapture;
      expect(firstCapture.mute).toHaveBeenCalled();

      await act(async () => {
        lastSocketCbs.onHostMismatch?.('ws://old-host:9786/ws/live', 'ws://new-host:9786/ws/live');
        // Flush the retarget's queueMicrotask with a microtask of our own.
        await Promise.resolve();
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      await act(async () => {
        lastSocketCbs.onMessage!({ type: 'state', data: { state: 'LISTENING' } });
      });

      expect(lastCapture).not.toBe(firstCapture);
      expect(result.current.muted).toBe(true);
      expect(lastCapture.mute).toHaveBeenCalled();
    });

    it('does not mute a capture the user never muted', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      expect(lastCapture.mute).not.toHaveBeenCalled();
      expect(result.current.muted).toBe(false);
    });

    it('a restart without an intervening stop still opens unmuted', async () => {
      // start() clears `muted` for anything that is not a retarget hop, so the
      // remembered flag has to be cleared with it - otherwise every session
      // after a muted one would come up silently muted. Driven without stop()
      // on purpose: stop() clears the flag too, and going through it would let
      // a start() that stopped clearing pass.
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      act(() => {
        result.current.toggleMute();
      });
      expect(result.current.muted).toBe(true);

      await driveToListening(result);

      expect(result.current.muted).toBe(false);
      expect(lastCapture.mute).not.toHaveBeenCalled();
    });

    it('stop() clears the mute along with the capture it belonged to', async () => {
      // SessionView hands the tray `transcription.muted || live.muted`, so a
      // mute left set after this capture died painted 'live-muted' over the
      // next one-shot recording - and the tray's mute item, which routes to
      // the recording while it is active, then MUTED that recording in an
      // attempt to unmute this one. Only start() cleared the flag, and
      // starting Live Mode again is not what the user does next.
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);

      act(() => {
        result.current.toggleMute();
      });
      expect(result.current.muted).toBe(true);

      act(() => {
        result.current.stop();
      });

      expect(result.current.muted).toBe(false);
    });
  });

  // ── GH-237: WS reconnect must not resurrect a dead live session ───────
  //
  // Same root cause as the longform hook: the server cannot resume a dropped
  // session, so re-sending `start` on an auto-reconnect used to silently
  // resurrect the session in the background (reconnect → start → LISTENING
  // flipped the UI back to active after it had already gone idle).

  describe('GH-237: reconnect start-gate + fail-loudly', () => {
    /** Count the `start` messages sent over a given socket instance. */
    const startSends = (s: typeof lastSocket = lastSocket): number =>
      s.sendJSON.mock.calls.filter((c) => (c[0] as { type?: string })?.type === 'start').length;

    it('does not re-send start when auth_ok fires again after LISTENING', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);
      expect(startSends()).toBe(1);

      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });

      expect(startSends()).toBe(1);
    });

    it('re-sends start on a reconnect before the engine acknowledged (still starting)', () => {
      const { result } = renderHook(() => useLiveMode());
      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      expect(startSends()).toBe(1);

      // Dropped during the model swap, before any `state` arrived.
      act(() => {
        lastSocketCbs.onClose!(1001, 'drop while starting');
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });

      expect(startSends()).toBe(2);
    });

    it('fails loudly when the socket closes unexpectedly while listening', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);
      lastSocket.disconnect.mockClear();
      lastCapture.stop.mockClear();

      act(() => {
        lastSocketCbs.onClose!(1001, 'server going away');
      });

      expect(result.current.status).toBe('error');
      expect(result.current.error).toMatch(/connection.*lost/i);
      expect(lastCapture.stop).toHaveBeenCalled();
      expect(lastSocket.disconnect).toHaveBeenCalledTimes(1);
    });

    it('a server STOPPED followed by an unintentional close stays idle and does not resurrect', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);
      expect(startSends()).toBe(1);

      // Server stops the engine (grace-period expiry / client link stop).
      act(() => {
        lastSocketCbs.onMessage!({ type: 'state', data: { state: 'STOPPED' } });
      });
      expect(result.current.status).toBe('idle');

      // The socket then drops and auto-reconnects.
      act(() => {
        lastSocketCbs.onClose!(1001, 'closed after stop');
      });
      // Nothing was capturing, so this is not a loud failure.
      expect(result.current.status).toBe('idle');
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });

      // Gate still closed — no background resurrection.
      expect(startSends()).toBe(1);
      expect(result.current.status).toBe('idle');
    });

    it('reopens the gate on a fresh start()', async () => {
      const { result } = renderHook(() => useLiveMode());
      await driveToListening(result);
      act(() => {
        result.current.stop();
      });

      await driveToListening(result);

      // lastSocket is the second socket instance — it sent its own start.
      expect(startSends()).toBe(1);
      expect(result.current.status).toBe('listening');
    });
  });
});
