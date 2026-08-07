/**
 * SessionView - speaker diarization for Session-tab recordings (GH-258).
 *
 * Diarization used to run only on the import routes, so a normal microphone
 * recording could never be speaker-labelled. These tests cover the Main
 * Transcription card control: that it renders, that it obeys the server's
 * feature flag, that the chosen values reach start(), and that a requested
 * diarization which did not happen is reported rather than silently dropped.
 */

import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const PARAKEET_MODEL = 'nvidia/parakeet-tdt-0.6b-v3';

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

// The server-reported diarization feature flag the toggle is gated on. Hoisted
// so a test can flip it before render without rebuilding the whole mock.
const mockDiarizationFeature = {
  value: { available: true, reason: 'ready' } as { available: boolean; reason: string },
};

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
      // GH-209 contract: the server computes the diarization feature status
      // once at container startup and reports it here.
      models: { features: { diarization: mockDiarizationFeature.value } },
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

describe('SessionView - speaker diarization for recordings (GH-258)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDiarizationFeature.value = { available: true, reason: 'ready' };
    mockTranscription.status = 'idle';
    // Reset between tests: the result-pane tests below mutate this, and a leak
    // would render the result block during the toggle tests.
    mockTranscription.result = null;
    mockGetConfig.mockImplementation((key: unknown) => {
      if (key === 'diarization.enabledForRecordings') return Promise.resolve(true);
      if (key === 'diarization.constrainSpeakers') return Promise.resolve(false);
      if (key === 'diarization.numSpeakers') return Promise.resolve(2);
      return Promise.resolve(undefined);
    });
    (window as any).electronAPI = {
      config: {
        get: vi.fn().mockResolvedValue(undefined),
        set: vi.fn().mockResolvedValue(undefined),
      },
      docker: { readComposeEnvValue: vi.fn().mockResolvedValue('false') },
    };
  });

  it('renders the diarization switch on the Main Transcription card', async () => {
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    const toggle = await screen.findByRole('switch', { name: 'Speaker Diarization' });
    expect(toggle).toBeTruthy();
  });

  it('renders Translate and Speaker Diarization as named toggle buttons on one row', async () => {
    // The two controls are pill buttons sharing one centered row. Both keep
    // role switch plus an accessible name, so screen readers announce two
    // named on/off controls instead of two anonymous buttons on the card.
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    const diarization = await screen.findByRole('switch', { name: 'Speaker Diarization' });
    const translate = await screen.findByRole('switch', { name: 'Translate to English' });

    expect(translate).toBeTruthy();
    // Translate is rendered above Speaker Diarization in document order.
    expect(
      translate.compareDocumentPosition(diarization) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('disables the switch when the server reports diarization unavailable', async () => {
    mockDiarizationFeature.value = { available: false, reason: 'token_missing' };
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    const toggle = await screen.findByRole('switch', { name: 'Speaker Diarization' });
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('false'));
    expect((toggle as HTMLButtonElement).disabled).toBe(true);
  });

  it('passes diarization through to start() when the switch is on', async () => {
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    const toggle = await screen.findByRole('switch', { name: 'Speaker Diarization' });
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('true'));

    fireEvent.click(await screen.findByRole('button', { name: /Start Recording/i }));

    await waitFor(() => expect(mockTranscription.start).toHaveBeenCalled());
    expect(mockTranscription.start.mock.calls[0][0]).toMatchObject({
      diarization: true,
      expectedSpeakers: undefined,
    });
  });

  it('sends the pinned speaker count when constrainSpeakers is on', async () => {
    mockGetConfig.mockImplementation((key: unknown) => {
      if (key === 'diarization.enabledForRecordings') return Promise.resolve(true);
      if (key === 'diarization.constrainSpeakers') return Promise.resolve(true);
      if (key === 'diarization.numSpeakers') return Promise.resolve(4);
      return Promise.resolve(undefined);
    });
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    const toggle = await screen.findByRole('switch', { name: 'Speaker Diarization' });
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('true'));

    fireEvent.click(await screen.findByRole('button', { name: /Start Recording/i }));

    await waitFor(() => expect(mockTranscription.start).toHaveBeenCalled());
    expect(mockTranscription.start.mock.calls[0][0]).toMatchObject({
      diarization: true,
      expectedSpeakers: 4,
    });
  });

  it('never sends diarization when the server says the feature is unavailable', async () => {
    mockDiarizationFeature.value = { available: false, reason: 'token_missing' };
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    fireEvent.click(await screen.findByRole('button', { name: /Start Recording/i }));

    await waitFor(() => expect(mockTranscription.start).toHaveBeenCalled());
    expect(mockTranscription.start.mock.calls[0][0]).toMatchObject({ diarization: false });
  });
});

describe('SessionView - skipped diarization notice (GH-258)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDiarizationFeature.value = { available: true, reason: 'ready' };
    mockTranscription.status = 'idle';
    mockTranscription.result = null;
    mockGetConfig.mockImplementation(() => Promise.resolve(undefined));
    (window as any).electronAPI = {
      config: {
        get: vi.fn().mockResolvedValue(undefined),
        set: vi.fn().mockResolvedValue(undefined),
      },
      docker: { readComposeEnvValue: vi.fn().mockResolvedValue('false') },
    };
  });

  it('warns when diarization was requested but did not happen', async () => {
    mockTranscription.status = 'complete';
    mockTranscription.result = {
      text: 'plain transcript',
      words: [],
      language: 'en',
      duration: 12,
      partial: false,
      partialReason: null,
      numSpeakers: 0,
      diarization: {
        requested: true,
        performed: false,
        reason: 'out_of_memory',
        remedy: 'Free VRAM and try again.',
      },
    } as any;

    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    expect(await screen.findByText(/Speaker labels are missing/i)).toBeTruthy();
    expect(await screen.findByText(/Free VRAM and try again/i)).toBeTruthy();
  });

  it('shows no diarization warning when it succeeded', async () => {
    mockTranscription.status = 'complete';
    mockTranscription.result = {
      text: 'SPEAKER_00: hello',
      words: [],
      language: 'en',
      duration: 12,
      partial: false,
      partialReason: null,
      numSpeakers: 2,
      diarization: { requested: true, performed: true, reason: 'ready', remedy: null },
    } as any;

    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    await screen.findByRole('switch', { name: 'Speaker Diarization' });
    expect(screen.queryByText(/Speaker labels are missing/i)).toBeNull();
  });
});
