/**
 * AudioNoteModal — Diarize + Export Markdown menu wiring (GH-279).
 *
 * The options dropdown must:
 *   1. Offer an enabled Diarize item for a non-diarized note WITH word
 *      timestamps, and clicking it must invoke the retroDiarize service.
 *   2. Disable Diarize (with an explanatory title tooltip) when the note has
 *      no word-level timestamps.
 *   3. Hide Diarize entirely once the note is diarized.
 *   4. Offer Export Markdown, wired to getExportUrl(id, 'md').
 */

import React from 'react';
import { render, act, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ── Hoisted controllable state ────────────────────────────────────────────

let mockRecording: Record<string, unknown> | null = null;
let mockSegments: Array<Record<string, unknown>> = [];
const mockDiarizeAndWait = vi.fn();
const mockGetExportUrl = vi.fn().mockReturnValue('http://localhost/export');
const mockRefresh = vi.fn();

// ── Heavy mocks (mirror AudioNoteModal hook surface) ───────────────────────

vi.mock('../../../src/hooks/useRecording', () => ({
  useRecording: () => ({
    recording: mockRecording,
    transcription: { recording_id: 1, segments: mockSegments },
    loading: false,
    error: null,
    refresh: mockRefresh,
    audioUrl: null,
  }),
}));

vi.mock('../../../src/hooks/useDiarizationConfidence', () => ({
  useDiarizationConfidence: () => ({
    turns: [],
    byTurn: new Map(),
    loading: false,
    error: null,
  }),
}));

vi.mock('../../../src/hooks/useDiarizationReview', () => ({
  useDiarizationReview: () => ({
    state: { recording_id: 1, status: null, reviewed_turns_json: null },
    refresh: vi.fn(),
    triggerOpen: vi.fn(),
    triggerComplete: vi.fn(),
  }),
}));

vi.mock('../../../src/hooks/useRecordingAliases', () => ({
  useRecordingAliases: () => ({
    aliases: [],
    aliasMap: new Map(),
    setAliases: vi.fn().mockResolvedValue(undefined),
    refresh: vi.fn(),
  }),
}));

vi.mock('../../../src/hooks/useWordHighlighter', () => ({
  useWordHighlighter: () => ({ activeWordIndex: -1, registerWord: vi.fn(), scrollTo: vi.fn() }),
}));

vi.mock('../../../src/hooks/useConfirm', () => ({
  useConfirm: () => ({ confirm: vi.fn().mockResolvedValue(true), dialog: null }),
}));

vi.mock('../../../src/hooks/useAutoActionRetry', () => ({
  useAutoActionRetry: () => ({ mutate: vi.fn(), isPending: false, error: null }),
}));

vi.mock('../../../src/stores/activeProfileStore', () => ({
  useActiveProfileStore: (selector?: (s: { activeProfileId: number | null }) => unknown) => {
    const state = { activeProfileId: null };
    return typeof selector === 'function' ? selector(state) : state;
  },
}));

vi.mock('../../../src/hooks/useAriaAnnouncer', () => ({
  useAriaAnnouncer: () => vi.fn(),
}));

vi.mock('../../../src/services/retroDiarize', () => ({
  diarizeRecordingAndWait: (...args: unknown[]) => mockDiarizeAndWait(...args),
}));

vi.mock('../../../src/api/client', () => ({
  apiClient: {
    listConversations: vi.fn().mockResolvedValue([]),
    getMessages: vi.fn().mockResolvedValue([]),
    getConversation: vi.fn().mockResolvedValue({ id: 0, title: '', messages: [] }),
    createConversation: vi.fn().mockResolvedValue({ id: 1, title: 'New Chat' }),
    updateConversation: vi.fn().mockResolvedValue(undefined),
    deleteConversation: vi.fn().mockResolvedValue(undefined),
    deleteMessagesFrom: vi.fn().mockResolvedValue(undefined),
    generateConversationTitle: vi.fn().mockResolvedValue({ title: '' }),
    chat: vi.fn(),
    summarizeRecordingStream: vi.fn(),
    summarizeRecording: vi.fn().mockResolvedValue({ summary: '' }),
    getAudioUrl: vi.fn().mockReturnValue(null),
    getAvailableModels: vi.fn().mockResolvedValue({ models: [] }),
    getLLMModels: vi.fn().mockResolvedValue([]),
    getLLMStatus: vi.fn().mockResolvedValue({ active: false, model: null }),
    deleteRecording: vi.fn().mockResolvedValue(undefined),
    updateRecordingTitle: vi.fn().mockResolvedValue(undefined),
    updateRecordingDate: vi.fn().mockResolvedValue(undefined),
    updateRecordingSummary: vi.fn().mockResolvedValue(undefined),
    getExportUrl: (...args: unknown[]) => mockGetExportUrl(...args),
    retryAutoAction: vi.fn().mockResolvedValue({ status: 'retry_initiated' }),
  },
}));

vi.mock('../../../src/config/store', () => ({
  getConfig: vi.fn().mockResolvedValue(undefined),
  setConfig: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

// react-markdown bundles ESM-only deps that vitest can't transform out of the box.
vi.mock('react-markdown', () => ({
  default: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
}));
vi.mock('remark-gfm', () => ({ default: () => undefined }));

// ── Imports after mocks ───────────────────────────────────────────────────

import { AudioNoteModal } from '../AudioNoteModal';

// ── Helpers ────────────────────────────────────────────────────────────────

function createWrapper(): ({ children }: { children: React.ReactNode }) => React.ReactElement {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }) =>
    React.createElement(QueryClientProvider, { client: qc }, children) as React.ReactElement;
}

const NOTE = {
  title: 'Test Recording',
  date: '2026-05-04',
  duration: '00:60',
  recordingId: 1,
};

const BASE_RECORDING = {
  id: 1,
  filename: 'test.wav',
  filepath: '/data/test.wav',
  title: 'Test Recording',
  duration_seconds: 60,
  recorded_at: '2026-05-04T12:00:00Z',
  imported_at: null,
  word_count: 5,
  has_diarization: false,
  summary: null,
  summary_model: null,
  transcription_backend: 'whisper',
};

const SEGMENT_WITH_WORDS = {
  text: 'hello there',
  start: 0.0,
  end: 1.2,
  speaker: null,
  words: [
    { word: 'hello', start: 0.0, end: 0.5 },
    { word: 'there', start: 0.6, end: 1.2 },
  ],
};

const SEGMENT_WITHOUT_WORDS = {
  text: 'hello there',
  start: 0.0,
  end: 1.2,
  speaker: null,
  words: [],
};

async function renderAndOpenMenu(): Promise<ReturnType<typeof render>> {
  const view = render(
    React.createElement(AudioNoteModal, { isOpen: true, onClose: vi.fn(), note: NOTE }),
    { wrapper: createWrapper() },
  );

  await act(async () => {
    // Portal container + double-rAF open animation gate (see the
    // auto-actions test for the rationale).
    await Promise.resolve();
    await Promise.resolve();
    await new Promise((r) => requestAnimationFrame(r));
    await new Promise((r) => requestAnimationFrame(r));
    await Promise.resolve();
  });

  const optionsButton = document.body.querySelector('button[title="More options"]');
  expect(optionsButton).toBeTruthy();
  await act(async () => {
    fireEvent.click(optionsButton as Element);
  });
  return view;
}

function findMenuButton(label: string): HTMLButtonElement | null {
  const buttons = Array.from(document.body.querySelectorAll('button'));
  return (buttons.find((b) => b.textContent?.trim() === label) as HTMLButtonElement) ?? null;
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe('AudioNoteModal — Diarize + Export Markdown wiring (GH-279)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRecording = { ...BASE_RECORDING };
    mockSegments = [SEGMENT_WITH_WORDS];
    mockDiarizeAndWait.mockResolvedValue({ job_id: 'abc12345', recording_id: 1 });
    mockGetExportUrl.mockReturnValue('http://localhost/export');
    document.body.innerHTML = '';
  });

  it('offers an enabled Diarize item and invokes the service on click', async () => {
    await renderAndOpenMenu();

    const diarize = findMenuButton('Diarize');
    expect(diarize).toBeTruthy();
    expect(diarize?.disabled).toBe(false);

    await act(async () => {
      fireEvent.click(diarize as Element);
    });
    expect(mockDiarizeAndWait).toHaveBeenCalledWith(1);
  });

  it('disables Diarize with a tooltip when word timestamps are absent', async () => {
    mockSegments = [SEGMENT_WITHOUT_WORDS];

    await renderAndOpenMenu();

    const diarize = findMenuButton('Diarize');
    expect(diarize).toBeTruthy();
    expect(diarize?.disabled).toBe(true);
    expect(diarize?.title).toMatch(/word-level timestamps/);

    await act(async () => {
      fireEvent.click(diarize as Element);
    });
    expect(mockDiarizeAndWait).not.toHaveBeenCalled();
  });

  it('hides Diarize once the recording is diarized', async () => {
    mockRecording = { ...BASE_RECORDING, has_diarization: true };
    mockSegments = [{ ...SEGMENT_WITH_WORDS, speaker: 'SPEAKER_00' }];

    await renderAndOpenMenu();

    expect(findMenuButton('Diarize')).toBeNull();
  });

  it('does not apply a stale refresh when the note switches mid-diarize', async () => {
    // GH-279 review finding: the modal instance is shared across notes, so a
    // diarize job finishing for note A must not refresh while note B is open
    // (the stale refresh would clobber B's displayed transcript with A's data).
    let resolveJob: (v: unknown) => void = () => undefined;
    mockDiarizeAndWait.mockReturnValue(
      new Promise((resolve) => {
        resolveJob = resolve;
      }),
    );

    const view = await renderAndOpenMenu();
    await act(async () => {
      fireEvent.click(findMenuButton('Diarize') as Element);
    });

    // Switch the modal to a DIFFERENT note while the job is in flight.
    view.rerender(
      React.createElement(AudioNoteModal, {
        isOpen: true,
        onClose: vi.fn(),
        note: { ...NOTE, recordingId: 2, title: 'Other Recording' },
      }),
    );

    await act(async () => {
      resolveJob({ job_id: 'abc12345', recording_id: 1 });
      await Promise.resolve();
    });
    expect(mockRefresh).not.toHaveBeenCalled();
  });

  it('applies the refresh when the same note is still open on completion', async () => {
    let resolveJob: (v: unknown) => void = () => undefined;
    mockDiarizeAndWait.mockReturnValue(
      new Promise((resolve) => {
        resolveJob = resolve;
      }),
    );

    await renderAndOpenMenu();
    await act(async () => {
      fireEvent.click(findMenuButton('Diarize') as Element);
    });

    await act(async () => {
      resolveJob({ job_id: 'abc12345', recording_id: 1 });
      await Promise.resolve();
    });
    expect(mockRefresh).toHaveBeenCalled();
  });

  it('offers Export Markdown wired to the md export URL', async () => {
    const windowOpen = vi.spyOn(window, 'open').mockImplementation(() => null);

    await renderAndOpenMenu();

    const exportMd = findMenuButton('Export Markdown');
    expect(exportMd).toBeTruthy();
    await act(async () => {
      fireEvent.click(exportMd as Element);
    });
    expect(mockGetExportUrl).toHaveBeenCalledWith(1, 'md');
    expect(windowOpen).toHaveBeenCalled();
    windowOpen.mockRestore();
  });
});
