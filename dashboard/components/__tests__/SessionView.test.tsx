/**
 * P2-VIEW-001 — SessionView renders with mock hooks
 *
 * Tests that SessionView correctly renders different UI states based on
 * the transcription status: idle, recording, processing, and complete.
 *
 * All hooks are mocked to isolate the component's rendering logic.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
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
    // GH-202 recovery notification (mounted via useEffect): return a Response
    // whose json() yields an empty list so the recovery useEffect resolves.
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
  // Whisper models have full Greek support - no final-sigma warning surface.
  truncatesGreekFinalSigma: () => false,
  CANARY_TRANSLATION_TARGETS: [],
}));

vi.mock('../../src/services/modelSelection', () => ({
  // gh-86 #1: tests for the recording-disabled-reason surface need to flip
  // `mainModelDisabled` per-test, so the mock is a `vi.fn()` (not a plain
  // arrow) — existing tests still get `false` by default.
  isModelDisabled: vi.fn(() => false),
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

// The embedded import surface has its own test suite; stub it so this file
// only exercises the Transcribe File disclosure wiring in SessionView.
vi.mock('../views/SessionImportTab', () => ({
  SessionImportTab: () => React.createElement('div', { 'data-testid': 'session-import-surface' }),
}));

vi.mock('../AudioVisualizer', () => ({
  AudioVisualizer: () => React.createElement('div', { 'data-testid': 'audio-visualizer' }),
}));

vi.mock('../../src/types/runtime', () => ({
  isRuntimeProfile: (v: unknown) =>
    ['gpu', 'cpu', 'vulkan', 'vulkan-wsl2', 'metal'].includes(v as string),
}));

import { SessionView } from '../views/SessionView';
import { isModelDisabled } from '../../src/services/modelSelection';
import { useNotificationsStore } from '../../src/stores/notificationsStore';

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
    gpuErrorRecoveryHint: null,
    refresh: vi.fn(),
  },
  clientRunning: true,
  setClientRunning: vi.fn(),
  onStartServer: vi.fn().mockResolvedValue(undefined),
  startupFlowPending: false,
  isUploading: false,
  live: baseLiveState,
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

    // JobProgressBlock renders the phase in both the header row and the
    // meta row, so match on all occurrences.
    expect(screen.getByText('Processing recording')).toBeDefined();
    expect(screen.getAllByText('Processing...').length).toBeGreaterThanOrEqual(1);
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

  it('expands the Transcribe File import surface from the Main Transcription card', () => {
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    // The surface stays MOUNTED while collapsed (hidden attribute, not a
    // conditional render) so the folder watcher it owns keeps running.
    const surface = screen.getByTestId('session-import-surface');
    const toggle = screen.getByRole('button', { name: /transcribe file/i });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(surface).not.toBeVisible();

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(surface).toBeVisible();

    fireEvent.click(toggle);
    expect(surface).not.toBeVisible();
    expect(screen.getByTestId('session-import-surface')).toBeDefined();
  });
});

// ── Task 10 hardening — cancel terminalizes the session-recording card ─────

describe('Session notifications lifecycle - cancel edge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTranscription.status = 'idle';
    mockTranscription.result = null;
    mockTranscription.error = null;
    mockTranscription.vadActive = false;
    mockTranscription.processingProgress = null;
    useNotificationsStore.setState({ notifications: [] });

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

  it('terminalizes the session-recording card as "Recording cancelled" when recording resets to idle', () => {
    const { rerender } = render(React.createElement(SessionView, baseProps), {
      wrapper: createWrapper(),
    });

    mockTranscription.status = 'recording';
    rerender(React.createElement(SessionView, baseProps));

    mockTranscription.status = 'idle';
    rerender(React.createElement(SessionView, baseProps));

    const entries = useNotificationsStore
      .getState()
      .notifications.filter((n) => n.id === 'session-recording');
    expect(entries).toHaveLength(1);
    expect(entries[0].title).toBe('Recording cancelled');
    expect(entries[0].status).toBe('complete');
  });
});

// ── Issue #86 #1 — Start Recording disabled-reason surface ──────────────────

describe('Start Recording disabled-reason surface', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTranscription.status = 'idle';
    mockTranscription.result = null;
    mockTranscription.error = null;
    mockTranscription.vadActive = false;
    mockTranscription.processingProgress = null;

    vi.mocked(isModelDisabled).mockReturnValue(false);

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

  it('shows "Server is not running" warning when clientRunning is false', () => {
    const props = { ...baseProps, clientRunning: false };
    render(React.createElement(SessionView, props), { wrapper: createWrapper() });

    const warning = screen.getByTestId('recording-disabled-reason');
    expect(warning).toBeDefined();
    expect(warning.textContent).toBe('Server is not running — start it from the Server view.');
  });

  it('shows "Server is starting or model is loading" warning when reachable but not ready', () => {
    const props = {
      ...baseProps,
      clientRunning: true,
      serverConnection: { ...baseProps.serverConnection, reachable: true, ready: false },
    };
    render(React.createElement(SessionView, props), { wrapper: createWrapper() });

    const warning = screen.getByTestId('recording-disabled-reason');
    expect(warning).toBeDefined();
    expect(warning.textContent).toBe(
      'Server is starting or model is loading — check the Server view for progress.',
    );
  });

  it('does NOT show recording-disabled-reason when mainModelDisabled is true', () => {
    vi.mocked(isModelDisabled).mockReturnValue(true);
    // Server reachable + ready so the ONLY gate firing is mainModelDisabled
    // (which has its own dedicated warning at SessionView lines 1529-1535).
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    expect(screen.queryByTestId('recording-disabled-reason')).toBeNull();
    expect(screen.getByText('Main model not selected.')).toBeDefined();
  });

  it('does NOT show recording-disabled-reason when all gates clear and Start button is enabled', () => {
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    expect(screen.queryByTestId('recording-disabled-reason')).toBeNull();
    const startButton = screen.getByText('Start Recording').closest('button');
    expect(startButton?.disabled).toBe(false);
  });

  it('does NOT show recording-disabled-reason when Stop button is shown (canStartRecording false)', () => {
    mockTranscription.status = 'recording';
    // Even with bad server state, the Stop button branch hides the new warning.
    const props = { ...baseProps, clientRunning: false };
    render(React.createElement(SessionView, props), { wrapper: createWrapper() });

    expect(screen.queryByTestId('recording-disabled-reason')).toBeNull();
    expect(screen.getByText('Stop Recording')).toBeDefined();
  });

  // Review-cycle additions — Matrix row 6 (multi-gate) + GPU-error noise.

  it('shows server-not-running warning even when mainModelDisabled is true (matrix row 6)', () => {
    // Matrix row 6: with multiple gates firing, BOTH warnings render — the
    // new server-state warning above and the existing model warning below.
    // Pre-patch this case produced a silent disabled button (the new warning
    // was suppressed by `!mainModelDisabled`); patch drops that gate.
    // Note: in production, `!clientRunning` typically forces
    // `serverConnection.ready === false`, which hides the existing model
    // warning naturally. The test sets `ready: true` (baseProps default) to
    // verify the patched gate; that artificial pairing exercises the gate
    // logic without depending on App.tsx-side derivation.
    vi.mocked(isModelDisabled).mockReturnValue(true);
    const props = { ...baseProps, clientRunning: false };
    render(React.createElement(SessionView, props), { wrapper: createWrapper() });

    const warning = screen.getByTestId('recording-disabled-reason');
    expect(warning.textContent).toBe('Server is not running — start it from the Server view.');
    // Existing model warning ALSO renders (its gate is independent of the
    // server-state warning).
    expect(screen.getByText('Main model not selected.')).toBeDefined();
  });

  it('does NOT show recording-disabled-reason when gpu_error is set (red GPU warning owns the surface)', () => {
    const props = {
      ...baseProps,
      clientRunning: true,
      serverConnection: {
        ...baseProps.serverConnection,
        reachable: true,
        ready: false,
        details: {
          status: 'unhealthy',
          gpu_error: 'CUDA initialization failed',
          gpu_error_action: 'GPU unavailable — restart your computer.',
        },
      },
    };
    render(React.createElement(SessionView, props), { wrapper: createWrapper() });

    expect(screen.queryByTestId('recording-disabled-reason')).toBeNull();
  });

  // gh-86 #1 follow-up — fourth disable gate (`isLive`) was previously silent
  // because `recordingDisabledReason` only covered the two server-state gates.
  // `isLive && canStartRecording === true` is the normal state when the user
  // starts Live Mode without a main transcription running (independent state
  // machines — see the `canStartRecording` derivation in SessionView.tsx).

  // `LiveStatus` positive set (`isLive === true`): 'connecting' | 'starting' |
  // 'listening' | 'processing' (defined in dashboard/src/hooks/useLiveMode.ts).
  // Parameterize across the full set so a future addition or exclusion is
  // caught — covers the most-common WS-handshake transients ('connecting',
  // 'starting') AND the steady-state ('listening') AND the post-utterance
  // pause ('processing'). Each case also asserts the warning↔disablement
  // coupling so a regression that surfaced the warning while leaving the
  // button enabled (or vice versa) does NOT pass silently.
  it.each(['connecting', 'starting', 'listening', 'processing'] as const)(
    'shows "Live Mode is active" warning AND disables Start button when live.status is "%s"',
    (status) => {
      const props = {
        ...baseProps,
        live: { ...baseLiveState, status },
      };
      render(React.createElement(SessionView, props), { wrapper: createWrapper() });

      const warning = screen.getByTestId('recording-disabled-reason');
      expect(warning.textContent).toBe('Live Mode is active — stop Live Mode to start recording.');
      const startButton = screen.getByText('Start Recording').closest('button');
      expect(startButton?.disabled).toBe(true);
    },
  );

  it('server-not-running message wins priority when both server and isLive gates fire', () => {
    // Locks in IIFE priority order: clientRunning → serverConnection.ready →
    // isLive. Server-down is the root cause; stopping Live Mode would not
    // re-enable Start Recording while the server is dead, so the server
    // message must win.
    const props = {
      ...baseProps,
      clientRunning: false,
      live: { ...baseLiveState, status: 'listening' as const },
    };
    render(React.createElement(SessionView, props), { wrapper: createWrapper() });

    const warning = screen.getByTestId('recording-disabled-reason');
    expect(warning.textContent).toBe('Server is not running — start it from the Server view.');
  });

  it('server-starting message wins priority over isLive', () => {
    // Mirror of the above for the second server-state gate.
    const props = {
      ...baseProps,
      clientRunning: true,
      serverConnection: { ...baseProps.serverConnection, reachable: true, ready: false },
      live: { ...baseLiveState, status: 'listening' as const },
    };
    render(React.createElement(SessionView, props), { wrapper: createWrapper() });

    const warning = screen.getByTestId('recording-disabled-reason');
    expect(warning.textContent).toBe(
      'Server is starting or model is loading — check the Server view for progress.',
    );
  });

  it('does NOT show recording-disabled-reason when live.status is "error" (counts as not-live)', () => {
    // Locks in the negative half of `isLive` — error state should NOT trigger
    // the live-mode message. Without this test, a refactor of `isLive` could
    // surface a misleading warning during a live-mode failure.
    const props = {
      ...baseProps,
      live: { ...baseLiveState, status: 'error' as const },
    };
    render(React.createElement(SessionView, props), { wrapper: createWrapper() });

    expect(screen.queryByTestId('recording-disabled-reason')).toBeNull();
  });
});

// ── Capture Gain must be handed to the hook BEFORE start() ─────────────────
//
// The AudioCapture instance is built a server round trip after start(), so the
// hook has nothing to apply a gain to at the moment start() is called. Handing
// the value over first is what gets it into the recording's first sample; the
// original code called setGain() on the line *after* start(), where it landed
// on a null ref (first recording) or the previous, already-stopped instance.

describe('capture gain handed to the hook at recording start', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTranscription.status = 'idle';
    mockTranscription.result = null;
    mockTranscription.error = null;
    mockTranscription.vadActive = false;
    mockTranscription.processingProgress = null;

    vi.mocked(isModelDisabled).mockReturnValue(false);

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

  /** Order of the LAST setGain call - the one that must precede start(). */
  const lastSetGainOrder = (): number => {
    const orders = mockTranscription.setGain.mock.invocationCallOrder;
    return orders[orders.length - 1];
  };

  it('hands the slider gain to the hook before start() on system audio', async () => {
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    fireEvent.click(screen.getByRole('button', { name: /System Audio/i }));
    fireEvent.change(screen.getByRole('slider'), { target: { value: '3' } });
    fireEvent.click(screen.getByRole('button', { name: /Start Recording/i }));

    await waitFor(() => expect(mockTranscription.start).toHaveBeenCalled());

    expect(mockTranscription.setGain).toHaveBeenLastCalledWith(3);
    expect(lastSetGainOrder()).toBeLessThan(mockTranscription.start.mock.invocationCallOrder[0]);
  });

  it('resets the gain to unity for a microphone recording', async () => {
    // Capture Gain is a system-audio-only control (its slider is not even
    // rendered for the mic). Now that the hook remembers the last value across
    // captures, a mic recording started after a boosted system one has to be
    // told to go back to 1.0 - otherwise it would inherit the amplification.
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    fireEvent.click(screen.getByRole('button', { name: /System Audio/i }));
    fireEvent.change(screen.getByRole('slider'), { target: { value: '3' } });
    // Exact name: the mic-mix switch rendered by the system-audio card is also
    // named "Also capture microphone" and would match a loose pattern.
    fireEvent.click(screen.getByRole('button', { name: 'Microphone' }));
    fireEvent.click(screen.getByRole('button', { name: /Start Recording/i }));

    await waitFor(() => expect(mockTranscription.start).toHaveBeenCalled());

    expect(mockTranscription.start.mock.calls[0][0]).toMatchObject({ systemAudio: false });
    expect(mockTranscription.setGain).toHaveBeenLastCalledWith(1);
    expect(lastSetGainOrder()).toBeLessThan(mockTranscription.start.mock.invocationCallOrder[0]);
  });
});

// ── Live Mode has its own copy of the gain-before-start call site ──────────
//
// SessionView seeds the gain twice - once in handleStartRecording and once in
// handleLiveToggle - and the two are independent lines that can drift apart.
// The recording half is covered above; this covers the Live Mode half.

describe('capture gain handed to the live hook at Live Mode start', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTranscription.status = 'idle';
    mockTranscription.result = null;
    mockTranscription.error = null;
    mockTranscription.vadActive = false;
    mockTranscription.processingProgress = null;

    vi.mocked(isModelDisabled).mockReturnValue(false);

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

  /** A live state with its own mocks, so call order is not shared across tests. */
  function makeLive() {
    return { ...baseLiveState, start: vi.fn(), stop: vi.fn(), setGain: vi.fn() };
  }

  it('hands the slider gain to the live hook before start() on system audio', async () => {
    const live = makeLive();
    render(React.createElement(SessionView, { ...baseProps, live }), { wrapper: createWrapper() });

    fireEvent.click(screen.getByRole('button', { name: /System Audio/i }));
    fireEvent.change(screen.getByRole('slider'), { target: { value: '3' } });
    fireEvent.click(screen.getAllByRole('switch', { name: 'Live Mode' })[0]);

    await waitFor(() => expect(live.start).toHaveBeenCalled());

    expect(live.setGain).toHaveBeenLastCalledWith(3);
    const orders = live.setGain.mock.invocationCallOrder;
    expect(orders[orders.length - 1]).toBeLessThan(live.start.mock.invocationCallOrder[0]);
  });

  it('resets the live gain to unity for a microphone session', async () => {
    const live = makeLive();
    render(React.createElement(SessionView, { ...baseProps, live }), { wrapper: createWrapper() });

    fireEvent.click(screen.getByRole('button', { name: /System Audio/i }));
    fireEvent.change(screen.getByRole('slider'), { target: { value: '3' } });
    fireEvent.click(screen.getByRole('button', { name: 'Microphone' }));
    fireEvent.click(screen.getAllByRole('switch', { name: 'Live Mode' })[0]);

    await waitFor(() => expect(live.start).toHaveBeenCalled());

    expect(live.start.mock.calls[0][0]).toMatchObject({ systemAudio: false });
    expect(live.setGain).toHaveBeenLastCalledWith(1);
    const orders = live.setGain.mock.invocationCallOrder;
    expect(orders[orders.length - 1]).toBeLessThan(live.start.mock.invocationCallOrder[0]);
  });
});

// ── The Main Transcription card's mute button drove the wrong hook ─────────
//
// That card owns the one-shot recording - the Record/Stop button, the result,
// the errors - but its header mute button called live.toggleMute() and
// rendered live.muted, left behind by the layout refactor that moved a Live
// Mode toolbar out of it (a8155a5f). Pressing it during a recording turned it
// red and flipped the tray to 'recording-muted' - SessionView feeds
// useTraySync the combined `transcription.muted || live.muted` - while the
// recording went on streaming to the server and being transcribed. The tray
// menu item was the only mute a recording actually had, and pressing THAT to
// "unmute" muted it for real without changing the icon.

describe('the Main Transcription card mutes the recording it owns', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTranscription.status = 'idle';
    mockTranscription.result = null;
    mockTranscription.error = null;
    mockTranscription.vadActive = false;
    mockTranscription.processingProgress = null;
    mockTranscription.muted = false;

    vi.mocked(isModelDisabled).mockReturnValue(false);

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

  // mockTranscription is shared across every describe in this file, so a muted
  // state left set here would leak into whatever runs next.
  afterEach(() => {
    mockTranscription.muted = false;
  });

  it('routes the card mute button to the transcription hook, not the live one', () => {
    const live = { ...baseLiveState, toggleMute: vi.fn() };
    mockTranscription.status = 'recording';
    render(React.createElement(SessionView, { ...baseProps, live }), { wrapper: createWrapper() });

    fireEvent.click(screen.getByRole('button', { name: 'Mute recording' }));

    expect(mockTranscription.toggleMute).toHaveBeenCalledTimes(1);
    expect(live.toggleMute).not.toHaveBeenCalled();
  });

  it('reads its muted state from the recording, not from Live Mode', () => {
    // A muted Live Mode session must not paint this button red: the card is
    // about the recording, and Live Mode has its own mute button.
    mockTranscription.status = 'recording';
    const live = { ...baseLiveState, muted: true, toggleMute: vi.fn() };
    render(React.createElement(SessionView, { ...baseProps, live }), { wrapper: createWrapper() });

    expect(screen.getByRole('button', { name: 'Mute recording' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Unmute recording' })).toBeNull();
  });

  it('offers to unmute once the recording is muted', () => {
    mockTranscription.status = 'recording';
    mockTranscription.muted = true;
    render(React.createElement(SessionView, baseProps), { wrapper: createWrapper() });

    expect(screen.getByRole('button', { name: 'Unmute recording' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Mute recording' })).toBeNull();
  });
});
