/**
 * useSessionImportQueue — manages a multi-file import queue for Session tab.
 *
 * Unlike useImportQueue (Notebook), this hook:
 * - Calls apiClient.importAndTranscribe() (no DB storage)
 * - After transcription, formats result as SRT or TXT based on diarization
 * - Writes the output file to disk via Electron fileIO IPC
 * - Falls back to browser download when Electron is unavailable
 */

import { useState, useCallback, useRef } from 'react';
import { apiClient } from '../api/client';
import type { TranscriptionUploadOptions, FileImportJobResult } from '../api/types';
import { renderSrt, renderAss, renderTxt } from '../services/transcriptionFormatters';

export type SessionImportJobStatus = 'pending' | 'processing' | 'writing' | 'success' | 'error';

export interface SessionImportJob {
  /** Unique job id */
  id: string;
  /** Original file */
  file: File;
  /** Upload/transcription options captured when the job was queued */
  options?: Omit<TranscriptionUploadOptions, 'file_created_at' | 'title'>;
  /** Current status */
  status: SessionImportJobStatus;
  /** Path where the output file was saved */
  outputPath?: string;
  /** Output filename (for display) */
  outputFilename?: string;
  /** Error message on failure */
  error?: string;
}

export interface UseSessionImportQueueReturn {
  /** All jobs in the queue (current + completed) */
  jobs: SessionImportJob[];
  /** Whether the queue is actively processing */
  isProcessing: boolean;
  /** Add files to the queue (auto-starts processing if idle) */
  addFiles: (
    files: File[],
    options?: Omit<TranscriptionUploadOptions, 'file_created_at' | 'title'>,
  ) => void;
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

interface UseSessionImportQueueConfig {
  /** Directory to write output files to */
  outputDir: string;
  /** Output format for diarized files (default: 'srt') */
  diarizedFormat?: 'srt' | 'ass';
}

let jobIdCounter = 0;
function nextJobId(): string {
  return `session-import-${Date.now()}-${++jobIdCounter}`;
}

/**
 * Derive output filename from the audio filename and format.
 */
function buildOutputFilename(
  audioFilename: string,
  diarizationPerformed: boolean,
  diarizedFormat: 'srt' | 'ass' = 'srt',
): string {
  const stem = audioFilename.replace(/\.[^.]+$/, '');
  if (!diarizationPerformed) return `${stem}.txt`;
  return `${stem}.${diarizedFormat}`;
}

/**
 * Trigger a browser download as fallback when Electron is unavailable.
 */
function browserDownload(filename: string, content: string): void {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function useSessionImportQueue(
  config: UseSessionImportQueueConfig,
): UseSessionImportQueueReturn {
  const [jobs, setJobs] = useState<SessionImportJob[]>([]);
  const jobsRef = useRef<SessionImportJob[]>([]);
  const processingRef = useRef(false);
  const abortRef = useRef(false);
  const configRef = useRef(config);
  configRef.current = config;

  const updateJobs = useCallback((updater: (prev: SessionImportJob[]) => SessionImportJob[]) => {
    const next = updater(jobsRef.current);
    jobsRef.current = next;
    setJobs(next);
    return next;
  }, []);

  /**
   * Poll /api/admin/status until job_tracker.result appears for the given job_id.
   */
  const pollForResult = useCallback(async (serverJobId: string): Promise<FileImportJobResult> => {
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
        const result = jobTracker?.result as FileImportJobResult | undefined;
        if (result && result.job_id === serverJobId) {
          return result;
        }

        // Job is not busy AND no result for our job_id — server may have restarted
        if (!jobTracker?.is_busy && (!result || result.job_id !== serverJobId)) {
          throw new Error('Transcription job lost — server may have restarted');
        }
      } catch (err) {
        if (err instanceof Error && err.message.includes('job lost')) throw err;
        if (err instanceof Error && err.message.includes('aborted')) throw err;
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
          const { job_id: serverJobId } = await apiClient.importAndTranscribe(file, jobOptions);

          // Poll for completion
          const result = await pollForResult(serverJobId);

          if (result.error) {
            throw new Error(result.error);
          }

          if (!result.transcription) {
            throw new Error('Server returned no transcription data');
          }

          // Determine output format based on whether diarization was performed
          const diarizationPerformed = result.diarization?.performed ?? false;
          const diarizedFormat = configRef.current.diarizedFormat ?? 'srt';
          const outputFilename = buildOutputFilename(
            file.name,
            diarizationPerformed,
            diarizedFormat,
          );
          const stem = file.name.replace(/\.[^.]+$/, '');
          const content = diarizationPerformed
            ? diarizedFormat === 'ass'
              ? renderAss(result.transcription, stem)
              : renderSrt(result.transcription)
            : renderTxt(result.transcription);

          // Update status to 'writing'
          updateJobs((prev) =>
            prev.map((j) => (j.id === jobId ? { ...j, status: 'writing' as const } : j)),
          );

          // Write file via Electron IPC or fall back to browser download
          const electronAPI = (window as any).electronAPI;
          let outputPath: string | undefined;

          if (electronAPI?.fileIO) {
            const dir = configRef.current.outputDir;
            outputPath = `${dir}/${outputFilename}`;
            await electronAPI.fileIO.writeText(outputPath, content);
          } else {
            browserDownload(outputFilename, content);
          }

          updateJobs((prev) =>
            prev.map((j) =>
              j.id === jobId
                ? {
                    ...j,
                    status: 'success' as const,
                    outputPath,
                    outputFilename,
                  }
                : j,
            ),
          );
        } catch (err) {
          const errorMsg = err instanceof Error ? err.message : 'Import failed';
          updateJobs((prev) =>
            prev.map((j) =>
              j.id === jobId ? { ...j, status: 'error' as const, error: errorMsg } : j,
            ),
          );
        }

        if (abortRef.current) break;

        // Small delay between jobs to let the server breathe
        await new Promise((r) => setTimeout(r, 500));
      }
    } finally {
      processingRef.current = false;
    }
  }, [updateJobs, pollForResult]);

  const addFiles = useCallback(
    (files: File[], options?: Omit<TranscriptionUploadOptions, 'file_created_at' | 'title'>) => {
      const capturedOptions = options ? { ...options } : undefined;
      const newJobs: SessionImportJob[] = files.map((file) => ({
        id: nextJobId(),
        file,
        options: capturedOptions,
        status: 'pending' as const,
      }));
      updateJobs((prev) => [...prev, ...newJobs]);
      setTimeout(() => processQueue(), 0);
    },
    [processQueue, updateJobs],
  );

  const removeJob = useCallback(
    (id: string) => {
      updateJobs((prev) =>
        prev.filter((j) => j.id !== id || j.status === 'processing' || j.status === 'writing'),
      );
    },
    [updateJobs],
  );

  const clearFinished = useCallback(() => {
    updateJobs((prev) =>
      prev.filter(
        (j) => j.status === 'pending' || j.status === 'processing' || j.status === 'writing',
      ),
    );
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
  const isProcessing = jobs.some((j) => j.status === 'processing' || j.status === 'writing');

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
