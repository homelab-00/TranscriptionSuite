/**
 * useImportQueue — manages a multi-file import queue.
 *
 * Accepts multiple files, processes them one-at-a-time through the
 * server's single-slot transcription endpoint, and tracks per-file status.
 */

import { useState, useCallback, useRef } from 'react';
import { apiClient } from '../api/client';
import type { TranscriptionUploadOptions, UploadResponse, JobTrackerResult } from '../api/types';

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
  /** Update callbacks (onJobSuccess, onJobError) without re-creating the hook */
  updateCallbacks: (config: UseImportQueueConfig) => void;
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

  const updateJobs = useCallback((updater: (prev: ImportJob[]) => ImportJob[]) => {
    const next = updater(jobsRef.current);
    jobsRef.current = next;
    setJobs(next);
    return next;
  }, []);

  /**
   * Poll /api/admin/status until job_tracker.result appears for the given job_id.
   * Polls every 5 seconds. Gives up after 24 hours to prevent infinite loops.
   */
  const pollForResult = useCallback(async (serverJobId: string): Promise<JobTrackerResult> => {
    const POLL_INTERVAL_MS = 5_000;
    const MAX_POLLS = (24 * 60 * 60 * 1000) / POLL_INTERVAL_MS; // 24 hours

    for (let i = 0; i < MAX_POLLS; i++) {
      if (abortRef.current) {
        throw new Error('Import queue aborted');
      }

      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));

      try {
        const status = await apiClient.getAdminStatus();
        const jobTracker = (status?.models as any)?.job_tracker;

        // If the job is still running, continue polling
        if (jobTracker?.is_busy && jobTracker?.active_job_id === serverJobId) {
          continue;
        }

        // Check for a result
        const result = jobTracker?.result as JobTrackerResult | undefined;
        if (result && result.job_id === serverJobId) {
          return result;
        }

        // Job is not busy AND no result for our job_id — server may have restarted
        if (!jobTracker?.is_busy && (!result || result.job_id !== serverJobId)) {
          throw new Error('Transcription job lost — server may have restarted');
        }
      } catch (err) {
        // If it's our own thrown error, re-throw
        if (err instanceof Error && err.message.includes('job lost')) throw err;
        if (err instanceof Error && err.message.includes('aborted')) throw err;
        // Network errors during polling are transient — keep trying
        console.warn('Poll error (will retry):', err);
      }
    }

    throw new Error('Transcription timed out after 24 hours');
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
          // Submit file — returns 202 immediately with server job_id
          const { job_id: serverJobId } = await apiClient.uploadAndTranscribe(file, jobOptions);

          // Poll /api/admin/status until job_tracker.result appears for this job
          const result = await pollForResult(serverJobId);

          // Check if the background job failed
          if (result.error) {
            throw new Error(result.error);
          }

          // Map job tracker result to UploadResponse shape
          const uploadResult: UploadResponse = {
            recording_id: result.recording_id!,
            message: result.message ?? 'Transcription complete',
            diarization: result.diarization ?? { requested: false, performed: false, reason: null },
          };

          updateJobs((prev) =>
            prev.map((j) =>
              j.id === jobId ? { ...j, status: 'success' as const, result: uploadResult } : j,
            ),
          );
          callbacksRef.current?.onJobSuccess?.(nextJob, uploadResult);
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

  const updateCallbacks = useCallback((newConfig: UseImportQueueConfig) => {
    callbacksRef.current = newConfig;
  }, []);

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
    updateCallbacks,
    pendingCount,
    completedCount,
    errorCount,
  };
}
