import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';

import { useTranscription } from './useTranscription';

// ── Mocks ──────────────────────────────────────────────────────────────

// Capture the latest TranscriptionSocket instance and its callbacks so tests
// can simulate server messages by calling lastSocketCbs.onMessage!({...}).
let lastSocket: {
  connect: Mock;
  disconnect: Mock;
  sendJSON: Mock;
  sendAudio: Mock;
  setAudioSampleRate: Mock;
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

vi.mock('../api/client', () => ({
  apiClient: {
    getAuthToken: vi.fn().mockReturnValue('test-token'),
    getBaseUrl: vi.fn().mockReturnValue('http://localhost:9786'),
  },
}));

// ── Helpers ────────────────────────────────────────────────────────────

/** Drive the hook through auth → session_started → recording. */
async function driveToRecording(result: { current: ReturnType<typeof useTranscription> }) {
  act(() => {
    result.current.start();
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
      });
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
});
