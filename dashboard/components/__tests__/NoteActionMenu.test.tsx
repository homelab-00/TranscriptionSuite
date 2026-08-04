/**
 * NoteActionMenu — Diarize + Export Markdown wiring (GH-279).
 *
 * The calendar-card context menu must:
 *   1. Offer an enabled Diarize item for a non-diarized note WITH word
 *      timestamps, and clicking it must start the retro-diarize job and
 *      close the menu.
 *   2. Disable Diarize (with an explanatory title tooltip) when the note has
 *      no word-level timestamps (wordCount === 0).
 *   3. Hide Diarize entirely once the note is diarized.
 *   4. Offer Export Markdown wired to getExportUrl(id, 'md').
 */

import React from 'react';
import { render, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Mocks (mirror NotebookView.test.tsx — the module graph is shared) ──────

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
    languages: [{ code: 'en', name: 'English' }],
    backendType: 'whisper',
    loading: false,
    error: null,
  }),
}));

vi.mock('../../src/hooks/useAdminStatus', () => ({
  useAdminStatus: () => ({ status: null, loading: false, error: null, refresh: vi.fn() }),
}));

vi.mock('../../src/hooks/useNotebookWatcher', () => ({
  useNotebookWatcher: () => ({
    notebookWatchPath: '',
    notebookWatchActive: false,
    notebookWatchAccessible: true,
    setNotebookWatchPath: vi.fn(),
    toggleNotebookWatch: vi.fn(),
  }),
}));

vi.mock('../../src/stores/importQueueStore', () => ({
  useImportQueueStore: (selector: (s: Record<string, unknown>) => unknown) => {
    const state = {
      jobs: [],
      isPaused: false,
      notebookCallbacks: {},
      updateNotebookCallbacks: vi.fn(),
      updateNotebookConfig: vi.fn(),
      enqueueFiles: vi.fn(),
      enqueueNotebookFiles: vi.fn(),
    };
    return typeof selector === 'function' ? selector(state) : state;
  },
  selectNotebookJobs: () => [],
  selectPendingCount: () => 0,
  selectCompletedCount: () => 0,
  selectErrorCount: () => 0,
  selectIsProcessing: () => false,
}));

const mockGetExportUrl = vi.fn().mockReturnValue('http://localhost/export');

vi.mock('../../src/api/client', () => ({
  apiClient: {
    getCalendar: vi.fn().mockResolvedValue({ days: {}, total_recordings: 0 }),
    getAdminStatus: vi.fn().mockResolvedValue(null),
    search: vi.fn().mockResolvedValue({ results: [], count: 0 }),
    updateRecordingTitle: vi.fn(),
    deleteRecording: vi.fn(),
    getExportUrl: (...args: unknown[]) => mockGetExportUrl(...args),
  },
}));

vi.mock('../../src/config/store', () => ({
  getConfig: vi.fn().mockResolvedValue(undefined),
  setConfig: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../../src/utils/transcriptionBackend', () => ({
  supportsExplicitWordTimestampToggle: () => true,
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

vi.mock('../../src/hooks/useConfirm', () => ({
  useConfirm: () => ({ confirm: vi.fn().mockResolvedValue(true), dialog: null }),
}));

vi.mock('zustand/react/shallow', () => ({
  useShallow: (selector: unknown) => selector,
}));

const mockDiarizeAndWait = vi.fn();

vi.mock('../../src/services/retroDiarize', () => ({
  diarizeRecordingAndWait: (...args: unknown[]) => mockDiarizeAndWait(...args),
}));

// ── Import after mocks ────────────────────────────────────────────────────

import { NoteActionMenu } from '../views/NotebookView';

// ── Helpers ────────────────────────────────────────────────────────────────

function renderMenu(overrides: Partial<React.ComponentProps<typeof NoteActionMenu>> = {}) {
  const onClose = vi.fn();
  const onRefresh = vi.fn();
  render(
    React.createElement(NoteActionMenu, {
      trigger: { type: 'point' as const, x: 10, y: 10 },
      onClose,
      noteEventId: '5',
      recordingId: 5,
      noteTitle: 'Test Note',
      wordCount: 12,
      hasDiarization: false,
      onRefresh,
      onPlay: vi.fn(),
      ...overrides,
    }),
  );
  return { onClose, onRefresh };
}

function findMenuButton(label: string): HTMLButtonElement | null {
  const buttons = Array.from(document.body.querySelectorAll('button'));
  return (buttons.find((b) => b.textContent?.trim() === label) as HTMLButtonElement) ?? null;
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe('NoteActionMenu — Diarize + Export Markdown wiring (GH-279)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDiarizeAndWait.mockResolvedValue({ job_id: 'abc12345', recording_id: 5 });
    mockGetExportUrl.mockReturnValue('http://localhost/export');
    document.body.innerHTML = '';
  });

  it('offers an enabled Diarize item that starts the job and closes the menu', async () => {
    const { onClose } = renderMenu();

    const diarize = findMenuButton('Diarize');
    expect(diarize).toBeTruthy();
    expect(diarize?.disabled).toBe(false);

    await act(async () => {
      fireEvent.click(diarize as Element);
    });
    expect(mockDiarizeAndWait).toHaveBeenCalledWith(5);
    expect(onClose).toHaveBeenCalled();
  });

  it('refreshes the calendar once the diarize job resolves successfully', async () => {
    let resolveJob: (v: unknown) => void = () => undefined;
    mockDiarizeAndWait.mockReturnValue(
      new Promise((resolve) => {
        resolveJob = resolve;
      }),
    );
    const { onRefresh } = renderMenu();

    await act(async () => {
      fireEvent.click(findMenuButton('Diarize') as Element);
    });
    expect(onRefresh).not.toHaveBeenCalled();

    await act(async () => {
      resolveJob({ job_id: 'abc12345', recording_id: 5 });
      await Promise.resolve();
    });
    expect(onRefresh).toHaveBeenCalled();
  });

  it('disables Diarize with a tooltip when the note has no word timestamps', async () => {
    renderMenu({ wordCount: 0 });

    const diarize = findMenuButton('Diarize');
    expect(diarize).toBeTruthy();
    expect(diarize?.disabled).toBe(true);
    expect(diarize?.title).toMatch(/word-level timestamps/);

    await act(async () => {
      fireEvent.click(diarize as Element);
    });
    expect(mockDiarizeAndWait).not.toHaveBeenCalled();
  });

  it('hides Diarize for an already-diarized note', () => {
    renderMenu({ hasDiarization: true });

    expect(findMenuButton('Diarize')).toBeNull();
    // The rest of the menu is intact.
    expect(findMenuButton('Export TXT')).toBeTruthy();
    expect(findMenuButton('Delete')).toBeTruthy();
  });

  it('offers Export Markdown wired to the md export URL', async () => {
    const windowOpen = vi.spyOn(window, 'open').mockImplementation(() => null);
    const { onClose } = renderMenu();

    const exportMd = findMenuButton('Export Markdown');
    expect(exportMd).toBeTruthy();
    await act(async () => {
      fireEvent.click(exportMd as Element);
    });
    expect(mockGetExportUrl).toHaveBeenCalledWith(5, 'md');
    expect(windowOpen).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
    windowOpen.mockRestore();
  });
});
