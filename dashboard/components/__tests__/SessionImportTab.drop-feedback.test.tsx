/**
 * SessionImportTab immediate drop feedback (GH-210)
 *
 * The manual-drop path used to enqueue silently while the Folder-Watch
 * auto-detect path already fired a toast (importQueueStore.ts). These tests
 * pin the new feedback surface:
 *
 *   1. Single-file drop → toast.success naming the file + polite aria-live
 *      announcement.
 *   2. Multi-file drop → count toast ("3 files added ...").
 *   3. A new job appearing in the queue scrolls the Import Queue card into
 *      view (job-id diff, not list length).
 *   4. The dropzone gets the brief `dropzone-flash` class after an add.
 *   5. The language-guard refusal path (no enqueue) shows NO success toast.
 */

import React from 'react';
import { render, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';

const WHISPER_MODEL = 'openai/whisper-large-v3-turbo';
const CANARY_MODEL = 'nvidia/canary-1b-v2';

// ── Hoisted mock state ────────────────────────────────────────────────────

interface MockLanguageSet {
  languages: Array<{ code: string; name: string }>;
  loading: boolean;
  backendType: string;
}

let mockActiveModel: string | null = WHISPER_MODEL;

let mockLanguageSet: MockLanguageSet = {
  languages: [
    { code: 'auto', name: 'Auto Detect' },
    { code: 'en', name: 'English' },
  ],
  loading: false,
  backendType: 'whisper',
};

// Mutable so the scroll test can change the queue contents between renders.
let mockJobs: Array<Record<string, unknown>> = [];

const mockToastSuccess = vi.fn();
const mockToastError = vi.fn();
const mockGetConfig = vi.fn();
const mockAddFiles = vi.fn();

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
      },
    },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock('../../src/hooks/useSessionWatcher', () => ({
  useSessionWatcher: () => ({
    sessionWatchPath: '',
    sessionWatchActive: false,
    setSessionWatchActive: vi.fn(),
    setWatchPath: vi.fn(),
    sessionWatchAccessible: true,
  }),
}));

vi.mock('../../src/stores/importQueueStore', () => {
  const fakeState: Record<string, unknown> = {
    jobs: [],
    isPaused: false,
    sessionConfig: {
      outputDir: '',
      diarizedFormat: 'srt',
      outputFormat: 'subtitles',
      hideTimestamps: false,
      enableDiarization: true,
      enableWordTimestamps: true,
      parallelDiarization: false,
      multitrack: false,
    },
    sessionWatchPath: '',
    sessionWatchActive: false,
    notebookWatchPath: '',
    notebookWatchActive: false,
    watcherServerConnected: true,
    watchLog: [],
    avgProcessingMs: 0,
    addFiles: (...args: unknown[]) => mockAddFiles(...args),
    removeJob: vi.fn(),
    retryJob: vi.fn(),
    clearFinished: vi.fn(),
    pauseQueue: vi.fn(),
    resumeQueue: vi.fn(),
    updateSessionConfig: vi.fn(),
    setLanguagesCache: vi.fn(),
    clearWatchLog: vi.fn(),
  };
  return {
    useImportQueueStore: (selector?: (s: Record<string, unknown>) => unknown) =>
      typeof selector === 'function' ? selector(fakeState) : fakeState,
    selectSessionJobs: () => mockJobs,
    selectPendingCount: () => 0,
    selectCompletedCount: () => 0,
    selectErrorCount: () => 0,
    selectIsProcessing: () => false,
  };
});

vi.mock('../../src/api/client', () => ({
  apiClient: {
    getAdminStatus: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock('../../src/config/store', () => ({
  getConfig: (...args: unknown[]) => mockGetConfig(...args),
  setConfig: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../../src/utils/transcriptionBackend', () => ({
  supportsExplicitWordTimestampToggle: () => true,
}));

// Real modelCapabilities so the auto-detect / Canary guard behaves end-to-end.
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

import { SessionImportTab } from '../views/SessionImportTab';
import { useAriaAnnouncerStore } from '../../src/stores/ariaAnnouncerStore';

function buildFile(name = 'sample.mp3'): File {
  return new File([new Uint8Array([0])], name, { type: 'audio/mpeg' });
}

function dropFiles(files: File[]): { dataTransfer: { files: FileList } } {
  // Construct a FileList-like object since jsdom doesn't expose a constructor.
  const list = {
    length: files.length,
    item: (i: number) => files[i] ?? null,
    [Symbol.iterator]: function* () {
      yield* files;
    },
  } as unknown as FileList;
  files.forEach((f, i) => {
    (list as unknown as Record<number, File>)[i] = f;
  });
  return { dataTransfer: { files: list } };
}

async function renderAndSettle() {
  const utils = render(React.createElement(SessionImportTab));
  // Wait for mount-time getConfig promises to resolve.
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  return utils;
}

describe('SessionImportTab drop feedback (GH-210)', () => {
  beforeAll(() => {
    // jsdom has no scrollIntoView; run rAF callbacks synchronously.
    Element.prototype.scrollIntoView = vi.fn();
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0);
      return 0;
    });
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mockToastSuccess.mockReset();
    mockToastError.mockReset();
    mockAddFiles.mockReset();
    mockGetConfig.mockReset();
    mockGetConfig.mockResolvedValue(undefined);

    mockActiveModel = WHISPER_MODEL;
    mockLanguageSet = {
      languages: [
        { code: 'auto', name: 'Auto Detect' },
        { code: 'en', name: 'English' },
      ],
      loading: false,
      backendType: 'whisper',
    };
    mockJobs = [];

    useAriaAnnouncerStore.setState({ politeMessage: '', assertiveMessage: '' });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as unknown as { electronAPI?: any }).electronAPI = {
      fileIO: {
        getDownloadsPath: vi.fn().mockResolvedValue('/tmp'),
        selectFolder: vi.fn().mockResolvedValue(null),
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    };
  });

  it('shows a success toast naming the file and announces politely on a single-file drop', async () => {
    const { container } = await renderAndSettle();

    const dropZone = container.querySelector('.cursor-pointer');
    expect(dropZone).toBeTruthy();

    await act(async () => {
      fireEvent.drop(dropZone as Element, dropFiles([buildFile('lecture.mp3')]));
    });

    expect(mockAddFiles).toHaveBeenCalledTimes(1);
    expect(mockToastSuccess).toHaveBeenCalledTimes(1);
    expect(String(mockToastSuccess.mock.calls[0][0])).toMatch(/lecture\.mp3/);
    expect(useAriaAnnouncerStore.getState().politeMessage).toMatch(/lecture\.mp3/);
  });

  it('shows a count toast on a multi-file drop', async () => {
    const { container } = await renderAndSettle();

    const dropZone = container.querySelector('.cursor-pointer');
    await act(async () => {
      fireEvent.drop(
        dropZone as Element,
        dropFiles([buildFile('a.mp3'), buildFile('b.mp3'), buildFile('c.mp3')]),
      );
    });

    expect(mockToastSuccess).toHaveBeenCalledTimes(1);
    expect(String(mockToastSuccess.mock.calls[0][0])).toMatch(/3 files added/i);
    expect(useAriaAnnouncerStore.getState().politeMessage).toMatch(/3 files/i);
  });

  it('scrolls the import queue into view when a new job appears', async () => {
    const { rerender } = await renderAndSettle();

    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();

    mockJobs = [
      {
        id: 'session-normal-1',
        file: buildFile('lecture.mp3'),
        type: 'session-normal',
        status: 'pending',
      },
    ];
    await act(async () => {
      rerender(React.createElement(SessionImportTab));
    });

    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it('flashes the dropzone after files are added', async () => {
    const { container } = await renderAndSettle();

    expect(container.querySelector('.dropzone-flash')).toBeNull();

    const dropZone = container.querySelector('.cursor-pointer');
    await act(async () => {
      fireEvent.drop(dropZone as Element, dropFiles([buildFile()]));
    });

    expect(container.querySelector('.dropzone-flash')).toBeTruthy();
  });

  it('shows no success toast when the language guard refuses the drop', async () => {
    // Canary with an unresolvable picker (Auto Detect) refuses the drop.
    mockActiveModel = CANARY_MODEL;
    mockLanguageSet = {
      languages: [
        { code: 'auto', name: 'Auto Detect' },
        { code: 'en', name: 'English' },
      ],
      loading: false,
      backendType: 'canary',
    };
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'Auto Detect';
      return undefined;
    });

    const { container } = await renderAndSettle();

    const dropZone = container.querySelector('.cursor-pointer');
    await act(async () => {
      fireEvent.drop(dropZone as Element, dropFiles([buildFile()]));
    });

    expect(mockAddFiles).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledTimes(1);
    expect(mockToastSuccess).not.toHaveBeenCalled();
    expect(useAriaAnnouncerStore.getState().politeMessage).toBe('');
  });
});
