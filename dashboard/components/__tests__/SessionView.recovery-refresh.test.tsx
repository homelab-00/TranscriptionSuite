/**
 * SessionView - keeping the recovery banner current (GH-239).
 *
 * The banner lists completed-but-undelivered jobs from GET /transcribe/recent,
 * which is how a transcript reaches the user when the socket that ordered it is
 * gone. It used to be fetched exactly once, on mount, so a result that landed
 * afterwards stayed invisible until the view was remounted.
 *
 * GH-239 made that reachable in normal use: after a mid-recording drop the
 * server salvages the buffered audio into the same job, and the salvage can
 * easily outlast the hook poll that waits for it. The result is then sitting in
 * the database, undelivered, with nothing on screen pointing at it.
 */

import React from 'react';
import { render, screen, waitFor, fireEvent, within, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ── Hoisted mock state ────────────────────────────────────────────────────

const mockTranscription = {
  status: 'error' as string,
  result: null as unknown,
  error: null as string | null,
  analyser: null,
  start: vi.fn(),
  stop: vi.fn(),
  reset: vi.fn(),
  vadActive: false,
  processingProgress: null,
  muted: false,
  toggleMute: vi.fn(),
  setGain: vi.fn(),
  jobId: null as string | null,
  resultJobId: null as string | null,
  busyInfo: null as null | { activeUser: string; isSalvage: boolean; salvageJobId: string | null },
  clearBusyInfo: vi.fn(),
  loadResult: vi.fn(),
  previewText: null,
  previewLanguage: undefined,
  previewSeconds: null,
  previewLoading: false,
  previewError: null,
  previewActive: false,
  startPreview: vi.fn(),
  stopPreview: vi.fn(),
};

const mockGetConfig = vi.fn().mockResolvedValue(undefined);

vi.mock('../../src/hooks/useTranscription', () => ({
  useTranscription: () => mockTranscription,
}));

vi.mock('../../src/hooks/useLanguages', () => ({
  useLanguages: () => ({
    languages: [
      { code: 'auto', name: 'Auto Detect' },
      { code: 'en', name: 'English' },
    ],
    backendType: 'whisper',
    loading: false,
    error: null,
  }),
}));

vi.mock('../../src/hooks/useAdminStatus', () => ({
  useAdminStatus: () => ({
    status: {
      models_loaded: true,
      config: {
        main_transcriber: { model: 'Systran/faster-whisper-large-v3' },
        live_transcriber: { model: 'Systran/faster-whisper-large-v3' },
      },
    },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock('../../src/hooks/DockerContext', () => ({
  useDockerContext: () => ({
    available: true,
    loading: false,
    runtimeKind: 'Docker',
    detectionGuidance: null,
    composeAvailable: true,
    images: [],
    container: { exists: true, running: true, status: 'running', health: 'healthy' },
    volumes: [],
    operating: false,
    operationError: null,
    pulling: false,
    sidecarPulling: false,
    logLines: [],
    logStreaming: false,
    hasSidecarImage: vi.fn().mockResolvedValue(false),
    startLogStream: vi.fn(),
    stopLogStream: vi.fn(),
    clearLogs: vi.fn(),
    refreshImages: vi.fn(),
    refreshVolumes: vi.fn(),
    pullImage: vi.fn(),
    cancelPull: vi.fn(),
    pullSidecarImage: vi.fn(),
    cancelSidecarPull: vi.fn(),
    removeImage: vi.fn(),
    startContainer: vi.fn(),
    stopContainer: vi.fn(),
    removeContainer: vi.fn(),
    removeVolume: vi.fn(),
    cleanAll: vi.fn(),
    retryDetection: vi.fn(),
  }),
}));

vi.mock('../../src/hooks/useTraySync', () => ({ useTraySync: vi.fn() }));

vi.mock('../../src/stores/importQueueStore', () => ({
  useImportQueueStore: (selector: (s: Record<string, unknown>) => unknown) => {
    const state = {
      jobs: [],
      isPaused: false,
      sessionConfig: { outputDir: '', diarizedFormat: 'srt', hideTimestamps: false },
      sessionWatchPath: '',
      sessionWatchActive: false,
    };
    return typeof selector === 'function' ? selector(state) : state;
  },
}));

// vi.mock factories are hoisted above the declarations in this file, and the
// api/client factory dereferences APIError eagerly — so the class has to be
// created inside vi.hoisted or it is still in the temporal dead zone.
const {
  MockAPIError,
  mockRetryTranscription,
  mockFetchTranscriptionResult,
  mockFetchRecentUndelivered,
  mockDismissTranscriptionResult,
  mockToast,
  mockGetStatus,
  mockCancelTranscription,
  mockWaitForJobSlotFree,
} = vi.hoisted(() => {
  class HoistedAPIError extends Error {
    constructor(
      public readonly status: number,
      public readonly body: string,
      public readonly path: string,
    ) {
      super(`API ${status} on ${path}`);
      this.name = 'APIError';
    }
  }
  return {
    MockAPIError: HoistedAPIError,
    mockRetryTranscription: vi.fn(),
    mockFetchTranscriptionResult: vi.fn(),
    mockFetchRecentUndelivered: vi.fn(),
    mockDismissTranscriptionResult: vi.fn(),
    mockToast: { success: vi.fn(), error: vi.fn() },
    mockGetStatus: vi.fn(),
    mockCancelTranscription: vi.fn(),
    mockWaitForJobSlotFree: vi.fn(),
  };
});

vi.mock('../../src/hooks/useSalvageProgress', () => ({
  waitForJobSlotFree: (...a: unknown[]) => mockWaitForJobSlotFree(...a),
}));

vi.mock('../../src/api/client', () => ({
  APIError: MockAPIError,
  apiClient: {
    checkConnection: vi.fn().mockResolvedValue({ reachable: true, ready: true }),
    getAdminStatus: vi.fn().mockResolvedValue({}),
    cancelTranscription: (...a: unknown[]) => mockCancelTranscription(...a),
    getStatus: (...a: unknown[]) => mockGetStatus(...a),
    getAuthToken: vi.fn().mockReturnValue(null),
    setAuthToken: vi.fn(),
    getJobAudioUrl: (id: string) => `http://localhost:7239/api/transcribe/audio/${id}`,
    getBaseUrl: vi.fn().mockReturnValue('http://localhost:7239'),
    syncFromConfig: vi.fn().mockResolvedValue(undefined),
    unloadModels: vi.fn().mockResolvedValue(undefined),
    unloadLLMModel: vi.fn().mockResolvedValue(undefined),
    loadModelsStream: vi.fn().mockReturnValue(vi.fn()),
    fetchRecentUndelivered: (...a: unknown[]) => mockFetchRecentUndelivered(...a),
    fetchTranscriptionResult: (...a: unknown[]) => mockFetchTranscriptionResult(...a),
    dismissTranscriptionResult: (...a: unknown[]) => mockDismissTranscriptionResult(...a),
    retryTranscription: (...a: unknown[]) => mockRetryTranscription(...a),
  },
}));

vi.mock('../../src/config/store', () => ({
  getConfig: (...args: unknown[]) => mockGetConfig(...args),
  setConfig: vi.fn().mockResolvedValue(undefined),
  getAuthToken: vi.fn().mockResolvedValue(null),
  DEFAULT_SERVER_PORT: 7239,
}));

vi.mock('../../src/services/modelCapabilities', async () => {
  const actual = await vi.importActual<typeof import('../../src/services/modelCapabilities')>(
    '../../src/services/modelCapabilities',
  );
  return actual;
});

vi.mock('../../src/services/modelSelection', () => ({
  isModelDisabled: () => false,
}));

vi.mock('../../src/hooks/useClipboard', () => ({ writeToClipboard: vi.fn() }));
vi.mock('../../src/services/clientDebugLog', () => ({ logClientEvent: vi.fn() }));

vi.mock('sonner', () => ({ toast: mockToast }));

vi.mock('../views/SessionImportTab', () => ({
  SessionImportTab: () => React.createElement('div', { 'data-testid': 'session-import-tab' }),
}));
vi.mock('../PopOutWindow', () => ({ PopOutWindow: () => null }));
vi.mock('../views/FullscreenVisualizer', () => ({ FullscreenVisualizer: () => null }));
vi.mock('../AudioVisualizer', () => ({
  AudioVisualizer: () => React.createElement('div', { 'data-testid': 'audio-visualizer' }),
}));

vi.mock('../../src/types/runtime', () => ({
  isRuntimeProfile: (v: unknown) =>
    ['gpu', 'cpu', 'vulkan', 'vulkan-wsl2', 'metal'].includes(v as string),
}));

import { SessionView } from '../views/SessionView';
import { useSalvageStore } from '../../src/stores/salvageStore';

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

const baseProps = {
  serverConnection: {
    serverStatus: 'active' as const,
    clientStatus: 'active' as const,
    details: null,
    serverLabel: 'Server ready',
    reachable: true,
    ready: true,
    error: null,
    gpuError: null,
    gpuErrorRecoveryHint: null,
    refresh: vi.fn(),
  },
  clientRunning: true,
  setClientRunning: vi.fn(),
  onStartServer: vi.fn().mockResolvedValue(undefined),
  startupFlowPending: false,
  isUploading: false,
  live: {
    status: 'idle' as const,
    sentences: [],
    partial: '',
    statusMessage: null,
    error: null,
    analyser: null,
    muted: false,
    start: vi.fn(),
    stop: vi.fn(),
    toggleMute: vi.fn(),
    setGain: vi.fn(),
    clearHistory: vi.fn(),
    getText: vi.fn().mockReturnValue(''),
  },
};

function renderSessionView() {
  return render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });
}

const JOB_ID = '48eae812-f5ff-400e-b2bc-4dede99c5a15';

// The Electron file bridge behind Save Audio. useFileSaveDialog reads
// window.electronAPI.fileIO directly, so stubbing the object is enough.
const mockSaveFile = vi.fn();
const mockDownloadToPath = vi.fn();

/** Fixed so the banner's relative-time label cannot drift between runs. */
const COMPLETED_AT = '2026-08-03T00:00:00.000Z';

const SALVAGED = [
  {
    job_id: 'salvaged-job',
    completed_at: COMPLETED_AT,
    text_preview: 'the half that made it',
  },
];

describe('SessionView - recovery banner refresh', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTranscription.status = 'idle';
    mockTranscription.result = null;
    mockTranscription.error = null;
    mockTranscription.jobId = null;
    mockTranscription.resultJobId = null;
    mockTranscription.busyInfo = null;
    mockGetConfig.mockResolvedValue(undefined);
    mockFetchRecentUndelivered.mockResolvedValue({ json: async () => [] });
    mockDismissTranscriptionResult.mockResolvedValue({ status: 200 });
    mockGetStatus.mockResolvedValue({
      models: { job_tracker: { is_busy: false, salvage: null } },
    });
    mockCancelTranscription.mockResolvedValue({
      success: true,
      cancelled_user: 'laptop',
      message: '',
    });
    mockWaitForJobSlotFree.mockResolvedValue(true);
    useSalvageStore.setState({ checkNonce: 0, dropRequestedJobId: null, lastCompletedAt: null });
  });

  it('lists an undelivered result found at mount', async () => {
    mockFetchRecentUndelivered.mockResolvedValue({ json: async () => SALVAGED });
    renderSessionView();

    expect(await screen.findByText(/the half that made it/)).toBeInTheDocument();
  });

  it('re-checks when the recording ends in an error', async () => {
    const { rerender } = renderSessionView();
    await waitFor(() => expect(mockFetchRecentUndelivered).toHaveBeenCalledTimes(1));

    // The GH-239 poll gave up. The salvage may well have finished since.
    mockFetchRecentUndelivered.mockResolvedValue({ json: async () => SALVAGED });
    mockTranscription.status = 'error';
    mockTranscription.error = 'Connection to the server was lost.';
    rerender(React.createElement(SessionView, baseProps));

    expect(await screen.findByText(/the half that made it/)).toBeInTheDocument();
  });

  it('does not re-check on every unrelated re-render', async () => {
    const { rerender } = renderSessionView();
    await waitFor(() => expect(mockFetchRecentUndelivered).toHaveBeenCalledTimes(1));

    rerender(React.createElement(SessionView, baseProps));
    rerender(React.createElement(SessionView, baseProps));

    expect(mockFetchRecentUndelivered).toHaveBeenCalledTimes(1);
  });

  it('re-checks when the window regains focus', async () => {
    renderSessionView();
    await waitFor(() => expect(mockFetchRecentUndelivered).toHaveBeenCalledTimes(1));

    // The user walked away while the salvage ran and has just come back.
    mockFetchRecentUndelivered.mockResolvedValue({ json: async () => SALVAGED });
    fireEvent(window, new Event('focus'));

    expect(await screen.findByText(/the half that made it/)).toBeInTheDocument();
  });

  it('stops listening for focus once unmounted', async () => {
    const { unmount } = renderSessionView();
    await waitFor(() => expect(mockFetchRecentUndelivered).toHaveBeenCalledTimes(1));

    unmount();
    fireEvent(window, new Event('focus'));

    expect(mockFetchRecentUndelivered).toHaveBeenCalledTimes(1);
  });

  it('does not offer to recover the transcript already on screen', async () => {
    // mark_delivered is best-effort, so a just-recovered job can still come
    // back from /recent. Announcing it beside its own transcript reads as a
    // second, missing result. The test is resultJobId, not jobId: what matters
    // is that THIS job's transcript is the one being displayed.
    mockFetchRecentUndelivered.mockResolvedValue({
      json: async () => [
        { job_id: JOB_ID, completed_at: COMPLETED_AT, text_preview: 'on screen now' },
        ...SALVAGED,
      ],
    });
    mockTranscription.status = 'complete';
    mockTranscription.jobId = JOB_ID;
    mockTranscription.resultJobId = JOB_ID;
    mockTranscription.result = { text: 'on screen now', words: [] };
    renderSessionView();

    expect(await screen.findByText(/the half that made it/)).toBeInTheDocument();
    // Exactly one banner: the salvaged job. Scoped to the banner wording,
    // because the on-screen job's text also appears in the transcript box.
    const banners = screen.getAllByText(/is available\./);
    expect(banners).toHaveLength(1);
    expect(banners[0].closest('div')?.textContent).toContain('the half that made it');
  });

  // The incident, end to end. A longform job died on a CUDA OOM, the user
  // pressed Retry, the retry succeeded, and the in-memory poll that was meant
  // to deliver it died. The row stayed completed and undelivered, /retry
  // refused it as already completed, and the banner - the last route to it -
  // hid it because the filter tested jobId, which deliberately survives an
  // error so the Retry button stays live. Nothing on screen pointed at a
  // transcript that was in the database the whole time.
  it('offers to recover the failed job whose transcript never arrived', async () => {
    mockFetchRecentUndelivered.mockResolvedValue({
      json: async () => [
        { job_id: JOB_ID, completed_at: COMPLETED_AT, text_preview: 'the transcript nobody saw' },
      ],
    });
    mockTranscription.status = 'error';
    mockTranscription.error = 'CUDA failed with error out of memory';
    mockTranscription.jobId = JOB_ID;
    mockTranscription.result = null;
    mockTranscription.resultJobId = null;
    renderSessionView();

    expect(await screen.findByText(/the transcript nobody saw/)).toBeInTheDocument();
  });

  // Same shape one step later: a PARTIAL transcript is on screen and the user
  // retried from its amber banner. jobId still points at that job, so the old
  // filter hid it again even though the retried, complete transcript is a
  // different result the user has never seen.
  it('still offers recovery while a partial from the same job is on screen', async () => {
    mockFetchRecentUndelivered.mockResolvedValue({
      json: async () => [
        { job_id: JOB_ID, completed_at: COMPLETED_AT, text_preview: 'the retried whole thing' },
      ],
    });
    mockTranscription.status = 'complete';
    mockTranscription.jobId = JOB_ID;
    mockTranscription.result = { text: 'only the first half', words: [], partial: true };
    // The retry delivery never landed, so nothing on screen belongs to a job.
    mockTranscription.resultJobId = null;
    renderSessionView();

    expect(await screen.findByText(/the retried whole thing/)).toBeInTheDocument();
  });

  // /recent returns at most 5 rows. A user who has been cancelling recordings
  // from the tray for days comes back to a full banner, and every Dismiss must
  // pull the next queued (older) job into view at once, not on the next focus.
  it('re-checks after a Dismiss so the next queued job surfaces immediately', async () => {
    mockFetchRecentUndelivered.mockResolvedValueOnce({ json: async () => SALVAGED });
    let settleDismiss: (v: { status: number }) => void = () => {};
    mockDismissTranscriptionResult.mockReturnValueOnce(
      new Promise<{ status: number }>((resolve) => {
        settleDismiss = resolve;
      }),
    );
    renderSessionView();
    expect(await screen.findByText(/the half that made it/)).toBeInTheDocument();
    expect(mockFetchRecentUndelivered).toHaveBeenCalledTimes(1);

    mockFetchRecentUndelivered.mockResolvedValue({
      json: async () => [
        { job_id: 'older-job', completed_at: COMPLETED_AT, text_preview: 'from three days ago' },
      ],
    });
    fireEvent.click(screen.getByText('Dismiss'));

    // Optimistic removal is instant, but the re-check waits for the server to
    // acknowledge the dismiss - otherwise the dismissed row would come back.
    expect(screen.queryByText(/the half that made it/)).not.toBeInTheDocument();
    expect(mockFetchRecentUndelivered).toHaveBeenCalledTimes(1);

    await act(async () => {
      settleDismiss({ status: 200 });
    });

    expect(await screen.findByText(/from three days ago/)).toBeInTheDocument();
    expect(mockFetchRecentUndelivered).toHaveBeenCalledTimes(2);
  });

  it('keeps a row whose dismiss is still in flight out of a concurrent re-check', async () => {
    const TWO = [
      ...SALVAGED,
      { job_id: 'second-job', completed_at: COMPLETED_AT, text_preview: 'the second one' },
    ];
    mockFetchRecentUndelivered.mockResolvedValueOnce({ json: async () => TWO });
    let settleSecond: (v: { status: number }) => void = () => {};
    mockDismissTranscriptionResult.mockResolvedValueOnce({ status: 200 }).mockReturnValueOnce(
      new Promise<{ status: number }>((resolve) => {
        settleSecond = resolve;
      }),
    );
    renderSessionView();
    expect(await screen.findByText(/the second one/)).toBeInTheDocument();

    // The first dismiss's re-check answers before the server has processed
    // the second dismiss, so it still lists the second job.
    mockFetchRecentUndelivered.mockResolvedValue({ json: async () => [TWO[1]] });
    const [first, second] = screen.getAllByText('Dismiss');
    fireEvent.click(first);
    fireEvent.click(second);

    await waitFor(() => expect(mockFetchRecentUndelivered).toHaveBeenCalledTimes(2));
    expect(screen.queryByText(/the second one/)).not.toBeInTheDocument();

    mockFetchRecentUndelivered.mockResolvedValue({ json: async () => [] });
    await act(async () => {
      settleSecond({ status: 200 });
    });
    await waitFor(() => expect(mockFetchRecentUndelivered).toHaveBeenCalledTimes(3));
    expect(screen.queryByText(/the second one/)).not.toBeInTheDocument();
  });

  it('drops a stale re-check that answers after a newer one', async () => {
    // A focus-triggered re-check was sent before the Dismiss and is slow. Its
    // payload still lists the job; it must not overwrite the newer, correct
    // answer that arrived after the dismiss was acknowledged.
    mockFetchRecentUndelivered.mockResolvedValueOnce({ json: async () => SALVAGED });
    renderSessionView();
    expect(await screen.findByText(/the half that made it/)).toBeInTheDocument();

    let settleStale: (v: { json: () => Promise<unknown> }) => void = () => {};
    mockFetchRecentUndelivered.mockReturnValueOnce(
      new Promise<{ json: () => Promise<unknown> }>((resolve) => {
        settleStale = resolve;
      }),
    );
    fireEvent(window, new Event('focus'));
    await waitFor(() => expect(mockFetchRecentUndelivered).toHaveBeenCalledTimes(2));

    mockFetchRecentUndelivered.mockResolvedValue({ json: async () => [] });
    fireEvent.click(screen.getByText('Dismiss'));
    await waitFor(() => expect(mockFetchRecentUndelivered).toHaveBeenCalledTimes(3));

    await act(async () => {
      settleStale({ json: async () => SALVAGED });
    });

    expect(screen.queryByText(/the half that made it/)).not.toBeInTheDocument();
  });

  it('re-checks after View loads a result so the next queued job surfaces', async () => {
    mockFetchRecentUndelivered.mockResolvedValueOnce({ json: async () => SALVAGED });
    mockFetchTranscriptionResult.mockResolvedValue({
      status: 200,
      json: async () => ({ result: { text: 'the half that made it', words: [] } }),
    });
    renderSessionView();
    expect(await screen.findByText(/the half that made it/)).toBeInTheDocument();

    mockFetchRecentUndelivered.mockResolvedValue({
      json: async () => [
        { job_id: 'older-job', completed_at: COMPLETED_AT, text_preview: 'from three days ago' },
      ],
    });
    fireEvent.click(screen.getByText('View'));

    await waitFor(() => expect(mockTranscription.loadResult).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/from three days ago/)).toBeInTheDocument();
    expect(mockFetchRecentUndelivered).toHaveBeenCalledTimes(2);
  });

  // The banner is the safety net the whole fix leans on, and it was hand
  // mapping four fewer fields than the hook does. A salvaged PARTIAL transcript
  // arrived here looking complete: no amber banner, no Retry, no speaker
  // labels, no reason. It also has to say which job it just delivered, or the
  // filter above cannot tell that this row is now on screen.
  it('View delivers the whole payload and names the job it belongs to', async () => {
    mockFetchRecentUndelivered.mockResolvedValueOnce({ json: async () => SALVAGED });
    mockFetchTranscriptionResult.mockResolvedValue({
      status: 200,
      json: async () => ({
        result: {
          text: 'the half that made it',
          words: [],
          partial: true,
          partial_reason: 'Client disconnected mid-recording',
          num_speakers: 3,
          diarization: {
            requested: true,
            performed: false,
            reason: 'model_missing',
            remedy: 'Install the diarization model',
          },
        },
      }),
    });
    renderSessionView();
    expect(await screen.findByText(/the half that made it/)).toBeInTheDocument();

    fireEvent.click(screen.getByText('View'));

    await waitFor(() => expect(mockTranscription.loadResult).toHaveBeenCalledTimes(1));
    expect(mockTranscription.loadResult).toHaveBeenCalledWith(
      expect.objectContaining({
        text: 'the half that made it',
        partial: true,
        partialReason: 'Client disconnected mid-recording',
        numSpeakers: 3,
        diarization: expect.objectContaining({ requested: true, performed: false }),
      }),
      'salvaged-job',
    );
  });
});

// Save Audio - the source recording is the one thing that cannot be recreated,
// and in the recovery row it has to come BEFORE View, because View delivers the
// transcript and delivering a session job unlinks its WAV.
describe('SessionView - Save Audio in the recovery row', () => {
  let previousElectronAPI: typeof window.electronAPI;

  beforeEach(() => {
    vi.clearAllMocks();
    mockTranscription.status = 'idle';
    mockTranscription.result = null;
    mockTranscription.error = null;
    mockTranscription.jobId = null;
    mockTranscription.resultJobId = null;
    mockTranscription.busyInfo = null;
    mockGetConfig.mockResolvedValue(undefined);
    mockFetchRecentUndelivered.mockResolvedValue({ json: async () => SALVAGED });
    mockGetStatus.mockResolvedValue({
      models: { job_tracker: { is_busy: false, salvage: null } },
    });
    useSalvageStore.setState({ checkNonce: 0, dropRequestedJobId: null, lastCompletedAt: null });
    mockSaveFile.mockResolvedValue('/home/user/keep.wav');
    mockDownloadToPath.mockResolvedValue({ ok: true, bytes: 1024 });
    previousElectronAPI = window.electronAPI;
    window.electronAPI = {
      fileIO: { saveFile: mockSaveFile, downloadToPath: mockDownloadToPath },
    } as unknown as typeof window.electronAPI;
  });

  // Restore rather than leave the stub behind: describes that run after this
  // one share the same jsdom window.
  afterEach(() => {
    window.electronAPI = previousElectronAPI;
  });

  it('renders before View, so the audio can be kept before it is released', async () => {
    renderSessionView();
    const button = await screen.findByTestId('recovery-save-audio');
    const view = screen.getByText('View');

    // Node.DOCUMENT_POSITION_FOLLOWING === 4
    expect(button.compareDocumentPosition(view) & 4).toBeTruthy();
  });

  it('downloads the WAV for that job to the chosen path', async () => {
    renderSessionView();
    fireEvent.click(await screen.findByTestId('recovery-save-audio'));

    await waitFor(() => expect(mockDownloadToPath).toHaveBeenCalledTimes(1));
    expect(mockDownloadToPath).toHaveBeenCalledWith(
      expect.objectContaining({
        url: 'http://localhost:7239/api/transcribe/audio/salvaged-job',
        filePath: '/home/user/keep.wav',
      }),
    );
    await waitFor(() => expect(mockToast.success).toHaveBeenCalled());
    expect(mockToast.success.mock.calls[0][1]).toMatchObject({
      description: '/home/user/keep.wav',
    });
  });

  it('says nothing when the save dialog is cancelled', async () => {
    mockSaveFile.mockResolvedValue(null);
    renderSessionView();
    fireEvent.click(await screen.findByTestId('recovery-save-audio'));

    await waitFor(() => expect(mockSaveFile).toHaveBeenCalledTimes(1));
    expect(mockDownloadToPath).not.toHaveBeenCalled();
    expect(mockToast.success).not.toHaveBeenCalled();
    expect(mockToast.error).not.toHaveBeenCalled();
  });

  // The 410 body distinguishes never-preserved from lost-on-restart from
  // already-deleted, and that distinction is the entire answer for the user.
  it('surfaces the server own reason when the audio is gone', async () => {
    mockDownloadToPath.mockResolvedValue({
      ok: false,
      error: 'HTTP 410',
      status: 410,
      body: JSON.stringify({ detail: 'Audio file has been deleted - cannot download' }),
    });
    renderSessionView();
    fireEvent.click(await screen.findByTestId('recovery-save-audio'));

    await waitFor(() => expect(mockToast.error).toHaveBeenCalled());
    expect(mockToast.error.mock.calls[0][1]).toMatchObject({
      description: 'Audio file has been deleted - cannot download',
    });
  });

  it('disables itself while a save is in flight', async () => {
    let settle: (v: { ok: true }) => void = () => {};
    mockDownloadToPath.mockReturnValueOnce(
      new Promise<{ ok: true }>((resolve) => {
        settle = resolve;
      }),
    );
    renderSessionView();
    const button = await screen.findByTestId('recovery-save-audio');
    fireEvent.click(button);

    await waitFor(() => expect(button).toBeDisabled());
    await act(async () => {
      settle({ ok: true });
    });
    await waitFor(() => expect(button).not.toBeDisabled());
  });
});

describe('SessionView - salvage drop popup (GH-239 follow-up)', () => {
  const BUSY = { activeUser: 'laptop', isSalvage: true, salvageJobId: 'salv-1' };

  // This describe has no shared setup with the one above, so mock call
  // history from one test (e.g. the cancel call in the drop-flow test) would
  // otherwise leak into the next (e.g. the decline test asserting no cancel).
  beforeEach(() => {
    vi.clearAllMocks();
    mockTranscription.busyInfo = null;
    mockGetStatus.mockResolvedValue({
      models: { job_tracker: { is_busy: false, salvage: null } },
    });
    mockCancelTranscription.mockResolvedValue({
      success: true,
      cancelled_user: 'laptop',
      message: '',
    });
    mockFetchRecentUndelivered.mockResolvedValue({ json: async () => [] });
    mockWaitForJobSlotFree.mockResolvedValue(true);
    // vi.clearAllMocks() keeps implementations, so the auto-stop test below
    // would otherwise leak its config answer into every later test.
    mockGetConfig.mockResolvedValue(undefined);
    useSalvageStore.setState({ checkNonce: 0, dropRequestedJobId: null, lastCompletedAt: null });
  });

  it('opens the confirm dialog when start bounced off an active salvage', async () => {
    mockTranscription.busyInfo = { ...BUSY };
    renderSessionView();

    expect(await screen.findByText(/interrupted recording/)).toBeInTheDocument();
    expect(mockTranscription.clearBusyInfo).toHaveBeenCalled();
  });

  it('points at the Settings toggle that suppresses the dialog', async () => {
    mockTranscription.busyInfo = { ...BUSY };
    renderSessionView();

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/Settings . Client . Recovery/)).toBeInTheDocument();
  });

  it('auto-stop setting drops the salvage without showing the confirm', async () => {
    mockGetConfig.mockImplementation(async (key: unknown) =>
      key === 'recovery.autoStopAndRecord' ? true : undefined,
    );
    mockGetStatus.mockResolvedValueOnce({
      models: {
        job_tracker: {
          is_busy: true,
          salvage: { job_id: 'salv-1', client_name: 'laptop', started_at: 1 },
        },
      },
    });
    mockTranscription.busyInfo = { ...BUSY };
    renderSessionView();

    await waitFor(() => expect(mockTranscription.start).toHaveBeenCalledTimes(1));
    expect(mockCancelTranscription).toHaveBeenCalledTimes(1);
    expect(useSalvageStore.getState().dropRequestedJobId).toBe('salv-1');
    expect(screen.queryByText('Stop and record')).not.toBeInTheDocument();
  });

  it('drop flow: cancels the salvage, marks the drop, and restarts recording', async () => {
    mockGetStatus.mockResolvedValueOnce({
      models: {
        job_tracker: {
          is_busy: true,
          salvage: { job_id: 'salv-1', client_name: 'laptop', started_at: 1 },
        },
      },
    });
    mockTranscription.busyInfo = { ...BUSY };
    renderSessionView();

    fireEvent.click(await screen.findByText('Stop and record'));

    await waitFor(() => expect(mockCancelTranscription).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockTranscription.start).toHaveBeenCalledTimes(1));
    expect(useSalvageStore.getState().dropRequestedJobId).toBe('salv-1');
  });

  it('skips the cancel when the salvage already ended', async () => {
    mockTranscription.busyInfo = { ...BUSY };
    renderSessionView();

    fireEvent.click(await screen.findByText('Stop and record'));

    await waitFor(() => expect(mockTranscription.start).toHaveBeenCalledTimes(1));
    expect(mockCancelTranscription).not.toHaveBeenCalled();
    expect(useSalvageStore.getState().dropRequestedJobId).toBeNull();
  });

  it('declining leaves the salvage alone', async () => {
    mockTranscription.busyInfo = { ...BUSY };
    renderSessionView();

    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByText('Cancel'));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(mockCancelTranscription).not.toHaveBeenCalled();
    expect(mockTranscription.start).not.toHaveBeenCalled();
  });

  it('refreshes the recovery banner when a salvage ends', async () => {
    renderSessionView();
    await waitFor(() => expect(mockFetchRecentUndelivered).toHaveBeenCalled());
    mockFetchRecentUndelivered.mockClear();

    act(() => {
      useSalvageStore.getState().markSalvageEnded();
    });

    await waitFor(() => expect(mockFetchRecentUndelivered).toHaveBeenCalled());
  });

  it('cancel failure aborts the drop flow with an error toast', async () => {
    mockGetStatus.mockResolvedValueOnce({
      models: {
        job_tracker: {
          is_busy: true,
          salvage: { job_id: 'salv-1', client_name: 'laptop', started_at: 1 },
        },
      },
    });
    mockTranscription.busyInfo = { ...BUSY };
    mockCancelTranscription.mockRejectedValueOnce(new Error('boom'));
    renderSessionView();

    fireEvent.click(await screen.findByText('Stop and record'));

    await waitFor(() => expect(mockToast.error).toHaveBeenCalled());
    expect(mockTranscription.start).not.toHaveBeenCalled();
    expect(useSalvageStore.getState().dropRequestedJobId).toBeNull();
  });

  it('slot-free timeout aborts the drop flow with an error toast', async () => {
    mockTranscription.busyInfo = { ...BUSY };
    mockWaitForJobSlotFree.mockResolvedValueOnce(false);
    renderSessionView();

    fireEvent.click(await screen.findByText('Stop and record'));

    await waitFor(() => expect(mockToast.error).toHaveBeenCalled());
    expect(mockTranscription.start).not.toHaveBeenCalled();
  });
});
