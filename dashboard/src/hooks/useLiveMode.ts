/**
 * useLiveMode — orchestrates continuous live transcription via /ws/live.
 *
 * Flow: connect → auth → start → stream audio → receive partial/sentence in real-time.
 * Sentences accumulate; the latest partial is shown as in-progress text.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
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
  /** Clear accumulated sentences */
  clearHistory: () => void;
  /** Copy all sentences as text */
  getText: () => string;
}

export interface LiveStartOptions {
  language?: string;
  deviceId?: string;
  translate?: boolean;
  model?: string;
  systemAudio?: boolean;
  desktopSourceId?: string;
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

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      captureRef.current?.stop();
      socketRef.current?.disconnect();
    };
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
              translation_target_language: 'en',
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
                desktopSourceId: startOptsRef.current.desktopSourceId,
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
        break;
    }
  }, []);

  const start = useCallback(
    (options?: LiveStartOptions) => {
      setError(null);
      setPartial('');
      setSentences([]);
      setStatusMessage(null);
      setMuted(false);
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
          captureRef.current?.stop();
          setAnalyser(null);
          setStatus('idle');
        },
      });
      socketRef.current.connect();
    },
    [handleMessage],
  );

  const stop = useCallback(() => {
    socketRef.current?.sendJSON({ type: 'stop' });
    captureRef.current?.stop();
    setAnalyser(null);
    setPartial('');
    // Status will be set to 'idle' when we receive the state STOPPED message or onClose
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
    clearHistory,
    getText,
  };
}
