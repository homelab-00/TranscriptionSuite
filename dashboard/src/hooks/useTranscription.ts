/**
 * useTranscription — orchestrates one-shot transcription via /ws.
 *
 * Flow: connect → auth → start → stream audio → stop → receive "final" result.
 *
 * Returns controls and state for the SessionView's main transcription panel.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { TranscriptionSocket, ServerMessage } from '../services/websocket';
import { AudioCapture } from '../services/audioCapture';
import { apiClient } from '../api/client';

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
    translationTarget?: string;
    systemAudio?: boolean;
    monitorDeviceLabel?: string;
  }) => void;
  /** Stop recording and wait for the final result */
  stop: () => void;
  /** Reset state back to idle */
  reset: () => void;
  /** VAD state from the server */
  vadActive: boolean;
  /** Segment progress while server is processing (current/total segments) */
  processingProgress: { current: number; total: number } | null;
  /** Whether audio is muted (capture continues but chunks not sent) */
  muted: boolean;
  /** Toggle mute during recording */
  toggleMute: () => void;
  /** Set capture gain (amplification). Values >1 boost quiet sources. */
  setGain: (value: number) => void;
  /** Job ID assigned by the server for this transcription session */
  jobId: string | null;
  /** Load an externally-fetched result into the hook (e.g. recovered from DB) */
  loadResult: (result: TranscriptionResult) => void;
}

export function useTranscription(): TranscriptionState {
  const [status, setStatus] = useState<TranscriptionStatus>('idle');
  const [result, setResult] = useState<TranscriptionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);
  const [vadActive, setVadActive] = useState(false);
  const [muted, setMuted] = useState(false);
  const [processingProgress, setProcessingProgress] = useState<{
    current: number;
    total: number;
  } | null>(null);

  const socketRef = useRef<TranscriptionSocket | null>(null);
  const captureRef = useRef<AudioCapture | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const jobIdRef = useRef<string | null>(null);
  const statusRef = useRef<TranscriptionStatus>('idle');
  // Ref-based cancel flag for the disconnect poll loop — accessible from the
  // useEffect cleanup on unmount (a plain `let cancelled` in the onClose closure
  // cannot be reached from the cleanup function).
  const pollCancelledRef = useRef(false);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Keep statusRef in sync so onClose can read the latest status without stale closure
  const setStatusTracked = useCallback((s: TranscriptionStatus) => {
    statusRef.current = s;
    setStatus(s);
  }, []);

  const startOptsRef = useRef<{
    language?: string;
    deviceId?: string;
    translate?: boolean;
    translationTarget?: string;
    systemAudio?: boolean;
    monitorDeviceLabel?: string;
  }>({});

  // Cleanup on unmount — skip disconnect if actively recording/processing
  // so the server can finish and the poll-for-result fallback can recover
  useEffect(() => {
    return () => {
      const active = statusRef.current === 'recording' || statusRef.current === 'processing';
      if (!active) {
        pollCancelledRef.current = true;
        if (pollTimerRef.current !== null) {
          clearTimeout(pollTimerRef.current);
          pollTimerRef.current = null;
        }
        captureRef.current?.stop();
        socketRef.current?.disconnect();
      }
    };
  }, []);

  const handleMessage = useCallback(
    (msg: ServerMessage) => {
      switch (msg.type) {
        case 'auth_ok':
          // Auth succeeded — now send start
          socketRef.current?.sendJSON({
            type: 'start',
            data: {
              language: startOptsRef.current.language,
              translation_enabled: startOptsRef.current.translate ?? false,
              translation_target_language: startOptsRef.current.translationTarget ?? 'en',
            },
          });
          break;

        case 'session_started':
          if (msg.data?.job_id) {
            const id = msg.data.job_id as string;
            jobIdRef.current = id;
            setJobId(id);
          }
          setStatusTracked('recording');
          {
            const rawCaptureRate = msg.data?.capture_sample_rate_hz;
            const captureSampleRateHz =
              typeof rawCaptureRate === 'number' &&
              Number.isFinite(rawCaptureRate) &&
              rawCaptureRate > 0
                ? Math.round(rawCaptureRate)
                : 16000;
            socketRef.current?.setAudioSampleRate(captureSampleRateHz);
            // Begin audio capture
            captureRef.current = new AudioCapture((chunk) => {
              socketRef.current?.sendAudio(chunk);
            });
            captureRef.current
              .start({
                deviceId: startOptsRef.current.deviceId,
                systemAudio: startOptsRef.current.systemAudio,
                monitorDeviceLabel: startOptsRef.current.monitorDeviceLabel,
                targetSampleRateHz: captureSampleRateHz,
              })
              .then(() => {
                setAnalyser(captureRef.current?.analyser ?? null);
              })
              .catch((err) => {
                setError(err instanceof Error ? err.message : 'Failed to start audio capture');
                setStatus('error');
                socketRef.current?.disconnect();
              });
          }
          break;

        case 'session_busy':
          setError(
            `Server busy — ${(msg.data?.active_user as string) ?? 'another session'} is active`,
          );
          setStatusTracked('error');
          socketRef.current?.disconnect();
          break;

        case 'session_stopped':
          setStatusTracked('processing');
          setProcessingProgress(null);
          break;

        case 'processing_progress':
          setProcessingProgress({
            current: (msg.data?.current as number) ?? 0,
            total: (msg.data?.total as number) ?? 0,
          });
          break;

        case 'final':
          setResult({
            text: (msg.data?.text as string) ?? '',
            words: (msg.data?.words as TranscriptionResult['words']) ?? [],
            language: msg.data?.language as string | undefined,
            duration: msg.data?.duration as number | undefined,
          });
          setProcessingProgress(null);
          setStatusTracked('complete');
          captureRef.current?.stop();
          setAnalyser(null);
          socketRef.current?.disconnect();
          break;

        case 'result_ready': {
          // Result was too large to stream over WebSocket — fetch it via HTTP
          const job_id = msg.data?.job_id as string;
          const token = apiClient.getAuthToken();
          const authHeader = token ? { Authorization: `Bearer ${token}` } : {};
          fetch(`/api/transcribe/result/${job_id}`, { headers: authHeader })
            .then(async (resp) => {
              if (resp.status === 200) {
                const data = await resp.json();
                const r = data.result ?? {};
                setResult({
                  text: r.text ?? '',
                  words: r.words ?? [],
                  language: r.language,
                  duration: r.duration,
                });
                setProcessingProgress(null);
                setStatusTracked('complete');
              } else {
                setError('Result too large to stream — fetch failed');
                setStatusTracked('error');
              }
            })
            .catch(() => {
              setError('Result too large to stream — fetch failed');
              setStatusTracked('error');
            });
          captureRef.current?.stop();
          setAnalyser(null);
          // Clear jobIdRef before disconnect so onClose skips the poll loop
          // (onClose captures jobIdRef.current as currentJobId — null means no poll starts)
          jobIdRef.current = null;
          setJobId(null);
          socketRef.current?.disconnect();
          break;
        }

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
          setStatusTracked('error');
          captureRef.current?.stop();
          setAnalyser(null);
          break;
      }
    },
    [setStatusTracked],
  );

  const start = useCallback(
    (options?: {
      language?: string;
      deviceId?: string;
      translate?: boolean;
      translationTarget?: string;
      systemAudio?: boolean;
    }) => {
      // Reset previous state
      setResult(null);
      setError(null);
      setVadActive(false);
      setMuted(false);
      jobIdRef.current = null;
      setJobId(null);
      startOptsRef.current = options ?? {};

      setStatusTracked('connecting');

      socketRef.current?.disconnect();
      socketRef.current = new TranscriptionSocket('/ws', {
        onMessage: handleMessage,
        onError: (err) => {
          setError(err);
          setStatusTracked('error');
          captureRef.current?.stop();
          setAnalyser(null);
        },
        onClose: () => {
          captureRef.current?.stop();
          setAnalyser(null);

          // If we were processing when the socket closed, poll for the result
          const currentJobId = jobIdRef.current;
          if (statusRef.current === 'processing' && currentJobId) {
            let pollRetries = 0;
            let networkErrors = 0;
            const maxRetries = 10;
            pollCancelledRef.current = false;

            // Cancel polling if the hook re-initialises a new session
            // (jobIdRef will be cleared by start() before a new socket is created)
            const poll = async () => {
              if (pollCancelledRef.current || jobIdRef.current !== currentJobId) return;
              try {
                const pollToken = apiClient.getAuthToken();
                const pollAuthHeader = pollToken ? { Authorization: `Bearer ${pollToken}` } : {};
                const resp = await fetch(`/api/transcribe/result/${currentJobId}`, {
                  headers: pollAuthHeader,
                });
                if (pollCancelledRef.current || jobIdRef.current !== currentJobId) return;
                if (resp.status === 200) {
                  const data = await resp.json();
                  const r = data.result ?? {};
                  setResult({
                    text: r.text ?? '',
                    words: r.words ?? [],
                    language: r.language,
                    duration: r.duration,
                  });
                  setProcessingProgress(null);
                  setStatusTracked('complete');
                  return;
                }
                if (resp.status === 202 && pollRetries < maxRetries) {
                  pollRetries++;
                  pollTimerRef.current = setTimeout(poll, 3000);
                  return;
                }
                // 410 = server says job failed
                if (resp.status === 410) {
                  setStatusTracked('error');
                  setError('Transcription failed on server');
                  return;
                }
                // 404 or unexpected — surface as error rather than silently idling
                setStatusTracked('error');
                setError('Transcription result unavailable');
              } catch {
                if (!pollCancelledRef.current && networkErrors < maxRetries) {
                  networkErrors++;
                  pollTimerRef.current = setTimeout(poll, 3000);
                } else if (!pollCancelledRef.current) {
                  setStatusTracked('error');
                  setError('Could not retrieve transcription result');
                }
              }
            };
            poll();
          }
        },
      });
      socketRef.current.connect();
    },
    [handleMessage, setStatusTracked],
  );

  const stop = useCallback(() => {
    if (status === 'recording') {
      // Tell the server to stop and produce the final result
      socketRef.current?.sendJSON({ type: 'stop' });
      // Stop audio capture immediately
      captureRef.current?.stop();
      setAnalyser(null);
      setStatusTracked('processing');
    }
  }, [status, setStatusTracked]);

  const reset = useCallback(() => {
    captureRef.current?.stop();
    socketRef.current?.disconnect();
    setStatusTracked('idle');
    setResult(null);
    setError(null);
    setAnalyser(null);
    setVadActive(false);
    setMuted(false);
    setProcessingProgress(null);
    jobIdRef.current = null;
    setJobId(null);
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

  const loadResult = useCallback(
    (r: TranscriptionResult) => {
      setResult(r);
      setStatusTracked('complete');
    },
    [setStatusTracked],
  );

  return {
    status,
    result,
    error,
    analyser,
    start,
    stop,
    reset,
    vadActive,
    muted,
    toggleMute,
    setGain,
    processingProgress,
    jobId,
    loadResult,
  };
}
