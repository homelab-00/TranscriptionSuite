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
import { describe, it, expect, vi, beforeEach } from 'vitest';
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
    getBaseUrl: vi.fn().mockReturnValue('http://localhost:7239'),
    syncFromConfig: vi.fn().mockResolvedValue(undefined),
    unloadModels: vi.fn().mockResolvedValue(undefined),
    unloadLLMModel: vi.fn().mockResolvedValue(undefined),
    loadModelsStream: vi.fn().mockReturnValue(vi.fn()),
    fetchRecentUndelivered: (...a: unknown[]) => mockFetchRecentUndelivered(...a),
    fetchTranscriptionResult: (...a: unknown[]) => mockFetchTranscriptionResult(...a),
    dismissTranscriptionResult: vi.fn().mockResolvedValue({ status: 200 }),
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
import { SessionTab } from '../../types';

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
  sessionTab: SessionTab.MAIN,
  onChangeSessionTab: vi.fn(),
};

function renderSessionView() {
  return render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });
}

const JOB_ID = '48eae812-f5ff-400e-b2bc-4dede99c5a15';

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
    mockTranscription.busyInfo = null;
    mockGetConfig.mockResolvedValue(undefined);
    mockFetchRecentUndelivered.mockResolvedValue({ json: async () => [] });
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
    // second, missing result.
    mockFetchRecentUndelivered.mockResolvedValue({
      json: async () => [
        { job_id: JOB_ID, completed_at: COMPLETED_AT, text_preview: 'on screen now' },
        ...SALVAGED,
      ],
    });
    mockTranscription.status = 'complete';
    mockTranscription.jobId = JOB_ID;
    mockTranscription.result = { text: 'on screen now', words: [] };
    renderSessionView();

    expect(await screen.findByText(/the half that made it/)).toBeInTheDocument();
    // Exactly one banner: the salvaged job. Scoped to the banner wording,
    // because the on-screen job's text also appears in the transcript box.
    const banners = screen.getAllByText(/is available\./);
    expect(banners).toHaveLength(1);
    expect(banners[0].closest('div')?.textContent).toContain('the half that made it');
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
    useSalvageStore.setState({ checkNonce: 0, dropRequestedJobId: null, lastCompletedAt: null });
  });

  it('opens the confirm dialog when start bounced off an active salvage', async () => {
    mockTranscription.busyInfo = { ...BUSY };
    renderSessionView();

    expect(await screen.findByText(/interrupted recording/)).toBeInTheDocument();
    expect(mockTranscription.clearBusyInfo).toHaveBeenCalled();
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
