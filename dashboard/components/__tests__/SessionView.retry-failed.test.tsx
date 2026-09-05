/**
 * SessionView - Retry button on the transcription error banner.
 *
 * The durability layer preserves the source WAV for a FAILED job indefinitely
 * (the retention sweep only collects `status='completed' AND delivered=1`), so
 * a transcription that died on a CUDA OOM or a crashed backend is always
 * recoverable. Until now the only way to trigger that recovery was a raw
 * `POST /api/transcribe/retry/{job_id}`; the error banner offered no way out.
 *
 * The retry must also DELIVER the result: the WebSocket that carried the
 * original job is gone by the time the banner shows, so the component polls
 * the durability endpoint and hands the transcript to `loadResult`.
 */

import React from 'react';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
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
  mockSaveFile,
  mockDownloadToPath,
  mockToast,
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
    mockSaveFile: vi.fn(),
    mockDownloadToPath: vi.fn(),
    mockToast: { success: vi.fn(), error: vi.fn() },
  };
});

vi.mock('../../src/api/client', () => ({
  APIError: MockAPIError,
  apiClient: {
    checkConnection: vi.fn().mockResolvedValue({ reachable: true, ready: true }),
    getAdminStatus: vi.fn().mockResolvedValue({}),
    cancelTranscription: vi.fn(),
    getAuthToken: vi.fn().mockReturnValue(null),
    setAuthToken: vi.fn(),
    getBaseUrl: vi.fn().mockReturnValue('http://localhost:7239'),
    syncFromConfig: vi.fn().mockResolvedValue(undefined),
    unloadModels: vi.fn().mockResolvedValue(undefined),
    unloadLLMModel: vi.fn().mockResolvedValue(undefined),
    loadModelsStream: vi.fn().mockReturnValue(vi.fn()),
    fetchRecentUndelivered: (...a: unknown[]) => mockFetchRecentUndelivered(...a),
    getJobAudioUrl: (id: string) => `http://localhost:7239/api/transcribe/audio/${id}`,
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

const OOM_ERROR = 'Transcription failed: CUDA failed with error out of memory';
const JOB_ID = '48eae812-f5ff-400e-b2bc-4dede99c5a15';

/** The Retry control that belongs to the red error banner. */
function findErrorRetryButton(): HTMLElement | undefined {
  return screen
    .queryAllByRole('button', { name: /retry/i })
    .find((b) => b.closest('[data-testid="transcription-error"]') !== null);
}

describe('SessionView - retry a failed transcription', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTranscription.status = 'error';
    mockTranscription.result = null;
    mockTranscription.error = OOM_ERROR;
    mockTranscription.jobId = JOB_ID;
    mockTranscription.resultJobId = null;
    mockGetConfig.mockResolvedValue(undefined);
    mockRetryTranscription.mockResolvedValue({ job_id: JOB_ID, status: 'processing' });
    mockFetchTranscriptionResult.mockResolvedValue({ status: 202, json: async () => ({}) });
    mockFetchRecentUndelivered.mockResolvedValue({ json: async () => [] });
  });

  it('shows the error message with a Retry button when a job id is known', async () => {
    renderSessionView();

    expect(await screen.findByText(OOM_ERROR)).toBeInTheDocument();
    await waitFor(() => expect(findErrorRetryButton()).toBeDefined());
  });

  it('offers no Retry when the failure happened before a job existed', async () => {
    mockTranscription.jobId = null;
    mockTranscription.error = 'Connection to the server was lost.';
    renderSessionView();

    expect(await screen.findByText('Connection to the server was lost.')).toBeInTheDocument();
    expect(findErrorRetryButton()).toBeUndefined();
  });

  it('re-transcribes from the saved audio and delivers the recovered result', async () => {
    mockFetchTranscriptionResult.mockResolvedValue({
      status: 200,
      json: async () => ({
        result: {
          text: 'recovered transcript',
          words: [],
          language: 'el',
          duration: 329.6,
        },
      }),
    });
    renderSessionView();

    await waitFor(() => expect(findErrorRetryButton()).toBeDefined());
    fireEvent.click(findErrorRetryButton()!);

    await waitFor(() => expect(mockRetryTranscription).toHaveBeenCalledWith(JOB_ID));
    await waitFor(() =>
      expect(mockTranscription.loadResult).toHaveBeenCalledWith(
        expect.objectContaining({ text: 'recovered transcript', language: 'el', duration: 329.6 }),
        JOB_ID,
      ),
    );
  });

  it('explains the refusal when the model is busy with another job', async () => {
    mockRetryTranscription.mockRejectedValue(
      new MockAPIError(
        409,
        JSON.stringify({
          detail: 'Model is currently busy. Try again when the active session ends.',
        }),
        '/api/transcribe/retry/x',
      ),
    );
    renderSessionView();

    await waitFor(() => expect(findErrorRetryButton()).toBeDefined());
    fireEvent.click(findErrorRetryButton()!);

    await waitFor(() =>
      expect(mockToast.error).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ description: expect.stringContaining('busy') }),
      ),
    );
    expect(mockTranscription.loadResult).not.toHaveBeenCalled();
  });

  it('explains the refusal when the saved audio is gone', async () => {
    mockRetryTranscription.mockRejectedValue(
      new MockAPIError(
        410,
        JSON.stringify({ detail: 'Audio file has been deleted — cannot retry' }),
        '/api/transcribe/retry/x',
      ),
    );
    renderSessionView();

    await waitFor(() => expect(findErrorRetryButton()).toBeDefined());
    fireEvent.click(findErrorRetryButton()!);

    await waitFor(() =>
      expect(mockToast.error).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ description: expect.stringContaining('deleted') }),
      ),
    );
  });

  // The toast from the incident. The first retry had already succeeded and its
  // transcript was sitting in the database; every later press was refused with
  // "Only failed or partial jobs can be retried (current status: completed)"
  // and the user was shown that refusal instead of their transcript.
  it('turns a completed-job 409 into a delivery instead of a refusal', async () => {
    mockRetryTranscription.mockRejectedValue(
      new MockAPIError(
        409,
        JSON.stringify({
          detail: 'Only failed or partial jobs can be retried (current status: completed)',
        }),
        '/api/transcribe/retry/x',
      ),
    );
    mockFetchTranscriptionResult.mockResolvedValue({
      status: 200,
      json: async () => ({ result: { text: 'the transcript nobody saw', words: [] } }),
    });
    renderSessionView();

    await waitFor(() => expect(findErrorRetryButton()).toBeDefined());
    fireEvent.click(findErrorRetryButton()!);

    await waitFor(() =>
      expect(mockTranscription.loadResult).toHaveBeenCalledWith(
        expect.objectContaining({ text: 'the transcript nobody saw' }),
        JOB_ID,
      ),
    );
    expect(mockToast.error).not.toHaveBeenCalled();
    await waitFor(() => expect(findErrorRetryButton()).not.toBeDisabled());
  });

  // The same 409 status also means "model busy", which is a genuine refusal.
  // The probe answers 202 there, so it must fall through to the toast. This is
  // why the branch is chosen on the status code and never on the refusal text.
  it('still refuses when the 409 is a busy model rather than a finished job', async () => {
    mockRetryTranscription.mockRejectedValue(
      new MockAPIError(
        409,
        JSON.stringify({
          detail: 'Model is currently busy. Try again when the active session ends.',
        }),
        '/api/transcribe/retry/x',
      ),
    );
    mockFetchTranscriptionResult.mockResolvedValue({ status: 202, json: async () => ({}) });
    renderSessionView();

    await waitFor(() => expect(findErrorRetryButton()).toBeDefined());
    fireEvent.click(findErrorRetryButton()!);

    await waitFor(() => expect(mockToast.error).toHaveBeenCalled());
    expect(mockTranscription.loadResult).not.toHaveBeenCalled();
  });

  // A retried job that was diarized used to come back with its speaker labels
  // stripped, because this delivery site hand mapped fewer fields than the hook.
  it('delivers the speaker fields a diarized job carries', async () => {
    mockFetchTranscriptionResult.mockResolvedValue({
      status: 200,
      json: async () => ({
        result: {
          text: 'recovered transcript',
          words: [],
          num_speakers: 2,
          diarization: { requested: true, performed: true, reason: null, remedy: null },
          partial: true,
          partial_reason: 'sidecar died',
        },
      }),
    });
    renderSessionView();

    await waitFor(() => expect(findErrorRetryButton()).toBeDefined());
    fireEvent.click(findErrorRetryButton()!);

    await waitFor(() =>
      expect(mockTranscription.loadResult).toHaveBeenCalledWith(
        expect.objectContaining({
          numSpeakers: 2,
          diarization: expect.objectContaining({ performed: true }),
          partial: true,
          partialReason: 'sidecar died',
        }),
        JOB_ID,
      ),
    );
  });

  // A throw while DELIVERING used to sit inside the same try as the fetch, so
  // it read as "not ready yet": the poll span on forever and the button stayed
  // stuck on "Retrying...".
  it('recovers when delivering the transcript itself throws', async () => {
    mockFetchTranscriptionResult.mockResolvedValue({
      status: 200,
      json: async () => ({ result: { text: 'recovered transcript', words: [] } }),
    });
    mockTranscription.loadResult.mockImplementationOnce(() => {
      throw new Error('render blew up');
    });
    renderSessionView();
    await waitFor(() => expect(findErrorRetryButton()).toBeDefined());
    mockFetchRecentUndelivered.mockClear();

    fireEvent.click(findErrorRetryButton()!);

    await waitFor(() => expect(mockToast.error).toHaveBeenCalled());
    // The button is usable again and the banner has been re-checked, so the
    // transcript is still reachable from the recovery notice.
    await waitFor(() => expect(findErrorRetryButton()).not.toBeDisabled());
    expect(mockFetchRecentUndelivered).toHaveBeenCalled();
  });

  it('ignores a second press while a retry is already in flight', async () => {
    renderSessionView();
    await waitFor(() => expect(findErrorRetryButton()).toBeDefined());
    const button = findErrorRetryButton()!;
    fireEvent.click(button);
    await waitFor(() => expect(mockRetryTranscription).toHaveBeenCalledTimes(1));
    fireEvent.click(button);

    expect(mockRetryTranscription).toHaveBeenCalledTimes(1);
  });
});

describe('SessionView - retry poll lifetime', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTranscription.status = 'error';
    mockTranscription.result = null;
    mockTranscription.error = OOM_ERROR;
    mockTranscription.jobId = JOB_ID;
    mockTranscription.resultJobId = null;
    mockGetConfig.mockResolvedValue(undefined);
    mockRetryTranscription.mockResolvedValue({ job_id: JOB_ID, status: 'processing' });
    mockFetchRecentUndelivered.mockResolvedValue({ json: async () => [] });
  });

  // Every give-up now ends by refreshing the recovery banner and saying so.
  // Before, it ended in a toast that told the user to reopen the tab, which is
  // exactly the manoeuvre that had already failed them.
  it('refreshes the recovery banner and frees the button when the poll gives up', async () => {
    mockFetchTranscriptionResult.mockResolvedValue({ status: 404, json: async () => ({}) });
    renderSessionView();
    await waitFor(() => expect(findErrorRetryButton()).toBeDefined());
    mockFetchRecentUndelivered.mockClear();

    fireEvent.click(findErrorRetryButton()!);

    await waitFor(() => expect(mockToast.error).toHaveBeenCalled());
    expect(mockFetchRecentUndelivered).toHaveBeenCalled();
    expect(mockTranscription.loadResult).not.toHaveBeenCalled();
    await waitFor(() => expect(findErrorRetryButton()).not.toBeDisabled());
  });

  // The poll used to survive the component. An in-flight request that answers
  // after unmount must be dropped, not delivered into a dead tree.
  it('drops a response that lands after the view unmounts', async () => {
    let answer: (v: { status: number; json: () => Promise<unknown> }) => void = () => {};
    mockFetchTranscriptionResult.mockReturnValue(
      new Promise<{ status: number; json: () => Promise<unknown> }>((resolve) => {
        answer = resolve;
      }),
    );
    const { unmount } = renderSessionView();
    await waitFor(() => expect(findErrorRetryButton()).toBeDefined());
    fireEvent.click(findErrorRetryButton()!);
    await waitFor(() => expect(mockFetchTranscriptionResult).toHaveBeenCalledTimes(1));

    unmount();
    await act(async () => {
      answer({
        status: 200,
        json: async () => ({ result: { text: 'too late', words: [] } }),
      });
    });

    expect(mockTranscription.loadResult).not.toHaveBeenCalled();
  });
});

// Save Audio - the recording itself, kept before the transcript pipeline gets
// another chance to fail. It sits beside Retry in both banners.
describe('SessionView - Save Audio beside Retry', () => {
  let previousElectronAPI: typeof window.electronAPI;

  beforeEach(() => {
    vi.clearAllMocks();
    mockTranscription.status = 'error';
    mockTranscription.result = null;
    mockTranscription.error = OOM_ERROR;
    mockTranscription.jobId = JOB_ID;
    mockTranscription.resultJobId = null;
    mockGetConfig.mockResolvedValue(undefined);
    mockFetchRecentUndelivered.mockResolvedValue({ json: async () => [] });
    mockSaveFile.mockResolvedValue('/home/user/keep.wav');
    mockDownloadToPath.mockResolvedValue({ ok: true, bytes: 4096 });
    previousElectronAPI = window.electronAPI;
    window.electronAPI = {
      fileIO: { saveFile: mockSaveFile, downloadToPath: mockDownloadToPath },
    } as unknown as typeof window.electronAPI;
  });

  afterEach(() => {
    window.electronAPI = previousElectronAPI;
  });

  it('offers Save Audio on the error banner and downloads that job WAV', async () => {
    renderSessionView();
    fireEvent.click(await screen.findByTestId('save-audio-error'));

    await waitFor(() => expect(mockSaveFile).toHaveBeenCalledTimes(1));
    expect(mockSaveFile.mock.calls[0][0]).toMatchObject({
      filters: [{ name: 'WAV Audio', extensions: ['wav'] }],
    });
    await waitFor(() =>
      expect(mockDownloadToPath).toHaveBeenCalledWith(
        expect.objectContaining({
          url: `http://localhost:7239/api/transcribe/audio/${JOB_ID}`,
          filePath: '/home/user/keep.wav',
        }),
      ),
    );
    await waitFor(() => expect(mockToast.success).toHaveBeenCalled());
  });

  it('offers Save Audio on the partial-transcript banner too', async () => {
    mockTranscription.status = 'complete';
    mockTranscription.error = null;
    mockTranscription.result = {
      text: 'only the first half',
      words: [],
      partial: true,
      partialReason: 'sidecar died',
    };
    renderSessionView();

    expect(await screen.findByTestId('save-audio-partial')).toBeInTheDocument();
  });

  it('sends the auth token as a header, never in the URL', async () => {
    renderSessionView();
    fireEvent.click(await screen.findByTestId('save-audio-error'));

    await waitFor(() => expect(mockDownloadToPath).toHaveBeenCalledTimes(1));
    const sent = mockDownloadToPath.mock.calls[0][0] as { url: string; headers: unknown };
    expect(sent.url).not.toContain('token=');
    expect(sent.headers).toEqual({});
  });
});
