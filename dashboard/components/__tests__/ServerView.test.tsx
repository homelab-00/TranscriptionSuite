/**
 * P2-VIEW-003 — ServerView connection status display
 *
 * Tests that ServerView renders correctly and displays the expected
 * heading and container status text for different Docker states.
 *
 * All hooks and heavy sub-components are mocked.
 */

import React from 'react';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
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
  remoteTags: [] as Array<{ tag: string; created: string | null }>,
  remoteTagsStatus: 'ok' as 'ok' | 'not-published' | 'error' | null,
  variantTags: null as Record<
    'cuda' | 'cuda-legacy' | 'vulkan-wsl2' | 'vulkan-linux',
    string[]
  > | null,
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

vi.mock('../../src/stores/notificationsStore', () => {
  // zustand-style store mock: callable as a hook AND exposing getState()
  // (handleRuntimeProfileChange and the pull handlers call
  // useNotificationsStore.getState() directly).
  const state = {
    notifications: [],
    notify: vi.fn(),
    updateNotification: vi.fn(),
    dismissToast: vi.fn(),
  };
  const useNotificationsStore = (selector?: (s: Record<string, unknown>) => unknown) =>
    typeof selector === 'function' ? selector(state) : state;
  useNotificationsStore.getState = () => state;
  return { useNotificationsStore };
});

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

// modelCapabilities — must export the full surface ServerView AND
// instanceMatrix import (a missing export throws "No <name> export is defined
// on the mock" the moment it is accessed during render). The test world treats
// every model as plain Whisper; `isSenseVoiceModel`, `isWhisperCppModel` and
// `isMLXModel` are name-based so the selector tests can drive family-specific
// greying / resets by choosing an appropriately named main model.
vi.mock('../../src/services/modelCapabilities', () => ({
  isWhisperModel: () => true,
  isWhisperCppModel: (m: string) =>
    typeof m === 'string' && /(?:^|\/)ggml-.*\.bin$|\.gguf$/i.test(m),
  isMLXModel: (m: string) => typeof m === 'string' && m.toLowerCase().startsWith('mlx-community/'),
  isNemoModel: () => false,
  isParakeetModel: () => false,
  isCanaryModel: () => false,
  isMLXParakeetModel: () => false,
  isMLXCanaryModel: () => false,
  isVibeVoiceASRModel: () => false,
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
  LIVE_RECOMMENDED_MODEL: 'openai/whisper-medium',
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
  // Same render-prop mock convention as SessionImportTab.output-format.test.tsx:
  // ListboxButton forwards aria-label so getByRole('button', { name }) works,
  // and ListboxOption wires its click to the Listbox onChange via context so
  // selecting an option drives the component (used by the GPU picker tests).
  const OnChangeCtx = React.createContext<(value: unknown) => void>(() => {});
  return {
    Dialog: ({ children, open }: { children: React.ReactNode; open: boolean }) =>
      open ? React.createElement('div', { role: 'dialog' }, renderChildren(children)) : null,
    DialogPanel: passthrough,
    DialogTitle: ({ children }: { children: React.ReactNode }) =>
      React.createElement('h2', null, renderChildren(children)),
    Listbox: ({
      children,
      value,
      onChange,
    }: {
      children: React.ReactNode;
      value: unknown;
      onChange?: (value: unknown) => void;
    }) =>
      React.createElement(
        OnChangeCtx.Provider,
        { value: onChange ?? (() => {}) },
        React.createElement(
          'div',
          { 'data-value': value },
          renderChildren(children, { open: true }),
        ),
      ),
    ListboxButton: ({
      children,
      ['aria-label']: ariaLabel,
    }: {
      children: React.ReactNode;
      'aria-label'?: string;
    }) =>
      React.createElement(
        'button',
        { type: 'button', 'aria-label': ariaLabel },
        renderChildren(children, { open: true, focus: false, hover: false }),
      ),
    ListboxOptions: passthrough,
    ListboxOption: ({ children, value }: { children: React.ReactNode; value: unknown }) => {
      const onChange = React.useContext(OnChangeCtx);
      return React.createElement(
        'div',
        { role: 'option', 'data-value': value, onClick: () => onChange(value) },
        renderChildren(children, { selected: false, focus: false, active: false }),
      );
    },
  };
});

// Runtime type guard
vi.mock('../../src/types/runtime', () => ({
  isRuntimeProfile: (v: unknown) =>
    ['gpu', 'cpu', 'vulkan', 'vulkan-wsl2', 'metal'].includes(v as string),
}));

// ── Import after mocks ────────────────────────────────────────────────────

import { ServerView } from '../views/ServerView';
import { getConfig, setConfig } from '../../src/config/store';
import { toast } from 'sonner';

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
  // Persisted electron-store values (must never change) …
  const SORTFORMER = 'Sortformer (Metal; ≤ 4 speakers)';
  const PYANNOTE = 'pyannote/speaker-diarization-community-1';
  const CUSTOM = 'Custom (HuggingFace repo)';
  // … and the short labels the diarization selector tiles display for them.
  const SORTFORMER_TILE = 'Sortformer';
  const PYANNOTE_TILE = 'PyAnnote';
  const CUSTOM_TILE = 'Custom';

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

    // Pyannote stays selected (its tile is pressed).
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: new RegExp(PYANNOTE_TILE, 'i'), pressed: true }),
      ).toBeDefined();
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

    // Sortformer is the stored selection; pyannote is a selectable tile.
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: new RegExp(SORTFORMER_TILE, 'i'), pressed: true }),
      ).toBeDefined();
    });
    expect(screen.queryAllByText(PYANNOTE_TILE).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryAllByText(CUSTOM_TILE).length).toBeGreaterThanOrEqual(1);
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
      expect(
        screen.getByRole('button', { name: new RegExp(PYANNOTE_TILE, 'i'), pressed: true }),
      ).toBeDefined();
    });
    const sortformerSet = setSpy.mock.calls.some(
      ([k, v]) => k === 'server.diarizationModelSelection' && v === SORTFORMER,
    );
    expect(sortformerSet).toBe(false);
    expect(screen.queryByText(/pyannote\.audio MPS path/i)).toBeNull();
    // Sortformer stays visible on non-Metal, greyed with its reason badge.
    expect(screen.queryAllByText(SORTFORMER_TILE).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText('Requires Metal')).not.toBeNull();
    expect(screen.queryAllByText(CUSTOM_TILE).length).toBeGreaterThanOrEqual(1);
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
      expect(screen.getByDisplayValue('pyannote/some-fork')).toBeDefined();
    });
    expect(
      screen.queryByText(/Custom pyannote repos are not supported on Apple Silicon/i),
    ).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Merged Diarization control — CAM++ + engine collapsed into ONE selector.
//
// The Server tab renders a single Diarization selector (tile grid) listing
// CAM++ alongside Sortformer, PyAnnote and Custom. Selecting CAM++ sends
// SENSEVOICE_DIARIZATION_ENGINE=funasr with an EMPTY DIARIZATION_MODEL; every
// other pick sends the pyannote engine. The merged value keeps the original
// server.diarizationModelSelection key (shared with the Model Manager tab and the
// Metal boot auto-start), storing the SAME literal strings as the pre-tile
// dropdown. The retired server.sensevoiceDiarizationEngine key acts as a
// one-shot migration marker and is cleared once the fold is applied.
// ─────────────────────────────────────────────────────────────────────────────

describe('Merged Diarization control (CAM++ + engine)', () => {
  // Persisted electron-store values (must never change) …
  const CAMPP = 'CAM++ (fast, built-in)';
  const SORTFORMER = 'Sortformer (Metal; ≤ 4 speakers)';
  const PYANNOTE = 'pyannote/speaker-diarization-community-1';
  // … and the short labels their tiles display.
  const CAMPP_TILE = 'CAM++';
  const SORTFORMER_TILE = 'Sortformer';
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

  it('greys the CAM++ tile (SenseVoice only) when the main transcriber is not SenseVoice', async () => {
    setupMergedAPI({ 'server.runtimeProfile': 'cpu', 'server.mainModelSelection': WHISPER_MAIN });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.queryByText('SenseVoice only')).not.toBeNull();
    });
    expect(screen.queryAllByText(CAMPP_TILE).length).toBeGreaterThanOrEqual(1);
  });

  it('enables the CAM++ tile (no SenseVoice-only badge) when the main transcriber is SenseVoice', async () => {
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
    expect(screen.queryAllByText(CAMPP_TILE).length).toBeGreaterThanOrEqual(1);
  });

  it('greys the Sortformer tile (Requires Metal) on a non-Metal runtime', async () => {
    setupMergedAPI({ 'server.runtimeProfile': 'cpu', 'server.mainModelSelection': WHISPER_MAIN });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.queryByText('Requires Metal')).not.toBeNull();
    });
    expect(screen.queryAllByText(SORTFORMER_TILE).length).toBeGreaterThanOrEqual(1);
  });

  it('does NOT grey Sortformer on the Metal runtime', async () => {
    setupMergedAPI(
      { 'server.runtimeProfile': 'metal', 'server.mainModelSelection': WHISPER_MAIN },
      'arm64',
    );
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.queryAllByText(SORTFORMER_TILE).length).toBeGreaterThanOrEqual(1);
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
    expect(screen.queryAllByText(CAMPP_TILE).length).toBeGreaterThanOrEqual(1);
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
    expect(screen.queryAllByText(CAMPP_TILE).length).toBeGreaterThanOrEqual(1);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Server tab matrix redesign — card layout + deferred runtime downloads.
//
// The tab is five numbered cards: Docker Image → Instance Settings (runtime +
// model + live + diarization selectors) → Remote Connection (auth token +
// Tailscale hostname) → Persistent Volumes → Clean Up. Selecting a runtime
// must never start downloads: in particular, picking Metal only persists the
// profile — the native MLX server (whose startup pre-downloads models) starts
// exclusively from the explicit Start button.
// ─────────────────────────────────────────────────────────────────────────────

describe('Server tab matrix redesign', () => {
  function setupRedesignAPI(configMap: Record<string, unknown>, arch = 'x64') {
    const setSpy = vi.fn().mockResolvedValue(undefined);
    const mlxStart = vi.fn().mockResolvedValue(undefined);
    const mlxStop = vi.fn().mockResolvedValue(undefined);
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
        start: mlxStart,
        stop: mlxStop,
      },
      tailscale: {
        getHostname: vi.fn().mockResolvedValue('my-server.tail1234.ts.net'),
      },
      server: {
        checkFirewallPort: vi.fn().mockResolvedValue(null),
        checkGpu: vi.fn().mockResolvedValue({ gpu: false, toolkit: false, vulkan: false }),
      },
    };
    return { setSpy, mlxStart, mlxStop };
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockDocker.available = true;
    mockDocker.images = [];
    mockDocker.container = { exists: false, running: false, status: 'unknown', health: undefined };
    mockDocker.operationError = null;
    mockDocker.operating = false;
    mockDocker.composeAvailable = true;
    mockAdminStatus.status = { models: {} };
  });

  it('renders the six renumbered cards and drops the old standalone model cards', async () => {
    setupRedesignAPI({ 'server.runtimeProfile': 'cpu' });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    expect(screen.getByText('1. Runtime Settings')).toBeDefined();
    expect(screen.getByText('2. Docker Image')).toBeDefined();
    expect(screen.getByText('3. Instance Settings')).toBeDefined();
    expect(screen.getByText('4. Remote Connection')).toBeDefined();
    expect(screen.getByText('5. Persistent Volumes')).toBeDefined();
    expect(screen.getByText('6. Clean Up')).toBeDefined();
    expect(screen.queryByText(/ASR Models Configuration/)).toBeNull();
    expect(screen.queryByText(/Diarization Models Configuration/)).toBeNull();
  });

  it('shows the Tailscale hostname inside the Remote Connection card', async () => {
    setupRedesignAPI({ 'server.runtimeProfile': 'cpu' });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText('my-server.tail1234.ts.net')).toBeDefined();
    });
    expect(screen.getByText('Tailscale Hostname')).toBeDefined();
  });

  it('selecting the Metal runtime does NOT start the MLX server (deferred downloads)', async () => {
    const { setSpy, mlxStart } = setupRedesignAPI({ 'server.runtimeProfile': 'cpu' }, 'arm64');
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    fireEvent.click(screen.getByText('Metal').closest('button') as HTMLButtonElement);
    await waitFor(() => {
      expect(setSpy).toHaveBeenCalledWith('server.runtimeProfile', 'metal');
    });
    expect(mlxStart).not.toHaveBeenCalled();
  });

  it('leaving the Metal runtime still stops a running MLX server', async () => {
    const { setSpy, mlxStop } = setupRedesignAPI({ 'server.runtimeProfile': 'metal' }, 'arm64');
    ((window as any).electronAPI.mlx.getStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      'running',
    );
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    // Exact text match: the accessible-name regex would also hit the
    // "CUDA / CPU Only" image-variant tile.
    fireEvent.click(screen.getByText('CPU Only').closest('button') as HTMLButtonElement);
    await waitFor(() => {
      expect(setSpy).toHaveBeenCalledWith('server.runtimeProfile', 'cpu');
    });
    await waitFor(() => {
      expect(mlxStop).toHaveBeenCalled();
    });
  });

  it('switching runtimes resets a main model the new runtime cannot run', async () => {
    // A GGML main persisted under a Vulkan profile must not survive a switch
    // to CUDA — the redesign resets it to the runtime default (previously the
    // stale GGML pick leaked into a CUDA start).
    const { setSpy } = setupRedesignAPI({
      'server.runtimeProfile': 'vulkan',
      'server.mainModelSelection': 'ggml-large-v3-turbo.bin',
    });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    await waitFor(() => {
      expect(setSpy).toHaveBeenCalledWith('server.mainModelSelection', 'ggml-large-v3-turbo.bin');
    });
    // Exact text match: 'CUDA' only hits the runtime tile label ('CUDA / CPU
    // Only' and 'CUDA Legacy' are different full strings).
    fireEvent.click(screen.getByText('CUDA').closest('button') as HTMLButtonElement);
    await waitFor(() => {
      // Runtime default for gpu in the mocked world = MAIN_RECOMMENDED_MODEL.
      expect(setSpy).toHaveBeenCalledWith(
        'server.mainModelSelection',
        'openai/whisper-large-v3-turbo',
      );
    });
  });

  it('renames the runtime tiles and drops the Experimental tag from Vulkan Linux', async () => {
    setupRedesignAPI({ 'server.runtimeProfile': 'cpu' });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    // The vulkan runtime labels are identical to the image-variant tiles, so
    // scope queries to the Runtime SelectorGroup (.space-y-2 root).
    const runtimeGroup = within(screen.getByText('Runtime').closest('.space-y-2') as HTMLElement);
    for (const label of ['CUDA', 'Vulkan Windows', 'Vulkan Linux', 'Metal', 'CPU Only']) {
      expect(runtimeGroup.getByText(label).closest('button')).not.toBeNull();
    }
    expect(screen.queryByText('GPU (CUDA)')).toBeNull();
    expect(screen.queryByText('GPU (Vulkan Linux)')).toBeNull();
    // Only the Vulkan Windows tile keeps its Experimental hint (hints render
    // only on enabled tiles; both vulkan tiles are enabled on 'unknown' host).
    expect(screen.getAllByText('Experimental').length).toBe(1);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Docker image variant selector — the Image Variant tile row in the Docker
// Image card. Replaces the Legacy GPU toggle that used to live in Instance
// Settings: cuda ↔ cuda-legacy switching goes through the same confirmation
// dialog, the vulkan variants are implied by the Runtime selector, and
// per-version availability comes from the four GHCR tag lists (fail-open
// when the probe is unavailable).
// ─────────────────────────────────────────────────────────────────────────────

describe('Docker image variant selector', () => {
  function setupVariantAPI(configMap: Record<string, unknown>) {
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
        getArch: vi.fn().mockReturnValue('x64'),
        getConfigDir: vi.fn().mockResolvedValue('/mock/config'),
      },
      mlx: {
        getStatus: vi.fn().mockResolvedValue('stopped'),
        onStatusChanged: vi.fn().mockReturnValue(vi.fn()),
      },
      tailscale: {
        getHostname: vi.fn().mockResolvedValue('my-server.tail1234.ts.net'),
      },
      server: {
        checkFirewallPort: vi.fn().mockResolvedValue(null),
        checkGpu: vi.fn().mockResolvedValue({ gpu: false, toolkit: false, vulkan: false }),
      },
    };
    return { setSpy };
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockDocker.available = true;
    mockDocker.images = [];
    mockDocker.remoteTags = [];
    mockDocker.variantTags = null;
    mockDocker.container = { exists: false, running: false, status: 'unknown', health: undefined };
    mockDocker.operationError = null;
    mockDocker.operating = false;
    mockDocker.composeAvailable = true;
    mockAdminStatus.status = { models: {} };
  });

  it('renders the four variant tiles and drops the Legacy GPU toggle', async () => {
    setupVariantAPI({ 'server.runtimeProfile': 'gpu' });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    expect(screen.getByText('Image Variant')).toBeDefined();
    // The vulkan variant labels are identical to the renamed runtime tiles
    // ('Vulkan Windows', 'Vulkan Linux'), so scope queries to the Image
    // Variant SelectorGroup (its root is the .space-y-2 wrapper).
    const variantGroup = within(
      screen.getByText('Image Variant').closest('.space-y-2') as HTMLElement,
    );
    expect(variantGroup.getByText('CUDA / CPU Only').closest('button')).not.toBeNull();
    expect(variantGroup.getByText('CUDA Legacy').closest('button')).not.toBeNull();
    expect(variantGroup.getByText('Vulkan Windows').closest('button')).not.toBeNull();
    expect(variantGroup.getByText('Vulkan Linux').closest('button')).not.toBeNull();
    expect(screen.queryByText('Legacy GPU image')).toBeNull();
  });

  it('clicking CUDA Legacy on the CUDA runtime opens the variant confirmation dialog', async () => {
    setupVariantAPI({ 'server.runtimeProfile': 'gpu' });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    const legacyTile = screen.getByText('CUDA Legacy').closest('button') as HTMLButtonElement;
    // Enabled only after the persisted gpu profile hydrates (initial state is cpu).
    await waitFor(() => {
      expect(legacyTile.disabled).toBe(false);
    });
    fireEvent.click(legacyTile);
    expect(screen.getByText('Switch to the CUDA Legacy image?')).toBeDefined();
  });

  it('gates CUDA Legacy to the CUDA runtime', async () => {
    setupVariantAPI({ 'server.runtimeProfile': 'cpu' });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    const legacyTile = screen.getByText('CUDA Legacy').closest('button') as HTMLButtonElement;
    expect(legacyTile.disabled).toBe(true);
    expect(screen.getByText('Requires CUDA runtime')).toBeDefined();
  });

  it('blocks variant switching while a container exists (volume-wipe rule)', async () => {
    mockDocker.container = { exists: true, running: false, status: 'exited', health: undefined };
    setupVariantAPI({ 'server.runtimeProfile': 'gpu' });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    // Badge flips from the runtime reason to the container reason once the
    // persisted gpu profile hydrates.
    await waitFor(() => {
      expect(screen.getByText('Remove container to switch')).toBeDefined();
    });
    const legacyTile = screen.getByText('CUDA Legacy').closest('button') as HTMLButtonElement;
    expect(legacyTile.disabled).toBe(true);
  });

  it('shows "Not published" for variants missing the selected version tag', async () => {
    mockDocker.remoteTags = [{ tag: 'v1.3.7', created: null }];
    mockDocker.variantTags = {
      cuda: ['v1.3.7'],
      'cuda-legacy': [],
      'vulkan-wsl2': ['v1.3.7'],
      'vulkan-linux': [],
    };
    setupVariantAPI({ 'server.runtimeProfile': 'gpu' });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    // cuda-legacy and vulkan-linux lack v1.3.7 → "Not published" wins over
    // their runtime badges; vulkan-wsl2 has the tag → keeps its runtime badge.
    await waitFor(() => {
      expect(screen.getAllByText('Not published').length).toBe(2);
    });
    expect(screen.getByText('Requires Vulkan Windows runtime')).toBeDefined();
    expect(screen.queryByText('Requires Vulkan Linux runtime')).toBeNull();
  });

  it('fails open when the variant probe is unavailable (variantTags null)', async () => {
    mockDocker.remoteTags = [{ tag: 'v1.3.7', created: null }];
    mockDocker.variantTags = null;
    setupVariantAPI({ 'server.runtimeProfile': 'gpu' });
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    const legacyTile = screen.getByText('CUDA Legacy').closest('button') as HTMLButtonElement;
    await waitFor(() => {
      expect(legacyTile.disabled).toBe(false);
    });
    expect(screen.queryByText('Not published')).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Extra CA certificates picker (GH-200) — the Volumes card exposes a folder
// picker whose value dockerManager reads at container start and passes to
// compose as EXTRA_CA_CERTS_DIR (TLS-intercepting antivirus/proxy networks).
// ─────────────────────────────────────────────────────────────────────────────

describe('Extra CA certificates picker (GH-200)', () => {
  function setupCaApi(configMap: Record<string, unknown>) {
    const selectFolder = vi.fn().mockResolvedValue(null);
    (window as any).electronAPI = {
      config: {
        get: vi.fn().mockImplementation(async (key: string) => configMap[key]),
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
        start: vi.fn().mockResolvedValue(undefined),
        stop: vi.fn().mockResolvedValue(undefined),
      },
      tailscale: {
        getHostname: vi.fn().mockResolvedValue('my-server.tail1234.ts.net'),
      },
      server: {
        checkFirewallPort: vi.fn().mockResolvedValue(null),
        checkGpu: vi.fn().mockResolvedValue({ gpu: false, toolkit: false, vulkan: false }),
      },
      fileIO: { selectFolder },
    };
    return { selectFolder };
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockDocker.available = true;
    mockDocker.images = [];
    mockDocker.volumes = [];
    mockDocker.container = { exists: false, running: false, status: 'unknown', health: undefined };
    mockDocker.operationError = null;
    mockDocker.operating = false;
    mockDocker.composeAvailable = true;
    mockAdminStatus.status = { models: {} };
    // Restore the module-factory default after tests that override it.
    vi.mocked(getConfig).mockReset();
    vi.mocked(getConfig).mockResolvedValue(undefined);
  });

  it('persists a chosen folder and shows it in the Volumes card', async () => {
    const { selectFolder } = setupCaApi({ 'server.runtimeProfile': 'cpu' });
    selectFolder.mockResolvedValue('/home/me/.config/TranscriptionSuite/ca');

    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    expect(await screen.findByText('Extra CA certificates')).toBeDefined();

    fireEvent.click(screen.getByText('Choose folder').closest('button') as HTMLButtonElement);

    await waitFor(() => {
      expect(vi.mocked(setConfig)).toHaveBeenCalledWith(
        'server.extraCaCertsDir',
        '/home/me/.config/TranscriptionSuite/ca',
      );
    });
    expect(screen.getByText('/home/me/.config/TranscriptionSuite/ca')).toBeDefined();
    expect(screen.getByText('Change')).toBeDefined();
    expect(screen.queryByText('Choose folder')).toBeNull();
  });

  it('loads a saved folder on mount and clears it back to unset', async () => {
    setupCaApi({ 'server.runtimeProfile': 'cpu' });
    vi.mocked(getConfig).mockImplementation(async (key: string) =>
      key === 'server.extraCaCertsDir'
        ? 'C:\\Users\\me\\AppData\\Roaming\\TranscriptionSuite\\ca'
        : undefined,
    );

    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    expect(
      await screen.findByText('C:\\Users\\me\\AppData\\Roaming\\TranscriptionSuite\\ca'),
    ).toBeDefined();

    fireEvent.click(screen.getByText('Clear').closest('button') as HTMLButtonElement);

    await waitFor(() => {
      expect(vi.mocked(setConfig)).toHaveBeenCalledWith('server.extraCaCertsDir', '');
    });
    await waitFor(() => {
      expect(
        screen.queryByText('C:\\Users\\me\\AppData\\Roaming\\TranscriptionSuite\\ca'),
      ).toBeNull();
    });
    expect(screen.getByText('Choose folder')).toBeDefined();
  });

  it('does not render on the Metal (bare-metal) runtime', async () => {
    setupCaApi({ 'server.runtimeProfile': 'metal' });

    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    expect(await screen.findByText('5. Persistent Volumes')).toBeDefined();
    expect(screen.queryByText('Extra CA certificates')).toBeNull();
  });

  it('does not show the folder as configured when persisting fails', async () => {
    const { selectFolder } = setupCaApi({ 'server.runtimeProfile': 'cpu' });
    selectFolder.mockResolvedValue('/home/me/ca');
    vi.mocked(setConfig).mockRejectedValueOnce(new Error('disk full'));

    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    expect(await screen.findByText('Extra CA certificates')).toBeDefined();

    fireEvent.click(screen.getByText('Choose folder').closest('button') as HTMLButtonElement);

    await waitFor(() => {
      expect(vi.mocked(toast.error)).toHaveBeenCalled();
    });
    // Container start reads the store, not the UI, so the UI must not claim
    // a folder the store never received.
    expect(screen.queryByText('/home/me/ca')).toBeNull();
    expect(screen.getByText('Choose folder')).toBeDefined();
  });

  it('rejects a folder whose path contains a colon without persisting it', async () => {
    const { selectFolder } = setupCaApi({ 'server.runtimeProfile': 'cpu' });
    // Finder maps "/" typed in a folder name to ":" on disk; Docker cannot
    // mount such a path.
    selectFolder.mockResolvedValue('/home/me/Certs 06:2026');

    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    expect(await screen.findByText('Extra CA certificates')).toBeDefined();

    fireEvent.click(screen.getByText('Choose folder').closest('button') as HTMLButtonElement);

    await waitFor(() => {
      expect(vi.mocked(toast.error)).toHaveBeenCalled();
    });
    expect(vi.mocked(setConfig)).not.toHaveBeenCalledWith(
      'server.extraCaCertsDir',
      expect.anything(),
    );
    expect(screen.queryByText('/home/me/Certs 06:2026')).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// NVIDIA runtime gating — when checkGpu() reports an NVIDIA GPU, only the
// CUDA and CPU Only runtimes stay selectable; the Vulkan and Metal tiles are
// disabled with an 'NVIDIA detected' badge.
//
// MUST STAY AFTER EVERY DESCRIBE THAT OMITS docker.checkGpu: ServerView
// module-caches the checkGpu result (cachedGpuInfo), so the gpu:true probe
// below leaks into the initial state of every mount that follows it. Earlier
// describes never provide docker.checkGpu, which keeps the cache unset until
// this point. The multi-GPU describe below tolerates the leak by clicking
// Re-detect, which resets the cache and re-fetches from its own mock.
// ─────────────────────────────────────────────────────────────────────────────

describe('NVIDIA runtime gating', () => {
  function setupNvidiaAPI() {
    const setSpy = vi.fn().mockResolvedValue(undefined);
    (window as any).electronAPI = {
      config: {
        get: vi.fn().mockImplementation(async (key: string) => {
          if (key === 'server.runtimeProfile') return 'gpu';
          // Keep the one-shot hardware auto-detection from firing so the
          // persisted profile is what the tiles reflect.
          if (key === 'server.gpuAutoDetectDone') return true;
          return undefined;
        }),
        set: setSpy,
      },
      docker: {
        readComposeEnvValue: vi.fn().mockResolvedValue('false'),
        checkModelCache: vi.fn().mockResolvedValue({}),
        checkGpu: vi.fn().mockResolvedValue({ gpu: true, toolkit: true, vulkan: false }),
      },
      app: {
        getArch: vi.fn().mockReturnValue('x64'),
        getConfigDir: vi.fn().mockResolvedValue('/mock/config'),
      },
      mlx: {
        getStatus: vi.fn().mockResolvedValue('stopped'),
        onStatusChanged: vi.fn().mockReturnValue(vi.fn()),
      },
      tailscale: {
        getHostname: vi.fn().mockResolvedValue('my-server.tail1234.ts.net'),
      },
      server: {
        checkFirewallPort: vi.fn().mockResolvedValue(null),
      },
    };
    return { setSpy };
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockDocker.available = true;
    mockDocker.images = [];
    mockDocker.remoteTags = [];
    mockDocker.variantTags = null;
    mockDocker.container = { exists: false, running: false, status: 'unknown', health: undefined };
    mockDocker.operationError = null;
    mockDocker.operating = false;
    mockDocker.composeAvailable = true;
    mockAdminStatus.status = { models: {} };
  });

  it('disables the Vulkan and Metal runtimes when an NVIDIA GPU is detected', async () => {
    setupNvidiaAPI();
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    // Runtime labels collide with the image-variant tiles, so scope to the
    // Runtime SelectorGroup.
    const runtimeGroup = within(screen.getByText('Runtime').closest('.space-y-2') as HTMLElement);
    await waitFor(() => {
      expect(runtimeGroup.getAllByText('NVIDIA detected').length).toBe(3);
    });
    for (const label of ['Vulkan Windows', 'Vulkan Linux', 'Metal']) {
      const tile = runtimeGroup.getByText(label).closest('button') as HTMLButtonElement;
      expect(tile.disabled).toBe(true);
    }
    expect((runtimeGroup.getByText('CUDA').closest('button') as HTMLButtonElement).disabled).toBe(
      false,
    );
    expect(
      (runtimeGroup.getByText('CPU Only').closest('button') as HTMLButtonElement).disabled,
    ).toBe(false);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Multi-GPU picker + mixed-vendor gating.
//
// cachedGpuInfo leaks from the describes above, so every test here clicks the
// Re-detect link first: handleRedetectGpu clears the module cache and
// re-invokes docker.checkGpu, whose mock carries the per-test gpus inventory.
// ─────────────────────────────────────────────────────────────────────────────

describe('Multi-GPU selection', () => {
  type MockGpu = {
    vendor: 'nvidia' | 'amd' | 'intel' | 'unknown';
    kind: 'discrete' | 'integrated' | 'virtual' | 'unknown';
    index: number | null;
    name: string;
    memoryMiB: number | null;
    uuid: string | null;
  };

  const RTX_3060: MockGpu = {
    vendor: 'nvidia',
    kind: 'discrete',
    index: 0,
    name: 'NVIDIA GeForce RTX 3060',
    memoryMiB: 12288,
    uuid: 'GPU-aaa',
  };
  const RTX_3090: MockGpu = {
    vendor: 'nvidia',
    kind: 'discrete',
    index: 1,
    name: 'NVIDIA GeForce RTX 3090',
    memoryMiB: 24576,
    uuid: 'GPU-bbb',
  };
  const RX_6700: MockGpu = {
    vendor: 'amd',
    kind: 'discrete',
    index: null,
    name: 'AMD Radeon RX 6700 XT',
    memoryMiB: null,
    uuid: null,
  };
  const INTEL_IGPU: MockGpu = {
    vendor: 'intel',
    kind: 'integrated',
    index: null,
    name: 'Intel UHD Graphics 770',
    memoryMiB: null,
    uuid: null,
  };

  function setupApi(gpus: MockGpu[], opts?: { storedGpuDevice?: string }) {
    const setSpy = vi.fn().mockResolvedValue(undefined);
    (window as any).electronAPI = {
      config: {
        get: vi.fn().mockImplementation(async (key: string) => {
          if (key === 'server.runtimeProfile') return 'gpu';
          if (key === 'server.gpuAutoDetectDone') return true;
          if (key === 'server.gpuDevice') return opts?.storedGpuDevice ?? 'auto';
          return undefined;
        }),
        set: setSpy,
      },
      docker: {
        readComposeEnvValue: vi.fn().mockResolvedValue('false'),
        checkModelCache: vi.fn().mockResolvedValue({}),
        resetGpuCache: vi.fn().mockResolvedValue(undefined),
        checkGpu: vi.fn().mockResolvedValue({
          gpu: gpus.some((g) => g.vendor === 'nvidia'),
          toolkit: true,
          vulkan: false,
          gpus,
        }),
      },
      app: {
        getArch: vi.fn().mockReturnValue('x64'),
        getConfigDir: vi.fn().mockResolvedValue('/mock/config'),
      },
      mlx: {
        getStatus: vi.fn().mockResolvedValue('stopped'),
        onStatusChanged: vi.fn().mockReturnValue(vi.fn()),
      },
      tailscale: {
        getHostname: vi.fn().mockResolvedValue('my-server.tail1234.ts.net'),
      },
      server: {
        checkFirewallPort: vi.fn().mockResolvedValue(null),
      },
    };
    return { setSpy };
  }

  /** Mount, then force a re-detect so the per-test checkGpu payload replaces
   *  the module-level cache leaked by earlier describes. */
  async function mountAndRedetect() {
    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });
    const redetect = await screen.findByRole('button', { name: 'Re-detect' });
    fireEvent.click(redetect);
    await waitFor(() => {
      expect((window as any).electronAPI.docker.checkGpu).toHaveBeenCalled();
    });
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockDocker.available = true;
    mockDocker.images = [];
    mockDocker.remoteTags = [];
    mockDocker.variantTags = null;
    mockDocker.container = { exists: false, running: false, status: 'unknown', health: undefined };
    mockDocker.operationError = null;
    mockDocker.operating = false;
    mockDocker.composeAvailable = true;
    mockAdminStatus.status = { models: {} };
  });

  // The picker is a CustomSelect (headlessui Listbox). The mock above renders
  // its options inline and always open: the trigger is the button named by
  // aria-label, and each option is a role="option" wired to onChange.
  const pickerButton = () => screen.queryByRole('button', { name: 'GPU for inference' });

  it('shows the GPU picker with one option per NVIDIA card when two are detected', async () => {
    setupApi([RTX_3060, RTX_3090]);
    await mountAndRedetect();
    await waitFor(() => {
      expect(pickerButton()).not.toBeNull();
    });
    const labels = screen.getAllByRole('option').map((o) => o.textContent);
    expect(labels).toEqual([
      'Automatic (Docker default)',
      'GPU 0: NVIDIA GeForce RTX 3060 (12 GB)',
      'GPU 1: NVIDIA GeForce RTX 3090 (24 GB)',
    ]);
    expect(pickerButton()?.textContent).toContain('Automatic (Docker default)');
  });

  it('persists a picked card to server.gpuDevice as its UUID', async () => {
    const { setSpy } = setupApi([RTX_3060, RTX_3090]);
    await mountAndRedetect();
    await waitFor(() => {
      expect(pickerButton()).not.toBeNull();
    });
    fireEvent.click(screen.getByRole('option', { name: 'GPU 1: NVIDIA GeForce RTX 3090 (24 GB)' }));
    await waitFor(() => {
      expect(setSpy).toHaveBeenCalledWith('server.gpuDevice', 'GPU-bbb');
    });
    expect(pickerButton()?.textContent).toContain('GPU 1: NVIDIA GeForce RTX 3090 (24 GB)');
  });

  it('hydrates a persisted selection from server.gpuDevice', async () => {
    setupApi([RTX_3060, RTX_3090], { storedGpuDevice: 'GPU-bbb' });
    await mountAndRedetect();
    await waitFor(() => {
      expect(pickerButton()?.textContent).toContain('GPU 1: NVIDIA GeForce RTX 3090 (24 GB)');
    });
  });

  it('hides the picker when only one NVIDIA GPU is present', async () => {
    setupApi([RTX_3090]);
    await mountAndRedetect();
    await waitFor(() => {
      expect((window as any).electronAPI.docker.checkGpu).toHaveBeenCalled();
    });
    expect(pickerButton()).toBeNull();
  });

  it('keeps the Vulkan tiles selectable on a mixed NVIDIA + AMD host', async () => {
    setupApi([RTX_3090, RX_6700]);
    await mountAndRedetect();
    const runtimeGroup = within(screen.getByText('Runtime').closest('.space-y-2') as HTMLElement);
    // Only the Metal tile still carries the NVIDIA badge; the Vulkan tiles are
    // free so inference can be routed to the AMD card.
    await waitFor(() => {
      expect(runtimeGroup.getAllByText('NVIDIA detected').length).toBe(1);
    });
    const vulkanLinux = runtimeGroup
      .getByText('Vulkan Linux')
      .closest('button') as HTMLButtonElement;
    expect(vulkanLinux.disabled).toBe(false);
    const metal = runtimeGroup.getByText('Metal').closest('button') as HTMLButtonElement;
    expect(metal.disabled).toBe(true);
    // Mixed-vendor hint under the CUDA runtime.
    expect(screen.getByText(/CUDA uses only NVIDIA cards/)).toBeTruthy();
  });

  it('does not show the picker on an NVIDIA-only single-GPU host with an AMD card present', async () => {
    setupApi([RTX_3090, RX_6700]);
    await mountAndRedetect();
    // The AMD card must not count toward the NVIDIA picker threshold.
    await waitFor(() => {
      expect(screen.getByText(/CUDA uses only NVIDIA cards/)).toBeTruthy();
    });
    expect(pickerButton()).toBeNull();
  });

  it('keeps the Vulkan lockout when the only extra GPU is an integrated one', async () => {
    setupApi([RTX_3090, INTEL_IGPU]);
    await mountAndRedetect();
    const runtimeGroup = within(screen.getByText('Runtime').closest('.space-y-2') as HTMLElement);
    // iGPUs and virtual adapters must not read as a routable second card:
    // both Vulkan tiles and Metal keep the NVIDIA badge.
    await waitFor(() => {
      expect(runtimeGroup.getAllByText('NVIDIA detected').length).toBe(3);
    });
    const vulkanLinux = runtimeGroup
      .getByText('Vulkan Linux')
      .closest('button') as HTMLButtonElement;
    expect(vulkanLinux.disabled).toBe(true);
    expect(screen.queryByText(/CUDA uses only NVIDIA cards/)).toBeNull();
  });

  it('surfaces a stale pin as an explicit option instead of silently claiming Automatic', async () => {
    setupApi([RTX_3060, RTX_3090], { storedGpuDevice: 'GPU-gone' });
    await mountAndRedetect();
    await waitFor(() => {
      expect(pickerButton()?.textContent).toContain(
        'Previously selected GPU not detected - starts as Automatic',
      );
    });
    expect(
      screen.getByRole('option', {
        name: 'Previously selected GPU not detected - starts as Automatic',
      }),
    ).toBeTruthy();
  });
});
