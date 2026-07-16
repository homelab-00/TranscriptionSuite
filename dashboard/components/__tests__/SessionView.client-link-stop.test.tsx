/**
 * GH-230: stopping the Client Link must terminate active sessions.
 *
 * Pre-fix, handleStopClient only flipped clientRunning=false — an active
 * recording kept streaming invisibly (status read "Disconnected" while the
 * OS microphone indicator stayed lit). These tests pin the new contract:
 *  - recording   → handleStopRecording() (stop-and-transcribe)
 *  - connecting  → transcription.reset()
 *  - processing  → untouched (server holds the audio; poll fallback recovers)
 *  - live active → handleLiveToggle(false)
 * and in every case the clientRunning flag still flips.
 */

import React from 'react';
import { render, screen, within, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

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

vi.mock('../../src/hooks/useTranscription', () => ({
  useTranscription: () => mockTranscription,
}));

vi.mock('../../src/hooks/useLanguages', () => ({
  useLanguages: () => ({
    languages: [{ code: 'auto', name: 'Auto Detect' }],
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
        main_transcriber: { model: 'large-v3' },
        live_transcriber: { model: 'large-v3' },
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
  getConfig: vi.fn().mockResolvedValue(undefined),
  setConfig: vi.fn().mockResolvedValue(undefined),
  getAuthToken: vi.fn().mockResolvedValue(null),
  DEFAULT_SERVER_PORT: 7239,
}));

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
import type { LiveModeState } from '../../src/hooks/useLiveMode';

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

const baseLiveState = {
  status: 'idle' as LiveModeState['status'],
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

const ORIGINAL_NAVIGATOR_PLATFORM = navigator.platform;

/** Render SessionView and click the Client Link card's Stop button. */
async function clickClientLinkStop(
  props: typeof baseProps & { live?: typeof baseLiveState },
): Promise<void> {
  render(React.createElement(SessionView, props), { wrapper: createWrapper() });
  await act(async () => {
    await Promise.resolve();
  });
  const clientCard = screen
    .getByText('Client Link')
    .closest('div[class*="rounded-xl"]') as HTMLElement;
  expect(clientCard).not.toBeNull();
  const stopButton = within(clientCard).getByRole('button', { name: 'Stop' });
  await act(async () => {
    fireEvent.click(stopButton);
  });
}

describe('SessionView — Client Link Stop terminates active sessions (GH-230)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTranscription.status = 'idle';
    // Linux platform: pins that the Linux loopback module is NOT touched by
    // SessionView (loopbackOwner owns it via capture teardown).
    Object.defineProperty(navigator, 'platform', { value: 'Linux x86_64', configurable: true });
    (window as unknown as { electronAPI: unknown }).electronAPI = {
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

  afterEach(() => {
    Object.defineProperty(navigator, 'platform', {
      value: ORIGINAL_NAVIGATOR_PLATFORM,
      configurable: true,
    });
  });

  it('while recording: stops the recording (stop-and-transcribe) and drops the link', async () => {
    mockTranscription.status = 'recording';
    const setClientRunning = vi.fn();
    await clickClientLinkStop({ ...baseProps, setClientRunning });

    expect(mockTranscription.stop).toHaveBeenCalledTimes(1);
    expect(mockTranscription.reset).not.toHaveBeenCalled();
    expect(setClientRunning).toHaveBeenCalledWith(false);
    // GH-230: no manual loopback IPC from the view — loopbackOwner owns it.
    const audio = (
      window as unknown as { electronAPI: { audio: Record<string, ReturnType<typeof vi.fn>> } }
    ).electronAPI.audio;
    expect(audio.removeMonitorLoopback).not.toHaveBeenCalled();
  });

  it('while connecting: resets the session and drops the link', async () => {
    mockTranscription.status = 'connecting';
    const setClientRunning = vi.fn();
    await clickClientLinkStop({ ...baseProps, setClientRunning });

    expect(mockTranscription.reset).toHaveBeenCalledTimes(1);
    expect(mockTranscription.stop).not.toHaveBeenCalled();
    expect(setClientRunning).toHaveBeenCalledWith(false);
  });

  it('while processing: leaves the job alone (durability) and drops the link', async () => {
    mockTranscription.status = 'processing';
    const setClientRunning = vi.fn();
    await clickClientLinkStop({ ...baseProps, setClientRunning });

    expect(mockTranscription.stop).not.toHaveBeenCalled();
    expect(mockTranscription.reset).not.toHaveBeenCalled();
    expect(setClientRunning).toHaveBeenCalledWith(false);
  });

  it('while live mode is active: stops live mode and drops the link', async () => {
    const liveStop = vi.fn();
    const setClientRunning = vi.fn();
    await clickClientLinkStop({
      ...baseProps,
      setClientRunning,
      live: { ...baseLiveState, status: 'listening', stop: liveStop },
    });

    expect(liveStop).toHaveBeenCalledTimes(1);
    expect(setClientRunning).toHaveBeenCalledWith(false);
  });

  it('while idle: just drops the link', async () => {
    const setClientRunning = vi.fn();
    await clickClientLinkStop({ ...baseProps, setClientRunning });

    expect(mockTranscription.stop).not.toHaveBeenCalled();
    expect(mockTranscription.reset).not.toHaveBeenCalled();
    expect(baseProps.live.stop).not.toHaveBeenCalled();
    expect(setClientRunning).toHaveBeenCalledWith(false);
  });
});
