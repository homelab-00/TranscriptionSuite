import { describe, it, expect, beforeEach, afterEach, vi, type Mock } from 'vitest';

// Mock apiClient before importing the store
vi.mock('../api/client', () => ({
  apiClient: {
    importAndTranscribe: vi.fn(),
    uploadAndTranscribe: vi.fn(),
    getAdminStatus: vi.fn(),
    cancelTranscription: vi.fn().mockResolvedValue(undefined),
  },
}));

// Mock transcription formatters. resolveTranscriptionOutputs (GH-212) stays
// REAL so the processSessionJob tests exercise genuine multi-file resolution;
// only the legacy single-output resolver keeps its historical stub.
vi.mock('../services/transcriptionFormatters', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/transcriptionFormatters')>();
  return {
    ...actual,
    resolveTranscriptionOutput: vi.fn(() => ({
      outputFilename: 'test.txt',
      content: 'txt-content',
    })),
  };
});

// Mock sonner so the new gh-102 #3 tests can assert on toast.warning calls
// without rendering. Existing tests don't assert on toast and stay unaffected.
vi.mock('sonner', () => ({
  toast: {
    warning: vi.fn(),
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}));

// Mock the config store so resolveDuplicateChoice's policy read is deterministic
// (GH-120). All other exports stay real — only getConfig is stubbed.
vi.mock('../config/store', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../config/store')>();
  return { ...actual, getConfig: vi.fn() };
});

// Stub window.electronAPI
Object.defineProperty(globalThis, 'window', {
  value: globalThis,
  writable: true,
});

import { toast } from 'sonner';
import { apiClient } from '../api/client';
import {
  useImportQueueStore,
  resolveDuplicateChoice,
  selectPendingCount,
  selectCompletedCount,
  selectErrorCount,
  selectIsProcessing,
  selectIsUploading,
  selectSessionJobs,
  selectNotebookJobs,
} from './importQueueStore';
import type { UnifiedImportJob } from './importQueueStore';
import { useDedupChoiceStore } from './dedupChoiceStore';
import { getConfig } from '../config/store';
import type { DedupMatch } from '../api/types';
import type { DedupChoice } from '../../components/import/DedupPromptModal';

function resetStore() {
  useImportQueueStore.setState({
    jobs: [],
    isPaused: false,
    sessionConfig: {
      outputDir: '',
      diarizedFormat: 'srt',
      outputFormat: 'subtitles',
      hideTimestamps: false,
      enableDiarization: true,
      enableWordTimestamps: true,
      parallelDiarization: false,
      multitrack: false,
    },
    notebookConfig: {
      enableDiarization: true,
      enableWordTimestamps: true,
      parallelDiarization: false,
    },
    notebookCallbacks: {},
    sessionWatchPath: '',
    sessionWatchActive: false,
    notebookWatchPath: '',
    notebookWatchActive: false,
    watcherServerConnected: true,
    watchLog: [],
    avgProcessingMs: 0,
    // gh-102 #3 — default to a "ready" cache with a Whisper model so the
    // language-resolution branch in handleFilesDetected falls through (no
    // pause, no explicit-required) and pre-existing tests stay green. Tests
    // that exercise the new behavior override this with setLanguagesCache.
    languagesCache: {
      model: 'large-v3',
      languages: [
        { code: 'en', name: 'English' },
        { code: 'es', name: 'Spanish' },
      ],
      loading: false,
    },
  });
}

function getState() {
  return useImportQueueStore.getState();
}

function makeJob(overrides: Partial<UnifiedImportJob> = {}): UnifiedImportJob {
  return {
    id: `test-${Date.now()}-${Math.random()}`,
    file: new File(['audio'], 'test.mp3'),
    type: 'session-normal',
    status: 'pending',
    ...overrides,
  };
}

describe('importQueueStore', () => {
  beforeEach(() => {
    resetStore();
    vi.useFakeTimers();
    // Clear sonner mock counts at the suite level so toast assertions never
    // bleed across describe blocks (e.g. the watcherServerConnected guard
    // emits toast.warning, which would otherwise contaminate the gh-102 #3
    // tests' toHaveBeenCalledWith checks).
    vi.mocked(toast.warning).mockClear();
    vi.mocked(toast.success).mockClear();
    vi.mocked(toast.error).mockClear();
    vi.mocked(toast.info).mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // ── addFiles ────────────────────────────────────────────────────────────

  describe('addFiles', () => {
    it('adds session-normal jobs with pending status', () => {
      const files = [new File(['a'], 'a.mp3'), new File(['b'], 'b.wav')];
      getState().addFiles(files, 'session-normal', { enable_diarization: true });

      const { jobs } = getState();
      expect(jobs).toHaveLength(2);
      expect(jobs[0].type).toBe('session-normal');
      expect(jobs[0].status).toBe('pending');
      expect(jobs[0].options?.enable_diarization).toBe(true);
      expect(jobs[1].file).toBe(files[1]);
    });

    it('adds notebook-normal jobs', () => {
      const files = [new File(['c'], 'c.flac')];
      getState().addFiles(files, 'notebook-normal', { title: 'My Note' });

      const { jobs } = getState();
      expect(jobs).toHaveLength(1);
      expect(jobs[0].type).toBe('notebook-normal');
      expect(jobs[0].options?.title).toBe('My Note');
    });

    it('adds auto-watch jobs with string paths', () => {
      getState().addFiles(['/home/user/recording.mp3'], 'session-auto');

      const { jobs } = getState();
      expect(jobs).toHaveLength(1);
      expect(jobs[0].type).toBe('session-auto');
      expect(jobs[0].file).toBe('/home/user/recording.mp3');
    });

    it('generates unique IDs for each job', () => {
      const files = [new File(['a'], 'a.mp3'), new File(['b'], 'b.mp3')];
      getState().addFiles(files, 'session-normal');

      const { jobs } = getState();
      expect(jobs[0].id).not.toBe(jobs[1].id);
    });

    it('appends to existing jobs', () => {
      getState().addFiles([new File(['a'], 'a.mp3')], 'session-normal');
      getState().addFiles([new File(['b'], 'b.mp3')], 'notebook-normal');

      expect(getState().jobs).toHaveLength(2);
    });

    it('snapshots options to avoid mutation', () => {
      const options = { enable_diarization: true };
      getState().addFiles([new File(['a'], 'a.mp3')], 'session-normal', options);
      options.enable_diarization = false;

      expect(getState().jobs[0].options?.enable_diarization).toBe(true);
    });

    // GH-212 — queued session jobs display the format chosen at enqueue time.
    it('stamps plannedFormat on session jobs from the current sessionConfig', () => {
      getState().updateSessionConfig({ outputFormat: 'both', diarizedFormat: 'srt' });
      getState().addFiles([new File(['a'], 'memo.m4a')], 'session-normal');

      expect(getState().jobs[0].plannedFormat).toBe('.txt + .srt');
    });

    it('stamps plannedFormat=.txt when the session format is plain text', () => {
      getState().updateSessionConfig({ outputFormat: 'txt' });
      getState().addFiles([new File(['a'], 'memo.m4a')], 'session-normal');

      expect(getState().jobs[0].plannedFormat).toBe('.txt');
    });

    it('stamps the subtitle flavor when the session format is subtitles', () => {
      getState().updateSessionConfig({ outputFormat: 'subtitles', diarizedFormat: 'ass' });
      getState().addFiles([new File(['a'], 'memo.m4a')], 'session-normal');

      expect(getState().jobs[0].plannedFormat).toBe('.ass');
    });

    it('does not stamp plannedFormat on notebook jobs', () => {
      getState().addFiles([new File(['a'], 'note.mp3')], 'notebook-normal');

      expect(getState().jobs[0].plannedFormat).toBeUndefined();
    });
  });

  // ── pause / resume ─────────────────────────────────────────────────────

  describe('pause / resume', () => {
    it('pauses the queue', () => {
      getState().pauseQueue();
      expect(getState().isPaused).toBe(true);
    });

    it('resumes the queue', () => {
      getState().pauseQueue();
      getState().resumeQueue();
      expect(getState().isPaused).toBe(false);
    });
  });

  // ── removeJob ──────────────────────────────────────────────────────────

  describe('removeJob', () => {
    it('removes a pending job', () => {
      const job = makeJob({ id: 'remove-me', status: 'pending' });
      useImportQueueStore.setState({ jobs: [job] });

      getState().removeJob('remove-me');
      expect(getState().jobs).toHaveLength(0);
    });

    it('removes an error job', () => {
      const job = makeJob({ id: 'err-job', status: 'error', error: 'fail' });
      useImportQueueStore.setState({ jobs: [job] });

      getState().removeJob('err-job');
      expect(getState().jobs).toHaveLength(0);
    });

    it('removes a success job', () => {
      const job = makeJob({ id: 'done-job', status: 'success' });
      useImportQueueStore.setState({ jobs: [job] });

      getState().removeJob('done-job');
      expect(getState().jobs).toHaveLength(0);
    });

    it('does NOT remove a processing job', () => {
      const job = makeJob({ id: 'busy-job', status: 'processing' });
      useImportQueueStore.setState({ jobs: [job] });

      getState().removeJob('busy-job');
      expect(getState().jobs).toHaveLength(1);
    });

    it('does NOT remove a writing job', () => {
      const job = makeJob({ id: 'write-job', status: 'writing' });
      useImportQueueStore.setState({ jobs: [job] });

      getState().removeJob('write-job');
      expect(getState().jobs).toHaveLength(1);
    });
  });

  // ── retryJob ───────────────────────────────────────────────────────────

  describe('retryJob', () => {
    it('resets an error job to pending', () => {
      const job = makeJob({ id: 'retry-me', status: 'error', error: 'oops' });
      useImportQueueStore.setState({ jobs: [job] });

      getState().retryJob('retry-me');
      const updated = getState().jobs[0];
      expect(updated.status).toBe('pending');
      expect(updated.error).toBeUndefined();
    });

    it('does nothing for non-error jobs', () => {
      const job = makeJob({ id: 'ok-job', status: 'success' });
      useImportQueueStore.setState({ jobs: [job] });

      getState().retryJob('ok-job');
      expect(getState().jobs[0].status).toBe('success');
    });
  });

  // ── clearFinished ──────────────────────────────────────────────────────

  describe('clearFinished', () => {
    it('removes success and error jobs, keeps pending/processing/writing', () => {
      const jobs = [
        makeJob({ id: 'j1', status: 'pending' }),
        makeJob({ id: 'j2', status: 'processing' }),
        makeJob({ id: 'j3', status: 'writing' }),
        makeJob({ id: 'j4', status: 'success' }),
        makeJob({ id: 'j5', status: 'error', error: 'fail' }),
      ];
      useImportQueueStore.setState({ jobs });

      getState().clearFinished();
      const remaining = getState().jobs;
      expect(remaining).toHaveLength(3);
      expect(remaining.map((j) => j.id)).toEqual(['j1', 'j2', 'j3']);
    });
  });

  // ── clearAll ───────────────────────────────────────────────────────────

  describe('clearAll', () => {
    it('removes all jobs', () => {
      useImportQueueStore.setState({
        jobs: [makeJob(), makeJob({ type: 'notebook-normal' })],
      });

      getState().clearAll();
      expect(getState().jobs).toHaveLength(0);
    });
  });

  // ── updateSessionConfig ────────────────────────────────────────────────

  describe('updateSessionConfig', () => {
    it('merges partial config', () => {
      getState().updateSessionConfig({ outputDir: '/tmp/out' });
      expect(getState().sessionConfig.outputDir).toBe('/tmp/out');
      expect(getState().sessionConfig.diarizedFormat).toBe('srt');
    });

    it('overwrites existing fields', () => {
      getState().updateSessionConfig({ diarizedFormat: 'ass' });
      expect(getState().sessionConfig.diarizedFormat).toBe('ass');
    });
  });

  // ── updateNotebookConfig ───────────────────────────────────────────────

  describe('updateNotebookConfig', () => {
    it('merges partial config', () => {
      getState().updateNotebookConfig({ enableDiarization: false });
      expect(getState().notebookConfig.enableDiarization).toBe(false);
      expect(getState().notebookConfig.enableWordTimestamps).toBe(true);
    });
  });

  // ── updateNotebookCallbacks ────────────────────────────────────────────

  describe('updateNotebookCallbacks', () => {
    it('sets callback functions', () => {
      const onSuccess = vi.fn();
      getState().updateNotebookCallbacks({ onJobSuccess: onSuccess });
      expect(getState().notebookCallbacks.onJobSuccess).toBe(onSuccess);
    });
  });

  // ── handleFilesDetected (Issue #93 — Folder Watch toggle propagation) ──
  //
  // The auto-watch path (session-auto / notebook-auto) MUST source toggle
  // state from the per-tab configs so user-facing UI selections actually
  // reach the backend. Each test asserts on the captured `options` of the
  // resulting job.

  describe('handleFilesDetected', () => {
    // Inspecting real addFiles (rather than a spy) is safe under
    // vi.useFakeTimers — processQueue is scheduled via setTimeout(0) and
    // never fires synchronously, so the mocked apiClient is unreachable.
    function lastJobOptions() {
      const { jobs } = getState();
      return jobs[jobs.length - 1].options;
    }

    it('session: passes diarization=true and parallel value when toggle is ON', () => {
      getState().updateSessionConfig({
        enableDiarization: true,
        enableWordTimestamps: true,
        parallelDiarization: true,
        multitrack: false,
      });
      getState().handleFilesDetected({
        type: 'session',
        files: ['/watch/a.wav'],
        count: 1,
        fileMeta: [],
      });
      expect(lastJobOptions()).toMatchObject({
        enable_diarization: true,
        enable_word_timestamps: true,
        parallel_diarization: true,
      });
      expect(lastJobOptions()?.multitrack).toBeUndefined();
    });

    it('session: multitrack ON forces enable_diarization=false and drops parallel', () => {
      getState().updateSessionConfig({
        enableDiarization: true,
        parallelDiarization: true,
        multitrack: true,
      });
      getState().handleFilesDetected({
        type: 'session',
        files: ['/watch/multi.wav'],
        count: 1,
        fileMeta: [],
      });
      expect(lastJobOptions()).toMatchObject({
        enable_diarization: false,
        multitrack: true,
      });
      expect(lastJobOptions()?.parallel_diarization).toBeUndefined();
    });

    it('session: diarization OFF and timestamps OFF flow through', () => {
      getState().updateSessionConfig({
        enableDiarization: false,
        enableWordTimestamps: false,
        parallelDiarization: false,
        multitrack: false,
      });
      getState().handleFilesDetected({
        type: 'session',
        files: ['/watch/plain.wav'],
        count: 1,
        fileMeta: [],
      });
      expect(lastJobOptions()).toMatchObject({
        enable_diarization: false,
        enable_word_timestamps: false,
      });
      expect(lastJobOptions()?.parallel_diarization).toBeUndefined();
      expect(lastJobOptions()?.multitrack).toBeUndefined();
    });

    it('notebook: passes diarization toggle and preserves file_created_at', () => {
      getState().updateNotebookConfig({
        enableDiarization: true,
        enableWordTimestamps: true,
        parallelDiarization: true,
      });
      getState().handleFilesDetected({
        type: 'notebook',
        files: ['/watch/note.wav'],
        count: 1,
        fileMeta: [{ path: '/watch/note.wav', createdAt: '2026-04-26T10:00:00Z' }],
      });
      expect(lastJobOptions()).toMatchObject({
        file_created_at: '2026-04-26T10:00:00Z',
        enable_diarization: true,
        enable_word_timestamps: true,
        parallel_diarization: true,
      });
    });

    it('notebook: diarization OFF drops parallel_diarization', () => {
      getState().updateNotebookConfig({
        enableDiarization: false,
        parallelDiarization: true,
      });
      getState().handleFilesDetected({
        type: 'notebook',
        files: ['/watch/note2.wav'],
        count: 1,
        fileMeta: [{ path: '/watch/note2.wav', createdAt: '2026-04-26T11:00:00Z' }],
      });
      expect(lastJobOptions()?.enable_diarization).toBe(false);
      expect(lastJobOptions()?.parallel_diarization).toBeUndefined();
    });

    it('uses defaults when notebook tab has not synced its toggles', () => {
      getState().handleFilesDetected({
        type: 'notebook',
        files: ['/watch/default.wav'],
        count: 1,
        fileMeta: [{ path: '/watch/default.wav', createdAt: '2026-04-26T12:00:00Z' }],
      });
      expect(lastJobOptions()).toMatchObject({
        enable_diarization: true,
        enable_word_timestamps: true,
      });
    });

    it('skips when watcherServerConnected is false', () => {
      useImportQueueStore.setState({ watcherServerConnected: false });
      getState().handleFilesDetected({
        type: 'session',
        files: ['/watch/x.wav'],
        count: 1,
        fileMeta: [],
      });
      expect(getState().jobs).toHaveLength(0);
    });

    // GH-212 — Folder Watch enqueues via addFiles, so auto jobs inherit the
    // plannedFormat stamp with no extra wiring.
    it('stamps plannedFormat on session-auto jobs from the current sessionConfig', () => {
      getState().updateSessionConfig({ outputFormat: 'txt' });
      getState().handleFilesDetected({
        type: 'session',
        files: ['/watch/memo.wav'],
        count: 1,
        fileMeta: [],
      });
      expect(getState().jobs[0].plannedFormat).toBe('.txt');
    });
  });

  // ── processSessionJob — explicit output formats (GH-212) ───────────────
  //
  // Drives the real queue end-to-end under fake timers: addFiles schedules
  // processQueue via setTimeout(0); pollForSessionResult waits one
  // POLL_INTERVAL_MS (5s) before reading the mocked job tracker; the queue
  // loop sleeps 500ms after the job. A single 10s advance covers all three.

  describe('processSessionJob — explicit output formats (GH-212)', () => {
    const sessionTranscription = {
      text: 'Hello world.',
      segments: [{ text: 'Hello world.', start: 0, end: 1.5 }],
      words: [],
      language_probability: 0.99,
      duration: 1.5,
      num_speakers: 0,
    };

    let writeText: Mock;

    beforeEach(() => {
      writeText = vi.fn().mockResolvedValue(undefined);
      (window as any).electronAPI = { fileIO: { writeText } };
      vi.mocked(getConfig).mockReset();
      vi.mocked(apiClient.importAndTranscribe).mockResolvedValue({
        job_id: 'server-job-1',
      } as never);
    });

    afterEach(() => {
      delete (window as any).electronAPI;
    });

    function mockConfig(values: Record<string, unknown>) {
      vi.mocked(getConfig).mockImplementation(
        (key: string) => Promise.resolve(values[key]) as never,
      );
    }

    function mockPollResult(result: Record<string, unknown>) {
      vi.mocked(apiClient.getAdminStatus).mockResolvedValue({
        models: { job_tracker: { is_busy: false, result: { job_id: 'server-job-1', ...result } } },
      } as never);
    }

    async function runQueue() {
      getState().updateSessionConfig({ outputDir: '/out' });
      getState().addFiles([new File(['audio'], 'memo.m4a')], 'session-normal');
      await vi.advanceTimersByTimeAsync(10_000);
    }

    it("writes .txt AND subtitle file when the stored format is 'both'", async () => {
      mockConfig({ 'sessionImport.outputFormat': 'both', 'output.hideTimestamps': false });
      mockPollResult({ transcription: sessionTranscription });

      await runQueue();

      expect(writeText).toHaveBeenCalledTimes(2);
      expect(writeText).toHaveBeenCalledWith('/out/memo.txt', expect.any(String));
      expect(writeText).toHaveBeenCalledWith('/out/memo.srt', expect.any(String));
      const job = getState().jobs[0];
      expect(job.status).toBe('success');
      expect(job.outputFilename).toBe('memo.txt, memo.srt');
      expect(job.outputPath).toBe('/out/memo.srt');
    });

    it('falls back to the hideTimestamps-derived default when no explicit format is stored', async () => {
      mockConfig({ 'output.hideTimestamps': true });
      mockPollResult({ transcription: sessionTranscription });

      await runQueue();

      expect(writeText).toHaveBeenCalledTimes(1);
      expect(writeText).toHaveBeenCalledWith('/out/memo.txt', 'Hello world.');
    });

    it('copies result.diarization onto the job as diarizationOutcome (deferred from GH-209)', async () => {
      mockConfig({ 'sessionImport.outputFormat': 'txt' });
      mockPollResult({
        transcription: sessionTranscription,
        diarization: { requested: true, performed: false, reason: 'token_missing' },
      });

      await runQueue();

      expect(getState().jobs[0].diarizationOutcome).toEqual({
        requested: true,
        performed: false,
        reason: 'token_missing',
      });
    });
  });

  // ── handleFilesDetected — gh-102 #3 language resolution ────────────────
  //
  // Folder-watch auto-imports must honor the user's persisted Source Language
  // picker. The handler resolves the snapshotted display name → code via the
  // languagesCache (populated by useLanguages consumers in SessionImportTab
  // and NotebookView ImportTab) and pauses the entire detection batch when
  // languages haven't loaded or the active model lacks auto-detect and the
  // resolve fails. Each test pre-seeds sessionConfig/notebookConfig and
  // languagesCache, then asserts on jobs[] (enqueue) or watchLog + toast.warning
  // (pause).

  describe('handleFilesDetected — gh-102 #3 language resolution', () => {
    function lastJobOptions() {
      const { jobs } = getState();
      return jobs[jobs.length - 1].options;
    }
    function lastWatchLogMessage() {
      const { watchLog } = getState();
      return watchLog[watchLog.length - 1]?.message;
    }

    it('session: Canary + Spanish loaded → enqueues with language=es', () => {
      getState().updateSessionConfig({ language: 'Spanish' });
      getState().setLanguagesCache({
        model: 'nvidia/canary-1b-v2',
        languages: [
          { code: 'en', name: 'English' },
          { code: 'es', name: 'Spanish' },
        ],
        loading: false,
      });
      getState().handleFilesDetected({
        type: 'session',
        files: ['/watch/spanish.wav'],
        count: 1,
        fileMeta: [],
      });
      expect(getState().jobs).toHaveLength(1);
      expect(lastJobOptions()?.language).toBe('es');
    });

    it('session: Canary + Auto Detect → pauses, no enqueue, "Source Language required" warn', () => {
      getState().updateSessionConfig({ language: 'Auto Detect' });
      getState().setLanguagesCache({
        model: 'nvidia/canary-1b-v2',
        languages: [{ code: 'es', name: 'Spanish' }],
        loading: false,
      });
      getState().handleFilesDetected({
        type: 'session',
        files: ['/watch/auto.wav'],
        count: 1,
        fileMeta: [],
      });
      expect(getState().jobs).toHaveLength(0);
      expect(lastWatchLogMessage()).toBe(
        'Folder Watch paused — Source Language required for the active model',
      );
      expect(toast.warning).toHaveBeenCalledWith(
        'Folder Watch paused — Source Language required for the active model',
      );
    });

    it('session: Canary + Spanish but languages loading → pauses, "languages still loading" warn', () => {
      getState().updateSessionConfig({ language: 'Spanish' });
      getState().setLanguagesCache({
        model: 'nvidia/canary-1b-v2',
        languages: [],
        loading: true,
      });
      getState().handleFilesDetected({
        type: 'session',
        files: ['/watch/early.wav'],
        count: 1,
        fileMeta: [],
      });
      expect(getState().jobs).toHaveLength(0);
      expect(lastWatchLogMessage()).toBe('Folder Watch paused — languages still loading');
      expect(toast.warning).toHaveBeenCalledWith('Folder Watch paused — languages still loading');
    });

    it('session: Whisper + Auto Detect → enqueues with language=undefined (auto-detect)', () => {
      getState().updateSessionConfig({ language: 'Auto Detect' });
      getState().setLanguagesCache({
        model: 'large-v3',
        languages: [{ code: 'es', name: 'Spanish' }],
        loading: false,
      });
      getState().handleFilesDetected({
        type: 'session',
        files: ['/watch/whisper-auto.wav'],
        count: 1,
        fileMeta: [],
      });
      expect(getState().jobs).toHaveLength(1);
      expect(lastJobOptions()?.language).toBeUndefined();
    });

    it('session: Whisper + Spanish → enqueues with language=es', () => {
      getState().updateSessionConfig({ language: 'Spanish' });
      getState().setLanguagesCache({
        model: 'large-v3',
        languages: [{ code: 'es', name: 'Spanish' }],
        loading: false,
      });
      getState().handleFilesDetected({
        type: 'session',
        files: ['/watch/whisper-es.wav'],
        count: 1,
        fileMeta: [],
      });
      expect(getState().jobs).toHaveLength(1);
      expect(lastJobOptions()?.language).toBe('es');
    });

    it('notebook: Canary + Spanish loaded → enqueues with language=es', () => {
      getState().updateNotebookConfig({ language: 'Spanish' });
      getState().setLanguagesCache({
        model: 'nvidia/canary-1b-v2',
        languages: [{ code: 'es', name: 'Spanish' }],
        loading: false,
      });
      getState().handleFilesDetected({
        type: 'notebook',
        files: ['/watch/notebook-es.wav'],
        count: 1,
        fileMeta: [{ path: '/watch/notebook-es.wav', createdAt: '2026-04-30T10:00:00Z' }],
      });
      expect(getState().jobs).toHaveLength(1);
      expect(lastJobOptions()?.language).toBe('es');
      expect(lastJobOptions()?.file_created_at).toBe('2026-04-30T10:00:00Z');
    });

    it('notebook: Canary + Auto Detect → pauses, no enqueue, "Source Language required" warn', () => {
      getState().updateNotebookConfig({ language: 'Auto Detect' });
      getState().setLanguagesCache({
        model: 'nvidia/canary-1b-v2',
        languages: [{ code: 'es', name: 'Spanish' }],
        loading: false,
      });
      getState().handleFilesDetected({
        type: 'notebook',
        files: ['/watch/notebook-auto.wav'],
        count: 1,
        fileMeta: [{ path: '/watch/notebook-auto.wav', createdAt: '2026-04-30T11:00:00Z' }],
      });
      expect(getState().jobs).toHaveLength(0);
      expect(lastWatchLogMessage()).toBe(
        'Folder Watch paused — Source Language required for the active model',
      );
      expect(toast.warning).toHaveBeenCalledWith(
        'Folder Watch paused — Source Language required for the active model',
      );
    });

    it('notebook: Canary + Spanish but languages loading → pauses, "languages still loading" warn', () => {
      getState().updateNotebookConfig({ language: 'Spanish' });
      getState().setLanguagesCache({
        model: 'nvidia/canary-1b-v2',
        languages: [],
        loading: true,
      });
      getState().handleFilesDetected({
        type: 'notebook',
        files: ['/watch/notebook-early.wav'],
        count: 1,
        fileMeta: [{ path: '/watch/notebook-early.wav', createdAt: '2026-04-30T12:00:00Z' }],
      });
      expect(getState().jobs).toHaveLength(0);
      expect(lastWatchLogMessage()).toBe('Folder Watch paused — languages still loading');
      expect(toast.warning).toHaveBeenCalledWith('Folder Watch paused — languages still loading');
    });

    it('notebook: Whisper + Auto Detect → enqueues with language=undefined (auto-detect)', () => {
      getState().updateNotebookConfig({ language: 'Auto Detect' });
      getState().setLanguagesCache({
        model: 'large-v3',
        languages: [{ code: 'es', name: 'Spanish' }],
        loading: false,
      });
      getState().handleFilesDetected({
        type: 'notebook',
        files: ['/watch/notebook-whisper-auto.wav'],
        count: 1,
        fileMeta: [{ path: '/watch/notebook-whisper-auto.wav', createdAt: '2026-04-30T13:00:00Z' }],
      });
      expect(getState().jobs).toHaveLength(1);
      expect(lastJobOptions()?.language).toBeUndefined();
    });

    it('notebook: Whisper + Spanish → enqueues with language=es', () => {
      getState().updateNotebookConfig({ language: 'Spanish' });
      getState().setLanguagesCache({
        model: 'large-v3',
        languages: [{ code: 'es', name: 'Spanish' }],
        loading: false,
      });
      getState().handleFilesDetected({
        type: 'notebook',
        files: ['/watch/notebook-whisper-es.wav'],
        count: 1,
        fileMeta: [{ path: '/watch/notebook-whisper-es.wav', createdAt: '2026-04-30T14:00:00Z' }],
      });
      expect(getState().jobs).toHaveLength(1);
      expect(lastJobOptions()?.language).toBe('es');
    });
  });

  // ── resolveDuplicateChoice (GH-120 — Folder Watch duplicate policy) ────
  //
  // The dedup gate must NOT block unattended Folder Watch (session-auto) jobs
  // on the interactive modal. session-auto jobs resolve duplicates per the
  // configured folderWatch.duplicatePolicy; manual (session-normal) jobs always
  // prompt. Default policy is 'create_new' so batch runs unattended out of the
  // box without ever silently dropping a file (data-loss invariant).

  describe('resolveDuplicateChoice (GH-120 — Folder Watch duplicate policy)', () => {
    const MATCHES: DedupMatch[] = [
      {
        recording_id: 'c3b4c22a',
        name: 'prior.mp3',
        created_at: '2026-05-07T00:00:00Z',
        source: 'transcription_job',
      },
    ];
    let requestChoiceSpy: Mock<(matches: DedupMatch[]) => Promise<DedupChoice>>;

    beforeEach(() => {
      // Override the dedup-choice store's interactive resolver so we can assert
      // whether the modal would have been raised.
      requestChoiceSpy = vi.fn(
        (_m: DedupMatch[]): Promise<DedupChoice> => Promise.resolve('create_new'),
      );
      useDedupChoiceStore.setState({ requestChoice: requestChoiceSpy });
      vi.mocked(getConfig).mockReset();
    });

    it('session-auto with no policy set defaults to create_new WITHOUT prompting (the GH-120 fix)', async () => {
      vi.mocked(getConfig).mockResolvedValue(undefined);
      const choice = await resolveDuplicateChoice('session-auto', MATCHES);
      expect(choice).toBe('create_new');
      expect(requestChoiceSpy).not.toHaveBeenCalled();
    });

    it("session-auto with policy 'create_new' resolves create_new without prompting", async () => {
      vi.mocked(getConfig).mockResolvedValue('create_new');
      const choice = await resolveDuplicateChoice('session-auto', MATCHES);
      expect(choice).toBe('create_new');
      expect(requestChoiceSpy).not.toHaveBeenCalled();
    });

    it("session-auto with policy 'ask' prompts the user via the interactive modal", async () => {
      vi.mocked(getConfig).mockResolvedValue('ask');
      const choice = await resolveDuplicateChoice('session-auto', MATCHES);
      expect(requestChoiceSpy).toHaveBeenCalledWith(MATCHES);
      expect(choice).toBe('create_new'); // whatever the modal returned
    });

    it('session-auto with an unknown/legacy policy value falls back to create_new (never re-blocks, never skips)', async () => {
      // e.g. a 'skip' value persisted by an earlier build, or a corrupt manual edit.
      // Must NOT fall through to the modal (that would re-introduce GH-120) and must
      // NOT skip transcription (that would risk data loss).
      vi.mocked(getConfig).mockResolvedValue('skip' as never);
      const choice = await resolveDuplicateChoice('session-auto', MATCHES);
      expect(choice).toBe('create_new');
      expect(requestChoiceSpy).not.toHaveBeenCalled();
    });

    it('session-auto defaults to create_new when the config read throws (no error cascade)', async () => {
      vi.mocked(getConfig).mockRejectedValue(new Error('IPC unavailable'));
      const choice = await resolveDuplicateChoice('session-auto', MATCHES);
      expect(choice).toBe('create_new');
      expect(requestChoiceSpy).not.toHaveBeenCalled();
    });

    it('session-normal (manual import) always prompts, ignoring the folder-watch policy', async () => {
      vi.mocked(getConfig).mockResolvedValue('create_new');
      const choice = await resolveDuplicateChoice('session-normal', MATCHES);
      expect(requestChoiceSpy).toHaveBeenCalledWith(MATCHES);
      expect(choice).toBe('create_new');
    });
  });

  // ── Watcher state stubs ────────────────────────────────────────────────

  describe('watcher state', () => {
    it('sets session watch path', () => {
      getState().setSessionWatchPath('/watch/session');
      expect(getState().sessionWatchPath).toBe('/watch/session');
    });

    it('sets session watch active', () => {
      getState().setSessionWatchActive(true);
      expect(getState().sessionWatchActive).toBe(true);
    });

    it('sets notebook watch path', () => {
      getState().setNotebookWatchPath('/watch/notebook');
      expect(getState().notebookWatchPath).toBe('/watch/notebook');
    });

    it('sets notebook watch active', () => {
      getState().setNotebookWatchActive(true);
      expect(getState().notebookWatchActive).toBe(true);
    });
  });

  // ── Derived selectors ─────────────────────────────────────────────────

  describe('selectors', () => {
    const mixedJobs = [
      makeJob({ id: 's1', type: 'session-normal', status: 'pending' }),
      makeJob({ id: 's2', type: 'session-auto', status: 'processing' }),
      makeJob({ id: 'n1', type: 'notebook-normal', status: 'success' }),
      makeJob({ id: 'n2', type: 'notebook-auto', status: 'error', error: 'fail' }),
      makeJob({ id: 's3', type: 'session-normal', status: 'writing' }),
      makeJob({ id: 'n3', type: 'notebook-normal', status: 'pending' }),
    ];

    beforeEach(() => {
      useImportQueueStore.setState({ jobs: mixedJobs });
    });

    it('selectPendingCount counts pending jobs', () => {
      expect(selectPendingCount(getState())).toBe(2);
    });

    it('selectCompletedCount counts success jobs', () => {
      expect(selectCompletedCount(getState())).toBe(1);
    });

    it('selectErrorCount counts error jobs', () => {
      expect(selectErrorCount(getState())).toBe(1);
    });

    it('selectIsProcessing detects processing or writing', () => {
      expect(selectIsProcessing(getState())).toBe(true);
    });

    it('selectIsProcessing returns false when no active jobs', () => {
      useImportQueueStore.setState({
        jobs: [makeJob({ status: 'pending' }), makeJob({ status: 'success' })],
      });
      expect(selectIsProcessing(getState())).toBe(false);
    });

    it('selectIsUploading returns true when pending or active jobs exist', () => {
      expect(selectIsUploading(getState())).toBe(true);
    });

    it('selectIsUploading returns false when all done', () => {
      useImportQueueStore.setState({
        jobs: [makeJob({ status: 'success' }), makeJob({ status: 'error' })],
      });
      expect(selectIsUploading(getState())).toBe(false);
    });

    it('selectSessionJobs filters session types', () => {
      const sessionJobs = selectSessionJobs(getState());
      expect(sessionJobs).toHaveLength(3);
      expect(sessionJobs.every((j) => j.type.startsWith('session'))).toBe(true);
    });

    it('selectNotebookJobs filters notebook types', () => {
      const notebookJobs = selectNotebookJobs(getState());
      expect(notebookJobs).toHaveLength(3);
      expect(notebookJobs.every((j) => j.type.startsWith('notebook'))).toBe(true);
    });
  });
});
