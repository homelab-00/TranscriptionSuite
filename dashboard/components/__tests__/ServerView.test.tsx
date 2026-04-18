/**
 * P2-VIEW-003 — ServerView connection status display
 *
 * Tests that ServerView renders correctly and displays the expected
 * heading and container status text for different Docker states.
 *
 * All hooks and heavy sub-components are mocked.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
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

// headlessui — mock all components used across ServerView and its children
vi.mock('@headlessui/react', () => {
  const passthrough = ({ children }: { children?: React.ReactNode }) =>
    React.createElement('div', null, children);
  return {
    Dialog: ({ children, open }: { children: React.ReactNode; open: boolean }) =>
      open ? React.createElement('div', { role: 'dialog' }, children) : null,
    DialogPanel: passthrough,
    DialogTitle: ({ children }: { children: React.ReactNode }) =>
      React.createElement('h2', null, children),
    Listbox: ({ children, value }: { children: React.ReactNode; value: unknown }) =>
      React.createElement('div', { 'data-value': value }, children),
    ListboxButton: passthrough,
    ListboxOptions: passthrough,
    ListboxOption: ({ children, value }: { children: React.ReactNode; value: unknown }) =>
      React.createElement('div', { 'data-value': value }, children),
  };
});

// Runtime type guard
vi.mock('../../src/types/runtime', () => ({
  isRuntimeProfile: (v: unknown) => ['gpu', 'cpu', 'vulkan', 'metal'].includes(v as string),
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
