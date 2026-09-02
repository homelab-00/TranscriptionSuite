import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest';

import { useTranscription } from './useTranscription';
import { apiClient } from '../api/client';
import { useSalvageStore } from '../stores/salvageStore';

// ── Mocks ──────────────────────────────────────────────────────────────

// Capture the latest TranscriptionSocket instance and its callbacks so tests
// can simulate server messages by calling lastSocketCbs.onMessage!({...}).
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

// When set, the NEXT AudioCapture instance's start() rejects with this error
// (consumed once). Lets tests exercise the capture-start failure paths even
// though instances are created inside the session_started handler.
let nextCaptureStartRejection: Error | null = null;

vi.mock('../services/audioCapture', () => ({
  AudioCapture: vi.fn().mockImplementation(function () {
    lastCapture = {
      start: vi.fn().mockImplementation(() => {
        if (nextCaptureStartRejection !== null) {
          const err = nextCaptureStartRejection;
          nextCaptureStartRejection = null;
          return Promise.reject(err);
        }
        return Promise.resolve(undefined);
      }),
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

// Minimal in-memory emitter so the hook's useEffect subscription resolves
// (apiClient is mocked; need to provide onConfigChanged and expose the
// emit surface for the rearm test below).
const configChangedListeners = new Set<() => void>();
function emitConfigChangedFromTest(): void {
  for (const fn of configChangedListeners) fn();
}

// Tests control this flag to simulate the install-gate predicate state.
// Defaulted to true so existing tests see a configured gate.
let mockGateConfigured = true;

vi.mock('../api/client', () => ({
  apiClient: {
    getAuthToken: vi.fn().mockReturnValue('test-token'),
    getBaseUrl: vi.fn().mockReturnValue('http://localhost:9786'),
    // GH-202: the large-result recovery path must go through apiClient (which
    // builds an absolute URL), never a bare relative fetch().
    fetchTranscriptionResult: vi.fn(),
    isBaseUrlConfigured: vi.fn(() => mockGateConfigured),
    onConfigChanged: vi.fn((listener: () => void) => {
      configChangedListeners.add(listener);
      return () => {
        configChangedListeners.delete(listener);
      };
    }),
  },
}));

// ── Helpers ────────────────────────────────────────────────────────────

/** Drive the hook through auth → session_started → recording. */
async function driveToRecording(
  result: { current: ReturnType<typeof useTranscription> },
  // Capture gain is clamped to unity for a microphone session, so gain tests
  // have to say which source they are starting.
  options: Parameters<ReturnType<typeof useTranscription>['start']>[0] = {},
) {
  act(() => {
    result.current.start(options);
  });
  await act(async () => {
    lastSocketCbs.onMessage!({ type: 'auth_ok' });
  });
  await act(async () => {
    lastSocketCbs.onMessage!({
      type: 'session_started',
      data: { job_id: 'job-1', capture_sample_rate_hz: 16000 },
    });
  });
}

// ── Tests ──────────────────────────────────────────────────────────────

describe('[P1] useTranscription', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── P1-HOOK-001: State machine transitions ──────────────────────────

  describe('P1-HOOK-001: state machine transitions', () => {
    it('starts in idle state with no result or error', () => {
      const { result } = renderHook(() => useTranscription());

      expect(result.current.status).toBe('idle');
      expect(result.current.result).toBeNull();
      expect(result.current.error).toBeNull();
      expect(result.current.jobId).toBeNull();
    });

    it('transitions idle → connecting on start()', () => {
      const { result } = renderHook(() => useTranscription());

      act(() => {
        result.current.start();
      });

      expect(result.current.status).toBe('connecting');
      expect(lastSocket.connect).toHaveBeenCalledTimes(1);
    });

    it('sends start command after auth_ok', () => {
      const { result } = renderHook(() => useTranscription());

      act(() => {
        result.current.start({ language: 'en', translate: true });
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });

      expect(lastSocket.sendJSON).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'start',
          data: expect.objectContaining({
            language: 'en',
            translation_enabled: true,
          }),
        }),
      );
    });

    it('transitions connecting → recording on session_started', async () => {
      const { result } = renderHook(() => useTranscription());

      await driveToRecording(result);

      expect(result.current.status).toBe('recording');
      expect(result.current.jobId).toBe('job-1');
      expect(lastSocket.setAudioSampleRate).toHaveBeenCalledWith(16000);
      expect(lastCapture.start).toHaveBeenCalled();
    });

    it('transitions recording → processing on stop()', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      act(() => {
        result.current.stop();
      });

      expect(result.current.status).toBe('processing');
      expect(lastSocket.sendJSON).toHaveBeenCalledWith({ type: 'stop' });
      expect(lastCapture.stop).toHaveBeenCalled();
    });

    it('transitions processing → complete on final result', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      act(() => {
        result.current.stop();
      });

      act(() => {
        lastSocketCbs.onMessage!({
          type: 'final',
          data: {
            text: 'Hello world',
            words: [{ word: 'Hello', start: 0, end: 0.5, probability: 0.99 }],
            language: 'en',
            duration: 1.5,
          },
        });
      });

      expect(result.current.status).toBe('complete');
      expect(result.current.result).toEqual({
        text: 'Hello world',
        words: [{ word: 'Hello', start: 0, end: 0.5, probability: 0.99 }],
        language: 'en',
        duration: 1.5,
        // A whole transcript. The server omits these on a complete result, and the
        // hook must normalise them rather than leave them undefined — the partial
        // banner keys off `partial`, so an undefined here would be indistinguishable
        // from false at the type level but noisier to reason about.
        partial: false,
        partialReason: null,
        // GH-258: same normalisation rationale. A server that never ran
        // diarization sends neither key, and `diarization: undefined` is what
        // the skipped-diarization notice checks for, so it must stay undefined
        // rather than becoming a fabricated "not performed" object.
        numSpeakers: 0,
        diarization: undefined,
      });
      expect(lastSocket.disconnect).toHaveBeenCalled();
    });

    // GH-202: a >1 MB result arrives as a `result_ready` reference; the hook
    // must retrieve it through apiClient (absolute URL), not a relative fetch()
    // that would resolve to file:// in a packaged build and always fail.
    it('completes via apiClient on result_ready (large-result recovery)', async () => {
      (apiClient.fetchTranscriptionResult as Mock).mockResolvedValue({
        status: 200,
        json: async () => ({
          result: { text: 'big transcript', words: [], language: 'en', duration: 42 },
        }),
      });

      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      act(() => {
        result.current.stop();
      });

      await act(async () => {
        lastSocketCbs.onMessage!({ type: 'result_ready', data: { job_id: 'job-1' } });
      });
      // Flush the fetch().then(async → json()) → setState microtask chain.
      await act(async () => {});

      expect(apiClient.fetchTranscriptionResult).toHaveBeenCalledWith('job-1');
      expect(result.current.status).toBe('complete');
      expect(result.current.result?.text).toBe('big transcript');
      expect(lastSocket.disconnect).toHaveBeenCalled();
    });

    it('transitions to error on connection error callback', () => {
      const { result } = renderHook(() => useTranscription());

      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onError!('Connection refused');
      });

      expect(result.current.status).toBe('error');
      expect(result.current.error).toBe('Connection refused');
    });

    it('transitions to error on server error message during recording', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      act(() => {
        lastSocketCbs.onMessage!({
          type: 'error',
          data: { message: 'Backend OOM' },
        });
      });

      expect(result.current.status).toBe('error');
      expect(result.current.error).toBe('Backend OOM');
      expect(lastCapture.stop).toHaveBeenCalled();
    });

    it('sets session_busy as error with active user info', () => {
      const { result } = renderHook(() => useTranscription());

      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      act(() => {
        lastSocketCbs.onMessage!({
          type: 'session_busy',
          data: { active_user: 'other-client' },
        });
      });

      expect(result.current.status).toBe('error');
      expect(result.current.error).toContain('other-client');
    });

    it('salvage-busy sets busyInfo and returns to idle instead of error', () => {
      const { result } = renderHook(() => useTranscription());

      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      const nonceBefore = useSalvageStore.getState().checkNonce;
      act(() => {
        lastSocketCbs.onMessage!({
          type: 'session_busy',
          data: { active_user: 'laptop', is_salvage: true, salvage_job_id: 'salv-1' },
        });
      });

      expect(result.current.status).toBe('idle');
      expect(result.current.error).toBeNull();
      expect(result.current.busyInfo).toEqual({
        activeUser: 'laptop',
        isSalvage: true,
        salvageJobId: 'salv-1',
      });
      expect(lastSocket.disconnect).toHaveBeenCalled();
      // The salvage progress monitor (Task 7) wakes up on this nudge.
      expect(useSalvageStore.getState().checkNonce).toBe(nonceBefore + 1);
    });

    it('session_busy without is_salvage keeps the generic error and no busyInfo', () => {
      const { result } = renderHook(() => useTranscription());

      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      act(() => {
        lastSocketCbs.onMessage!({
          type: 'session_busy',
          data: { active_user: 'other-client' },
        });
      });

      expect(result.current.status).toBe('error');
      expect(result.current.busyInfo).toBeNull();
    });

    it('clearBusyInfo and reset both clear busyInfo', () => {
      const { result } = renderHook(() => useTranscription());

      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      act(() => {
        lastSocketCbs.onMessage!({
          type: 'session_busy',
          data: { active_user: 'laptop', is_salvage: true, salvage_job_id: null },
        });
      });
      expect(result.current.busyInfo).not.toBeNull();

      act(() => {
        result.current.clearBusyInfo();
      });
      expect(result.current.busyInfo).toBeNull();

      act(() => {
        lastSocketCbs.onMessage!({
          type: 'session_busy',
          data: { active_user: 'laptop', is_salvage: true, salvage_job_id: null },
        });
      });
      act(() => {
        result.current.reset();
      });
      expect(result.current.busyInfo).toBeNull();
    });

    it('unexpected close while recording nudges the salvage monitor', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      const nonceBefore = useSalvageStore.getState().checkNonce;
      act(() => {
        lastSocketCbs.onClose!(1006, 'abnormal');
      });

      expect(useSalvageStore.getState().checkNonce).toBe(nonceBefore + 1);
    });
  });

  // ── P1-HOOK-002: Unmount cleanup ────────────────────────────────────

  describe('P1-HOOK-002: unmount cleanup', () => {
    it('disconnects socket on unmount when in idle state', () => {
      const { result, unmount } = renderHook(() => useTranscription());

      act(() => {
        result.current.start();
      });
      // Return to idle so the cleanup effect runs its full path
      act(() => {
        result.current.reset();
      });

      // Clear counts from start()/reset() calls
      lastSocket.disconnect.mockClear();

      unmount();

      // Cleanup fires: status is idle → cancels polls, disconnects
      expect(lastSocket.disconnect).toHaveBeenCalledTimes(1);
    });

    it('preserves session on unmount when processing (by design)', async () => {
      const { result, unmount } = renderHook(() => useTranscription());
      await driveToRecording(result);

      act(() => {
        result.current.stop();
      });
      expect(result.current.status).toBe('processing');

      // Clear counts from the stop() flow
      lastSocket.disconnect.mockClear();
      lastCapture.stop.mockClear();

      unmount();

      // Cleanup intentionally skips disconnect during processing so the
      // poll-for-result fallback can recover the transcription.
      expect(lastSocket.disconnect).not.toHaveBeenCalled();
    });
  });

  // ── P1-HOOK-003: Cancel during processing ───────────────────────────

  describe('P1-HOOK-003: cancel during processing', () => {
    it('reset() during processing returns to clean idle state', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      act(() => {
        result.current.stop();
      });
      expect(result.current.status).toBe('processing');

      act(() => {
        result.current.reset();
      });

      expect(result.current.status).toBe('idle');
      expect(result.current.result).toBeNull();
      expect(result.current.error).toBeNull();
      expect(result.current.jobId).toBeNull();
      expect(result.current.vadActive).toBe(false);
      expect(result.current.muted).toBe(false);
      expect(result.current.processingProgress).toBeNull();
      expect(result.current.analyser).toBeNull();
    });

    it('reset() stops capture and disconnects socket', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      act(() => {
        result.current.stop();
      });

      lastCapture.stop.mockClear();
      lastSocket.disconnect.mockClear();

      act(() => {
        result.current.reset();
      });

      expect(lastCapture.stop).toHaveBeenCalled();
      expect(lastSocket.disconnect).toHaveBeenCalled();
    });
  });

  // ── Additional coverage ─────────────────────────────────────────────

  describe('supplementary transitions', () => {
    it('tracks VAD state from server messages', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      act(() => {
        lastSocketCbs.onMessage!({ type: 'vad_start' });
      });
      expect(result.current.vadActive).toBe(true);

      act(() => {
        lastSocketCbs.onMessage!({ type: 'vad_stop' });
      });
      expect(result.current.vadActive).toBe(false);
    });

    it('tracks processing progress from server', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      act(() => {
        result.current.stop();
      });
      act(() => {
        lastSocketCbs.onMessage!({
          type: 'processing_progress',
          data: { current: 2, total: 5 },
        });
      });

      expect(result.current.processingProgress).toEqual({
        current: 2,
        total: 5,
        // GH-258: the server forwards the job phase so a silent diarization
        // pass is visible; null when it sent none.
        phase: null,
      });
    });

    it('loadResult sets result and transitions to complete', () => {
      const { result } = renderHook(() => useTranscription());

      act(() => {
        result.current.loadResult({
          text: 'Recovered',
          words: [],
          language: 'en',
        });
      });

      expect(result.current.status).toBe('complete');
      expect(result.current.result?.text).toBe('Recovered');
    });

    it('toggleMute delegates to AudioCapture', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

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
  });

  // ── config-changed forwarding: the hook no longer branches on socket state
  //   itself — it just forwards `isBaseUrlConfigured()` to
  //   TranscriptionSocket.handleConfigChanged so the socket class can own the
  //   error-rearm / pending-backoff-shortcut / active-session-warn branches.
  //   Exhaustive per-branch coverage lives in src/services/websocket.test.ts.
  describe('config-changed forwarding to socket.handleConfigChanged', () => {
    beforeEach(() => {
      configChangedListeners.clear();
      mockGateConfigured = true;
    });

    it('forwards configured=true when the gate is open', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      lastSocket.handleConfigChanged.mockClear();

      act(() => {
        emitConfigChangedFromTest();
      });

      expect(lastSocket.handleConfigChanged).toHaveBeenCalledTimes(1);
      expect(lastSocket.handleConfigChanged).toHaveBeenCalledWith(true);
    });

    it('forwards configured=false when the sync that fired the event failed', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      lastSocket.handleConfigChanged.mockClear();
      mockGateConfigured = false;

      act(() => {
        emitConfigChangedFromTest();
      });

      expect(lastSocket.handleConfigChanged).toHaveBeenCalledWith(false);
    });

    it('unsubscribes on unmount; emit after unmount does not call handleConfigChanged', async () => {
      const { result, unmount } = renderHook(() => useTranscription());
      await driveToRecording(result);

      lastSocket.handleConfigChanged.mockClear();

      unmount();

      act(() => {
        emitConfigChangedFromTest();
      });

      expect(lastSocket.handleConfigChanged).not.toHaveBeenCalled();
    });
  });

  // ── Rolling preview (auto-refreshing last-N-seconds pane) ───────────
  describe('rolling preview', () => {
    beforeEach(() => {
      // Explicit toFake so Date.now() advances with the timers — the adaptive
      // refresh delay is computed from Date.now() deltas.
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    /** Count sendJSON calls that were preview requests. */
    function previewSends(): Array<Record<string, unknown>> {
      return (lastSocket?.sendJSON.mock.calls ?? [])
        .map((c) => c[0] as { type: string; data?: Record<string, unknown> })
        .filter((m) => m.type === 'preview');
    }

    function deliverPreviewResult(text = 'recent words', actualSeconds = 20): void {
      act(() => {
        lastSocketCbs.onMessage!({
          type: 'preview_result',
          data: { text, language: 'en', actual_seconds: actualSeconds },
        });
      });
    }

    it('startPreview sends the first request immediately with the requested duration', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      lastSocket.sendJSON.mockClear();

      act(() => {
        result.current.startPreview(30);
      });

      expect(lastSocket.sendJSON).toHaveBeenCalledWith({
        type: 'preview',
        data: { duration_seconds: 30 },
      });
      expect(result.current.previewActive).toBe(true);
      expect(result.current.previewLoading).toBe(true);
    });

    it('is a no-op when not recording', () => {
      const { result } = renderHook(() => useTranscription());

      act(() => {
        result.current.startPreview(20);
      });

      expect(previewSends()).toHaveLength(0);
      expect(result.current.previewActive).toBe(false);
      expect(result.current.previewLoading).toBe(false);
    });

    it('ignores startPreview while already active', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      lastSocket.sendJSON.mockClear();

      act(() => {
        result.current.startPreview(20);
        result.current.startPreview(20);
      });

      expect(previewSends()).toHaveLength(1);
    });

    it('populates preview state on preview_result and stays active', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      act(() => {
        result.current.startPreview(20);
      });

      deliverPreviewResult('the last words I said', 20);

      expect(result.current.previewText).toBe('the last words I said');
      expect(result.current.previewSeconds).toBe(20);
      expect(result.current.previewLanguage).toBe('en');
      expect(result.current.previewLoading).toBe(false);
      expect(result.current.previewError).toBeNull();
      expect(result.current.previewActive).toBe(true);
    });

    it('schedules the next refresh 5s after a fast result', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      lastSocket.sendJSON.mockClear();

      act(() => {
        result.current.startPreview(20);
      });
      deliverPreviewResult();
      expect(previewSends()).toHaveLength(1);

      act(() => {
        vi.advanceTimersByTime(4999);
      });
      expect(previewSends()).toHaveLength(1);

      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(previewSends()).toHaveLength(2);
      expect(previewSends()[1]).toEqual({
        type: 'preview',
        data: { duration_seconds: 20 },
      });
    });

    it('backs off to the transcription duration when a result is slow (50% duty cycle)', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      lastSocket.sendJSON.mockClear();

      act(() => {
        result.current.startPreview(20);
      });
      // The request takes 8s to come back — longer than the 5s base cadence.
      act(() => {
        vi.advanceTimersByTime(8000);
      });
      deliverPreviewResult();
      expect(previewSends()).toHaveLength(1);

      // Next refresh must wait a further 8s (not 5s - 8s = immediate).
      act(() => {
        vi.advanceTimersByTime(7999);
      });
      expect(previewSends()).toHaveLength(1);

      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(previewSends()).toHaveLength(2);
    });

    it('stopPreview cancels the pending refresh and clears the pane state', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      lastSocket.sendJSON.mockClear();

      act(() => {
        result.current.startPreview(20);
      });
      deliverPreviewResult('something');
      expect(result.current.previewText).toBe('something');

      act(() => {
        result.current.stopPreview();
      });

      expect(result.current.previewActive).toBe(false);
      expect(result.current.previewText).toBeNull();
      expect(result.current.previewError).toBeNull();
      expect(result.current.previewLoading).toBe(false);

      act(() => {
        vi.advanceTimersByTime(60000);
      });
      expect(previewSends()).toHaveLength(1);
    });

    it('ignores a late preview_result that lands after stopPreview', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      act(() => {
        result.current.startPreview(20);
      });
      act(() => {
        result.current.stopPreview();
      });
      deliverPreviewResult('late text');

      expect(result.current.previewText).toBeNull();
      expect(result.current.previewLoading).toBe(false);

      act(() => {
        vi.advanceTimersByTime(60000);
      });
      expect(previewSends()).toHaveLength(1);
    });

    it('stops the loop on preview_error and surfaces the message', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      lastSocket.sendJSON.mockClear();

      act(() => {
        result.current.startPreview(20);
      });
      act(() => {
        lastSocketCbs.onMessage!({
          type: 'preview_error',
          data: { message: 'No audio captured yet' },
        });
      });

      expect(result.current.previewError).toBe('No audio captured yet');
      expect(result.current.previewActive).toBe(false);
      expect(result.current.previewLoading).toBe(false);

      act(() => {
        vi.advanceTimersByTime(60000);
      });
      expect(previewSends()).toHaveLength(1);
    });

    it('stops the loop when the recording stops', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      lastSocket.sendJSON.mockClear();

      act(() => {
        result.current.startPreview(20);
      });
      deliverPreviewResult();

      act(() => {
        result.current.stop();
      });
      act(() => {
        vi.advanceTimersByTime(60000);
      });

      expect(result.current.previewActive).toBe(false);
      expect(previewSends()).toHaveLength(1);
    });

    it('halts the loop when the socket closes unexpectedly (server restart)', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      lastSocket.sendJSON.mockClear();

      act(() => {
        result.current.startPreview(20);
      });
      expect(result.current.previewLoading).toBe(true);

      // Unintentional close — intentional disconnects never invoke onClose.
      act(() => {
        lastSocketCbs.onClose!(1001, 'server going away');
      });

      expect(result.current.previewActive).toBe(false);
      expect(result.current.previewLoading).toBe(false);

      act(() => {
        vi.advanceTimersByTime(60000);
      });
      expect(previewSends()).toHaveLength(1);
    });

    it('halts the loop on a socket error', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      lastSocket.sendJSON.mockClear();

      act(() => {
        result.current.startPreview(20);
      });
      deliverPreviewResult();

      act(() => {
        lastSocketCbs.onError!('Connection lost');
      });
      act(() => {
        vi.advanceTimersByTime(60000);
      });

      expect(result.current.previewActive).toBe(false);
      expect(result.current.previewLoading).toBe(false);
      expect(previewSends()).toHaveLength(1);
    });

    it('reuses an in-flight response after a quick off/on toggle instead of double-sending', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      lastSocket.sendJSON.mockClear();

      // R1 goes out, then the user toggles off and immediately back on
      // before R1 returns. A second 'preview' now would be rejected by the
      // server ('Preview already in progress') and kill the loop.
      act(() => {
        result.current.startPreview(20);
      });
      act(() => {
        result.current.stopPreview();
      });
      act(() => {
        result.current.startPreview(20);
      });

      expect(previewSends()).toHaveLength(1);
      expect(result.current.previewActive).toBe(true);
      expect(result.current.previewLoading).toBe(true);

      // R1's response arrives and is adopted by the restarted loop.
      deliverPreviewResult('carried over');
      expect(result.current.previewText).toBe('carried over');
      expect(result.current.previewLoading).toBe(false);

      // ...and the loop keeps rolling from it.
      act(() => {
        vi.advanceTimersByTime(5000);
      });
      expect(previewSends()).toHaveLength(2);
    });

    it('stops the loop on a server error', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      lastSocket.sendJSON.mockClear();

      act(() => {
        result.current.startPreview(20);
      });
      deliverPreviewResult();

      act(() => {
        lastSocketCbs.onMessage!({ type: 'error', data: { message: 'Backend OOM' } });
      });
      act(() => {
        vi.advanceTimersByTime(60000);
      });

      expect(result.current.previewActive).toBe(false);
      expect(previewSends()).toHaveLength(1);
    });

    it('clears preview state on a new start()', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      act(() => {
        result.current.startPreview(20);
      });
      deliverPreviewResult('something');
      expect(result.current.previewText).toBe('something');

      act(() => {
        result.current.start();
      });

      expect(result.current.previewText).toBeNull();
      expect(result.current.previewError).toBeNull();
      expect(result.current.previewLoading).toBe(false);
      expect(result.current.previewActive).toBe(false);
    });
  });

  // ── GH-230: system-audio option pass-through ─────────────────────────
  //
  // The Linux loopback module lifecycle is owned by AudioCapture/loopbackOwner;
  // the hook's only responsibility is to hand the selected sink through to
  // capture.start() so the capture can acquire the module.

  describe('GH-230: monitorSinkName pass-through', () => {
    it('passes systemAudio + monitorSinkName to AudioCapture.start on session_started', async () => {
      const { result } = renderHook(() => useTranscription());
      act(() => {
        result.current.start({ systemAudio: true, monitorSinkName: 'alsa_output.sink' });
      });
      await act(async () => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      await act(async () => {
        lastSocketCbs.onMessage!({
          type: 'session_started',
          data: { job_id: 'job-sys', capture_sample_rate_hz: 16000 },
        });
      });

      expect(lastCapture.start).toHaveBeenCalledWith(
        expect.objectContaining({
          systemAudio: true,
          monitorSinkName: 'alsa_output.sink',
        }),
      );
    });

    it('a capture start aborted by a racing stop() does NOT flip the hook to error', async () => {
      const abort = new Error('Audio capture start aborted by stop()');
      abort.name = 'AbortError';
      nextCaptureStartRejection = abort;

      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      expect(result.current.status).not.toBe('error');
      expect(result.current.error).toBeNull();
      // The socket was NOT torn down by the swallowed abort.
      expect(lastSocket.disconnect).not.toHaveBeenCalled();
    });
  });

  // ── Capture gain must cross the gap between start() and the instance ──
  //
  // start() only opens the socket; the AudioCapture is constructed a server
  // round trip later, in the session_started handler. setGain() therefore has
  // no instance to talk to at the moment the UI calls it - and because it
  // forwards through `captureRef.current?.setGain(...)`, the value used to
  // vanish without a sound: the recording ran at 1.0 while the slider went on
  // displaying the gain the user had chosen and persisted.

  describe('capture gain reaches the AudioCapture built on session_started', () => {
    it('applies a gain set before start() to the capture instance', async () => {
      const { result } = renderHook(() => useTranscription());

      act(() => {
        result.current.setGain(3);
      });
      await driveToRecording(result, { systemAudio: true });

      expect(lastCapture.setGain).toHaveBeenCalledWith(3);
      // Before start(), not after: start() reads the remembered gain when it
      // builds the gain node, so anything applied afterwards would leave the
      // opening audio of every recording at unity.
      expect(lastCapture.setGain.mock.invocationCallOrder[0]).toBeLessThan(
        lastCapture.start.mock.invocationCallOrder[0],
      );
    });

    it('remembers a gain set mid-session and re-applies it to the next capture', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result, { systemAudio: true });
      const firstCapture = lastCapture;

      act(() => {
        result.current.setGain(2.5);
      });
      expect(firstCapture.setGain).toHaveBeenCalledWith(2.5);

      // Second recording: a fresh instance, born at unity unless the hook
      // hands it the remembered value. The old one is dead - writing to it is
      // what the buggy path did on every recording after the first.
      act(() => {
        result.current.stop();
      });
      await driveToRecording(result, { systemAudio: true });

      expect(lastCapture).not.toBe(firstCapture);
      expect(lastCapture.setGain).toHaveBeenCalledWith(2.5);
    });

    it('opens a microphone recording at unity whatever gain is remembered', async () => {
      // Capture Gain is a system-audio control, but the slider forwards to both
      // hooks unconditionally and the Active Input Source buttons stay live
      // mid-session, so the remembered value can belong to a source this
      // recording is not using. The clamp lives next to the seed so it holds
      // for whatever builds the capture, not only for the SessionView path.
      const { result } = renderHook(() => useTranscription());

      act(() => {
        result.current.setGain(4);
      });
      await driveToRecording(result, { systemAudio: false });

      expect(lastCapture.setGain).toHaveBeenCalledWith(1);
      expect(lastCapture.setGain).not.toHaveBeenCalledWith(4);
    });
  });

  // ── Mute must reach the AudioCapture built on session_started ─────────
  //
  // The same lifetime gap as the capture gain, with a worse payload. `muted`
  // is React state in this hook; the object that actually gates chunk delivery
  // is the AudioCapture, and that is built a server round trip later. A mute
  // pressed before it existed forwarded through `captureRef.current?.mute()`
  // and hit nothing, so the session came up unmuted: audio kept streaming to
  // the server and being transcribed while the tray icon showed muted.
  //
  // Both mute controls are live in exactly that window. The tray's mute item
  // is enabled from `connecting` onwards (useTraySync counts connecting as
  // recording) and SessionView routes it to this hook for that status, and the
  // Main Transcription card's own mute button - rewired to this hook on this
  // branch - is never disabled.
  //
  // Unlike the gain, the flag cannot be handed over before start(): start()
  // opens with a defensive stop() and stop() clears it, so the mute has to be
  // re-applied once start() has built the graph.

  describe('mute reaches the AudioCapture built on session_started', () => {
    /** Drive to an open socket with no AudioCapture built yet. */
    async function driveToConnecting(result: {
      current: ReturnType<typeof useTranscription>;
    }): Promise<void> {
      act(() => {
        result.current.start({});
      });
      await act(async () => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
    }

    /** Deliver the message the AudioCapture is constructed on. */
    async function deliverSessionStarted(): Promise<void> {
      await act(async () => {
        lastSocketCbs.onMessage!({
          type: 'session_started',
          data: { job_id: 'job-1', capture_sample_rate_hz: 16000 },
        });
      });
    }

    it('mutes the capture built after a mute pressed while connecting', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToConnecting(result);

      act(() => {
        result.current.toggleMute();
      });
      expect(result.current.muted).toBe(true);

      await deliverSessionStarted();

      expect(lastCapture.mute).toHaveBeenCalled();
      // AFTER start(), not before - the opposite of the gain. start()'s
      // defensive stop() clears the muted flag, so a mute handed over first
      // would be wiped before the graph was built. Re-applying here still
      // leaks nothing: the worklet delivers chunks as tasks and this runs as a
      // microtask off start()'s promise, which drains first.
      expect(lastCapture.mute.mock.invocationCallOrder[0]).toBeGreaterThan(
        lastCapture.start.mock.invocationCallOrder[0],
      );
    });

    it('does not mute a capture the user never muted', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      expect(lastCapture.mute).not.toHaveBeenCalled();
      expect(result.current.muted).toBe(false);
    });

    it('honours an unmute that lands before the capture is built', async () => {
      // This one constrains the toggle, not the re-apply: the pre-fix code
      // also left the new capture unmuted here, so the `mute` assertion alone
      // would pass against the bug. What it pins is that the remembered flag
      // toggles BOTH ways - stop writing it on the off-branch and the second
      // press stops registering, leaving `muted` stuck true.
      const { result } = renderHook(() => useTranscription());
      await driveToConnecting(result);

      act(() => {
        result.current.toggleMute();
      });
      act(() => {
        result.current.toggleMute();
      });
      expect(result.current.muted).toBe(false);

      await deliverSessionStarted();

      expect(lastCapture.mute).not.toHaveBeenCalled();
    });

    it('unmutes the capture it muted on construction', async () => {
      // The round trip the two tests above only cover half of each: the mute
      // crosses the gap, and the unmute afterwards reaches the instance the
      // mute was applied to rather than being dropped on the floor.
      const { result } = renderHook(() => useTranscription());
      await driveToConnecting(result);

      act(() => {
        result.current.toggleMute();
      });
      await deliverSessionStarted();
      expect(lastCapture.mute).toHaveBeenCalled();

      act(() => {
        result.current.toggleMute();
      });

      expect(result.current.muted).toBe(false);
      expect(lastCapture.unmute).toHaveBeenCalled();
    });

    it('a restart without an intervening stop still opens unmuted', async () => {
      // start() clears `muted`, so the remembered flag must be cleared with
      // it. Driven without stop() on purpose - stop() clears the flag too, and
      // going through it would let a start() that stopped clearing pass.
      const { result } = renderHook(() => useTranscription());
      await driveToConnecting(result);

      act(() => {
        result.current.toggleMute();
      });
      expect(result.current.muted).toBe(true);

      await driveToRecording(result);

      expect(result.current.muted).toBe(false);
      expect(lastCapture.mute).not.toHaveBeenCalled();
    });

    it('stop() clears the mute along with the capture it belonged to', async () => {
      // SessionView hands the tray `transcription.muted || live.muted`, so a
      // mute left set after this capture died painted a muted icon over
      // whatever ran next - and the tray's mute item then muted THAT session
      // in an attempt to unmute this one.
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

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

  // ── GH-237: WS reconnect must not spawn zombie server sessions ────────
  //
  // The server assigns a NEW session_id + job_id per WS connection and cannot
  // resume a dropped session. The socket auto-reconnects unintentional closes,
  // so a `start` re-sent on every reconnect used to silently abandon the
  // original job and spin up a fresh one for a new slice of audio — a
  // truncated transcript passed off as complete (data-loss invariant breach).

  describe('GH-237: reconnect start-gate + fail-loudly', () => {
    /** Count the `start` messages sent over a given socket instance. */
    const startSends = (s: typeof lastSocket = lastSocket): number =>
      s.sendJSON.mock.calls.filter((c) => (c[0] as { type?: string })?.type === 'start').length;

    it('does not re-send start when auth_ok fires again after the session is established', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      expect(startSends()).toBe(1);

      // A reconnect re-runs the auth handshake on the same socket instance.
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });

      // Gate held — otherwise the server would have spawned a second job.
      expect(startSends()).toBe(1);
    });

    it('re-sends start on a reconnect that lands before the session was established', () => {
      const { result } = renderHook(() => useTranscription());
      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      expect(startSends()).toBe(1);

      // Dropped mid-handshake (still 'connecting', no session_started yet).
      act(() => {
        lastSocketCbs.onClose!(1001, 'drop before session');
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });

      // No job existed yet, so re-establishing the first session is correct.
      expect(startSends()).toBe(2);
      expect(result.current.status).not.toBe('error');
    });

    it('fails loudly when the socket closes unexpectedly while recording', async () => {
      (apiClient.fetchTranscriptionResult as Mock).mockResolvedValue({ status: 202 });
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      lastSocket.disconnect.mockClear();
      lastCapture.stop.mockClear();

      await act(async () => {
        lastSocketCbs.onClose!(1001, 'server going away');
        await Promise.resolve();
      });

      expect(result.current.error).toMatch(/connection.*lost/i);
      expect(lastCapture.stop).toHaveBeenCalled();
      // Auto-reconnect is halted so no zombie session is created.
      expect(lastSocket.disconnect).toHaveBeenCalledTimes(1);
      // The status is no longer terminal: GH-239 made the server salvage the
      // audio it already received, so the hook waits on that instead of
      // stopping at the error. The interruption is still announced above -
      // what changed is that it is now recoverable, not that it is quiet.
      expect(result.current.status).toBe('processing');
    });

    it('does not re-send start on a reconnect during processing (poll owns recovery)', async () => {
      (apiClient.fetchTranscriptionResult as Mock).mockResolvedValue({ status: 202 });
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      act(() => {
        result.current.stop();
      });
      expect(result.current.status).toBe('processing');
      expect(startSends()).toBe(1);

      // Socket drops mid-processing, then auto-reconnects and re-authenticates.
      await act(async () => {
        lastSocketCbs.onClose!(1001, 'drop during processing');
        await Promise.resolve();
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });

      // No phantom job: the poll-for-result fallback recovers the real one.
      expect(startSends()).toBe(1);
      expect(result.current.status).toBe('processing');
    });

    it('reopens the gate on a fresh start() so the next session sends its own start', async () => {
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      act(() => {
        lastSocketCbs.onMessage!({ type: 'final', data: { text: 'one', words: [] } });
      });
      expect(result.current.status).toBe('complete');

      // A brand-new user-initiated session builds a fresh socket instance.
      await driveToRecording(result);

      // lastSocket is now the second socket — it sent exactly one start.
      expect(startSends()).toBe(1);
      expect(result.current.status).toBe('recording');
    });
  });

  // ── GH-239: recover the head audio the server salvaged ──────────────

  describe('GH-239: mid-recording drop recovers the salvaged partial', () => {
    beforeEach(() => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    /** Advance one poll interval and let the fetch promise settle. */
    async function tickPoll(times = 1): Promise<void> {
      for (let i = 0; i < times; i++) {
        await act(async () => {
          vi.advanceTimersByTime(3000);
          await Promise.resolve();
          await Promise.resolve();
        });
      }
    }

    it('polls for the salvaged result when the socket drops while recording', async () => {
      (apiClient.fetchTranscriptionResult as Mock).mockResolvedValue({
        status: 200,
        json: async () => ({
          result: {
            text: 'the half that made it',
            words: [],
            partial: true,
            partial_reason: 'Client disconnected mid-recording',
          },
        }),
      });
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      await act(async () => {
        lastSocketCbs.onClose!(1001, 'server going away');
        await Promise.resolve();
      });

      expect(apiClient.fetchTranscriptionResult).toHaveBeenCalledWith('job-1');
      expect(result.current.status).toBe('complete');
      expect(result.current.result?.text).toBe('the half that made it');
    });

    it('surfaces the truncation so the transcript is never mistaken for whole', async () => {
      (apiClient.fetchTranscriptionResult as Mock).mockResolvedValue({
        status: 200,
        json: async () => ({
          result: {
            text: 'the half that made it',
            words: [],
            partial: true,
            partial_reason: 'Client disconnected mid-recording',
          },
        }),
      });
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      await act(async () => {
        lastSocketCbs.onClose!(1001, 'server going away');
        await Promise.resolve();
      });

      expect(result.current.result?.partial).toBe(true);
      expect(result.current.result?.partialReason).toMatch(/disconnected/i);
      // The red "connection lost" banner has served its purpose - the amber
      // partial banner now carries the signal. Leaving both reads as a failure.
      expect(result.current.error).toBeNull();
    });

    it('still halts the auto-reconnect so no zombie session is spawned', async () => {
      (apiClient.fetchTranscriptionResult as Mock).mockResolvedValue({ status: 202 });
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);
      lastSocket.disconnect.mockClear();
      lastCapture.stop.mockClear();

      await act(async () => {
        lastSocketCbs.onClose!(1001, 'server going away');
        await Promise.resolve();
      });

      expect(lastSocket.disconnect).toHaveBeenCalledTimes(1);
      expect(lastCapture.stop).toHaveBeenCalled();
    });

    it('tells the user recovery is under way rather than going quiet', async () => {
      (apiClient.fetchTranscriptionResult as Mock).mockResolvedValue({ status: 202 });
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      await act(async () => {
        lastSocketCbs.onClose!(1001, 'server going away');
        await Promise.resolve();
      });

      expect(result.current.error).toMatch(/lost/i);
      expect(result.current.status).toBe('processing');
    });

    it('keeps polling well past the old ten-attempt cap', async () => {
      // Salvaging a long recording means transcribing all of it. Ten tries at
      // 3s gave up after 30 seconds - far short of any real recording.
      (apiClient.fetchTranscriptionResult as Mock).mockResolvedValue({ status: 202 });
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      await act(async () => {
        lastSocketCbs.onClose!(1001, 'server going away');
        await Promise.resolve();
      });
      await tickPoll(30);

      expect((apiClient.fetchTranscriptionResult as Mock).mock.calls.length).toBeGreaterThan(11);
      expect(result.current.status).toBe('processing');
    });

    it('gives up loudly when the server reports the job failed', async () => {
      (apiClient.fetchTranscriptionResult as Mock).mockResolvedValue({ status: 410 });
      const { result } = renderHook(() => useTranscription());
      await driveToRecording(result);

      await act(async () => {
        lastSocketCbs.onClose!(1001, 'server going away');
        await Promise.resolve();
      });

      expect(result.current.status).toBe('error');
      expect(result.current.error).toMatch(/failed/i);
    });

    it('fails loudly without polling when the recording never got a job id', async () => {
      // create_job failed server-side, so session_started carries no job_id.
      // There is no row to salvage into - the GH-237 fail-loudly behaviour is
      // still the only honest answer.
      const { result } = renderHook(() => useTranscription());
      act(() => {
        result.current.start();
      });
      await act(async () => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      await act(async () => {
        lastSocketCbs.onMessage!({
          type: 'session_started',
          data: { capture_sample_rate_hz: 16000 },
        });
      });
      expect(result.current.status).toBe('recording');
      expect(result.current.jobId).toBeNull();
      (apiClient.fetchTranscriptionResult as Mock).mockClear();

      await act(async () => {
        lastSocketCbs.onClose!(1001, 'server going away');
        await Promise.resolve();
      });

      expect(apiClient.fetchTranscriptionResult).not.toHaveBeenCalled();
      expect(result.current.status).toBe('error');
      expect(result.current.error).toMatch(/lost/i);
    });

    it('does not poll for a drop during the connecting handshake', async () => {
      // Pre-existing GH-237 contract: no session was established yet, so the
      // auto-reconnect re-establishes the FIRST session. Nothing to recover,
      // and flipping to an error state here would break that.
      const { result } = renderHook(() => useTranscription());
      act(() => {
        result.current.start();
      });
      await act(async () => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      (apiClient.fetchTranscriptionResult as Mock).mockClear();

      await act(async () => {
        lastSocketCbs.onClose!(1001, 'drop before session');
        await Promise.resolve();
      });

      expect(apiClient.fetchTranscriptionResult).not.toHaveBeenCalled();
      expect(result.current.status).toBe('connecting');
    });
  });
});
