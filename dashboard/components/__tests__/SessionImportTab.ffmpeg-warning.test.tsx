/**
 * SessionImportTab ffmpeg-missing warning (GH-255)
 *
 * The native mac-metal server host may have no ffmpeg installed, which makes
 * every non-WAV import fail with a decode error. The server now reports
 * ffmpeg_available on /api/status; SessionView passes it down and the Import
 * tab must warn up front instead of letting the user drop an m4a and get a
 * misleading "corrupt file" failure. These tests pin the banner contract:
 *
 *   1. ffmpegAvailable={false} → amber warning naming FFmpeg + the brew fix.
 *   2. ffmpegAvailable={true} → no warning.
 *   3. prop absent (older servers without the field) → no warning; the
 *      absence of evidence must never render as a scare banner.
 */

import React from 'react';
import { render, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';

const WHISPER_MODEL = 'openai/whisper-large-v3-turbo';

const mockGetConfig = vi.fn();

vi.mock('../../src/hooks/useLanguages', () => ({
  useLanguages: () => ({
    languages: [
      { code: 'auto', name: 'Auto Detect' },
      { code: 'en', name: 'English' },
    ],
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
        main_transcriber: { model: WHISPER_MODEL },
        transcription: { model: WHISPER_MODEL },
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
    addFiles: vi.fn(),
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

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { SessionImportTab } from '../views/SessionImportTab';

async function renderAndSettle(props?: { ffmpegAvailable?: boolean }) {
  const utils = render(React.createElement(SessionImportTab, props));
  // Wait for mount-time getConfig promises to resolve.
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  return utils;
}

describe('SessionImportTab ffmpeg-missing warning (GH-255)', () => {
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
    mockGetConfig.mockReset();
    mockGetConfig.mockResolvedValue(undefined);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as unknown as { electronAPI?: any }).electronAPI = {
      fileIO: {
        getDownloadsPath: vi.fn().mockResolvedValue('/tmp'),
        selectFolder: vi.fn().mockResolvedValue(null),
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    };
  });

  it('shows the amber warning with the brew fix when the server reports ffmpeg missing', async () => {
    const { getByText } = await renderAndSettle({ ffmpegAvailable: false });

    expect(getByText(/FFmpeg is not installed on the server host/)).toBeTruthy();
    expect(getByText(/brew install ffmpeg/)).toBeTruthy();
    expect(getByText(/only WAV files can be imported/)).toBeTruthy();
  });

  it('shows no warning when the server reports ffmpeg available', async () => {
    const { queryByText } = await renderAndSettle({ ffmpegAvailable: true });

    expect(queryByText(/brew install ffmpeg/)).toBeNull();
  });

  it('shows no warning when the server does not report the field (older servers)', async () => {
    const { queryByText } = await renderAndSettle();

    expect(queryByText(/brew install ffmpeg/)).toBeNull();
  });
});
