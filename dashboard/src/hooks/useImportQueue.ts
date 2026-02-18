/**
 * useImportQueue — manages a multi-file import queue.
 *
 * Accepts multiple files, processes them one-at-a-time through the
 * server's single-slot transcription endpoint, and tracks per-file status.
 */

import { useState, useCallback, useRef } from 'react';
import { apiClient } from '../api/client';
import type { TranscriptionUploadOptions, UploadResponse } from '../api/types';

export type ImportJobStatus = 'pending' | 'processing' | 'success' | 'error';

export interface ImportJob {
  /** Unique job id */
  id: string;
  /** Original file */
  file: File;
  /** Current status */
  status: ImportJobStatus;
  /** Result on success */
  result?: UploadResponse;
  /** Error message on failure */
  error?: string;
}

export interface UseImportQueueReturn {
  /** All jobs in the queue (current + completed) */
  jobs: ImportJob[];
  /** Whether the queue is actively processing */
  isProcessing: boolean;
  /** Add files to the queue (auto-starts processing if idle) */
  addFiles: (files: File[], options?: TranscriptionUploadOptions) => void;
  /** Remove a specific job from the queue (only if pending or done) */
  removeJob: (id: string) => void;
  /** Clear all completed/errored jobs */
  clearFinished: () => void;
  /** Clear entire queue (stops processing if active) */
  clearAll: () => void;
  /** Retry a failed job */
  retryJob: (id: string) => void;
  /** Number of pending jobs */
  pendingCount: number;
  /** Number of completed jobs */
  completedCount: number;
  /** Number of failed jobs */
  errorCount: number;
}

let jobIdCounter = 0;
function nextJobId(): string {
  return `import-${Date.now()}-${++jobIdCounter}`;
}

export function useImportQueue(): UseImportQueueReturn {
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const processingRef = useRef(false);
  const optionsRef = useRef<TranscriptionUploadOptions | undefined>(undefined);
  const abortRef = useRef(false);

  const processQueue = useCallback(async () => {
    if (processingRef.current) return;
    processingRef.current = true;
    abortRef.current = false;

    // Keep processing until all jobs are done or aborted
    while (!abortRef.current) {
      // Find next pending job
      let nextJob: ImportJob | undefined;
      setJobs((prev) => {
        nextJob = prev.find((j) => j.status === 'pending');
        if (nextJob) {
          return prev.map((j) =>
            j.id === nextJob!.id ? { ...j, status: 'processing' as const } : j,
          );
        }
        return prev;
      });

      if (!nextJob) break;
      const jobId = nextJob.id;
      const file = nextJob.file;

      try {
        const result = await apiClient.uploadAndTranscribe(file, optionsRef.current);
        setJobs((prev) =>
          prev.map((j) => (j.id === jobId ? { ...j, status: 'success' as const, result } : j)),
        );
      } catch (err) {
        const errorMsg = err instanceof Error ? err.message : 'Upload failed';
        setJobs((prev) =>
          prev.map((j) =>
            j.id === jobId ? { ...j, status: 'error' as const, error: errorMsg } : j,
          ),
        );
      }

      // Small delay between jobs to let the server breathe
      await new Promise((r) => setTimeout(r, 500));
    }

    processingRef.current = false;
  }, []);

  const addFiles = useCallback(
    (files: File[], options?: TranscriptionUploadOptions) => {
      optionsRef.current = options;
      const newJobs: ImportJob[] = files.map((file) => ({
        id: nextJobId(),
        file,
        status: 'pending' as const,
      }));
      setJobs((prev) => [...prev, ...newJobs]);
      // Kick off processing (will no-op if already running)
      setTimeout(() => processQueue(), 0);
    },
    [processQueue],
  );

  const removeJob = useCallback((id: string) => {
    setJobs((prev) => prev.filter((j) => j.id !== id || j.status === 'processing'));
  }, []);

  const clearFinished = useCallback(() => {
    setJobs((prev) => prev.filter((j) => j.status === 'pending' || j.status === 'processing'));
  }, []);

  const clearAll = useCallback(() => {
    abortRef.current = true;
    setJobs([]);
  }, []);

  const retryJob = useCallback(
    (id: string) => {
      setJobs((prev) =>
        prev.map((j) =>
          j.id === id && j.status === 'error'
            ? { ...j, status: 'pending' as const, error: undefined }
            : j,
        ),
      );
      setTimeout(() => processQueue(), 0);
    },
    [processQueue],
  );

  const pendingCount = jobs.filter((j) => j.status === 'pending').length;
  const completedCount = jobs.filter((j) => j.status === 'success').length;
  const errorCount = jobs.filter((j) => j.status === 'error').length;
  const isProcessing = jobs.some((j) => j.status === 'processing');

  return {
    jobs,
    isProcessing,
    addFiles,
    removeJob,
    clearFinished,
    clearAll,
    retryJob,
    pendingCount,
    completedCount,
    errorCount,
  };
}
