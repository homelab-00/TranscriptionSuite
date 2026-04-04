/**
 * Unified import queue store — replaces useSessionImportQueue + useImportQueue hooks.
 *
 * Manages a single queue with 4 job types (session-normal, session-auto,
 * notebook-normal, notebook-auto), global pause/resume, and processing logic
 * for both session (write-to-disk) and notebook (DB) import paths.
 */

import { create } from 'zustand';
import { toast } from 'sonner';
import { apiClient } from '../api/client';
import type {
  TranscriptionUploadOptions,
  FileImportJobResult,
  JobTrackerResult,
  UploadResponse,
} from '../api/types';
import { resolveTranscriptionOutput } from '../services/transcriptionFormatters';
import { getConfig } from '../config/store';

// ─── Types ───────────────────────────────────────────────────────────────────

export type ImportJobType = 'session-normal' | 'session-auto' | 'notebook-normal' | 'notebook-auto';

export type UnifiedImportJobStatus = 'pending' | 'processing' | 'writing' | 'success' | 'error';

export interface UnifiedImportJob {
  id: string;
  /** Browser File object (manual imports) or native file path string (auto-watch) */
  file: File | string;
  type: ImportJobType;
  options?: TranscriptionUploadOptions;
  status: UnifiedImportJobStatus;
  /** Session jobs: path where output was saved */
  outputPath?: string;
  /** Session jobs: output filename for display */
  outputFilename?: string;
  /** Notebook jobs: server result */
  result?: UploadResponse;
  error?: string;
}

export interface SessionConfig {
  outputDir: string;
  diarizedFormat: 'srt' | 'ass';
}

export interface NotebookCallbacks {
  onJobSuccess?: (job: UnifiedImportJob, result: UploadResponse) => void;
  onJobError?: (job: UnifiedImportJob, error: string) => void;
}

// ─── Watcher state ────────────────────────────────────────────────────────────

export interface WatchLogEntry {
  ts: string;
  message: string;
  level: 'info' | 'warn';
}

export interface WatcherState {
  sessionWatchPath: string;
  sessionWatchActive: boolean;
  notebookWatchPath: string;
  notebookWatchActive: boolean;
  /** true when the transcription server is reachable (4.2) */
  watcherServerConnected: boolean;
  /** Activity log — last 100 entries (4.3) */
  watchLog: WatchLogEntry[];
  /** Exponential moving average of successful job durations in ms (4.5) */
  avgProcessingMs: number;
}

// ─── Store interface ─────────────────────────────────────────────────────────

interface ImportQueueState extends WatcherState {
  jobs: UnifiedImportJob[];
  isPaused: boolean;
  sessionConfig: SessionConfig;
  notebookCallbacks: NotebookCallbacks;

  // Actions
  addFiles: (
    files: (File | string)[],
    type: ImportJobType,
    options?: TranscriptionUploadOptions,
  ) => void;
  /** Prepend files to the front of the queue with highest priority.
   *  If a job is currently processing, it is cancelled and reset to pending. */
  addPriorityFiles: (
    files: (File | string)[],
    type: ImportJobType,
    options?: TranscriptionUploadOptions,
  ) => void;
  pauseQueue: () => void;
  resumeQueue: () => void;
  removeJob: (id: string) => void;
  retryJob: (id: string) => void;
  clearFinished: () => void;
  clearAll: () => void;
  updateSessionConfig: (patch: Partial<SessionConfig>) => void;
  updateNotebookCallbacks: (callbacks: NotebookCallbacks) => void;

  // Watcher actions
  setSessionWatchPath: (path: string) => void;
  setSessionWatchActive: (active: boolean) => void;
  setNotebookWatchPath: (path: string) => void;
  setNotebookWatchActive: (active: boolean) => void;
  handleFilesDetected: (payload: {
    type: 'session' | 'notebook';
    files: string[];
    count: number;
    fileMeta: Array<{ path: string; createdAt: string }>;
  }) => void;
  // 4.2 — server connectivity
  setWatcherServerConnected: (connected: boolean) => void;
  // 4.3 — activity log
  appendWatchLog: (entry: Omit<WatchLogEntry, 'ts'>) => void;
  clearWatchLog: () => void;
}

// ─── Derived selectors ──────────────────────────────────────────────────────

export const selectPendingCount = (s: ImportQueueState) =>
  s.jobs.filter((j) => j.status === 'pending').length;

export const selectCompletedCount = (s: ImportQueueState) =>
  s.jobs.filter((j) => j.status === 'success').length;

export const selectErrorCount = (s: ImportQueueState) =>
  s.jobs.filter((j) => j.status === 'error').length;

export const selectIsProcessing = (s: ImportQueueState) =>
  s.jobs.some((j) => j.status === 'processing' || j.status === 'writing');

export const selectIsUploading = (s: ImportQueueState) =>
  s.jobs.some((j) => j.status === 'processing' || j.status === 'writing') ||
  s.jobs.some((j) => j.status === 'pending');

export const selectSessionJobs = (s: ImportQueueState) =>
  s.jobs.filter((j) => j.type === 'session-normal' || j.type === 'session-auto');

export const selectNotebookJobs = (s: ImportQueueState) =>
  s.jobs.filter((j) => j.type === 'notebook-normal' || j.type === 'notebook-auto');

// ─── Module-level refs (outside store to avoid stale closures) ───────────────

let _processing = false;
let _abort = false;
/** Per-job processing start timestamps — used for time estimates (4.5) */
const _jobStartedAt: Record<string, number> = {};
/** Job IDs preempted by priority files — reset to 'pending' instead of 'error'
 *  when their cancellation propagates. A Set handles rapid double-preemption. */
const _preemptedJobIds = new Set<string>();

let _jobIdCounter = 0;
function nextJobId(type: ImportJobType): string {
  const prefix = type.startsWith('session') ? 'session' : 'notebook';
  return `${prefix}-import-${Date.now()}-${++_jobIdCounter}`;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

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

/** Extract filename from a native file path string. */
function filenameFromPath(filePath: string): string {
  const parts = filePath.replace(/\\/g, '/').split('/');
  return parts[parts.length - 1] || filePath;
}

const POLL_INTERVAL_MS = 5_000;
const MAX_POLLS = (24 * 60 * 60 * 1000) / POLL_INTERVAL_MS; // 24 hours

// ─── Polling ─────────────────────────────────────────────────────────────────

async function pollForSessionResult(serverJobId: string): Promise<FileImportJobResult> {
  for (let i = 0; i < MAX_POLLS; i++) {
    if (_abort) throw new Error('Import queue aborted');
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));

    try {
      const status = await apiClient.getAdminStatus();
      const jobTracker = (status?.models as any)?.job_tracker;

      if (jobTracker?.is_busy && jobTracker?.active_job_id === serverJobId) continue;

      const result = jobTracker?.result as FileImportJobResult | undefined;
      if (result && result.job_id === serverJobId) return result;

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
}

async function pollForNotebookResult(serverJobId: string): Promise<JobTrackerResult> {
  for (let i = 0; i < MAX_POLLS; i++) {
    if (_abort) throw new Error('Import queue aborted');
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
      if (err instanceof Error && err.message.includes('job lost')) throw err;
      if (err instanceof Error && err.message.includes('aborted')) throw err;
      console.warn('Poll error (will retry):', err);
    }
  }
  throw new Error('Transcription timed out after 24 hours');
}

// ─── Processing ──────────────────────────────────────────────────────────────

async function processSessionJob(
  job: UnifiedImportJob,
  store: typeof useImportQueueStore,
): Promise<void> {
  const file = job.file;
  const isPath = typeof file === 'string';
  const filename = isPath ? filenameFromPath(file) : file.name;

  // For auto-watch jobs (file paths), read the file via Electron IPC
  let fileObj: File;
  if (isPath) {
    const electronAPI = (window as any).electronAPI;
    if (!electronAPI?.app?.readLocalFile) {
      throw new Error('Auto-watch requires Electron — cannot read local file in browser');
    }
    const { buffer } = await electronAPI.app.readLocalFile(file as string);
    fileObj = new File([buffer], filename);
  } else {
    fileObj = file;
  }

  const { job_id: serverJobId } = await apiClient.importAndTranscribe(fileObj, job.options);
  const result = await pollForSessionResult(serverJobId);

  if (result.error) throw new Error(result.error);
  if (!result.transcription) throw new Error('Server returned no transcription data');

  const { sessionConfig } = store.getState();
  const hideTimestamps = (await getConfig<boolean>('output.hideTimestamps')) ?? false;
  const { outputFilename, content } = resolveTranscriptionOutput(filename, result.transcription, {
    hideTimestamps,
    diarizationPerformed: result.diarization?.performed ?? false,
    diarizedFormat: sessionConfig.diarizedFormat ?? 'srt',
  });

  // Update status to 'writing'
  store.setState((s) => ({
    jobs: s.jobs.map((j) => (j.id === job.id ? { ...j, status: 'writing' as const } : j)),
  }));

  const electronAPI = (window as any).electronAPI;
  let outputPath: string | undefined;

  if (electronAPI?.fileIO) {
    const dir = sessionConfig.outputDir;
    outputPath = `${dir}/${outputFilename}`;
    await electronAPI.fileIO.writeText(outputPath, content);
  } else {
    browserDownload(outputFilename, content);
  }

  store.setState((s) => ({
    jobs: s.jobs.map((j) =>
      j.id === job.id ? { ...j, status: 'success' as const, outputPath, outputFilename } : j,
    ),
  }));
}

async function processNotebookJob(
  job: UnifiedImportJob,
  store: typeof useImportQueueStore,
): Promise<void> {
  const file = job.file;
  const isPath = typeof file === 'string';

  let fileObj: File;
  if (isPath) {
    const electronAPI = (window as any).electronAPI;
    if (!electronAPI?.app?.readLocalFile) {
      throw new Error('Auto-watch requires Electron — cannot read local file in browser');
    }
    const filename = filenameFromPath(file);
    const { buffer } = await electronAPI.app.readLocalFile(file as string);
    fileObj = new File([buffer], filename);
  } else {
    fileObj = file;
  }

  const { job_id: serverJobId } = await apiClient.uploadAndTranscribe(fileObj, job.options);
  const result = await pollForNotebookResult(serverJobId);

  if (result.error) throw new Error(result.error);

  const uploadResult: UploadResponse = {
    recording_id: result.recording_id!,
    message: result.message ?? 'Transcription complete',
    diarization: result.diarization ?? { requested: false, performed: false, reason: null },
  };

  store.setState((s) => ({
    jobs: s.jobs.map((j) =>
      j.id === job.id ? { ...j, status: 'success' as const, result: uploadResult } : j,
    ),
  }));

  const { notebookCallbacks } = store.getState();
  notebookCallbacks.onJobSuccess?.(job, uploadResult);
}

async function processQueue(): Promise<void> {
  if (_processing) return;
  _processing = true;
  _abort = false;

  const store = useImportQueueStore;

  try {
    while (!_abort) {
      const { jobs, isPaused } = store.getState();
      if (isPaused) break;

      const nextJob = jobs.find((j) => j.status === 'pending');
      if (!nextJob) break;

      const jobId = nextJob.id;
      const isSession = nextJob.type === 'session-normal' || nextJob.type === 'session-auto';

      // Mark processing and record start time for time estimates (4.5)
      _jobStartedAt[jobId] = Date.now();
      store.setState((s) => ({
        jobs: s.jobs.map((j) =>
          j.id === jobId ? { ...j, status: 'processing' as const, error: undefined } : j,
        ),
      }));

      try {
        if (isSession) {
          await processSessionJob(nextJob, store);
        } else {
          await processNotebookJob(nextJob, store);
        }

        // Update exponential moving average on success (4.5)
        const startedAt = _jobStartedAt[jobId];
        if (startedAt) {
          const duration = Date.now() - startedAt;
          const prev = store.getState().avgProcessingMs;
          const next = prev === 0 ? duration : Math.round(prev * 0.7 + duration * 0.3);
          store.setState({ avgProcessingMs: next });
        }
      } catch (err) {
        // If this job was preempted by a priority file, reset it to pending
        // so it restarts after the priority job completes.
        if (_preemptedJobIds.has(jobId)) {
          _preemptedJobIds.delete(jobId);
          store.setState((s) => ({
            jobs: s.jobs.map((j) =>
              j.id === jobId ? { ...j, status: 'pending' as const, error: undefined } : j,
            ),
          }));
        } else {
          const errorMsg = err instanceof Error ? err.message : 'Import failed';
          store.setState((s) => ({
            jobs: s.jobs.map((j) =>
              j.id === jobId ? { ...j, status: 'error' as const, error: errorMsg } : j,
            ),
          }));

          if (isSession) {
            // No callback for session errors — error is visible in the job
          } else {
            const { notebookCallbacks } = store.getState();
            notebookCallbacks.onJobError?.(nextJob, errorMsg);
          }
        }
      } finally {
        delete _jobStartedAt[jobId];
      }

      if (_abort) break;

      // Small delay between jobs to let the server breathe
      await new Promise((r) => setTimeout(r, 500));
    }
  } finally {
    _processing = false;
  }
}

// ─── Store ───────────────────────────────────────────────────────────────────

export const useImportQueueStore = create<ImportQueueState>()((set) => ({
  // State
  jobs: [],
  isPaused: false,
  sessionConfig: { outputDir: '', diarizedFormat: 'srt' },
  notebookCallbacks: {},

  // Watcher state
  sessionWatchPath: '',
  sessionWatchActive: false,
  notebookWatchPath: '',
  notebookWatchActive: false,
  watcherServerConnected: true,
  watchLog: [],
  avgProcessingMs: 0,

  // ─── Queue Actions ───────────────────────────────────────────────────────

  addFiles: (files, type, options) => {
    const capturedOptions = options ? { ...options } : undefined;
    const newJobs: UnifiedImportJob[] = files.map((file) => ({
      id: nextJobId(type),
      file,
      type,
      options: capturedOptions,
      status: 'pending' as const,
    }));
    set((s) => ({ jobs: [...s.jobs, ...newJobs] }));
    setTimeout(() => processQueue(), 0);
  },

  addPriorityFiles: (files, type, options) => {
    const capturedOptions = options ? { ...options } : undefined;
    const newJobs: UnifiedImportJob[] = files.map((file) => ({
      id: nextJobId(type),
      file,
      type,
      options: capturedOptions,
      status: 'pending' as const,
    }));

    // If a job is currently processing, preempt it
    const { jobs } = useImportQueueStore.getState();
    const processingJob = jobs.find((j) => j.status === 'processing');
    if (processingJob) {
      _preemptedJobIds.add(processingJob.id);
      apiClient.cancelTranscription().catch(() => {});
    }

    // Prepend priority jobs to the front of the queue
    set((s) => ({ jobs: [...newJobs, ...s.jobs] }));
    setTimeout(() => processQueue(), 0);
  },

  pauseQueue: () => {
    set({ isPaused: true });
    // Best-effort cancel the active server job
    apiClient.cancelTranscription().catch(() => {});
  },

  resumeQueue: () => {
    set({ isPaused: false });
    setTimeout(() => processQueue(), 0);
  },

  removeJob: (id) => {
    set((s) => ({
      jobs: s.jobs.filter(
        (j) => j.id !== id || j.status === 'processing' || j.status === 'writing',
      ),
    }));
  },

  retryJob: (id) => {
    set((s) => ({
      jobs: s.jobs.map((j) =>
        j.id === id && j.status === 'error'
          ? { ...j, status: 'pending' as const, error: undefined }
          : j,
      ),
    }));
    setTimeout(() => processQueue(), 0);
  },

  clearFinished: () => {
    set((s) => ({
      jobs: s.jobs.filter(
        (j) => j.status === 'pending' || j.status === 'processing' || j.status === 'writing',
      ),
    }));
  },

  clearAll: () => {
    _abort = true;
    set({ jobs: [] });
  },

  updateSessionConfig: (patch) => {
    set((s) => ({ sessionConfig: { ...s.sessionConfig, ...patch } }));
  },

  updateNotebookCallbacks: (callbacks) => {
    set({ notebookCallbacks: callbacks });
  },

  // ─── Watcher Actions ──────────────────────────────────────────────────────

  setSessionWatchPath: (_path) => {
    set({ sessionWatchPath: _path });
  },

  setSessionWatchActive: (_active) => {
    set({ sessionWatchActive: _active });
  },

  setNotebookWatchPath: (_path) => {
    set({ notebookWatchPath: _path });
  },

  setNotebookWatchActive: (_active) => {
    set({ notebookWatchActive: _active });
  },

  handleFilesDetected: (payload) => {
    const { type, files, fileMeta } = payload;
    if (files.length === 0) return;

    const { watcherServerConnected } = useImportQueueStore.getState();
    const label = type === 'session' ? 'Session Watch' : 'Notebook Watch';

    // 4.2 — pause file discovery when server is unreachable
    if (!watcherServerConnected) {
      toast.warning(
        `${files.length} file${files.length === 1 ? '' : 's'} detected from ${label} but server is offline — files skipped`,
      );
      useImportQueueStore.getState().appendWatchLog({
        message: `${files.length} file(s) detected but server offline — skipped`,
        level: 'warn',
      });
      return;
    }

    if (type === 'notebook') {
      // Add each notebook file individually so we can attach its creation timestamp.
      // This ensures the entry lands on the correct calendar date.
      for (const meta of fileMeta) {
        useImportQueueStore.getState().addFiles([meta.path], 'notebook-auto', {
          file_created_at: meta.createdAt,
        });
      }
    } else {
      useImportQueueStore.getState().addFiles(files, 'session-auto');
    }

    toast.success(`${files.length} file${files.length === 1 ? '' : 's'} auto-queued from ${label}`);
    // 4.3 — log the detection event
    useImportQueueStore.getState().appendWatchLog({
      message: `${files.length} file(s) auto-queued from ${label}`,
      level: 'info',
    });
  },

  // 4.2 — server connectivity
  setWatcherServerConnected: (connected) => {
    set({ watcherServerConnected: connected });
  },

  // 4.3 — activity log
  appendWatchLog: (entry) => {
    set((s) => ({
      watchLog: [
        ...s.watchLog.slice(-99), // keep last 100 entries
        { ...entry, ts: new Date().toISOString() },
      ],
    }));
  },

  clearWatchLog: () => {
    set({ watchLog: [] });
  },
}));
