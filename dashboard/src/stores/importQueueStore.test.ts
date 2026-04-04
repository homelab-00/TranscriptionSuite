import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Mock apiClient before importing the store
vi.mock('../api/client', () => ({
  apiClient: {
    importAndTranscribe: vi.fn(),
    uploadAndTranscribe: vi.fn(),
    getAdminStatus: vi.fn(),
    cancelTranscription: vi.fn().mockResolvedValue(undefined),
  },
}));

// Mock transcription formatters
vi.mock('../services/transcriptionFormatters', () => ({
  renderSrt: vi.fn(() => 'srt-content'),
  renderAss: vi.fn(() => 'ass-content'),
  renderTxt: vi.fn(() => 'txt-content'),
  resolveTranscriptionOutput: vi.fn(() => ({
    outputFilename: 'test.txt',
    content: 'txt-content',
  })),
}));

// Stub window.electronAPI
Object.defineProperty(globalThis, 'window', {
  value: globalThis,
  writable: true,
});

import {
  useImportQueueStore,
  selectPendingCount,
  selectCompletedCount,
  selectErrorCount,
  selectIsProcessing,
  selectIsUploading,
  selectSessionJobs,
  selectNotebookJobs,
} from './importQueueStore';
import type { UnifiedImportJob } from './importQueueStore';

function resetStore() {
  useImportQueueStore.setState({
    jobs: [],
    isPaused: false,
    sessionConfig: { outputDir: '', diarizedFormat: 'srt' },
    notebookCallbacks: {},
    sessionWatchPath: '',
    sessionWatchActive: false,
    notebookWatchPath: '',
    notebookWatchActive: false,
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

  // ── updateNotebookCallbacks ────────────────────────────────────────────

  describe('updateNotebookCallbacks', () => {
    it('sets callback functions', () => {
      const onSuccess = vi.fn();
      getState().updateNotebookCallbacks({ onJobSuccess: onSuccess });
      expect(getState().notebookCallbacks.onJobSuccess).toBe(onSuccess);
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
