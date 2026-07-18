/**
 * SessionImportTab — explicit output-format selector (GH-212)
 *
 * The output format for Session imports used to be inferred from the global
 * hideTimestamps setting, while the UI copy falsely claimed the Speaker
 * Diarization toggle controlled it. These tests pin the decoupled design:
 *
 *   1. The "Output Format" select is always visible — even when the
 *      diarization switch is OFF.
 *   2. Selecting "Plain text (.txt)" hides the "Subtitle format" select;
 *      selecting "Both" shows it.
 *   3. A pending job stamped with plannedFormat renders `Queued (<format>)`.
 *   4. The info note no longer claims diarization controls the format.
 */

import React from 'react';
import { render, fireEvent, act, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const WHISPER_MODEL = 'openai/whisper-large-v3-turbo';

// ── Hoisted mock state ────────────────────────────────────────────────────

const mockGetConfig = vi.fn();
const mockSetConfig = vi.fn();
const mockAddFiles = vi.fn();

interface MockJob {
  id: string;
  file: File | string;
  type: string;
  status: string;
  plannedFormat?: string;
}

let mockJobs: MockJob[] = [];

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
      models: { features: { diarization: { available: true, reason: 'ready' } } },
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
    useImportQueueStore: (selector?: (s: Record<string, unknown>) => unknown) => {
      const state = { ...fakeState, jobs: mockJobs };
      return typeof selector === 'function' ? selector(state) : state;
    },
    // Reads the mutable module-level jobs so tests can vary the queue.
    selectSessionJobs: () => mockJobs,
    selectPendingCount: () => mockJobs.filter((j) => j.status === 'pending').length,
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
  setConfig: (...args: unknown[]) => {
    mockSetConfig(...args);
    return Promise.resolve(undefined);
  },
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

// headlessui — the Output Format / Subtitle format controls are CustomSelect
// (a Listbox). Same render-prop mock convention as ServerView.test.tsx, plus:
//   * ListboxButton forwards aria-label so getByRole('button', { name }) works.
//   * ListboxOption is a role="option" that wires its click to the Listbox's
//     onChange (via context), so selecting an option drives the component.
vi.mock('@headlessui/react', () => {
  const renderChildren = (
    children: React.ReactNode | ((args: any) => React.ReactNode),
    args: Record<string, unknown> = {},
  ): React.ReactNode =>
    typeof children === 'function' ? (children as (a: any) => React.ReactNode)(args) : children;
  const passthrough = ({ children }: { children?: React.ReactNode }) =>
    React.createElement('div', null, renderChildren(children));
  const OnChangeCtx = React.createContext<(value: unknown) => void>(() => {});
  return {
    Listbox: ({
      children,
      value,
      onChange,
    }: {
      children: React.ReactNode;
      value: unknown;
      onChange: (value: unknown) => void;
    }) =>
      React.createElement(
        OnChangeCtx.Provider,
        { value: onChange },
        React.createElement(
          'div',
          { 'data-value': value },
          renderChildren(children, { open: true }),
        ),
      ),
    ListboxButton: ({
      children,
      ['aria-label']: ariaLabel,
    }: {
      children: React.ReactNode;
      'aria-label'?: string;
    }) =>
      React.createElement(
        'button',
        { type: 'button', 'aria-label': ariaLabel },
        renderChildren(children, { open: true, focus: false, hover: false }),
      ),
    ListboxOptions: passthrough,
    ListboxOption: ({ children, value }: { children: React.ReactNode; value: unknown }) => {
      const onChange = React.useContext(OnChangeCtx);
      return React.createElement(
        'div',
        { role: 'option', 'data-value': value, onClick: () => onChange(value) },
        renderChildren(children, { selected: false, focus: false, active: false }),
      );
    },
  };
});

import { SessionImportTab } from '../views/SessionImportTab';

async function renderTab() {
  const result = render(React.createElement(SessionImportTab));
  // Wait for mount-time getConfig promises to resolve.
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  return result;
}

function outputFormatButton(): HTMLElement {
  return screen.getByRole('button', { name: /output format/i });
}

function querySubtitleFormatButton(): HTMLElement | null {
  return screen.queryByRole('button', { name: /subtitle format/i });
}

// Open the CustomSelect (mock renders options inline) and click the option
// whose visible label matches `optionName`.
async function pickOutputFormat(optionName: string): Promise<void> {
  await act(async () => {
    fireEvent.click(outputFormatButton());
  });
  await act(async () => {
    fireEvent.click(screen.getByRole('option', { name: optionName }));
  });
}

describe('SessionImportTab — explicit output-format selector (GH-212)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetConfig.mockReset();
    mockSetConfig.mockReset();
    mockAddFiles.mockReset();
    mockJobs = [];

    // Default: no persisted config keys.
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

  it('shows the Output Format select even when the diarization switch is OFF', async () => {
    await renderTab();

    const diarizationSwitch = screen.getByRole('switch', { name: /speaker diarization/i });
    expect(diarizationSwitch).toHaveAttribute('aria-checked', 'true');

    await act(async () => {
      fireEvent.click(diarizationSwitch);
    });

    expect(diarizationSwitch).toHaveAttribute('aria-checked', 'false');
    expect(outputFormatButton()).toBeInTheDocument();
  });

  it('hides the Subtitle format select for Plain text and shows it for Both', async () => {
    await renderTab();

    // Default 'subtitles' → the subtitle-flavor select is visible.
    expect(querySubtitleFormatButton()).not.toBeNull();

    await pickOutputFormat('Plain text (.txt)');
    expect(querySubtitleFormatButton()).toBeNull();

    await pickOutputFormat('Both');
    expect(querySubtitleFormatButton()).not.toBeNull();
  });

  it('persists the selection under sessionImport.outputFormat', async () => {
    await renderTab();

    await pickOutputFormat('Plain text (.txt)');

    expect(mockSetConfig).toHaveBeenCalledWith('sessionImport.outputFormat', 'txt');
  });

  it('renders Queued (<format>) on a pending job stamped with plannedFormat', async () => {
    mockJobs = [
      {
        id: 'job-1',
        file: new File([new Uint8Array([0])], 'memo.m4a', { type: 'audio/mp4' }),
        type: 'session-normal',
        status: 'pending',
        plannedFormat: '.srt',
      },
    ];

    await renderTab();

    expect(screen.getByText('Queued (.srt)')).toBeInTheDocument();
  });

  it('no longer claims diarization controls the output format', async () => {
    const { container } = await renderTab();

    expect(container.textContent).not.toContain('when diarization is enabled');
  });
});
