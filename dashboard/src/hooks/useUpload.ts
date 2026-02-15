/**
 * useUpload — handles file upload + transcription to notebook.
 * Provides progress tracking via state.
 */

import { useState, useCallback } from 'react';
import { apiClient } from '../api/client';
import type { TranscriptionUploadOptions, UploadResponse } from '../api/types';

export type UploadStatus = 'idle' | 'uploading' | 'success' | 'error';

export interface UploadState {
  status: UploadStatus;
  result: UploadResponse | null;
  error: string | null;
  upload: (file: File, options?: TranscriptionUploadOptions) => Promise<void>;
  reset: () => void;
}

export function useUpload(): UploadState {
  const [status, setStatus] = useState<UploadStatus>('idle');
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const upload = useCallback(async (file: File, options?: TranscriptionUploadOptions) => {
    setStatus('uploading');
    setError(null);
    setResult(null);
    try {
      const res = await apiClient.uploadAndTranscribe(file, options);
      setResult(res);
      setStatus('success');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
      setStatus('error');
    }
  }, []);

  const reset = useCallback(() => {
    setStatus('idle');
    setResult(null);
    setError(null);
  }, []);

  return { status, result, error, upload, reset };
}
