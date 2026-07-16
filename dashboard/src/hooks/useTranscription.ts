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
  /**
   * True when the backend salvaged an INCOMPLETE transcript — the sidecar failed
   * partway through long audio, or the user cancelled mid-file. The text stops
   * early, so this must be surfaced: the job is stored as 'completed', and
   * without a visible banner the user cannot tell a truncated transcript from a
   * whole one.
   */
  partial?: boolean;
  /** Human-readable reason the transcript is incomplete. */
  partialReason?: string | null;
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
    /** Save the finished recording to the Audio Notebook (GH-199). */
    autoAddToNotebook?: boolean;
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
  /** Ephemeral "last N seconds" preview text (null until a preview has run) */
  previewText: string | null;
  /** Detected language of the most recent preview */
  previewLanguage?: string;
  /** Actual seconds of audio transcribed by the most recent preview */
  previewSeconds: number | null;
  /** Whether a preview refresh is currently in flight */
  previewLoading: boolean;
  /** Error message from the most recent preview attempt */
  previewError: string | null;
  /** Whether the rolling preview loop is running */
  previewActive: boolean;
  /** Start the rolling preview of the last `durationSeconds` of audio */
  startPreview: (durationSeconds: number) => void;
  /** Stop the rolling preview and clear its pane state */
  stopPreview: () => void;
}

// Rolling-preview cadence: refresh every 5s measured send-to-send. The
// adaptive delay in the preview_result handler stretches this for slow
// models so transcription never exceeds a ~50% duty cycle.
const PREVIEW_REFRESH_BASE_MS = 5000;

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
  const [previewText, setPreviewText] = useState<string | null>(null);
  const [previewLanguage, setPreviewLanguage] = useState<string | undefined>(undefined);
  const [previewSeconds, setPreviewSeconds] = useState<number | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewActive, setPreviewActive] = useState(false);
  // Ref guard so refresh scheduling can reject overlapping requests without
  // a stale-closure read of previewLoading.
  const previewLoadingRef = useRef(false);
  // Ref mirror of previewActive for the WS message handler and timer callbacks.
  const previewActiveRef = useRef(false);
  // Window length the active rolling preview was started with.
  const previewDurationRef = useRef(20);
  // Date.now() when the in-flight refresh was sent — drives the adaptive delay.
  const previewSentAtRef = useRef(0);
  const previewTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
    /** Active recording-profile id (FR18). Snapshotted server-side at job start. */
    profileId?: number | null;
    /** Save the finished recording to the Audio Notebook (GH-199). */
    autoAddToNotebook?: boolean;
  }>({});

  // Cleanup on unmount — skip disconnect if actively recording/processing
  // so the server can finish and the poll-for-result fallback can recover
  useEffect(() => {
    return () => {
      // Always kill a pending preview refresh — nothing is listening for the
      // result after unmount, and previews are trivially reproducible.
      if (previewTimerRef.current !== null) {
        clearTimeout(previewTimerRef.current);
        previewTimerRef.current = null;
      }
      previewActiveRef.current = false;
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

  // Rearm / diagnostic dispatch for config-changed events. The socket class
  // owns the branching (error rearm, pending-backoff shortcut, active-session
  // host-change warn) so this listener just forwards the current install-gate
  // predicate. See TranscriptionSocket.handleConfigChanged for each branch.
  useEffect(() => {
    return apiClient.onConfigChanged(() => {
      socketRef.current?.handleConfigChanged(apiClient.isBaseUrlConfigured());
    });
  }, []);

  // Halt the rolling preview loop (flag + pending timer) without touching the
  // pane state — preview_error keeps its message visible after the loop dies.
  const haltPreviewLoop = useCallback(() => {
    previewActiveRef.current = false;
    setPreviewActive(false);
    if (previewTimerRef.current !== null) {
      clearTimeout(previewTimerRef.current);
      previewTimerRef.current = null;
    }
  }, []);

  const sendPreviewRequest = useCallback(() => {
    if (!previewActiveRef.current || statusRef.current !== 'recording') return;
    // Reject overlapping requests (server also guards, this avoids spamming).
    if (previewLoadingRef.current) return;
    previewLoadingRef.current = true;
    setPreviewLoading(true);
    previewSentAtRef.current = Date.now();
    socketRef.current?.sendJSON({
      type: 'preview',
      data: { duration_seconds: previewDurationRef.current },
    });
  }, []);

  const stopPreview = useCallback(() => {
    haltPreviewLoop();
    // previewLoadingRef is intentionally NOT cleared: it tracks whether a
    // request is still on the wire. The socket stays open, so the server's
    // response WILL arrive and clear it — and until then a new startPreview
    // must not send a second 'preview' (the server rejects overlaps).
    setPreviewLoading(false);
    setPreviewText(null);
    setPreviewLanguage(undefined);
    setPreviewSeconds(null);
    setPreviewError(null);
  }, [haltPreviewLoop]);

  const startPreview = useCallback(
    (durationSeconds: number) => {
      // Preview only makes sense during an active recording; ignore otherwise.
      if (statusRef.current !== 'recording') return;
      if (previewActiveRef.current) return;
      previewActiveRef.current = true;
      setPreviewActive(true);
      setPreviewError(null);
      previewDurationRef.current = durationSeconds;
      if (previewLoadingRef.current) {
        // A response from before a quick off/on toggle is still on the wire.
        // Adopt it: the preview_result handler sees the loop active again,
        // displays it, and schedules the next refresh. Sending now would be
        // rejected server-side ('Preview already in progress') and the
        // resulting preview_error would spuriously kill the new loop.
        setPreviewLoading(true);
        return;
      }
      sendPreviewRequest();
    },
    [sendPreviewRequest],
  );

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
              // Story 1.3 — server snapshots the profile at job start when present.
              profile_id: startOptsRef.current.profileId ?? null,
              // GH-199: server promotes the finished recording into the Notebook.
              auto_add_to_notebook: startOptsRef.current.autoAddToNotebook ?? false,
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
            partial: (msg.data?.partial as boolean | undefined) ?? false,
            partialReason: (msg.data?.partial_reason as string | null | undefined) ?? null,
          });
          setProcessingProgress(null);
          setStatusTracked('complete');
          captureRef.current?.stop();
          setAnalyser(null);
          socketRef.current?.disconnect();
          break;

        case 'result_ready': {
          // Result was too large to stream over WebSocket — fetch it via HTTP.
          // Must go through apiClient (absolute base URL): a relative fetch
          // resolves against the packaged renderer file:// origin and never
          // reaches the backend (GH-202).
          const job_id = msg.data?.job_id as string;
          apiClient
            .fetchTranscriptionResult(job_id)
            .then(async (resp) => {
              if (resp.status === 200) {
                const data = await resp.json();
                const r = data.result ?? {};
                setResult({
                  text: r.text ?? '',
                  words: r.words ?? [],
                  language: r.language,
                  duration: r.duration,
                  partial: r.partial ?? false,
                  partialReason: r.partial_reason ?? null,
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

        case 'preview_result': {
          previewLoadingRef.current = false;
          setPreviewLoading(false);
          // A late result landing after stopPreview() — the pane is already
          // cleared and hidden; don't resurrect it.
          if (!previewActiveRef.current) break;
          setPreviewText((msg.data?.text as string) ?? '');
          setPreviewLanguage(msg.data?.language as string | undefined);
          setPreviewSeconds((msg.data?.actual_seconds as number) ?? null);
          setPreviewError(null);
          if (statusRef.current === 'recording') {
            // Aim for one refresh every PREVIEW_REFRESH_BASE_MS send-to-send,
            // but a refresh that took T ms waits at least T ms before the next
            // one, capping transcription at a ~50% duty cycle on slow models.
            const elapsedMs = Date.now() - previewSentAtRef.current;
            const delayMs = Math.max(PREVIEW_REFRESH_BASE_MS - elapsedMs, elapsedMs);
            // Defensive: never leave two refresh timers alive.
            if (previewTimerRef.current !== null) {
              clearTimeout(previewTimerRef.current);
            }
            previewTimerRef.current = setTimeout(() => {
              previewTimerRef.current = null;
              sendPreviewRequest();
            }, delayMs);
          }
          break;
        }

        case 'preview_error':
          previewLoadingRef.current = false;
          setPreviewLoading(false);
          setPreviewError((msg.data?.message as string) ?? 'Preview failed');
          // A failed refresh ends the loop; the user re-toggles to retry.
          haltPreviewLoop();
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
          setStatusTracked('error');
          haltPreviewLoop();
          previewLoadingRef.current = false;
          setPreviewLoading(false);
          captureRef.current?.stop();
          setAnalyser(null);
          break;
      }
    },
    [setStatusTracked, haltPreviewLoop, sendPreviewRequest],
  );

  const start = useCallback(
    (options?: {
      language?: string;
      deviceId?: string;
      translate?: boolean;
      translationTarget?: string;
      systemAudio?: boolean;
      monitorDeviceLabel?: string;
      profileId?: number | null;
      autoAddToNotebook?: boolean;
    }) => {
      // Reset previous state
      setResult(null);
      setError(null);
      setVadActive(false);
      setMuted(false);
      jobIdRef.current = null;
      setJobId(null);
      stopPreview();
      // The old socket is being replaced — any in-flight preview response is
      // lost with it, so the wire flag must not carry into the new session.
      previewLoadingRef.current = false;
      startOptsRef.current = options ?? {};

      setStatusTracked('connecting');

      socketRef.current?.disconnect();
      socketRef.current = new TranscriptionSocket('/ws', {
        onMessage: handleMessage,
        onError: (err) => {
          setError(err);
          setStatusTracked('error');
          haltPreviewLoop();
          previewLoadingRef.current = false;
          setPreviewLoading(false);
          captureRef.current?.stop();
          setAnalyser(null);
        },
        onClose: () => {
          captureRef.current?.stop();
          setAnalyser(null);
          // onClose only fires for UNINTENTIONAL closes (disconnect() detaches
          // it), so the socket is gone: an in-flight preview response can never
          // arrive. Kill the loop and the wire flag, or the stuck previewLoading
          // guard would block every future refresh — even across a reconnect.
          stopPreview();
          previewLoadingRef.current = false;

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
                // Absolute base URL via apiClient — a relative fetch fails in
                // the packaged (file://) renderer (GH-202).
                const resp = await apiClient.fetchTranscriptionResult(currentJobId);
                if (pollCancelledRef.current || jobIdRef.current !== currentJobId) return;
                if (resp.status === 200) {
                  const data = await resp.json();
                  const r = data.result ?? {};
                  setResult({
                    text: r.text ?? '',
                    words: r.words ?? [],
                    language: r.language,
                    duration: r.duration,
                    partial: r.partial ?? false,
                    partialReason: r.partial_reason ?? null,
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
    [handleMessage, setStatusTracked, stopPreview, haltPreviewLoop],
  );

  const stop = useCallback(() => {
    if (status === 'recording') {
      // The rolling preview only exists during recording — halt it so no
      // refresh fires into the processing phase.
      haltPreviewLoop();
      // Tell the server to stop and produce the final result
      socketRef.current?.sendJSON({ type: 'stop' });
      // Stop audio capture immediately
      captureRef.current?.stop();
      setAnalyser(null);
      setStatusTracked('processing');
    }
  }, [status, setStatusTracked, haltPreviewLoop]);

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
    stopPreview();
    // reset() disconnects the socket — the in-flight response (if any) is lost.
    previewLoadingRef.current = false;
  }, [setStatusTracked, stopPreview]);

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
    previewText,
    previewLanguage,
    previewSeconds,
    previewLoading,
    previewError,
    previewActive,
    startPreview,
    stopPreview,
  };
}
