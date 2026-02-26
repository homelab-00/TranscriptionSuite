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
  /** Upload/transcription options captured when the job was queued */
  options?: TranscriptionUploadOptions;
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

interface UseImportQueueConfig {
  /** Called when a queued upload completes successfully */
  onJobSuccess?: (job: ImportJob, result: UploadResponse) => void;
  /** Called when a queued upload fails */
  onJobError?: (job: ImportJob, error: string) => void;
}

let jobIdCounter = 0;
function nextJobId(): string {
  return `import-${Date.now()}-${++jobIdCounter}`;
}

export function useImportQueue(config?: UseImportQueueConfig): UseImportQueueReturn {
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const jobsRef = useRef<ImportJob[]>([]);
  const processingRef = useRef(false);
  const abortRef = useRef(false);
  const callbacksRef = useRef<UseImportQueueConfig | undefined>(config);
  callbacksRef.current = config;

  const updateJobs = useCallback((updater: (prev: ImportJob[]) => ImportJob[]) => {
    const next = updater(jobsRef.current);
    jobsRef.current = next;
    setJobs(next);
    return next;
  }, []);

  const processQueue = useCallback(async () => {
    if (processingRef.current) return;
    processingRef.current = true;
    abortRef.current = false;

    try {
      // Keep processing until all jobs are done or aborted
      while (!abortRef.current) {
        const nextJob = jobsRef.current.find((j) => j.status === 'pending');
        if (!nextJob) break;

        const jobId = nextJob.id;
        const file = nextJob.file;
        const jobOptions = nextJob.options;

        updateJobs((prev) =>
          prev.map((j) =>
            j.id === jobId ? { ...j, status: 'processing' as const, error: undefined } : j,
          ),
        );

        try {
          const result = await apiClient.uploadAndTranscribe(file, jobOptions);
          updateJobs((prev) =>
            prev.map((j) => (j.id === jobId ? { ...j, status: 'success' as const, result } : j)),
          );
          callbacksRef.current?.onJobSuccess?.(nextJob, result);
        } catch (err) {
          const errorMsg = err instanceof Error ? err.message : 'Upload failed';
          updateJobs((prev) =>
            prev.map((j) =>
              j.id === jobId ? { ...j, status: 'error' as const, error: errorMsg } : j,
            ),
          );
          callbacksRef.current?.onJobError?.(nextJob, errorMsg);
        }

        if (abortRef.current) break;

        // Small delay between jobs to let the server breathe
        await new Promise((r) => setTimeout(r, 500));
      }
    } finally {
      processingRef.current = false;
    }
  }, [updateJobs]);

  const addFiles = useCallback(
    (files: File[], options?: TranscriptionUploadOptions) => {
      const capturedOptions = options ? { ...options } : undefined;
      const newJobs: ImportJob[] = files.map((file) => ({
        id: nextJobId(),
        file,
        options: capturedOptions,
        status: 'pending' as const,
      }));
      updateJobs((prev) => [...prev, ...newJobs]);
      // Kick off processing (will no-op if already running)
      setTimeout(() => processQueue(), 0);
    },
    [processQueue, updateJobs],
  );

  const removeJob = useCallback(
    (id: string) => {
      updateJobs((prev) => prev.filter((j) => j.id !== id || j.status === 'processing'));
    },
    [updateJobs],
  );

  const clearFinished = useCallback(() => {
    updateJobs((prev) => prev.filter((j) => j.status === 'pending' || j.status === 'processing'));
  }, [updateJobs]);

  const clearAll = useCallback(() => {
    abortRef.current = true;
    updateJobs(() => []);
  }, [updateJobs]);

  const retryJob = useCallback(
    (id: string) => {
      updateJobs((prev) =>
        prev.map((j) =>
          j.id === id && j.status === 'error'
            ? { ...j, status: 'pending' as const, error: undefined }
            : j,
        ),
      );
      setTimeout(() => processQueue(), 0);
    },
    [processQueue, updateJobs],
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
