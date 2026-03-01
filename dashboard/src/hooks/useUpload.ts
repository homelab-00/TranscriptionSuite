/**
 * useUpload — handles file upload + transcription to notebook.
 * Submits the file (gets 202 back instantly), then polls for the result.
 */

import { useState, useCallback, useRef } from 'react';
import { apiClient } from '../api/client';
import type { TranscriptionUploadOptions, UploadResponse, JobTrackerResult } from '../api/types';

export type UploadStatus = 'idle' | 'uploading' | 'success' | 'error';

export interface UploadState {
  status: UploadStatus;
  result: UploadResponse | null;
  error: string | null;
  upload: (file: File, options?: TranscriptionUploadOptions) => Promise<void>;
  reset: () => void;
}

/** Poll interval for checking transcription job result */
const POLL_INTERVAL_MS = 5_000;
const MAX_POLLS = (24 * 60 * 60 * 1000) / POLL_INTERVAL_MS; // 24 hours

async function pollForResult(
  serverJobId: string,
  abortRef: React.RefObject<boolean>,
): Promise<JobTrackerResult> {
  for (let i = 0; i < MAX_POLLS; i++) {
    if (abortRef.current) throw new Error('Upload aborted');

    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));

    try {
      const status = await apiClient.getAdminStatus();
      const jobTracker = (status?.models as any)?.job_tracker;

      if (jobTracker?.is_busy && jobTracker?.active_job_id === serverJobId) continue;

      const result = jobTracker?.result as JobTrackerResult | undefined;
      if (result && result.job_id === serverJobId) return result;

      if (!jobTracker?.is_busy && (!result || result.job_id !== serverJobId)) {
        throw new Error('Transcription job lost — server may have restarted');
      }
    } catch (err) {
      if (
        err instanceof Error &&
        (err.message.includes('job lost') || err.message.includes('aborted'))
      )
        throw err;
      console.warn('Poll error (will retry):', err);
    }
  }
  throw new Error('Transcription timed out after 24 hours');
}

export function useUpload(): UploadState {
  const [status, setStatus] = useState<UploadStatus>('idle');
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef(false);

  const upload = useCallback(async (file: File, options?: TranscriptionUploadOptions) => {
    setStatus('uploading');
    setError(null);
    setResult(null);
    abortRef.current = false;
    try {
      const { job_id: serverJobId } = await apiClient.uploadAndTranscribe(file, options);
      const jobResult = await pollForResult(serverJobId, abortRef);

      if (jobResult.error) throw new Error(jobResult.error);

      const res: UploadResponse = {
        recording_id: jobResult.recording_id!,
        message: jobResult.message ?? 'Transcription complete',
        diarization: jobResult.diarization ?? { requested: false, performed: false, reason: null },
      };
      setResult(res);
      setStatus('success');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
      setStatus('error');
    }
  }, []);

  const reset = useCallback(() => {
    abortRef.current = true;
    setStatus('idle');
    setResult(null);
    setError(null);
  }, []);

  return { status, result, error, upload, reset };
}
