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
  monitorDeviceLabel?: string;
}

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

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      captureRef.current?.stop();
      socketRef.current?.disconnect();
    };
  }, []);

  // Rearm / diagnostic dispatch for config-changed events. The socket class
  // owns the branching (error rearm, pending-backoff shortcut, active-session
  // host-change warn/retarget) so this listener just forwards the current
  // install-gate predicate. See TranscriptionSocket.handleConfigChanged.
  useEffect(() => {
    return apiClient.onConfigChanged(() => {
      socketRef.current?.handleConfigChanged(apiClient.isBaseUrlConfigured());
    });
  }, []);

  const handleMessage = useCallback((msg: ServerMessage) => {
    switch (msg.type) {
      case 'auth_ok':
        // Authenticated — send start with config
        setStatus('starting');
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
        const state = msg.data?.state as string;
        if (state === 'LISTENING') {
          setStatus('listening');
          setStatusMessage(null);
          // Start audio capture once engine is ready
          if (!captureRef.current?.isCapturing) {
            captureRef.current = new AudioCapture((chunk) => {
              socketRef.current?.sendAudio(chunk);
            });
            captureRef.current
              .start({
                deviceId: startOptsRef.current.deviceId,
                systemAudio: startOptsRef.current.systemAudio,
                monitorDeviceLabel: startOptsRef.current.monitorDeviceLabel,
              })
              .then(() => {
                setAnalyser(captureRef.current?.analyser ?? null);
              })
              .catch((err) => {
                setError(err instanceof Error ? err.message : 'Audio capture failed');
                setStatus('error');
                socketRef.current?.disconnect();
              });
          }
        } else if (state === 'PROCESSING') {
          setStatus('processing');
        } else if (state === 'STOPPED') {
          setStatus('idle');
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

      case 'error':
        setError((msg.data?.message as string) ?? 'Live mode error');
        setStatus('error');
        captureRef.current?.stop();
        setAnalyser(null);
        setStatusMessage(null);
        break;
    }
  }, []);

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
      }
      setStatusMessage(null);
      startOptsRef.current = options ?? {};

      setStatus('connecting');

      socketRef.current?.disconnect();
      socketRef.current = new TranscriptionSocket('/ws/live', {
        onMessage: handleMessage,
        onError: (err) => {
          setError(err);
          setStatus('error');
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
          setStatusMessage(null);
          setStatus('idle');
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
      socketRef.current.connect();
    },
    [handleMessage],
  );

  // Keep the retarget ref pointed at the latest `start` closure. Updated every
  // time `start` is recreated (i.e. when handleMessage changes). Without this
  // the onHostMismatch callback would capture a stale `start` reference.
  useEffect(() => {
    retargetRef.current = () => start(startOptsRef.current);
  }, [start]);

  const stop = useCallback(() => {
    socketRef.current?.sendJSON({ type: 'stop' });
    socketRef.current?.disconnect(); // sets intentionalDisconnect=true, prevents reconnect loop
    captureRef.current?.stop();
    setAnalyser(null);
    setStatusMessage(null);
    setStatus('idle');
  }, []);

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
