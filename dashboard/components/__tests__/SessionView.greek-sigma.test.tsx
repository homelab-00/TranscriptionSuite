/**
 * SessionView - Greek final-sigma warning for Parakeet-family models.
 *
 * NVIDIA's NeMo models were trained with SentencePiece vocabularies that lack
 * ς (U+03C2), so every NeMo model (Parakeet AND Canary, CUDA and MLX alike)
 * truncates Greek word endings ("σας" becomes "σα"). Unfixable at the app
 * level - the UI must warn whenever Greek is selected with a NeMo model and
 * steer users toward Whisper.
 *
 * Upstream defect: https://huggingface.co/nvidia/canary-1b-v2/discussions/26
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const PARAKEET_MODEL = 'nvidia/parakeet-tdt-0.6b-v3';
const CANARY_MODEL = 'nvidia/canary-1b-v2';

// ── Hoisted mock state ────────────────────────────────────────────────────

const mockModels = {
  main: PARAKEET_MODEL,
  live: PARAKEET_MODEL,
};

const mockTranscription = {
  status: 'idle' as string,
  result: null,
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
  jobId: null,
  loadResult: vi.fn(),
};

const mockGetConfig = vi.fn();

vi.mock('../../src/hooks/useTranscription', () => ({
  useTranscription: () => mockTranscription,
}));

vi.mock('../../src/hooks/useLanguages', () => ({
  useLanguages: () => ({
    languages: [
      { code: 'auto', name: 'Auto Detect' },
      { code: 'en', name: 'English' },
      { code: 'el', name: 'Greek' },
      { code: 'es', name: 'Spanish' },
    ],
    backendType: 'parakeet',
    loading: false,
    error: null,
  }),
}));

vi.mock('../../src/hooks/useAdminStatus', () => ({
  useAdminStatus: () => ({
    status: {
      models_loaded: true,
      config: {
        main_transcriber: { model: mockModels.main },
        live_transcriber: { model: mockModels.live },
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

vi.mock('../../src/api/client', () => ({
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
    fetchRecentUndelivered: vi.fn().mockResolvedValue({ json: async () => [] }),
    fetchTranscriptionResult: vi.fn().mockResolvedValue({ status: 404, json: async () => ({}) }),
    dismissTranscriptionResult: vi.fn().mockResolvedValue({ status: 200 }),
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

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

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
import { SessionTab } from '../../types';

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

const baseLiveState = {
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
};

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
  live: baseLiveState,
  sessionTab: SessionTab.MAIN,
  onChangeSessionTab: vi.fn(),
};

function setPersistedLanguages(main: string | undefined, live?: string | undefined) {
  mockGetConfig.mockImplementation((key: unknown) => {
    if (key === 'session.mainLanguage') return Promise.resolve(main);
    if (key === 'session.liveLanguage') return Promise.resolve(live);
    return Promise.resolve(undefined);
  });
}

function renderSessionView() {
  return render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });
}

describe('SessionView - Greek final-sigma warning', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockModels.main = PARAKEET_MODEL;
    mockModels.live = PARAKEET_MODEL;
    setPersistedLanguages(undefined, undefined);

    (window as any).electronAPI = {
      config: {
        get: vi.fn().mockResolvedValue(undefined),
        set: vi.fn().mockResolvedValue(undefined),
      },
      docker: { readComposeEnvValue: vi.fn().mockResolvedValue('false') },
      audio: {
        listSinks: vi.fn().mockResolvedValue([]),
        removeMonitorLoopback: vi.fn().mockResolvedValue(undefined),
        disableSystemAudioLoopback: vi.fn().mockResolvedValue(undefined),
      },
      tray: { onAction: vi.fn().mockReturnValue(vi.fn()) },
      notifications: { show: vi.fn() },
    };
  });

  it('shows the warning when Greek is selected with a Parakeet main model', async () => {
    setPersistedLanguages('Greek');

    renderSessionView();

    const warning = await screen.findByTestId('greek-sigma-warning-main');
    expect(warning.textContent).toMatch(/final sigma|ς/);
  });

  it('warns for a Canary main model too (real speech emits no repairable marker)', async () => {
    mockModels.main = CANARY_MODEL;
    mockModels.live = CANARY_MODEL;
    setPersistedLanguages('Greek');

    renderSessionView();

    const warning = await screen.findByTestId('greek-sigma-warning-main');
    expect(warning.textContent).toMatch(/final sigma|ς/);
  });

  it('does not warn when a non-Greek language is selected', async () => {
    setPersistedLanguages('English');

    renderSessionView();

    await waitFor(() => {
      expect(mockGetConfig).toHaveBeenCalledWith('session.mainLanguage');
    });
    expect(screen.queryByTestId('greek-sigma-warning-main')).toBeNull();
  });

  it('shows the live warning when the live language is Greek on a Parakeet live model', async () => {
    setPersistedLanguages('English', 'Greek');

    renderSessionView();

    const warning = await screen.findByTestId('greek-sigma-warning-live');
    expect(warning.textContent).toMatch(/final sigma|ς/);
  });
});
