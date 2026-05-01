/**
 * P2-VIEW-002 — NotebookView calendar interaction
 *
 * Tests that NotebookView renders correctly with empty and populated
 * recordings, and that the calendar sub-tab is rendered by default.
 *
 * All hooks and sub-components are mocked to isolate rendering logic.
 */

import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
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
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
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

// ── GH #92: drop audio files directly onto a Notebook hour row ─────────────

describe('[GH #92] NotebookView per-hour drag-and-drop', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
    (window as any).electronAPI = {
      config: {
        get: vi.fn().mockResolvedValue(undefined),
        set: vi.fn().mockResolvedValue(undefined),
      },
    };
  });

  function buildAudioFile(name = 'note.mp3'): File {
    return new File([new Uint8Array([0])], name, { type: 'audio/mpeg' });
  }

  function buildTextFile(name = 'unrelated.txt'): File {
    return new File([new Uint8Array([0])], name, { type: 'text/plain' });
  }

  /** Build a synthetic dataTransfer.files FileList containing the given files. */
  function buildFileList(files: File[]): FileList {
    const list = {
      length: files.length,
      item: (i: number) => files[i] ?? null,
      [Symbol.iterator]: function* () {
        for (const f of files) yield f;
      },
    } as unknown as FileList;
    files.forEach((f, i) => {
      (list as unknown as Record<number, File>)[i] = f;
    });
    return list;
  }

  /** Find an hour row by its time label (e.g. "10:00"). */
  function findHourRow(label: string): HTMLElement {
    const span = Array.from(document.querySelectorAll('span')).find((s) => s.textContent === label);
    if (!span) throw new Error(`Hour label ${label} not found in NotebookView`);
    // The hour row is the closest ancestor with the per-hour drag handlers.
    // The label sits inside the sticky-left column which is a direct child of
    // the row div; one parentElement up gets us to the row.
    const stickyCol = span.parentElement;
    if (!stickyCol) throw new Error('hour label has no parent');
    const row = stickyCol.parentElement;
    if (!row) throw new Error('sticky column has no row parent');
    return row as HTMLElement;
  }

  it('opens AddNoteModal preloaded with files when audio is dropped on an hour row', async () => {
    render(React.createElement(NotebookView, { activeTab: NotebookTab.CALENDAR }), {
      wrapper: createWrapper(),
    });

    const row = findHourRow('10:00');
    const file = buildAudioFile('lecture.mp3');

    await act(async () => {
      fireEvent.drop(row, {
        dataTransfer: { files: buildFileList([file]) },
      });
      await Promise.resolve();
    });

    // Modal renders into document.body via createPortal. Header text is
    // unique to the New Audio Note modal.
    expect(screen.getByText('New Audio Note')).toBeDefined();
    // The dropped file appears in the selected files list.
    expect(screen.getByText('lecture.mp3')).toBeDefined();
  });

  it('filters mixed drops down to audio files only', async () => {
    render(React.createElement(NotebookView, { activeTab: NotebookTab.CALENDAR }), {
      wrapper: createWrapper(),
    });

    const row = findHourRow('14:00');
    const audio1 = buildAudioFile('a.mp3');
    const audio2 = buildAudioFile('b.wav');
    const text = buildTextFile();

    await act(async () => {
      fireEvent.drop(row, {
        dataTransfer: { files: buildFileList([audio1, text, audio2]) },
      });
      await Promise.resolve();
    });

    expect(screen.getByText('New Audio Note')).toBeDefined();
    expect(screen.getByText('a.mp3')).toBeDefined();
    expect(screen.getByText('b.wav')).toBeDefined();
    expect(screen.queryByText('unrelated.txt')).toBeNull();
  });

  it('does not open the modal when only non-audio files are dropped', async () => {
    render(React.createElement(NotebookView, { activeTab: NotebookTab.CALENDAR }), {
      wrapper: createWrapper(),
    });

    const row = findHourRow('11:00');
    const text = buildTextFile();

    await act(async () => {
      fireEvent.drop(row, {
        dataTransfer: { files: buildFileList([text]) },
      });
      await Promise.resolve();
    });

    expect(screen.queryByText('New Audio Note')).toBeNull();
  });
});
