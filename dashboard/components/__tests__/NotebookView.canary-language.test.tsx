/**
 * NotebookView ImportTab — Canary language plumbing (gh-102 followup #2)
 *
 * Verifies the inline ImportTab inside NotebookView (lines 1302–1480) honors
 * the persisted `session.mainLanguage` (and translation-target keys when
 * Canary bidi is active). Mirrors the SessionImportTab pattern shipped in
 * gh-102-followup-1 and the parallel AddNoteModal coverage:
 *
 *   1. Canary + Source Language = Spanish, drop file → addFiles called with
 *      options.language="es".
 *   2. Canary + Auto Detect (or empty/unresolvable), drop file → addFiles NOT
 *      called; toast.error shown with the same wording the live-recording /
 *      session-import guard uses ("Source language required").
 *   3. Canary + bidi translation active (English source, target = French),
 *      drop file → addFiles called with language="en", translation_enabled=true,
 *      translation_target_language="fr".
 *   4. Whisper + Auto Detect → addFiles called with options.language=undefined
 *      (regression check on the auto-detect happy path).
 *   5. Languages still loading when user drops a file (Canary active) →
 *      refuse-with-toast using "loading languages — please try again in a
 *      moment." wording.
 */

import React from 'react';
import { render, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const CANARY_MODEL = 'nvidia/canary-1b-v2';
const WHISPER_MODEL = 'openai/whisper-large-v3-turbo';

// ── Hoisted mock state ────────────────────────────────────────────────────

interface MockLanguageSet {
  languages: Array<{ code: string; name: string }>;
  loading: boolean;
  backendType: string;
}

let mockActiveModel: string | null = CANARY_MODEL;

let mockLanguageSet: MockLanguageSet = {
  languages: [{ code: 'auto', name: 'Auto Detect' }],
  loading: true,
  backendType: 'canary',
};

const mockToastError = vi.fn();
const mockToastSuccess = vi.fn();
const mockGetConfig = vi.fn();
const mockAddFiles = vi.fn();

// ── Mocks (mirror NotebookView.test.tsx isolation pattern) ────────────────

vi.mock('../../src/hooks/useCalendar', () => ({
  useCalendar: () => ({
    days: {},
    totalRecordings: 0,
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock('../../src/hooks/useSearch', () => ({
  useSearch: () => ({
    results: [],
    count: 0,
    loading: false,
    error: null,
    search: vi.fn(),
  }),
}));

vi.mock('../../src/hooks/useLanguages', () => ({
  useLanguages: () => ({
    languages: mockLanguageSet.languages,
    backendType: mockLanguageSet.backendType,
    loading: mockLanguageSet.loading,
    error: null,
  }),
}));

vi.mock('../../src/hooks/useAdminStatus', () => ({
  useAdminStatus: () => ({
    status: {
      models_loaded: true,
      config: {
        main_transcriber: { model: mockActiveModel },
        transcription: { model: mockActiveModel },
        diarization: { parallel: false },
      },
    },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock('../../src/hooks/useNotebookWatcher', () => ({
  useNotebookWatcher: () => ({
    notebookWatchPath: '',
    notebookWatchActive: false,
    notebookWatchAccessible: true,
    setNotebookWatchPath: vi.fn(),
    setWatchPath: vi.fn(),
    setNotebookWatchActive: vi.fn(),
    toggleNotebookWatch: vi.fn(),
  }),
}));

vi.mock('../../src/stores/importQueueStore', () => {
  const fakeState: Record<string, unknown> = {
    jobs: [],
    isPaused: false,
    notebookCallbacks: {},
    notebookWatchPath: '',
    notebookWatchActive: false,
    sessionWatchPath: '',
    watcherServerConnected: true,
    watchLog: [],
    avgProcessingMs: 0,
    addFiles: (...args: unknown[]) => mockAddFiles(...args),
    removeJob: vi.fn(),
    retryJob: vi.fn(),
    clearFinished: vi.fn(),
    pauseQueue: vi.fn(),
    resumeQueue: vi.fn(),
    updateNotebookCallbacks: vi.fn(),
    updateNotebookConfig: vi.fn(),
    setLanguagesCache: vi.fn(),
    clearWatchLog: vi.fn(),
  };
  return {
    useImportQueueStore: (selector?: (s: Record<string, unknown>) => unknown) =>
      typeof selector === 'function' ? selector(fakeState) : fakeState,
    selectNotebookJobs: () => [],
    selectPendingCount: () => 0,
    selectCompletedCount: () => 0,
    selectErrorCount: () => 0,
    selectIsProcessing: () => false,
  };
});

vi.mock('../../src/api/client', () => ({
  apiClient: {
    getCalendar: vi.fn().mockResolvedValue({ days: {}, total_recordings: 0 }),
    getAdminStatus: vi.fn().mockResolvedValue({ config: { diarization: { parallel: false } } }),
    search: vi.fn().mockResolvedValue({ results: [], count: 0 }),
    updateRecordingTitle: vi.fn(),
    deleteRecording: vi.fn(),
    getExportUrl: vi.fn().mockReturnValue('http://localhost:9786/api/notebook/recordings/1/export'),
  },
}));

vi.mock('../../src/config/store', () => ({
  getConfig: (...args: unknown[]) => mockGetConfig(...args),
  setConfig: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../../src/utils/transcriptionBackend', () => ({
  supportsExplicitWordTimestampToggle: () => true,
}));

vi.mock('../../src/services/modelCapabilities', async () => {
  const actual = await vi.importActual<typeof import('../../src/services/modelCapabilities')>(
    '../../src/services/modelCapabilities',
  );
  return actual;
});

vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

vi.mock('../../src/hooks/useConfirm', () => ({
  useConfirm: () => ({
    confirm: vi.fn().mockResolvedValue(true),
    dialog: null,
  }),
}));

vi.mock('zustand/react/shallow', () => ({
  useShallow: (selector: unknown) => selector,
}));

// ── Import after mocks ────────────────────────────────────────────────────

import { NotebookView } from '../views/NotebookView';
import { NotebookTab } from '../../types';

// ── Helpers ────────────────────────────────────────────────────────────────

const NEMO_LANGUAGES_FOR_TEST: Array<{ code: string; name: string }> = [
  { code: 'auto', name: 'Auto Detect' },
  { code: 'en', name: 'English' },
  { code: 'es', name: 'Spanish' },
  { code: 'fr', name: 'French' },
  { code: 'de', name: 'German' },
];

const WHISPER_LANGUAGES_FOR_TEST: Array<{ code: string; name: string }> = [
  { code: 'auto', name: 'Auto Detect' },
  { code: 'en', name: 'English' },
  { code: 'es', name: 'Spanish' },
];

function buildFile(name = 'sample.mp3'): File {
  return new File([new Uint8Array([0])], name, { type: 'audio/mpeg' });
}

function dropFile(file: File): { dataTransfer: { files: FileList } } {
  const list = {
    0: file,
    length: 1,
    item: (i: number) => (i === 0 ? file : null),
    [Symbol.iterator]: function* () {
      yield file;
    },
  } as unknown as FileList;
  return { dataTransfer: { files: list } };
}

function createWrapper(): ({ children }: { children: React.ReactNode }) => React.ReactElement {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }) =>
    React.createElement(QueryClientProvider, { client: qc }, children) as React.ReactElement;
}

/** Find the ImportTab dropzone — the cursor-pointer div with the upload icon. */
function findDropZone(container: HTMLElement): Element {
  // ImportTab's dropzone has the same cursor-pointer + border-dashed shape as
  // SessionImportTab's. Filter for "Drag & Drop Audio Files" heading nearby
  // to disambiguate from the watch-folder drag area (which also has cursor
  // styling on its inner buttons).
  const candidates = Array.from(container.querySelectorAll<HTMLElement>('.cursor-pointer'));
  const dropZone = candidates.find((el) => /drag.*drop/i.test(el.textContent ?? ''));
  if (!dropZone) throw new Error('ImportTab dropzone not found');
  return dropZone;
}

describe('NotebookView ImportTab — Canary language plumbing (gh-102 followup #2)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockToastError.mockReset();
    mockToastSuccess.mockReset();
    mockAddFiles.mockReset();
    mockGetConfig.mockReset();
    mockGetConfig.mockResolvedValue(undefined);

    mockActiveModel = CANARY_MODEL;
    mockLanguageSet = {
      languages: NEMO_LANGUAGES_FOR_TEST,
      loading: false,
      backendType: 'canary',
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as unknown as { electronAPI?: any }).electronAPI = {
      fileIO: {
        getDownloadsPath: vi.fn().mockResolvedValue('/tmp'),
        selectFolder: vi.fn().mockResolvedValue(null),
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    };
  });

  it('Canary + Spanish persisted: drop enqueues with options.language="es"', async () => {
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'Spanish';
      return undefined;
    });

    const { container } = render(
      React.createElement(NotebookView, { activeTab: NotebookTab.IMPORT }),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const dropZone = findDropZone(container);
    await act(async () => {
      fireEvent.drop(dropZone, dropFile(buildFile()));
    });

    expect(mockToastError).not.toHaveBeenCalled();
    expect(mockAddFiles).toHaveBeenCalledTimes(1);
    const [, , options] = mockAddFiles.mock.calls[0] as [unknown, unknown, Record<string, unknown>];
    expect(options.language).toBe('es');
    expect(options.translation_enabled).toBeUndefined();
    expect(options.translation_target_language).toBeUndefined();
  });

  it('Canary + Auto Detect: drop refuses with toast.error and does not enqueue', async () => {
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'Auto Detect';
      return undefined;
    });

    const { container } = render(
      React.createElement(NotebookView, { activeTab: NotebookTab.IMPORT }),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const dropZone = findDropZone(container);
    await act(async () => {
      fireEvent.drop(dropZone, dropFile(buildFile()));
    });

    expect(mockAddFiles).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledTimes(1);
    const [title, opts] = mockToastError.mock.calls[0] as [string, { description?: string }];
    // Strict equality enforces the spec's "wording-grep parity" Always:
    // invariant — any future copy drift between NotebookView.ImportTab,
    // AddNoteModal, and SessionImportTab.handleFiles will fail tests
    // instead of silently succeeding.
    expect(title).toBe('Source language required');
    expect(opts?.description).toBe(
      '"Auto Detect" is not a valid source language for the active model. Pick a language from the Source Language dropdown.',
    );
  });

  it('Canary + bidi (English source, French target): drop enqueues with translation fields', async () => {
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'English';
      if (key === 'session.mainBidiTarget') return 'French';
      return undefined;
    });

    const { container } = render(
      React.createElement(NotebookView, { activeTab: NotebookTab.IMPORT }),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const dropZone = findDropZone(container);
    await act(async () => {
      fireEvent.drop(dropZone, dropFile(buildFile()));
    });

    expect(mockToastError).not.toHaveBeenCalled();
    expect(mockAddFiles).toHaveBeenCalledTimes(1);
    const [, , options] = mockAddFiles.mock.calls[0] as [unknown, unknown, Record<string, unknown>];
    expect(options.language).toBe('en');
    expect(options.translation_enabled).toBe(true);
    expect(options.translation_target_language).toBe('fr');
  });

  it('Whisper + Auto Detect: drop enqueues with options.language=undefined (regression check)', async () => {
    mockActiveModel = WHISPER_MODEL;
    mockLanguageSet = {
      languages: WHISPER_LANGUAGES_FOR_TEST,
      loading: false,
      backendType: 'whisper',
    };
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'Auto Detect';
      return undefined;
    });

    const { container } = render(
      React.createElement(NotebookView, { activeTab: NotebookTab.IMPORT }),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const dropZone = findDropZone(container);
    await act(async () => {
      fireEvent.drop(dropZone, dropFile(buildFile()));
    });

    expect(mockToastError).not.toHaveBeenCalled();
    expect(mockAddFiles).toHaveBeenCalledTimes(1);
    const [, , options] = mockAddFiles.mock.calls[0] as [unknown, unknown, Record<string, unknown>];
    expect(options.language).toBeUndefined();
    expect(options.translation_enabled).toBeUndefined();
    expect(options.translation_target_language).toBeUndefined();
  });

  it('Canary + languages still loading: drop refuses with "loading languages" wording', async () => {
    mockLanguageSet = {
      languages: [{ code: 'auto', name: 'Auto Detect' }],
      loading: true,
      backendType: 'canary',
    };
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'Spanish';
      return undefined;
    });

    const { container } = render(
      React.createElement(NotebookView, { activeTab: NotebookTab.IMPORT }),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const dropZone = findDropZone(container);
    await act(async () => {
      fireEvent.drop(dropZone, dropFile(buildFile()));
    });

    expect(mockAddFiles).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledTimes(1);
    const [title, opts] = mockToastError.mock.calls[0] as [string, { description?: string }];
    // Strict equality enforces wording-grep parity for the loading branch
    // tail ("please try again in a moment.") — see comment in the
    // Auto-Detect refuse case above.
    expect(title).toBe('Source language required');
    expect(opts?.description).toBe('Loading languages — please try again in a moment.');
  });
});
