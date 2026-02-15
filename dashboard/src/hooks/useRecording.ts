/**
 * useRecording — fetches a single recording's detail + transcription.
 */

import { useState, useEffect, useCallback } from 'react';
import { apiClient } from '../api/client';
import type { RecordingDetail, RecordingTranscription } from '../api/types';

export interface RecordingState {
  recording: RecordingDetail | null;
  transcription: RecordingTranscription | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
  /** Get the streaming audio URL for this recording */
  audioUrl: string | null;
}

export function useRecording(recordingId: number | null): RecordingState {
  const [recording, setRecording] = useState<RecordingDetail | null>(null);
  const [transcription, setTranscription] = useState<RecordingTranscription | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    if (recordingId === null) {
      setRecording(null);
      setTranscription(null);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const [detail, trans] = await Promise.all([
        apiClient.getRecording(recordingId),
        apiClient.getRecordingTranscription(recordingId),
      ]);
      setRecording(detail);
      setTranscription(trans);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load recording');
      setRecording(null);
      setTranscription(null);
    } finally {
      setLoading(false);
    }
  }, [recordingId]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  const audioUrl = recordingId !== null ? apiClient.getAudioUrl(recordingId) : null;

  return { recording, transcription, loading, error, refresh: fetch, audioUrl };
}
