/**
 * SessionView — Canary language guards (gh-102)
 *
 * Verifies the two safeguards added to fix issue 102:
 *
 * 1. Start Recording is refused when the active model lacks auto-detect
 *    support and `resolveLanguage(mainLanguage)` returns undefined (e.g.
 *    languages query still loading, or stale "Auto Detect" left over from
 *    a pre-gh-81 install). The user sees a sonner toast and no websocket
 *    start frame is emitted.
 *
 * 2. When languages are loaded and the user picks a valid Canary language
 *    (Spanish), Start Recording calls transcription.start with the resolved
 *    code (`language: 'es'`).
 */

import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const CANARY_MODEL = 'nvidia/canary-1b-v2';

// ── Hoisted mock state ────────────────────────────────────────────────────
//
// We need to flip the language list and the active model per-test, so the
// mocks read from module-level mutable state and tests reset it in beforeEach.

interface MockLanguageSet {
  languages: Array<{ code: string; name: string }>;
  loading: boolean;
}

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

let mockLanguageSet: MockLanguageSet = {
  languages: [{ code: 'auto', name: 'Auto Detect' }],
  loading: true,
};

const mockToastError = vi.fn();
const mockGetConfig = vi.fn();

vi.mock('../../src/hooks/useTranscription', () => ({
  useTranscription: () => mockTranscription,
}));

vi.mock('../../src/hooks/useLanguages', () => ({
  useLanguages: () => ({
    languages: mockLanguageSet.languages,
    backendType: 'canary',
    loading: mockLanguageSet.loading,
    error: null,
  }),
}));

vi.mock('../../src/hooks/useAdminStatus', () => ({
  useAdminStatus: () => ({
    status: {
      models_loaded: true,
      config: {
        main_transcriber: { model: CANARY_MODEL },
        live_transcriber: { model: CANARY_MODEL },
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
  },
}));

vi.mock('../../src/config/store', () => ({
  getConfig: (...args: unknown[]) => mockGetConfig(...args),
  setConfig: vi.fn().mockResolvedValue(undefined),
  getAuthToken: vi.fn().mockResolvedValue(null),
  DEFAULT_SERVER_PORT: 7239,
}));

// Real modelCapabilities for the Canary path — we want the actual filter,
// supportsAutoDetect, and pickDefaultLanguage logic from the source module.
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
  toast: { success: vi.fn(), error: (...args: unknown[]) => mockToastError(...args) },
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
  isRuntimeProfile: (v: unknown) => ['gpu', 'cpu', 'vulkan', 'metal'].includes(v as string),
}));

import { SessionView } from '../views/SessionView';
import { SessionTab } from '../../types';
import { useTraySync } from '../../src/hooks/useTraySync';
import { apiClient } from '../../src/api/client';

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

const NEMO_LANGUAGES_FOR_TEST: Array<{ code: string; name: string }> = [
  { code: 'auto', name: 'Auto Detect' }, // included as the synthetic prepend; filter will drop it for canary
  { code: 'en', name: 'English' },
  { code: 'es', name: 'Spanish' },
  { code: 'de', name: 'German' },
];

// Captured at module load so we can restore navigator.platform between tests
// that stub it via Object.defineProperty (the gh-102 followup #2 tray
// Stop/Cancel cases). Without this restore, the last per-test stub would
// poison subsequent tests if vitest's pool config ever shares jsdom across
// files (`pool: 'threads'` / `singleThread: true`), or if `--shuffle` is used
// to reorder tests within this file.
const ORIGINAL_NAVIGATOR_PLATFORM = navigator.platform;

describe('SessionView — Canary language guards (gh-102)', () => {
  afterEach(() => {
    Object.defineProperty(navigator, 'platform', {
      value: ORIGINAL_NAVIGATOR_PLATFORM,
      configurable: true,
    });
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mockTranscription.status = 'idle';
    mockTranscription.result = null;
    mockTranscription.error = null;
    mockTranscription.start.mockReset();
    mockTranscription.reset.mockReset();
    mockToastError.mockReset();

    // Default: no persisted language (mainLanguage starts at "Auto Detect").
    mockGetConfig.mockResolvedValue(undefined);

    (window as any).electronAPI = {
      config: {
        get: vi.fn().mockResolvedValue(undefined),
        set: vi.fn().mockResolvedValue(undefined),
      },
      docker: { readComposeEnvValue: vi.fn().mockResolvedValue('false') },
      audio: {
        listSinks: vi.fn().mockResolvedValue([]),
        // mockResolvedValue(undefined) matches the surrounding async-IPC convention
        // — production currently doesn't await these but the IPC bridge returns Promises,
        // so any future `await` site won't trip on `.then()` of undefined.
        removeMonitorLoopback: vi.fn().mockResolvedValue(undefined),
        disableSystemAudioLoopback: vi.fn().mockResolvedValue(undefined),
      },
      tray: { onAction: vi.fn().mockReturnValue(vi.fn()) },
      notifications: { show: vi.fn() },
    };

    // Languages query in-flight (placeholder Auto Detect only) to start.
    mockLanguageSet = {
      languages: [{ code: 'auto', name: 'Auto Detect' }],
      loading: true,
    };
  });

  it('refuses Start Recording when Canary is active and resolveLanguage returns undefined (languages still loading)', async () => {
    // Persisted "Auto Detect" — invalid for Canary, but matches what a user
    // upgrading from a pre-gh-81 install would have.
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'Auto Detect';
      return undefined;
    });

    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    // Wait a tick so the async persistence load has a chance to settle.
    await act(async () => {
      await Promise.resolve();
    });

    const startButton = await screen.findByText('Start Recording');
    fireEvent.click(startButton);

    expect(mockTranscription.start).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledTimes(1);
    const [title, opts] = mockToastError.mock.calls[0] as [string, { description?: string }];
    expect(title).toMatch(/source language required/i);
    expect(String(opts?.description ?? '')).toMatch(/loading languages/i);
  });

  it('starts recording with language="es" when Canary is active and Spanish is selected after languages have loaded', async () => {
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'Spanish';
      return undefined;
    });

    // Languages have already loaded with the NEMO list.
    mockLanguageSet = {
      languages: NEMO_LANGUAGES_FOR_TEST,
      loading: false,
    };

    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    await act(async () => {
      await Promise.resolve();
    });

    const startButton = await screen.findByText('Start Recording');
    fireEvent.click(startButton);

    expect(mockToastError).not.toHaveBeenCalled();
    expect(mockTranscription.start).toHaveBeenCalledTimes(1);
    const startArgs = mockTranscription.start.mock.calls[0][0] as { language?: string };
    expect(startArgs.language).toBe('es');
  });

  it('SessionView snap effect respects the loading flag (consumer-side contract)', async () => {
    // This test pins SessionView's *consumer-side* contract: when
    // `useLanguages` reports `loading=true`, the snap effect that picks a
    // valid language for the active model must skip — no
    // `setConfig('session.mainLanguage', ...)` writes. The actual gh-102
    // fix lives one layer down (useLanguages returning an honest `loading`
    // flag); see useLanguages.test.tsx for the hook-side regression. This
    // test is the matching belt: if a future refactor removes the snap
    // effect's `if (languagesLoading) return;` guard, this catches it.
    const setConfigCalls: Array<{ key: string; value: unknown }> = [];
    const { setConfig: realSetConfig } = await import('../../src/config/store');
    (realSetConfig as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      async (key: string, value: unknown) => {
        setConfigCalls.push({ key, value });
      },
    );

    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'Spanish';
      return undefined;
    });
    // languages still loading; loading=true means snap effect should skip.
    mockLanguageSet = {
      languages: [{ code: 'auto', name: 'Auto Detect' }],
      loading: true,
    };

    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // The snap effect must NOT have written "Auto Detect" or "English" to
    // session.mainLanguage while loading=true. (Pre-fix: this assertion
    // would fail because setConfig('session.mainLanguage', 'Auto Detect')
    // was called from the snap effect on placeholder data.)
    const mainLanguageWrites = setConfigCalls.filter((c) => c.key === 'session.mainLanguage');
    expect(mainLanguageWrites).toEqual([]);
  });

  // Tray-menu Start Recording must run the same gh-102 guard the on-screen
  // button has. Pre-fix the tray callback was `() => transcription.start()`,
  // bypassing the guard and producing the cryptic backend "received None"
  // toast on Canary. The fix routes the tray through handleStartRecording.
  it('refuses Start Recording from tray menu when Canary is active and resolveLanguage returns undefined', async () => {
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'Auto Detect';
      return undefined;
    });

    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    await act(async () => {
      await Promise.resolve();
    });

    // Wait for the render with resolved persisted config / loaded languages
    // to settle before we snapshot the tray callback — otherwise
    // mock.calls.at(-1) can grab a stale-closure render where state hadn't
    // yet propagated. Mirrors the on-screen tests' findByText pattern.
    await screen.findByText('Start Recording');

    const trayDeps = vi.mocked(useTraySync).mock.calls.at(-1)?.[0];
    expect(trayDeps).toBeDefined();

    await act(async () => {
      trayDeps!.onStartRecording?.();
    });

    expect(mockTranscription.start).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledTimes(1);
    const [title, opts] = mockToastError.mock.calls[0] as [string, { description?: string }];
    expect(title).toMatch(/source language required/i);
    expect(String(opts?.description ?? '')).toMatch(/loading languages/i);
  });

  it('starts recording from tray menu with language="es" when Canary is active and Spanish is selected', async () => {
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'Spanish';
      return undefined;
    });

    mockLanguageSet = {
      languages: NEMO_LANGUAGES_FOR_TEST,
      loading: false,
    };

    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    await act(async () => {
      await Promise.resolve();
    });

    // Wait for the render with resolved persisted config / loaded languages
    // to settle before we snapshot the tray callback — otherwise
    // mock.calls.at(-1) can grab a stale-closure render where state hadn't
    // yet propagated. Mirrors the on-screen tests' findByText pattern.
    await screen.findByText('Start Recording');

    const trayDeps = vi.mocked(useTraySync).mock.calls.at(-1)?.[0];
    expect(trayDeps).toBeDefined();

    await act(async () => {
      trayDeps!.onStartRecording?.();
    });

    expect(mockToastError).not.toHaveBeenCalled();
    expect(mockTranscription.start).toHaveBeenCalledTimes(1);
    const startArgs = mockTranscription.start.mock.calls[0][0] as { language?: string };
    expect(startArgs.language).toBe('es');
  });

  // ── Tray Stop / Cancel routed through their handlers (gh-102 followup #2) ──
  //
  // Pre-fix the tray callbacks bypassed handleStopRecording (skipping Linux
  // loopback / Win+Mac system-audio cleanup) and handleCancelProcessing
  // (leaving orphan transcription jobs running on the server during
  // `processing` — a CLAUDE.md data-loss-class regression). The fix routes
  // them through the existing handlers via wrapped arrows (TDZ — same
  // pattern as the gh-102 Start Recording fix at SessionView.tsx:633).

  it('tray Stop on Linux while recording calls handleStopRecording (transcription.stop + removeMonitorLoopback)', async () => {
    Object.defineProperty(navigator, 'platform', { value: 'Linux x86_64', configurable: true });
    mockTranscription.status = 'recording';

    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const trayDeps = vi.mocked(useTraySync).mock.calls.at(-1)?.[0];
    expect(trayDeps).toBeDefined();

    await act(async () => {
      trayDeps!.onStopRecording?.();
    });

    expect(mockTranscription.stop).toHaveBeenCalledTimes(1);
    const audio = (
      window as unknown as { electronAPI: { audio: Record<string, ReturnType<typeof vi.fn>> } }
    ).electronAPI.audio;
    expect(audio.removeMonitorLoopback).toHaveBeenCalledTimes(1);
    expect(audio.disableSystemAudioLoopback).not.toHaveBeenCalled();
  });

  it('tray Stop on non-Linux while recording calls handleStopRecording (transcription.stop + disableSystemAudioLoopback)', async () => {
    Object.defineProperty(navigator, 'platform', { value: 'Win32', configurable: true });
    mockTranscription.status = 'recording';

    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const trayDeps = vi.mocked(useTraySync).mock.calls.at(-1)?.[0];
    expect(trayDeps).toBeDefined();

    await act(async () => {
      trayDeps!.onStopRecording?.();
    });

    expect(mockTranscription.stop).toHaveBeenCalledTimes(1);
    const audio = (
      window as unknown as { electronAPI: { audio: Record<string, ReturnType<typeof vi.fn>> } }
    ).electronAPI.audio;
    expect(audio.disableSystemAudioLoopback).toHaveBeenCalledTimes(1);
    expect(audio.removeMonitorLoopback).not.toHaveBeenCalled();
  });

  it('tray Cancel during processing calls apiClient.cancelTranscription then transcription.reset and loopback cleanup', async () => {
    Object.defineProperty(navigator, 'platform', { value: 'Linux x86_64', configurable: true });
    mockTranscription.status = 'processing';

    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const trayDeps = vi.mocked(useTraySync).mock.calls.at(-1)?.[0];
    expect(trayDeps).toBeDefined();

    // onCancelRecording is typed `() => void` but at runtime returns the
    // Promise from handleCancelProcessing. Cast and await so the handler's
    // try/finally completes before assertions.
    await act(async () => {
      await (trayDeps!.onCancelRecording?.() as unknown as Promise<void> | undefined);
    });

    expect(vi.mocked(apiClient.cancelTranscription)).toHaveBeenCalledTimes(1);
    expect(mockTranscription.reset).toHaveBeenCalledTimes(1);
    const audio = (
      window as unknown as { electronAPI: { audio: Record<string, ReturnType<typeof vi.fn>> } }
    ).electronAPI.audio;
    expect(audio.removeMonitorLoopback).toHaveBeenCalledTimes(1);
  });

  it('tray Cancel during recording skips apiClient.cancelTranscription but still runs reset and loopback cleanup', async () => {
    Object.defineProperty(navigator, 'platform', { value: 'Linux x86_64', configurable: true });
    mockTranscription.status = 'recording';

    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const trayDeps = vi.mocked(useTraySync).mock.calls.at(-1)?.[0];
    expect(trayDeps).toBeDefined();

    await act(async () => {
      await (trayDeps!.onCancelRecording?.() as unknown as Promise<void> | undefined);
    });

    expect(vi.mocked(apiClient.cancelTranscription)).not.toHaveBeenCalled();
    expect(mockTranscription.reset).toHaveBeenCalledTimes(1);
    const audio = (
      window as unknown as { electronAPI: { audio: Record<string, ReturnType<typeof vi.fn>> } }
    ).electronAPI.audio;
    expect(audio.removeMonitorLoopback).toHaveBeenCalledTimes(1);
  });
});
