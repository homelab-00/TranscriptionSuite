/**
 * SessionImportTab — diarization feature gating (GH-209)
 *
 * The server computes models.features.diarization = {available, reason} once
 * at startup and exposes it via /api/admin/status. Before GH-209 the Speaker
 * Diarization toggle defaulted to ON with zero awareness of that flag, so a
 * server without a HuggingFace token silently skipped diarization on every
 * job. These tests verify:
 *
 *   1. Feature available → switch enabled, ON by default, payload carries
 *      enable_diarization: true.
 *   2. Feature unavailable (token_missing) → switch disabled + OFF, the
 *      "no HuggingFace token" explanation renders, payload is forced to
 *      enable_diarization: false.
 *   3. Admin status not loaded yet (feature undefined) → switch stays usable
 *      (no false lockout while polling).
 *   4. A completed job that requested diarization but could not perform it
 *      shows "diarization skipped: no HF token" on its queue row.
 */

import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const WHISPER_MODEL = 'openai/whisper-large-v3-turbo';

// ── Hoisted mock state ────────────────────────────────────────────────────

let mockDiarizationFeature: { available: boolean; reason: string } | undefined = {
  available: true,
  reason: 'ready',
};

let mockJobs: Array<Record<string, unknown>> = [];

const mockToastError = vi.fn();
const mockGetConfig = vi.fn();
const mockAddFiles = vi.fn();

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
      status: 'running',
      models: { features: { diarization: mockDiarizationFeature } },
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
    setLanguagesCache: vi.fn(),
    clearWatchLog: vi.fn(),
  };
  return {
    useImportQueueStore: (selector?: (s: Record<string, unknown>) => unknown) => {
      const state = { ...fakeState, jobs: mockJobs };
      return typeof selector === 'function' ? selector(state) : state;
    },
    selectSessionJobs: (s: { jobs: unknown[] }) => s.jobs,
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
    error: (...args: unknown[]) => mockToastError(...args),
    warning: vi.fn(),
  },
}));

import { SessionImportTab } from '../views/SessionImportTab';

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

async function flushMountEffects(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('SessionImportTab diarization gating (GH-209)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockToastError.mockReset();
    mockAddFiles.mockReset();
    mockGetConfig.mockReset();
    mockGetConfig.mockResolvedValue(undefined);
    mockJobs = [];
    mockDiarizationFeature = { available: true, reason: 'ready' };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as unknown as { electronAPI?: any }).electronAPI = {
      fileIO: {
        getDownloadsPath: vi.fn().mockResolvedValue('/tmp'),
        selectFolder: vi.fn().mockResolvedValue(null),
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    };
  });

  it('renders the Speaker Diarization switch enabled and ON when the feature is available', async () => {
    mockDiarizationFeature = { available: true, reason: 'ready' };
    const { container } = render(React.createElement(SessionImportTab));
    await flushMountEffects();

    const toggle = screen.getByRole('switch', { name: /speaker diarization/i });
    expect(toggle).not.toBeDisabled();
    expect(toggle).toHaveAttribute('aria-checked', 'true');

    const dropZone = container.querySelector('.cursor-pointer');
    await act(async () => {
      fireEvent.drop(dropZone as Element, dropFile(buildFile()));
    });
    expect(mockAddFiles).toHaveBeenCalledWith(
      expect.anything(),
      'session-normal',
      expect.objectContaining({ enable_diarization: true }),
    );
  });

  it('renders the switch disabled and OFF when reason=token_missing, and sends enable_diarization: false', async () => {
    mockDiarizationFeature = { available: false, reason: 'token_missing' };
    const { container } = render(React.createElement(SessionImportTab));
    await flushMountEffects();

    const toggle = screen.getByRole('switch', { name: /speaker diarization/i });
    expect(toggle).toBeDisabled();
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByText(/no huggingface token/i)).toBeInTheDocument();

    const dropZone = container.querySelector('.cursor-pointer');
    await act(async () => {
      fireEvent.drop(dropZone as Element, dropFile(buildFile()));
    });
    expect(mockAddFiles).toHaveBeenCalledWith(
      expect.anything(),
      'session-normal',
      expect.objectContaining({ enable_diarization: false }),
    );
  });

  it('leaves the switch usable while admin status has not loaded yet (feature undefined)', async () => {
    mockDiarizationFeature = undefined;
    render(React.createElement(SessionImportTab));
    await flushMountEffects();

    const toggle = screen.getByRole('switch', { name: /speaker diarization/i });
    expect(toggle).not.toBeDisabled();
  });

  it('labels a completed job whose diarization was requested but skipped', async () => {
    mockJobs = [
      {
        id: 'session-normal-1',
        file: buildFile('meeting.mp3'),
        type: 'session-normal',
        status: 'success',
        outputFilename: 'meeting.srt',
        outputPath: '/tmp/meeting.srt',
        diarizationOutcome: { requested: true, performed: false, reason: 'token_missing' },
      },
    ];
    render(React.createElement(SessionImportTab));
    await flushMountEffects();

    expect(screen.getByText(/diarization skipped: no HF token/i)).toBeInTheDocument();
  });
});
