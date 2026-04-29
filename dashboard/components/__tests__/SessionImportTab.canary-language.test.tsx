/**
 * SessionImportTab — Canary language plumbing (gh-102 followup, issue 102 reopened)
 *
 * Verifies the file-import surface honors the persisted `session.mainLanguage`
 * (and translation-target keys when Canary bidi is active). Mirrors the
 * live-recording guard pattern at SessionView.handleStartRecording (gh-102):
 *
 *   1. Canary + Source Language = Spanish, drop file → addFiles called with
 *      options.language="es".
 *   2. Canary + Auto Detect (or empty/unresolvable), drop file → addFiles NOT
 *      called; toast.error shown with the same wording the live-recording
 *      guard uses ("Source language required").
 *   3. Canary + bidi translation active (English source, target = French),
 *      drop file → addFiles called with language="en",
 *      translation_enabled=true, translation_target_language="fr".
 *   4. Whisper + Auto Detect → addFiles called with options.language=undefined
 *      (regression check on the auto-detect happy path).
 *   5. Languages still loading when user drops a file (Canary active) →
 *      refuse-with-toast using "loading languages — please try again in a
 *      moment." wording (mirrors handleStartRecording's loading branch).
 */

import React from 'react';
import { render, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const CANARY_MODEL = 'nvidia/canary-1b-v2';
const WHISPER_MODEL = 'openai/whisper-large-v3-turbo';

// ── Hoisted mock state ────────────────────────────────────────────────────
//
// Tests flip the language list, the active model, and the persisted config
// per-case. Mocks read from module-level mutable state and tests reset it in
// beforeEach.

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
    clearWatchLog: vi.fn(),
  };
  return {
    useImportQueueStore: (selector?: (s: Record<string, unknown>) => unknown) =>
      typeof selector === 'function' ? selector(fakeState) : fakeState,
    selectSessionJobs: () => [],
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

// Real modelCapabilities — we want the real `supportsAutoDetect`,
// `isCanaryModel`, and `supportsTranslation` so the picker→code resolution
// is end-to-end.
vi.mock('../../src/services/modelCapabilities', async () => {
  const actual = await vi.importActual<typeof import('../../src/services/modelCapabilities')>(
    '../../src/services/modelCapabilities',
  );
  return actual;
});

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

import { SessionImportTab } from '../views/SessionImportTab';

// NEMO Canary language list (canary-1b-v2 supports 25 EU languages).
const NEMO_LANGUAGES_FOR_TEST: Array<{ code: string; name: string }> = [
  { code: 'auto', name: 'Auto Detect' }, // synthetic prepend; filter drops for canary
  { code: 'en', name: 'English' },
  { code: 'es', name: 'Spanish' },
  { code: 'fr', name: 'French' },
  { code: 'de', name: 'German' },
];

// Whisper auto-detect-capable list.
const WHISPER_LANGUAGES_FOR_TEST: Array<{ code: string; name: string }> = [
  { code: 'auto', name: 'Auto Detect' },
  { code: 'en', name: 'English' },
  { code: 'es', name: 'Spanish' },
];

function buildFile(name = 'sample.mp3'): File {
  return new File([new Uint8Array([0])], name, { type: 'audio/mpeg' });
}

function dropFile(file: File): { dataTransfer: { files: FileList } } {
  // Construct a FileList-like object since jsdom doesn't expose a constructor.
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

describe('SessionImportTab — Canary language plumbing (gh-102 followup)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockToastError.mockReset();
    mockAddFiles.mockReset();
    mockGetConfig.mockReset();

    // Default: no persisted config keys.
    mockGetConfig.mockResolvedValue(undefined);

    mockActiveModel = CANARY_MODEL;
    mockLanguageSet = {
      languages: NEMO_LANGUAGES_FOR_TEST,
      loading: false,
      backendType: 'canary',
    };

    // jsdom electronAPI shim — SessionImportTab reads downloadsPath on mount.
    // The fileIO surface is wider than what we exercise here, so use `any`
    // (with eslint-disable) instead of the full IpcFileIO type.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as unknown as { electronAPI?: any }).electronAPI = {
      fileIO: {
        getDownloadsPath: vi.fn().mockResolvedValue('/tmp'),
        selectFolder: vi.fn().mockResolvedValue(null),
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    };
  });

  it('Canary + Spanish persisted: drop file enqueues with options.language="es"', async () => {
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'Spanish';
      return undefined;
    });

    const { container } = render(React.createElement(SessionImportTab));

    // Wait for mount-time getConfig promises to resolve.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const dropZone = container.querySelector('.cursor-pointer');
    expect(dropZone).toBeTruthy();

    await act(async () => {
      fireEvent.drop(dropZone as Element, dropFile(buildFile()));
    });

    expect(mockToastError).not.toHaveBeenCalled();
    expect(mockAddFiles).toHaveBeenCalledTimes(1);
    const [, , options] = mockAddFiles.mock.calls[0] as [unknown, unknown, Record<string, unknown>];
    expect(options.language).toBe('es');
    // Whisper-like translation fields must NOT be present on a non-translation
    // path — only emit them for Canary bidi.
    expect(options.translation_enabled).toBeUndefined();
    expect(options.translation_target_language).toBeUndefined();
  });

  it('Canary + Auto Detect: drop refuses with toast.error and does not enqueue', async () => {
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'Auto Detect';
      return undefined;
    });

    const { container } = render(React.createElement(SessionImportTab));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const dropZone = container.querySelector('.cursor-pointer');
    await act(async () => {
      fireEvent.drop(dropZone as Element, dropFile(buildFile()));
    });

    expect(mockAddFiles).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledTimes(1);
    const [title, opts] = mockToastError.mock.calls[0] as [string, { description?: string }];
    expect(title).toMatch(/source language required/i);
    expect(String(opts?.description ?? '')).toMatch(
      /not a valid source language|no source language/i,
    );
  });

  it('Canary + bidi (English source, French target): drop enqueues with translation fields', async () => {
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'English';
      if (key === 'session.mainBidiTarget') return 'French';
      // mainTranslate is irrelevant when bidi is active (Canary path uses
      // mainBidiTarget !== 'Off' as the activation signal — same shape
      // SessionView.handleStartRecording produces).
      return undefined;
    });

    const { container } = render(React.createElement(SessionImportTab));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const dropZone = container.querySelector('.cursor-pointer');
    await act(async () => {
      fireEvent.drop(dropZone as Element, dropFile(buildFile()));
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

    const { container } = render(React.createElement(SessionImportTab));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const dropZone = container.querySelector('.cursor-pointer');
    await act(async () => {
      fireEvent.drop(dropZone as Element, dropFile(buildFile()));
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

    const { container } = render(React.createElement(SessionImportTab));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const dropZone = container.querySelector('.cursor-pointer');
    await act(async () => {
      fireEvent.drop(dropZone as Element, dropFile(buildFile()));
    });

    expect(mockAddFiles).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledTimes(1);
    const [title, opts] = mockToastError.mock.calls[0] as [string, { description?: string }];
    expect(title).toMatch(/source language required/i);
    expect(String(opts?.description ?? '')).toMatch(/loading languages/i);
  });
});
