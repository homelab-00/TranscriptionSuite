/**
 * P2-VIEW-001 — SessionView renders with mock hooks
 *
 * Tests that SessionView correctly renders different UI states based on
 * the transcription status: idle, recording, processing, and complete.
 *
 * All hooks are mocked to isolate the component's rendering logic.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockTranscription = {
  status: 'idle' as string,
  result: null as { text: string; words: never[]; language?: string; duration?: number } | null,
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

vi.mock('../../src/hooks/useTraySync', () => ({
  useTraySync: vi.fn(),
}));

vi.mock('../../src/hooks/useAdminStatus', () => ({
  useAdminStatus: () => ({
    status: {
      models_loaded: true,
      config: {
        main_transcriber: { model: 'openai/whisper-large-v3-turbo' },
        live_transcriber: { model: 'openai/whisper-medium' },
      },
    },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

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
  },
}));

vi.mock('../../src/config/store', () => ({
  getConfig: vi.fn().mockResolvedValue(undefined),
  setConfig: vi.fn().mockResolvedValue(undefined),
  getAuthToken: vi.fn().mockResolvedValue(null),
  DEFAULT_SERVER_PORT: 7239,
}));

vi.mock('../../src/services/modelCapabilities', () => ({
  supportsTranslation: () => false,
  filterLanguagesForModel: (langs: unknown[]) => langs,
  isCanaryModel: () => false,
  isWhisperModel: () => true,
  // gh-102: SessionView now consults supportsAutoDetect when guarding the
  // start-recording / live-toggle entry points. Default mock matches Whisper
  // (auto-detect supported).
  supportsAutoDetect: () => true,
  pickDefaultLanguage: (options: string[]) =>
    options.includes('English') ? 'English' : (options[0] ?? 'Auto Detect'),
  CANARY_TRANSLATION_TARGETS: [],
}));

vi.mock('../../src/services/modelSelection', () => ({
  isModelDisabled: () => false,
}));

vi.mock('../../src/hooks/useClipboard', () => ({
  writeToClipboard: vi.fn(),
}));

vi.mock('../../src/services/clientDebugLog', () => ({
  logClientEvent: vi.fn(),
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('../views/SessionImportTab', () => ({
  SessionImportTab: () => React.createElement('div', { 'data-testid': 'session-import-tab' }),
}));

vi.mock('../PopOutWindow', () => ({
  PopOutWindow: () => null,
}));

vi.mock('../views/FullscreenVisualizer', () => ({
  FullscreenVisualizer: () => null,
}));

vi.mock('../AudioVisualizer', () => ({
  AudioVisualizer: () => React.createElement('div', { 'data-testid': 'audio-visualizer' }),
}));

vi.mock('../../src/types/runtime', () => ({
  isRuntimeProfile: (v: unknown) => ['gpu', 'cpu', 'vulkan', 'metal'].includes(v as string),
}));

import { SessionView } from '../views/SessionView';
import { SessionTab } from '../../types';

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
  return wrapper;
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

// ── Tests ───────────────────────────────────────────────────────────────���──

describe('[P2] SessionView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset transcription state for each test
    mockTranscription.status = 'idle';
    mockTranscription.result = null;
    mockTranscription.error = null;
    mockTranscription.vadActive = false;
    mockTranscription.processingProgress = null;

    // Mock electronAPI for config reads
    (window as any).electronAPI = {
      config: {
        get: vi.fn().mockResolvedValue(undefined),
        set: vi.fn().mockResolvedValue(undefined),
      },
      docker: {
        readComposeEnvValue: vi.fn().mockResolvedValue('false'),
      },
      audio: { listSinks: vi.fn().mockResolvedValue([]) },
      tray: { onAction: vi.fn().mockReturnValue(vi.fn()) },
      notifications: { show: vi.fn() },
    };
  });

  it('renders "Start Recording" button in idle state', () => {
    mockTranscription.status = 'idle';
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    expect(screen.getByText('Start Recording')).toBeDefined();
  });

  it('renders "Stop Recording" button when recording', () => {
    mockTranscription.status = 'recording';
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    expect(screen.getByText('Stop Recording')).toBeDefined();
  });

  it('renders processing indicator when processing', () => {
    mockTranscription.status = 'processing';
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    expect(screen.getByText('Processing...')).toBeDefined();
  });

  it('renders transcription result when complete', () => {
    mockTranscription.status = 'complete';
    mockTranscription.result = {
      text: 'Hello world, this is a test transcription.',
      words: [],
      language: 'en',
      duration: 5.2,
    };
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    expect(screen.getByText('Hello world, this is a test transcription.')).toBeDefined();
    // Copy and Download buttons may appear more than once in the DOM
    expect(screen.getAllByText('Copy').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Download').length).toBeGreaterThanOrEqual(1);
  });
});
