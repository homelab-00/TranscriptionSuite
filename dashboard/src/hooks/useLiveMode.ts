/**
 * useLiveMode — orchestrates continuous live transcription via /ws/live.
 *
 * Flow: connect → auth → start → stream audio → receive partial/sentence in real-time.
 * Sentences accumulate; the latest partial is shown as in-progress text.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { apiClient } from '../api/client';
import { TranscriptionSocket, ServerMessage } from '../services/websocket';
import { AudioCapture } from '../services/audioCapture';

export type LiveStatus =
  | 'idle'
  | 'connecting'
  | 'starting' // model swap in progress
  | 'listening'
  | 'processing'
  | 'error';

export interface LiveSentence {
  text: string;
  timestamp: number; // Date.now() when received
}

export interface LiveModeState {
  status: LiveStatus;
  /** Completed sentences accumulated during this session */
  sentences: LiveSentence[];
  /** Current partial (in-progress) text */
  partial: string;
  /** Status message during model loading */
  statusMessage: string | null;
  error: string | null;
  /** AnalyserNode for visualizer */
  analyser: AnalyserNode | null;
  /** Whether audio is muted (capture continues but chunks not sent) */
  muted: boolean;
  /** Start live mode */
  start: (options?: LiveStartOptions) => void;
  /** Stop live mode (reloads main model on server) */
  stop: () => void;
  /** Toggle mute */
  toggleMute: () => void;
  /** Set capture gain (amplification). Values >1 boost quiet sources. */
  setGain: (value: number) => void;
  /** Clear accumulated sentences */
  clearHistory: () => void;
  /** Copy all sentences as text */
  getText: () => string;
}

export interface LiveStartOptions {
  language?: string;
  deviceId?: string;
  translate?: boolean;
  translationTarget?: string;
  gracePeriodSeconds?: number;
  model?: string;
  systemAudio?: boolean;
  monitorSinkName?: string;
  /** Also capture the microphone alongside system audio and mix them. */
  mixMicWithSystem?: boolean;
  /** Device ID for the mixed-in microphone. Falls back to the default mic. */
  mixMicDeviceId?: string;
  /**
   * GGML filename of the live model, used ONLY on the Windows `vulkan-wsl2`
   * profile to relaunch the native whisper-server.exe onto this model before
   * connecting (it serves one model per launch and cannot hot-swap). Ignored by
   * the server and a no-op on every other profile / non-GGML model. See
   * dockerManager.switchWhisperServerModel.
   */
  whisperServerModel?: string;
}

// Cap on consecutive automatic reconnect attempts after the engine reports a
// terminal ERROR (see the 'ERROR' branch in handleMessage below).
const MAX_AUTO_RECONNECTS = 5;

export function useLiveMode(): LiveModeState {
  const [status, setStatus] = useState<LiveStatus>('idle');
  const [sentences, setSentences] = useState<LiveSentence[]>([]);
  const [partial, setPartial] = useState('');
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);
  const [muted, setMuted] = useState(false);

  const socketRef = useRef<TranscriptionSocket | null>(null);
  const captureRef = useRef<AudioCapture | null>(null);
  const startOptsRef = useRef<LiveStartOptions>({});
  // Retarget hook: holds the latest `start` closure so the socket's
  // onHostMismatch callback can reopen the session on the new URL without
  // a stale reference. Updated on every render (see the effect below).
  const retargetRef = useRef<(() => void) | null>(null);
  const isRetargetingRef = useRef(false);
  // Mirror of `status` so the socket callbacks (created once in start()) can
  // read the CURRENT status without a stale closure — mirrors useTranscription.
  const statusRef = useRef<LiveStatus>('idle');
  const setStatusTracked = useCallback((s: LiveStatus) => {
    statusRef.current = s;
    setStatus(s);
  }, []);
  // GH-237: gate the `start` re-send across auto-reconnects (same rationale as
  // useTranscription). The server cannot resume a dropped live session, so
  // re-sending `start` on reconnect resurrects it in the background. Flipped
  // true on the first `state` message (engine acknowledged our start); stays
  // true across a server STOPPED + reconnect so nothing resurrects; reopened
  // only by a user-initiated start()/stop().
  const sessionEstablishedRef = useRef(false);
  // Auto-reconnect on engine ERROR: counts consecutive reconnect attempts
  // (reset on a fresh manual start or a successful LISTENING) and holds the
  // pending timer so a manual start()/stop() can cancel it.
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      captureRef.current?.stop();
      socketRef.current?.disconnect();
    };
  }, []);

  // Schedules an auto-reconnect attempt (shared by the engine-ERROR path and
  // the "another session is already active" rejection — see the 'error' case
  // below). Returns false once the budget is exhausted so the caller can fall
  // back to a terminal error instead. Keeps any more specific message an
  // `error` frame already delivered (or is about to): the two frames can
  // race, and the specific one always wins.
  const scheduleReconnect = useCallback(
    (fallbackMessage: string) => {
      // A retry is already armed. The socket runs its own auto-reconnect, so
      // several rejections can arrive here in quick succession; none of them
      // may burn a fresh attempt or stack a second timer.
      if (reconnectTimerRef.current !== null) return true;

      const attempt = reconnectAttemptsRef.current + 1;
      if (attempt > MAX_AUTO_RECONNECTS) return false;

      reconnectAttemptsRef.current = attempt;
      const delaySec = Math.min(attempt, 5);
      setError((prev) => prev ?? fallbackMessage);
      // The countdown lives in statusMessage, not error. TranscriptionSocket
      // dispatches a server `error` frame to onError BEFORE forwarding it to
      // onMessage, and onError sets a specific reason unconditionally - so
      // folding the countdown into `error` would either be swallowed by the
      // `prev ??` guard above or clobber that specific reason. Separate fields
      // show both.
      setStatusMessage(`Reconnecting in ${delaySec}s (attempt ${attempt}/${MAX_AUTO_RECONNECTS})…`);
      setStatusTracked('error');
      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null;
        const retarget = retargetRef.current;
        if (!retarget) return;
        // Treat this like a retarget hop so accumulated sentences and mute
        // state survive the reconnect.
        isRetargetingRef.current = true;
        try {
          setError(null);
          setStatusMessage(null);
          retarget();
        } finally {
          isRetargetingRef.current = false;
        }
      }, delaySec * 1000);
      return true;
    },
    [setStatusTracked],
  );

  // Rearm / diagnostic dispatch for config-changed events. The socket class
  // owns the branching (error rearm, pending-backoff shortcut, active-session
  // host-change warn/retarget) so this listener just forwards the current
  // install-gate predicate. See TranscriptionSocket.handleConfigChanged.
  useEffect(() => {
    return apiClient.onConfigChanged(() => {
      socketRef.current?.handleConfigChanged(apiClient.isBaseUrlConfigured());
    });
  }, []);

  const handleMessage = useCallback(
    (msg: ServerMessage) => {
      switch (msg.type) {
        case 'auth_ok':
          // GH-237: only send `start` on the FIRST connect of a user session.
          // After the engine has acknowledged us, an auth_ok is an auto-reconnect
          // and re-sending `start` would resurrect the session (see
          // sessionEstablishedRef).
          if (sessionEstablishedRef.current) break;
          // Authenticated — send start with config
          setStatusTracked('starting');
          socketRef.current?.sendJSON({
            type: 'start',
            data: {
              config: {
                language: startOptsRef.current.language,
                model: startOptsRef.current.model,
                translation_enabled: startOptsRef.current.translate ?? false,
                translation_target_language: startOptsRef.current.translationTarget ?? 'en',
                post_speech_silence_duration: startOptsRef.current.gracePeriodSeconds,
              },
            },
          });
          break;

        case 'status':
          // Model loading/swapping progress
          setStatusMessage((msg.data?.message as string) ?? null);
          break;

        case 'state': {
          // GH-237: the engine has acknowledged our start — close the start-gate
          // so a later auto-reconnect cannot resurrect the session.
          sessionEstablishedRef.current = true;
          const state = msg.data?.state as string;
          if (state === 'LISTENING') {
            setStatusTracked('listening');
            setStatusMessage(null);
            // A confirmed-good session resets the auto-reconnect budget so a
            // later, unrelated error gets the full retry allowance again.
            reconnectAttemptsRef.current = 0;
            // Start audio capture once engine is ready. Stop any previous
            // instance first — GH-230: replacing a still-starting capture
            // without stopping it would orphan its loopback hold and stream.
            if (!captureRef.current?.isCapturing) {
              captureRef.current?.stop();
              captureRef.current = new AudioCapture((chunk) => {
                socketRef.current?.sendAudio(chunk);
              });
              captureRef.current
                .start({
                  deviceId: startOptsRef.current.deviceId,
                  systemAudio: startOptsRef.current.systemAudio,
                  monitorSinkName: startOptsRef.current.monitorSinkName,
                  mixMicWithSystem: startOptsRef.current.mixMicWithSystem,
                  mixMicDeviceId: startOptsRef.current.mixMicDeviceId,
                })
                .then(() => {
                  setAnalyser(captureRef.current?.analyser ?? null);
                })
                .catch((err) => {
                  // A stop() that raced the start — the stop already put the
                  // state machine where it belongs; don't flip to error.
                  if (err instanceof Error && err.name === 'AbortError') return;
                  setError(err instanceof Error ? err.message : 'Audio capture failed');
                  setStatusTracked('error');
                  socketRef.current?.disconnect();
                });
            }
          } else if (state === 'PROCESSING') {
            setStatusTracked('processing');
          } else if (state === 'STARTING') {
            // The backend is retrying a transient transcription error
            // (rebuilding the recorder) — reflect that instead of leaving
            // the UI on a stale 'listening'/'processing' while audio is
            // silently dropped underneath it until the rebuild completes.
            setStatusTracked('starting');
            setStatusMessage('Recovering from a transcription error…');
          } else if (state === 'ERROR') {
            // GH-271: the engine reports a terminal failure out of band. This
            // branch used to be missing, so an engine that died mid-session
            // left the UI sitting in listening forever with audio still
            // streaming into a dead session.
            captureRef.current?.stop();
            setAnalyser(null);
            setStatusMessage(null);
            // Retry the whole session with backoff — the backend already
            // retries transient recorder errors on its own (with its own
            // backoff/watchdog), so reaching ERROR here means it gave up;
            // a fresh session is the next thing worth trying.
            const scheduled = scheduleReconnect(
              'Live mode stopped because the engine reported an error.',
            );
            if (!scheduled) {
              // Out of attempts — keep any more specific message an `error`
              // frame already delivered (or is about to): the two frames
              // race, and the specific one always wins.
              setError(
                (prev) =>
                  prev ?? 'Live Mode stopped after too many errors. Start again manually to retry.',
              );
              setStatusTracked('error');
            }
          } else if (state === 'STOPPED') {
            // GH-230: a server-initiated stop must tear down capture too —
            // leaving it running kept streaming audio into a dead session and
            // stranded the Linux loopback module (mic indicator stayed lit).
            captureRef.current?.stop();
            setAnalyser(null);
            setStatusTracked('idle');
            setStatusMessage(null);
          }
          break;
        }

        case 'sentence':
          setSentences((prev) => [
            ...prev,
            {
              text: (msg.data?.text as string) ?? '',
              timestamp: Date.now(),
            },
          ]);
          setPartial(''); // Clear partial when sentence completes
          break;

        case 'partial':
          setPartial((msg.data?.text as string) ?? '');
          break;

        case 'history':
          // Restore history from server
          if (Array.isArray(msg.data?.sentences)) {
            setSentences(
              (msg.data.sentences as string[]).map((text) => ({
                text,
                timestamp: Date.now(),
              })),
            );
          }
          break;

        case 'history_cleared':
          setSentences([]);
          break;

        case 'error': {
          const message = (msg.data?.message as string) ?? 'Live mode error';
          // The single-session slot is released only after the PREVIOUS
          // connection's cleanup (including a main-model reload) finishes,
          // so a reconnect racing that teardown is routinely rejected here
          // — it is transient, not a reason to give up. Retry it through the
          // same budget as an engine ERROR instead of stopping cold.
          if (message.includes('Another Live Mode session is already active')) {
            if (scheduleReconnect(message)) break;
          }
          setError(message);
          setStatusTracked('error');
          captureRef.current?.stop();
          setAnalyser(null);
          setStatusMessage(null);
          break;
        }
      }
    },
    [setStatusTracked, scheduleReconnect],
  );

  const start = useCallback(
    (options?: LiveStartOptions) => {
      setError(null);
      setPartial('');
      // A retarget hop is a continuation of the same user session, not a new
      // one — preserve already-accumulated sentences and unmute state so the
      // transcript doesn't visually reset on host change.
      if (!isRetargetingRef.current) {
        setSentences([]);
        setMuted(false);
        // A fresh manual start resets the auto-reconnect budget.
        reconnectAttemptsRef.current = 0;
      }
      // Cancel any pending auto-reconnect timer — the user (or a retarget
      // hop) is already starting a new session before the countdown expired.
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      setStatusMessage(null);
      startOptsRef.current = options ?? {};
      // GH-237: a user-initiated session reopens the start-gate.
      sessionEstablishedRef.current = false;

      setStatusTracked('connecting');

      socketRef.current?.disconnect();
      socketRef.current = new TranscriptionSocket('/ws/live', {
        onMessage: handleMessage,
        onError: (err) => {
          setError(err);
          setStatusTracked('error');
          captureRef.current?.stop();
          setAnalyser(null);
        },
        onClose: () => {
          // During a retarget the onClose of the OLD socket fires AFTER we've
          // already installed the new socket. Swallow the status reset so the
          // UI doesn't flip to 'idle' between hops.
          if (isRetargetingRef.current) return;
          captureRef.current?.stop();
          setAnalyser(null);
          // A reconnect is already armed - an engine ERROR, or a session-busy
          // rejection that the server follows with a close. Leave the status
          // and the countdown alone so the UI keeps showing the pending retry
          // instead of flipping to idle underneath it.
          if (reconnectTimerRef.current !== null) return;
          setStatusMessage(null);
          // GH-237: if the drop happened while a session was actively running
          // (listening/processing), it is an unrecoverable interruption — the
          // server cannot resume, and the start-gate now blocks the reconnect
          // from resurrecting it. Fail loudly and halt the reconnect. A drop
          // before the engine acknowledged us (connecting/starting) or after a
          // clean STOPPED (idle) is not fatal: let the reconnect re-establish.
          if (statusRef.current === 'listening' || statusRef.current === 'processing') {
            setError('Connection to the server was lost. Live mode stopped.');
            setStatusTracked('error');
            socketRef.current?.disconnect();
            return;
          }
          setStatusTracked('idle');
        },
        onHostMismatch: () => {
          // Drain + retarget for EC-6: the user changed hosts while live mode
          // was recording. Stop frames to the old host, drain its VAD buffer
          // via `stop`, tear down cleanly, then reconnect against the new URL
          // with the same options. Deferred until microtask so the socket's
          // handleConfigChanged call can return cleanly before we destroy it.
          const retarget = retargetRef.current;
          if (!retarget) return;
          isRetargetingRef.current = true;
          try {
            captureRef.current?.stop();
            setAnalyser(null);
            socketRef.current?.sendJSON({ type: 'stop' });
          } catch {
            // sendJSON/stop is best-effort — if the socket already closed,
            // there's nothing to drain. Retarget anyway.
          }
          queueMicrotask(() => {
            try {
              retarget();
            } finally {
              isRetargetingRef.current = false;
            }
          });
        },
      });

      // vulkan-wsl2 (Windows): the native whisper-server.exe serves ONE model
      // per launch and can't hot-swap, so relaunch it onto the live model BEFORE
      // connecting — otherwise the backend would transcribe against the main
      // model. The IPC self-gates (no-op off vulkan-wsl2 / for non-GGML models),
      // so this only defers the connect when a native switch is actually in play.
      // When the IPC is absent (web build, or already-correct model), connect
      // synchronously to preserve existing behaviour.
      const sock = socketRef.current;
      const switchModel = window.electronAPI?.docker?.switchWhisperServerModel;
      if (switchModel) {
        const requested = startOptsRef.current.whisperServerModel ?? null;
        console.info('[useLiveMode] requesting whisper-server model switch:', requested);
        void switchModel(requested)
          .then((res) => {
            console.info('[useLiveMode] whisper-server model switch result:', res);
          })
          .catch((err) => {
            // A relaunch failure is not fatal here: the backend has its own
            // sidecar-readiness wait, and connecting still surfaces a clear
            // server-side error if the model truly can't serve. Log and proceed.
            console.warn('[useLiveMode] whisper-server model switch failed:', err);
          })
          .finally(() => {
            // Only connect if this socket is still current — a stop()/retarget
            // between the switch call and its resolution supersedes it.
            if (socketRef.current === sock) sock.connect();
          });
      } else {
        sock.connect();
      }
    },
    [handleMessage, setStatusTracked],
  );

  // Keep the retarget ref pointed at the latest `start` closure. Updated every
  // time `start` is recreated (i.e. when handleMessage changes). Without this
  // the onHostMismatch callback would capture a stale `start` reference.
  useEffect(() => {
    retargetRef.current = () => start(startOptsRef.current);
  }, [start]);

  const stop = useCallback(() => {
    // A manual stop supersedes any pending auto-reconnect.
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    reconnectAttemptsRef.current = 0;
    socketRef.current?.sendJSON({ type: 'stop' });
    socketRef.current?.disconnect(); // sets intentionalDisconnect=true, prevents reconnect loop
    captureRef.current?.stop();
    setAnalyser(null);
    setStatusMessage(null);
    // GH-237: user stop reopens the start-gate for the next session.
    sessionEstablishedRef.current = false;
    setStatusTracked('idle');
    // vulkan-wsl2: restore the native whisper-server.exe to the main model the
    // live session displaced (pass null → the launch/default model). Best-effort
    // and self-gating; a no-op off vulkan-wsl2. Runs in the background — the next
    // main transcription won't begin until the user initiates it, by which time
    // the (few-second) relaunch has completed.
    void window.electronAPI?.docker?.switchWhisperServerModel?.(null).catch((err) => {
      console.warn('[useLiveMode] whisper-server main-model restore failed:', err);
    });
  }, [setStatusTracked]);

  const toggleMute = useCallback(() => {
    setMuted((prev) => {
      const next = !prev;
      if (next) {
        captureRef.current?.mute();
      } else {
        captureRef.current?.unmute();
      }
      return next;
    });
  }, []);

  const setGain = useCallback((value: number) => {
    captureRef.current?.setGain(value);
  }, []);

  const clearHistory = useCallback(() => {
    socketRef.current?.sendJSON({ type: 'clear_history' });
    setSentences([]);
    setPartial('');
  }, []);

  const getText = useCallback(() => {
    return sentences.map((s) => s.text).join(' ');
  }, [sentences]);

  return {
    status,
    sentences,
    partial,
    statusMessage,
    error,
    analyser,
    muted,
    start,
    stop,
    toggleMute,
    setGain,
    clearHistory,
    getText,
  };
}
