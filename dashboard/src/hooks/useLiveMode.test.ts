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
async function driveToListening(result: { current: ReturnType<typeof useLiveMode> }) {
  act(() => {
    result.current.start();
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
});
