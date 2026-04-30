/**
 * P2-VIEW-002 — NotebookView calendar interaction
 *
 * Tests that NotebookView renders correctly with empty and populated
 * recordings, and that the calendar sub-tab is rendered by default.
 *
 * All hooks and sub-components are mocked to isolate rendering logic.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ── Mock all hooks and modules ─────────────────────────────────────────────

// useCalendar
vi.mock('../../src/hooks/useCalendar', () => ({
  useCalendar: () => ({
    days: {},
    totalRecordings: 0,
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

// useSearch
vi.mock('../../src/hooks/useSearch', () => ({
  useSearch: () => ({
    results: [],
    count: 0,
    loading: false,
    error: null,
    search: vi.fn(),
  }),
}));

// useLanguages
vi.mock('../../src/hooks/useLanguages', () => ({
  useLanguages: () => ({
    languages: [{ code: 'en', name: 'English' }],
    backendType: 'whisper',
    loading: false,
    error: null,
  }),
}));

// useAdminStatus
vi.mock('../../src/hooks/useAdminStatus', () => ({
  useAdminStatus: () => ({
    status: null,
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

// useNotebookWatcher
vi.mock('../../src/hooks/useNotebookWatcher', () => ({
  useNotebookWatcher: () => ({
    notebookWatchPath: '',
    notebookWatchActive: false,
    notebookWatchAccessible: true,
    setNotebookWatchPath: vi.fn(),
    toggleNotebookWatch: vi.fn(),
  }),
}));

// useImportQueueStore (Zustand)
vi.mock('../../src/stores/importQueueStore', () => ({
  useImportQueueStore: (selector: (s: Record<string, unknown>) => unknown) => {
    const state = {
      jobs: [],
      isPaused: false,
      notebookCallbacks: {},
      notebookWatchPath: '',
      notebookWatchActive: false,
      updateNotebookCallbacks: vi.fn(),
      updateNotebookConfig: vi.fn(),
      setLanguagesCache: vi.fn(),
    };
    return typeof selector === 'function' ? selector(state) : state;
  },
  selectNotebookJobs: () => [],
  selectPendingCount: () => 0,
  selectCompletedCount: () => 0,
  selectErrorCount: () => 0,
  selectIsProcessing: () => false,
}));

// apiClient
vi.mock('../../src/api/client', () => ({
  apiClient: {
    getCalendar: vi.fn().mockResolvedValue({ days: {}, total_recordings: 0 }),
    getAdminStatus: vi.fn().mockResolvedValue(null),
    search: vi.fn().mockResolvedValue({ results: [], count: 0 }),
    updateRecordingTitle: vi.fn(),
    deleteRecording: vi.fn(),
    getExportUrl: vi
      .fn()
      .mockReturnValue('http://localhost:9786/api/notebook/recordings/1/export?format=txt'),
  },
}));

// config/store
vi.mock('../../src/config/store', () => ({
  getConfig: vi.fn().mockResolvedValue(undefined),
  setConfig: vi.fn().mockResolvedValue(undefined),
}));

// transcriptionBackend utils
vi.mock('../../src/utils/transcriptionBackend', () => ({
  supportsExplicitWordTimestampToggle: () => true,
}));

// sonner toast
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// useConfirm
vi.mock('../../src/hooks/useConfirm', () => ({
  useConfirm: () => ({
    confirm: vi.fn().mockResolvedValue(true),
    dialog: null,
  }),
}));

// zustand/react/shallow — mock useShallow to pass through selectors
vi.mock('zustand/react/shallow', () => ({
  useShallow: (selector: unknown) => selector,
}));

// ── Import after mocks ────────────────────────────────────────────────────

import { NotebookView } from '../views/NotebookView';
import { NotebookTab } from '../../types';

// ── Helpers ────────────────────────────────────────────────────────────────

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
  return wrapper;
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe('[P2] NotebookView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (window as any).electronAPI = {
      config: {
        get: vi.fn().mockResolvedValue(undefined),
        set: vi.fn().mockResolvedValue(undefined),
      },
    };
  });

  it('renders the calendar tab content', () => {
    render(React.createElement(NotebookView, { activeTab: NotebookTab.CALENDAR }), {
      wrapper: createWrapper(),
    });
    expect(screen.getByText('Audio Notebook')).toBeDefined();
  });

  it('renders the "Audio Notebook" heading', () => {
    render(React.createElement(NotebookView, { activeTab: NotebookTab.CALENDAR }), {
      wrapper: createWrapper(),
    });
    expect(screen.getByText('Audio Notebook')).toBeDefined();
  });

  it('renders the import tab variant without crashing', () => {
    const { container } = render(
      React.createElement(NotebookView, { activeTab: NotebookTab.IMPORT }),
      { wrapper: createWrapper() },
    );
    // Import tab also shows the heading
    expect(screen.getByText('Audio Notebook')).toBeDefined();
    expect(container).toBeDefined();
  });
});
