/**
 * P2-VIEW-003 — ServerView connection status display
 *
 * Tests that ServerView renders correctly and displays the expected
 * heading and container status text for different Docker states.
 *
 * All hooks and heavy sub-components are mocked.
 */

import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ── Mock state containers ──────────────────────────────────────────────────

const mockDocker = {
  available: true,
  loading: false,
  runtimeKind: 'Docker' as string | null,
  detectionGuidance: null as string | null,
  composeAvailable: true,
  images: [] as Array<{ tag: string; fullName: string; size: string; created: string; id: string }>,
  container: {
    exists: false,
    running: false,
    status: 'unknown',
    health: undefined as string | undefined,
  },
  volumes: [] as Array<{ name: string; label: string; driver: string; mountpoint: string }>,
  operating: false,
  operationError: null as string | null,
  pulling: false,
  sidecarPulling: false,
  logLines: [] as string[],
  logStreaming: false,
  hasSidecarImage: vi.fn().mockResolvedValue(false),
  startLogStream: vi.fn(),
  stopLogStream: vi.fn(),
  clearLogs: vi.fn(),
  remoteTags: [] as string[],
  remoteTagsStatus: 'ok' as 'ok' | 'not-published' | 'error' | null,
  refreshImages: vi.fn(),
  refreshRemoteTags: vi.fn(),
  clearRemoteTags: vi.fn(),
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
};

const mockAdminStatus = {
  status: null as Record<string, unknown> | null,
  loading: false,
  error: null as string | null,
  refresh: vi.fn(),
};

// ── Hook mocks ─────────────────────────────────────────────────────────────

vi.mock('../../src/hooks/DockerContext', () => ({
  useDockerContext: () => mockDocker,
}));

vi.mock('../../src/hooks/useAdminStatus', () => ({
  useAdminStatus: () => mockAdminStatus,
}));

vi.mock('../../src/stores/activityStore', () => ({
  useActivityStore: (selector: (s: Record<string, unknown>) => unknown) => {
    const state = { items: [], addActivity: vi.fn(), updateActivity: vi.fn() };
    return typeof selector === 'function' ? selector(state) : state;
  },
}));

// apiClient
vi.mock('../../src/api/client', () => ({
  apiClient: {
    checkConnection: vi.fn().mockResolvedValue({ reachable: true, ready: true }),
    getAdminStatus: vi.fn().mockResolvedValue(null),
    loadModels: vi.fn().mockResolvedValue(undefined),
    unloadModels: vi.fn().mockResolvedValue(undefined),
    setModel: vi.fn().mockResolvedValue(undefined),
  },
}));

// useClipboard
vi.mock('../../src/hooks/useClipboard', () => ({
  writeToClipboard: vi.fn(),
}));

// config/store
vi.mock('../../src/config/store', () => ({
  getConfig: vi.fn().mockResolvedValue(undefined),
  setConfig: vi.fn().mockResolvedValue(undefined),
  DEFAULT_SERVER_PORT: 7239,
}));

// modelCapabilities — must export the full surface ServerView imports
// (isWhisperModel, isWhisperCppModel, isMLXModel, isNemoModel, isSenseVoiceModel);
// a missing export throws "No <name> export is defined on the mock" the moment
// ServerView accesses it during render. The test world treats every model as
// plain Whisper. `isSenseVoiceModel` is name-based so the merged-diarization
// tests can drive the SenseVoice-only greying / migration by selecting a main
// model whose id contains "sensevoice".
vi.mock('../../src/services/modelCapabilities', () => ({
  isWhisperModel: () => true,
  isWhisperCppModel: () => false,
  isMLXModel: () => false,
  isNemoModel: () => false,
  isSenseVoiceModel: (m: string) => typeof m === 'string' && m.toLowerCase().includes('sensevoice'),
}));

// modelRegistry
vi.mock('../../src/services/modelRegistry', () => ({
  MODEL_REGISTRY: [],
  getModelsByFamily: () => [],
  getModelById: () => null,
}));

// modelSelection
vi.mock('../../src/services/modelSelection', () => ({
  MODEL_DEFAULT_LOADING_PLACEHOLDER: 'Loading…',
  MAIN_MODEL_CUSTOM_OPTION: 'Custom (HuggingFace repo)',
  MAIN_RECOMMENDED_MODEL: 'openai/whisper-large-v3-turbo',
  LIVE_MODEL_SAME_AS_MAIN_OPTION: 'Same as main model',
  LIVE_MODEL_CUSTOM_OPTION: 'Custom live model',
  MODEL_DISABLED_OPTION: 'Disabled',
  DISABLED_MODEL_SENTINEL: '__disabled__',
  WHISPER_MEDIUM: 'openai/whisper-medium',
  MAIN_MODEL_PRESETS: ['openai/whisper-large-v3-turbo', 'iic/SenseVoiceSmall'],
  LIVE_MODEL_PRESETS: ['openai/whisper-medium'],
  VULKAN_RECOMMENDED_MODEL: 'ggml-large-v3-turbo.bin',
  resolveMainModelSelectionValue: (v: string) => v,
  resolveLiveModelSelectionValue: (v: string) => v,
  toBackendModelEnvValue: (v: string) => v,
  isModelDisabled: () => false,
}));

// sonner toast
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// headlessui — mock all components used across ServerView and its children.
// Render-prop children (e.g. {({ selected }) => <>...</>}) are invoked with
// neutral defaults so the text inside actually appears in the DOM for queries.
vi.mock('@headlessui/react', () => {
  const renderChildren = (
    children: React.ReactNode | ((args: any) => React.ReactNode),
    args: Record<string, unknown> = {},
  ): React.ReactNode =>
    typeof children === 'function' ? (children as (a: any) => React.ReactNode)(args) : children;
  const passthrough = ({ children }: { children?: React.ReactNode }) =>
    React.createElement('div', null, renderChildren(children));
  return {
    Dialog: ({ children, open }: { children: React.ReactNode; open: boolean }) =>
      open ? React.createElement('div', { role: 'dialog' }, renderChildren(children)) : null,
    DialogPanel: passthrough,
    DialogTitle: ({ children }: { children: React.ReactNode }) =>
      React.createElement('h2', null, renderChildren(children)),
    Listbox: ({ children, value }: { children: React.ReactNode; value: unknown }) =>
      React.createElement('div', { 'data-value': value }, renderChildren(children, { open: true })),
    ListboxButton: ({ children }: { children: React.ReactNode }) =>
      React.createElement(
        'button',
        { type: 'button' },
        renderChildren(children, { open: true, focus: false, hover: false }),
      ),
    ListboxOptions: passthrough,
    ListboxOption: ({ children, value }: { children: React.ReactNode; value: unknown }) =>
      React.createElement(
        'div',
        { 'data-value': value },
        renderChildren(children, { selected: false, focus: false, active: false }),
      ),
  };
});

// Runtime type guard
vi.mock('../../src/types/runtime', () => ({
  isRuntimeProfile: (v: unknown) =>
    ['gpu', 'cpu', 'vulkan', 'vulkan-wsl2', 'metal'].includes(v as string),
}));

// ── Import after mocks ────────────────────────────────────────────────────

import { ServerView } from '../views/ServerView';

// ── Helpers ────────────────────────────────────────────────────────────────

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
  return wrapper;
}

const baseProps = {
  onStartServer: vi.fn().mockResolvedValue(undefined),
  startupFlowPending: false,
};

// ── Tests ──────────────────────────────────────────────────────────────────

describe('[P2] ServerView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset mutable mock state
    mockDocker.available = true;
    mockDocker.images = [];
    mockDocker.container = { exists: false, running: false, status: 'unknown', health: undefined };
    mockDocker.operationError = null;
    mockDocker.operating = false;
    mockAdminStatus.status = null;

    (window as any).electronAPI = {
      config: {
        get: vi.fn().mockResolvedValue(undefined),
        set: vi.fn().mockResolvedValue(undefined),
      },
      docker: {
        readComposeEnvValue: vi.fn().mockResolvedValue('false'),
        checkModelCache: vi.fn().mockResolvedValue({}),
      },
      app: {
        getArch: vi.fn().mockReturnValue('x64'),
        getConfigDir: vi.fn().mockResolvedValue('/mock/config'),
      },
      mlx: {
        getStatus: vi.fn().mockResolvedValue('stopped'),
        onStatusChanged: vi.fn().mockReturnValue(vi.fn()),
      },
      server: {
        checkFirewallPort: vi.fn().mockResolvedValue(null),
        checkGpu: vi.fn().mockResolvedValue({ gpu: false, toolkit: false, vulkan: false }),
      },
    };
  });

  it('renders "Server Configuration" heading', () => {
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    expect(screen.getByText('Server Configuration')).toBeDefined();
  });

  it('displays "Not Found" status when container does not exist', () => {
    mockDocker.container = { exists: false, running: false, status: 'unknown', health: undefined };
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    expect(screen.getByText('Not Found')).toBeDefined();
  });

  it('displays container status label when container exists but is not running', () => {
    mockDocker.container = { exists: true, running: false, status: 'exited', health: undefined };
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    expect(screen.getByText('Exited')).toBeDefined();
  });

  it('displays operation error when docker.operationError is set', () => {
    mockDocker.operationError = 'Failed to start container: permission denied';
    mockDocker.container = { exists: true, running: false, status: 'exited', health: undefined };
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    expect(
      screen.getAllByText('Failed to start container: permission denied').length,
    ).toBeGreaterThanOrEqual(1);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Issue #112 / #86 #2 — Pyannote diarization on Mac Metal (gate REMOVED)
//
// pyannote.audio 4.x runs on Apple Silicon GPU (MPS) for *inference* — validated
// on M2 hardware, including >4 speakers (beyond Sortformer's 4-cap). The upstream
// MPS issues (#1886/#1337/#1091) concern training, not inference. So on Mac Metal
// the dashboard now OFFERS pyannote: it is no longer hidden, no longer
// auto-migrated to Sortformer, and shows no "unsupported on Apple Silicon" copy.
// Sortformer stays the no-token Metal-native default; pyannote is opt-in.
// ─────────────────────────────────────────────────────────────────────────────

describe('Pyannote diarization on Mac Metal (gate removed, Issue #112)', () => {
  const SORTFORMER = 'Sortformer (Metal; ≤ 4 speakers)';
  const PYANNOTE = 'pyannote/speaker-diarization-community-1';
  const CUSTOM = 'Custom (HuggingFace repo)';

  function setupElectronAPI(configMap: Record<string, unknown>) {
    const setSpy = vi.fn().mockResolvedValue(undefined);
    (window as any).electronAPI = {
      config: {
        get: vi.fn().mockImplementation(async (key: string) => configMap[key]),
        set: setSpy,
      },
      docker: {
        readComposeEnvValue: vi.fn().mockResolvedValue('false'),
        checkModelCache: vi.fn().mockResolvedValue({}),
      },
      app: {
        getArch: vi.fn().mockReturnValue('arm64'),
        getConfigDir: vi.fn().mockResolvedValue('/mock/config'),
      },
      mlx: {
        getStatus: vi.fn().mockResolvedValue('stopped'),
        onStatusChanged: vi.fn().mockReturnValue(vi.fn()),
      },
      server: {
        checkFirewallPort: vi.fn().mockResolvedValue(null),
        checkGpu: vi.fn().mockResolvedValue({ gpu: false, toolkit: false, vulkan: false }),
      },
    };
    return setSpy;
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockDocker.available = true;
    mockDocker.images = [];
    mockDocker.container = { exists: false, running: false, status: 'unknown', health: undefined };
    mockDocker.operationError = null;
    // Truthy adminStatus so the diarization-hydration effect at ServerView.tsx:774
    // can flip `diarizationHydrated` to true — which our migration effect depends on.
    // The shape only needs to satisfy the `?.` chains at lines 725-744.
    mockAdminStatus.status = { models: {} };
  });

  it('on Mac Metal with persisted Pyannote, does NOT migrate the selection to Sortformer', async () => {
    const setSpy = setupElectronAPI({
      'server.runtimeProfile': 'metal',
      'server.diarizationModelSelection': PYANNOTE,
      'server.diarizationCustomModel': '',
    });

    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });

    // Pyannote stays selected (appears in the ListboxButton and/or an option).
    await waitFor(() => {
      expect(screen.queryAllByText(PYANNOTE).length).toBeGreaterThanOrEqual(1);
    });
    // The old auto-migration to Sortformer must NOT fire on Metal anymore.
    // (ServerView persists the merged control under server.diarizationModelSelection.)
    const sortformerWrites = setSpy.mock.calls.filter(
      ([k, v]) => k === 'server.diarizationModelSelection' && v === SORTFORMER,
    );
    expect(sortformerWrites.length).toBe(0);
  });

  it('on Mac Metal, Pyannote IS offered and no "unsupported" copy is rendered', async () => {
    setupElectronAPI({
      'server.runtimeProfile': 'metal',
      'server.diarizationModelSelection': SORTFORMER,
      'server.diarizationCustomModel': '',
    });

    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });

    // Sortformer is the default selection; pyannote is now a selectable option.
    await waitFor(() => {
      expect(screen.queryAllByText(SORTFORMER).length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.queryAllByText(PYANNOTE).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryAllByText(CUSTOM).length).toBeGreaterThanOrEqual(1);
    // The "not supported on Apple Silicon" inline reason is gone.
    expect(screen.queryByText(/pyannote\.audio MPS path/i)).toBeNull();
  });

  it('on non-Metal profile (cpu), Pyannote remains available and is not migrated', async () => {
    const setSpy = setupElectronAPI({
      'server.runtimeProfile': 'cpu',
      'server.diarizationModelSelection': PYANNOTE,
      'server.diarizationCustomModel': '',
    });

    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.queryAllByText(PYANNOTE).length).toBeGreaterThanOrEqual(1);
    });
    const sortformerSet = setSpy.mock.calls.some(
      ([k, v]) => k === 'server.diarizationModelSelection' && v === SORTFORMER,
    );
    expect(sortformerSet).toBe(false);
    expect(screen.queryByText(/pyannote\.audio MPS path/i)).toBeNull();
    expect(screen.queryAllByText(SORTFORMER).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryAllByText(CUSTOM).length).toBeGreaterThanOrEqual(1);
  });

  it('on Mac Metal with Custom + pyannote-prefixed value, shows NO unsupported warning', async () => {
    setupElectronAPI({
      'server.runtimeProfile': 'metal',
      'server.diarizationModelSelection': CUSTOM,
      'server.diarizationCustomModel': 'pyannote/some-fork',
    });

    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });

    // The custom-repo input renders; the old amber "not supported" warning is gone.
    await waitFor(() => {
      expect(screen.queryAllByText(CUSTOM).length).toBeGreaterThanOrEqual(1);
    });
    expect(
      screen.queryByText(/Custom pyannote repos are not supported on Apple Silicon/i),
    ).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Merged Diarization dropdown — CAM++ + engine collapsed into ONE control.
//
// The Server tab renders a SINGLE "Diarization Model" dropdown listing CAM++
// alongside Sortformer, pyannote and Custom. Selecting CAM++ sends
// SENSEVOICE_DIARIZATION_ENGINE=funasr with an EMPTY DIARIZATION_MODEL; every
// other pick sends the pyannote engine. The merged value keeps the original
// server.diarizationModelSelection key (shared with the Model Manager tab and the
// Metal boot auto-start). The retired server.sensevoiceDiarizationEngine key acts
// as a one-shot migration marker and is cleared once the fold is applied.
// ─────────────────────────────────────────────────────────────────────────────

describe('Merged Diarization dropdown (CAM++ + engine)', () => {
  const CAMPP = 'CAM++ (fast, built-in)';
  const SORTFORMER = 'Sortformer (Metal; ≤ 4 speakers)';
  const PYANNOTE = 'pyannote/speaker-diarization-community-1';
  const SENSEVOICE_MAIN = 'iic/SenseVoiceSmall';
  const WHISPER_MAIN = 'openai/whisper-large-v3-turbo';

  function setupMergedAPI(configMap: Record<string, unknown>, arch = 'x64') {
    const setSpy = vi.fn().mockResolvedValue(undefined);
    (window as any).electronAPI = {
      config: {
        get: vi.fn().mockImplementation(async (key: string) => configMap[key]),
        set: setSpy,
      },
      docker: {
        readComposeEnvValue: vi.fn().mockResolvedValue('false'),
        checkModelCache: vi.fn().mockResolvedValue({}),
      },
      app: {
        getArch: vi.fn().mockReturnValue(arch),
        getConfigDir: vi.fn().mockResolvedValue('/mock/config'),
      },
      mlx: {
        getStatus: vi.fn().mockResolvedValue('stopped'),
        onStatusChanged: vi.fn().mockReturnValue(vi.fn()),
      },
      server: {
        checkFirewallPort: vi.fn().mockResolvedValue(null),
        checkGpu: vi.fn().mockResolvedValue({ gpu: false, toolkit: false, vulkan: false }),
      },
    };
    return setSpy;
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockDocker.available = true;
    mockDocker.images = [];
    mockDocker.container = { exists: false, running: false, status: 'unknown', health: undefined };
    mockDocker.operationError = null;
    mockDocker.operating = false;
    mockDocker.composeAvailable = true;
    // Truthy adminStatus so the diarization-hydration effect can settle.
    mockAdminStatus.status = { models: {} };
  });

  it('greys the CAM++ option (SenseVoice only) when the main transcriber is not SenseVoice', async () => {
    setupMergedAPI({ 'server.runtimeProfile': 'cpu', 'server.mainModelSelection': WHISPER_MAIN });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.queryByText('SenseVoice only')).not.toBeNull();
    });
    expect(screen.queryAllByText(CAMPP).length).toBeGreaterThanOrEqual(1);
  });

  it('enables the CAM++ option (no SenseVoice-only badge) when the main transcriber is SenseVoice', async () => {
    setupMergedAPI({
      'server.runtimeProfile': 'cpu',
      'server.mainModelSelection': SENSEVOICE_MAIN,
    });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    // The badge is present transiently before hydration (main is the loading
    // placeholder), then clears once the SenseVoice main is restored.
    await waitFor(() => {
      expect(screen.queryByText('SenseVoice only')).toBeNull();
    });
    expect(screen.queryAllByText(CAMPP).length).toBeGreaterThanOrEqual(1);
  });

  it('greys the Sortformer option (Requires Metal) on a non-Metal runtime', async () => {
    setupMergedAPI({ 'server.runtimeProfile': 'cpu', 'server.mainModelSelection': WHISPER_MAIN });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.queryByText('Requires Metal')).not.toBeNull();
    });
    expect(screen.queryAllByText(SORTFORMER).length).toBeGreaterThanOrEqual(1);
  });

  it('does NOT grey Sortformer on the Metal runtime', async () => {
    setupMergedAPI(
      { 'server.runtimeProfile': 'metal', 'server.mainModelSelection': WHISPER_MAIN },
      'arm64',
    );
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.queryAllByText(SORTFORMER).length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.queryByText('Requires Metal')).toBeNull();
  });

  it('selecting CAM++ sends funasr engine + empty diarization model to onStartServer', async () => {
    const onStart = vi.fn().mockResolvedValue(undefined);
    const setSpy = setupMergedAPI({
      'server.runtimeProfile': 'cpu',
      'server.mainModelSelection': SENSEVOICE_MAIN,
      'server.diarizationModelSelection': CAMPP,
    });
    render(React.createElement(ServerView, { ...baseProps, onStartServer: onStart }), {
      wrapper: createWrapper(),
    });
    await waitFor(() => {
      expect(setSpy).toHaveBeenCalledWith('server.diarizationModelSelection', CAMPP);
    });
    fireEvent.click(screen.getByText('Start Local'));
    expect(onStart).toHaveBeenCalledTimes(1);
    const models = onStart.mock.calls[0][3];
    expect(models.sensevoiceDiarizationEngine).toBe('funasr');
    expect(models.diarizationModel).toBe('');
  });

  it('selecting pyannote sends pyannote engine + pyannote model to onStartServer', async () => {
    const onStart = vi.fn().mockResolvedValue(undefined);
    const setSpy = setupMergedAPI({
      'server.runtimeProfile': 'cpu',
      'server.mainModelSelection': WHISPER_MAIN,
      'server.diarizationModelSelection': PYANNOTE,
    });
    render(React.createElement(ServerView, { ...baseProps, onStartServer: onStart }), {
      wrapper: createWrapper(),
    });
    await waitFor(() => {
      expect(setSpy).toHaveBeenCalledWith('server.diarizationModelSelection', PYANNOTE);
    });
    fireEvent.click(screen.getByText('Start Local'));
    const models = onStart.mock.calls[0][3];
    expect(models.sensevoiceDiarizationEngine).toBe('pyannote');
    expect(models.diarizationModel).toBe(PYANNOTE);
  });

  it('migrates legacy {pyannote model, CAM++ engine} + SenseVoice main to CAM++ and consumes the marker', async () => {
    const setSpy = setupMergedAPI({
      'server.runtimeProfile': 'cpu',
      'server.mainModelSelection': SENSEVOICE_MAIN,
      'server.diarizationModelSelection': PYANNOTE,
      'server.sensevoiceDiarizationEngine': CAMPP,
    });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    await waitFor(() => {
      expect(setSpy).toHaveBeenCalledWith('server.diarizationModelSelection', CAMPP);
    });
    // The retired key is cleared so the migration can never re-fire and clobber a
    // later user choice.
    expect(setSpy).toHaveBeenCalledWith('server.sensevoiceDiarizationEngine', '');
    expect(screen.queryAllByText(CAMPP).length).toBeGreaterThanOrEqual(1);
  });

  it('migrates legacy {pyannote model, CAM++ engine} + Whisper main to the pyannote option', async () => {
    const setSpy = setupMergedAPI({
      'server.runtimeProfile': 'cpu',
      'server.mainModelSelection': WHISPER_MAIN,
      'server.diarizationModelSelection': PYANNOTE,
      'server.sensevoiceDiarizationEngine': CAMPP,
    });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    await waitFor(() => {
      expect(setSpy).toHaveBeenCalledWith('server.diarizationModelSelection', PYANNOTE);
    });
    // CAM++ was a no-op under a non-SenseVoice main, so the merged value must be
    // the legacy pyannote pick, never CAM++.
    expect(setSpy).not.toHaveBeenCalledWith('server.diarizationModelSelection', CAMPP);
  });

  it('does not re-fire the migration once the retired engine key is cleared', async () => {
    // Post-migration store: the marker is an empty string, which getString reports
    // as null. A user who has since picked pyannote must keep it.
    const setSpy = setupMergedAPI({
      'server.runtimeProfile': 'cpu',
      'server.mainModelSelection': SENSEVOICE_MAIN,
      'server.diarizationModelSelection': PYANNOTE,
      'server.sensevoiceDiarizationEngine': '',
    });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    await waitFor(() => {
      expect(setSpy).toHaveBeenCalledWith('server.diarizationModelSelection', PYANNOTE);
    });
    expect(setSpy).not.toHaveBeenCalledWith('server.diarizationModelSelection', CAMPP);
  });

  it('does NOT reset a stored CAM++ selection before adminStatus arrives', async () => {
    // Regression guard. Until adminStatus lands, configuredMainModel is the
    // DISABLED_MODEL_SENTINEL, so activeTranscriber resolves to a truthy value that
    // is NOT the loading placeholder. A placeholder-only guard would let the
    // fallback-to-pyannote reset through and clobber a legitimately stored CAM++.
    mockAdminStatus.status = null;
    const setSpy = setupMergedAPI({
      'server.runtimeProfile': 'cpu',
      'server.mainModelSelection': WHISPER_MAIN,
      'server.diarizationModelSelection': CAMPP,
    });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    await waitFor(() => {
      expect(setSpy).toHaveBeenCalledWith('server.diarizationModelSelection', CAMPP);
    });
    expect(setSpy).not.toHaveBeenCalledWith('server.diarizationModelSelection', PYANNOTE);
    expect(screen.queryAllByText(CAMPP).length).toBeGreaterThanOrEqual(1);
  });
});
