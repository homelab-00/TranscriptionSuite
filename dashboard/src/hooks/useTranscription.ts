/**
 * useTranscription — orchestrates one-shot transcription via /ws.
 *
 * Flow: connect → auth → start → stream audio → stop → receive "final" result.
 *
 * Returns controls and state for the SessionView's main transcription panel.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { TranscriptionSocket, ConnectionState, ServerMessage } from '../services/websocket';
import { AudioCapture } from '../services/audioCapture';

export type TranscriptionStatus =
  | 'idle'
  | 'connecting'
  | 'recording'
  | 'processing'
  | 'complete'
  | 'error';

export interface TranscriptionResult {
  text: string;
  words: Array<{ word: string; start: number; end: number; probability?: number }>;
  language?: string;
  duration?: number;
}

export interface TranscriptionState {
  status: TranscriptionStatus;
  result: TranscriptionResult | null;
  error: string | null;
  /** AnalyserNode for visualizer (available while recording) */
  analyser: AnalyserNode | null;
  /** Begin a transcription session */
  start: (options?: {
    language?: string;
    deviceId?: string;
    translate?: boolean;
    systemAudio?: boolean;
    desktopSourceId?: string;
  }) => void;
  /** Stop recording and wait for the final result */
  stop: () => void;
  /** Reset state back to idle */
  reset: () => void;
  /** VAD state from the server */
  vadActive: boolean;
}

export function useTranscription(): TranscriptionState {
  const [status, setStatus] = useState<TranscriptionStatus>('idle');
  const [result, setResult] = useState<TranscriptionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);
  const [vadActive, setVadActive] = useState(false);

  const socketRef = useRef<TranscriptionSocket | null>(null);
  const captureRef = useRef<AudioCapture | null>(null);
  const startOptsRef = useRef<{
    language?: string;
    deviceId?: string;
    translate?: boolean;
    systemAudio?: boolean;
    desktopSourceId?: string;
  }>({});

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
        // Auth succeeded — now send start
        socketRef.current?.sendJSON({
          type: 'start',
          data: {
            language: startOptsRef.current.language,
            translation_enabled: startOptsRef.current.translate ?? false,
            translation_target_language: 'en',
          },
        });
        break;

      case 'session_started':
        setStatus('recording');
        // Begin audio capture
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
            setError(err instanceof Error ? err.message : 'Failed to start audio capture');
            setStatus('error');
            socketRef.current?.disconnect();
          });
        break;

      case 'session_busy':
        setError(
          `Server busy — ${(msg.data?.active_user as string) ?? 'another session'} is active`,
        );
        setStatus('error');
        socketRef.current?.disconnect();
        break;

      case 'session_stopped':
        setStatus('processing');
        break;

      case 'final':
        setResult({
          text: (msg.data?.text as string) ?? '',
          words: (msg.data?.words as TranscriptionResult['words']) ?? [],
          language: msg.data?.language as string | undefined,
          duration: msg.data?.duration as number | undefined,
        });
        setStatus('complete');
        captureRef.current?.stop();
        setAnalyser(null);
        socketRef.current?.disconnect();
        break;

      case 'vad_start':
      case 'vad_recording_start':
        setVadActive(true);
        break;
      case 'vad_stop':
      case 'vad_recording_stop':
        setVadActive(false);
        break;

      case 'error':
        setError((msg.data?.message as string) ?? 'Transcription error');
        setStatus('error');
        captureRef.current?.stop();
        setAnalyser(null);
        break;
    }
  }, []);

  const start = useCallback(
    (options?: {
      language?: string;
      deviceId?: string;
      translate?: boolean;
      systemAudio?: boolean;
      desktopSourceId?: string;
    }) => {
      // Reset previous state
      setResult(null);
      setError(null);
      setVadActive(false);
      startOptsRef.current = options ?? {};

      setStatus('connecting');

      socketRef.current?.disconnect();
      socketRef.current = new TranscriptionSocket('/ws', {
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
        },
      });
      socketRef.current.connect();
    },
    [handleMessage],
  );

  const stop = useCallback(() => {
    if (status === 'recording') {
      // Tell the server to stop and produce the final result
      socketRef.current?.sendJSON({ type: 'stop' });
      // Stop audio capture immediately
      captureRef.current?.stop();
      setAnalyser(null);
      setStatus('processing');
    }
  }, [status]);

  const reset = useCallback(() => {
    captureRef.current?.stop();
    socketRef.current?.disconnect();
    setStatus('idle');
    setResult(null);
    setError(null);
    setAnalyser(null);
    setVadActive(false);
  }, []);

  return { status, result, error, analyser, start, stop, reset, vadActive };
}
