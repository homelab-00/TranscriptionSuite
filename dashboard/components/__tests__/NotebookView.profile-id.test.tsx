/**
 * NotebookView ImportTab — profile_id forwarding (Issue #104, Sprint 4 deferred-work no. 2).
 *
 * Without this wiring, manual notebook uploads omit `profile_id`, the backend
 * persists `profile_snapshot=None` on the transcription job, and the auto-
 * action coordinator short-circuits as a no-op. Two cases:
 *
 *   1. Active profile id is set (e.g. 7) → addFiles receives `profile_id: 7`.
 *   2. Active profile id is null → addFiles receives `profile_id: undefined`
 *      (NOT null, NOT '7', NOT '') so apiClient.uploadAndTranscribe's `!= null`
 *      guard correctly omits the FormData field.
 */

import React from 'react';
import { render, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ── Hoisted state controlled per-test ─────────────────────────────────────

let mockActiveProfileId: number | null = null;
const mockAddFiles = vi.fn();
const mockGetConfig = vi.fn();

const TEST_LANGUAGES: Array<{ code: string; name: string }> = [
  { code: 'auto', name: 'Auto Detect' },
  { code: 'en', name: 'English' },
];

// ── Mocks (mirror NotebookView.canary-language.test.tsx isolation pattern) ─

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
  useSearch: () => ({ results: [], count: 0, loading: false, error: null, search: vi.fn() }),
}));

vi.mock('../../src/hooks/useLanguages', () => ({
  useLanguages: () => ({
    languages: TEST_LANGUAGES,
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
        main_transcriber: { model: 'openai/whisper-large-v3-turbo' },
        transcription: { model: 'openai/whisper-large-v3-turbo' },
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

vi.mock('../../src/stores/activeProfileStore', () => ({
  useActiveProfileStore: (
    selector?: (s: { activeProfileId: number | null; hydrated: boolean }) => unknown,
  ) => {
    const state = { activeProfileId: mockActiveProfileId, hydrated: true };
    return typeof selector === 'function' ? selector(state) : state;
  },
}));

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
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

vi.mock('../../src/hooks/useConfirm', () => ({
  useConfirm: () => ({ confirm: vi.fn().mockResolvedValue(true), dialog: null }),
}));

vi.mock('zustand/react/shallow', () => ({
  useShallow: (selector: unknown) => selector,
}));

// ── Import after mocks ────────────────────────────────────────────────────

import { NotebookView } from '../views/NotebookView';
import { NotebookTab } from '../../types';

// ── Helpers ────────────────────────────────────────────────────────────────

function buildFile(): File {
  return new File([new Uint8Array([0])], 'sample.mp3', { type: 'audio/mpeg' });
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

function findDropZone(container: HTMLElement): Element {
  const candidates = Array.from(container.querySelectorAll<HTMLElement>('.cursor-pointer'));
  const dropZone = candidates.find((el) => /drag.*drop/i.test(el.textContent ?? ''));
  if (!dropZone) throw new Error('ImportTab dropzone not found');
  return dropZone;
}

describe('NotebookView ImportTab — profile_id forwarding (Sprint 4 deferred-work no. 2)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAddFiles.mockReset();
    mockGetConfig.mockReset();
    mockGetConfig.mockResolvedValue(undefined);
    mockActiveProfileId = null;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as unknown as { electronAPI?: any }).electronAPI = {
      fileIO: {
        getDownloadsPath: vi.fn().mockResolvedValue('/tmp'),
        selectFolder: vi.fn().mockResolvedValue(null),
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    };
  });

  it('forwards activeProfileId to addFiles options when a profile is selected', async () => {
    mockActiveProfileId = 7;

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

    expect(mockAddFiles).toHaveBeenCalledTimes(1);
    const [, , options] = mockAddFiles.mock.calls[0] as [unknown, unknown, Record<string, unknown>];
    expect(options.profile_id).toBe(7);
  });

  it('forwards undefined (NOT null) when no profile is selected', async () => {
    mockActiveProfileId = null;

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

    expect(mockAddFiles).toHaveBeenCalledTimes(1);
    const [, , options] = mockAddFiles.mock.calls[0] as [unknown, unknown, Record<string, unknown>];
    // The `?? undefined` coalesce is what guarantees apiClient.uploadAndTranscribe's
    // `options?.profile_id != null` guard correctly skips the FormData append.
    expect(options.profile_id).toBeUndefined();
    expect(options.profile_id).not.toBeNull();
  });
});
