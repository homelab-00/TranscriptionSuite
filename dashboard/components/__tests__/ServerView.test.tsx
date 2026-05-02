/**
 * P2-VIEW-003 — ServerView connection status display
 *
 * Tests that ServerView renders correctly and displays the expected
 * heading and container status text for different Docker states.
 *
 * All hooks and heavy sub-components are mocked.
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
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

// modelCapabilities
vi.mock('../../src/services/modelCapabilities', () => ({
  isWhisperModel: () => true,
  isMLXModel: () => false,
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
  MAIN_MODEL_PRESETS: ['openai/whisper-large-v3-turbo'],
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
// Issue #86 #2 — Pyannote diarization gate on Mac Metal
//
// Background: pyannote.audio 4.x has no working MPS path
// (pyannote/pyannote-audio#1886 / #1337 / #1091 — all closed wontfix).
// On Mac Metal, the dashboard must hide the Pyannote dropdown option,
// auto-migrate any persisted Pyannote selection to Sortformer, render
// an inline reason, and warn beside the Custom HF-repo input when its
// value matches a pyannote pattern.
//
// Note on the mid-session profile-toggle row from the spec I/O matrix:
// the migration useEffect's dependency array includes `isMetal`, so it
// fires on any false→true transition of `isMetal`. Testing the mount-time
// case with `runtimeProfile === 'metal'` therefore exercises the same
// code path as a mid-session toggle from cpu→metal.
// ─────────────────────────────────────────────────────────────────────────────

describe('Pyannote diarization gate on Mac Metal', () => {
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

  it('on Mac Metal with persisted Pyannote, migrates selection to Sortformer and persists it exactly once', async () => {
    const setSpy = setupElectronAPI({
      'server.runtimeProfile': 'metal',
      'server.diarizationModelSelection': PYANNOTE,
      'server.diarizationCustomModel': '',
    });

    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(setSpy).toHaveBeenCalledWith('server.diarizationModelSelection', SORTFORMER);
    });
    // Persistence flows through the existing auto-persist effect — assert that
    // the SORTFORMER write happens exactly once (the explicit set in the migration
    // effect was removed as redundant after the edge-case-hunter review).
    const sortformerWrites = setSpy.mock.calls.filter(
      ([k, v]) => k === 'server.diarizationModelSelection' && v === SORTFORMER,
    );
    expect(sortformerWrites.length).toBe(1);
  });

  it('on Mac Metal, removes Pyannote from the dropdown DOM and renders the inline reason', async () => {
    setupElectronAPI({
      'server.runtimeProfile': 'metal',
      'server.diarizationModelSelection': SORTFORMER,
      'server.diarizationCustomModel': '',
    });

    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.queryByText(/pyannote.audio MPS path/i)).toBeTruthy();
    });
    // The pyannote model option must NOT appear anywhere (dropdown filtered, not selected).
    expect(screen.queryAllByText(PYANNOTE).length).toBe(0);
    // Sortformer is selected → appears in both ListboxButton and ListboxOption (>=1 match).
    expect(screen.queryAllByText(SORTFORMER).length).toBeGreaterThanOrEqual(1);
    // Custom is an available option (not selected) → appears in dropdown.
    expect(screen.queryAllByText(CUSTOM).length).toBeGreaterThanOrEqual(1);
  });

  it('on non-Metal profile (cpu), does NOT migrate Pyannote and keeps all three options', async () => {
    const setSpy = setupElectronAPI({
      'server.runtimeProfile': 'cpu',
      'server.diarizationModelSelection': PYANNOTE,
      'server.diarizationCustomModel': '',
    });

    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });

    // Pyannote is selected → appears in both ListboxButton AND ListboxOption.
    await waitFor(() => {
      expect(screen.queryAllByText(PYANNOTE).length).toBeGreaterThanOrEqual(1);
    });
    // Migration must NOT have fired — `set` was never called with Sortformer for diarization.
    const sortformerSet = setSpy.mock.calls.some(
      ([k, v]) => k === 'server.diarizationModelSelection' && v === SORTFORMER,
    );
    expect(sortformerSet).toBe(false);
    // Inline reason must NOT be visible on non-Metal.
    expect(screen.queryByText(/pyannote.audio MPS path/i)).toBeNull();
    // All three options remain in the dropdown DOM.
    expect(screen.queryAllByText(SORTFORMER).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryAllByText(CUSTOM).length).toBeGreaterThanOrEqual(1);
  });

  it('on Mac Metal with Custom selection and pyannote-prefixed value, shows the amber warning', async () => {
    setupElectronAPI({
      'server.runtimeProfile': 'metal',
      'server.diarizationModelSelection': CUSTOM,
      'server.diarizationCustomModel': 'pyannote/some-fork',
    });

    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(
        screen.queryByText(/Custom pyannote repos are not supported on Apple Silicon/i),
      ).toBeTruthy();
    });
  });

  it('on Mac Metal with Custom selection and a non-pyannote value, does NOT show the warning', async () => {
    setupElectronAPI({
      'server.runtimeProfile': 'metal',
      'server.diarizationModelSelection': CUSTOM,
      'server.diarizationCustomModel': 'nvidia/sortformer-fork',
    });

    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });

    // Wait for hydration to settle by asserting the inline reason renders (it always does on Metal).
    await waitFor(() => {
      expect(screen.queryByText(/pyannote\.audio MPS path/i)).toBeTruthy();
    });
    // The custom-input warning must NOT appear for a non-pyannote value.
    expect(
      screen.queryByText(/Custom pyannote repos are not supported on Apple Silicon/i),
    ).toBeNull();
  });

  it('on Mac Metal with Custom + whitespace-prefixed pyannote value, still shows the warning', async () => {
    // Edge-case-hunter finding #2: `activeDiarizationModel` at ServerView.tsx:815-819
    // calls `.trim()` before sending to the server, so a leading-whitespace pyannote
    // value would otherwise bypass the gate while still reaching the broken backend.
    setupElectronAPI({
      'server.runtimeProfile': 'metal',
      'server.diarizationModelSelection': CUSTOM,
      'server.diarizationCustomModel': '  pyannote/community  ',
    });

    render(React.createElement(ServerView, baseProps), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(
        screen.queryByText(/Custom pyannote repos are not supported on Apple Silicon/i),
      ).toBeTruthy();
    });
  });
});
