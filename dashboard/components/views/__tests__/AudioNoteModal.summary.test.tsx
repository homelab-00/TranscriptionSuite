/**
 * AudioNoteModal — AI summary panel wiring (GH-254).
 *
 * The row has always been persisted (recordings.summary). The defect was that
 * the modal cleared the panel on open, always labelled the control "Generate
 * AI Summary", and replayed the STORED text through a 15ms/char typewriter —
 * which looked and felt exactly like a fresh generation.
 *
 * What we verify here is the wiring:
 *   1. A stored summary renders immediately, with no call to the LLM.
 *   2. No stored summary leaves the collapsed Generate button in place.
 *   3. Regenerate confirms, then streams.
 *   4. A failed stream restores the previous text instead of leaving an error
 *      where the summary was.
 */

import React from 'react';
import { render, act, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ── Hoisted controllable state ────────────────────────────────────────────

let mockRecording: Record<string, unknown> | null = null;
const mockRefresh = vi.fn();
const mockConfirm = vi.fn();

// ── Heavy mocks (mirror AudioNoteModal hook surface) ───────────────────────

vi.mock('../../../src/hooks/useRecording', () => ({
  useRecording: () => ({
    recording: mockRecording,
    transcription: { recording_id: 1, segments: [] },
    loading: false,
    error: null,
    refresh: mockRefresh,
    audioUrl: null,
  }),
}));

vi.mock('../../../src/hooks/useDiarizationConfidence', () => ({
  useDiarizationConfidence: () => ({ turns: [], loading: false, error: null }),
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
  useConfirm: () => ({ confirm: mockConfirm, dialog: null }),
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

const mockSummarizeStream = vi.fn();

vi.mock('../../../src/api/client', () => ({
  apiClient: {
    listConversations: vi.fn().mockResolvedValue({ conversations: [] }),
    getConversation: vi.fn().mockResolvedValue({ id: 0, title: '', messages: [] }),
    createConversation: vi.fn().mockResolvedValue({ id: 1, title: 'New Chat' }),
    updateConversation: vi.fn().mockResolvedValue(undefined),
    deleteConversation: vi.fn().mockResolvedValue(undefined),
    deleteMessagesFrom: vi.fn().mockResolvedValue(undefined),
    generateConversationTitle: vi.fn().mockResolvedValue({ title: '' }),
    chat: vi.fn(),
    summarizeRecordingStream: (...args: unknown[]) => mockSummarizeStream(...args),
    summarizeRecording: vi.fn().mockResolvedValue({ summary: '' }),
    getAudioUrl: vi.fn().mockReturnValue(null),
    getAvailableModels: vi.fn().mockResolvedValue({ models: [] }),
    getLLMStatus: vi.fn().mockResolvedValue({ available: true, model: 'test-model' }),
    deleteRecording: vi.fn().mockResolvedValue(undefined),
    updateRecordingTitle: vi.fn().mockResolvedValue(undefined),
    updateRecordingDate: vi.fn().mockResolvedValue(undefined),
    updateRecordingSummary: vi.fn().mockResolvedValue(undefined),
    updateRecordingCorrectedTranscript: vi.fn().mockResolvedValue(undefined),
    getExportUrl: vi.fn().mockReturnValue('http://localhost/export'),
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

const NOTE = { title: 'Test Recording', date: '2026-05-04', duration: '00:60', recordingId: 1 };

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
  transcript_corrected: null,
  transcription_backend: 'whisper',
  auto_summary_status: null,
  auto_export_status: null,
  webhook_status: null,
};

/** Flush the modal's portal effect and its double-rAF open animation. */
async function openModal() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await new Promise((r) => requestAnimationFrame(r));
    await new Promise((r) => requestAnimationFrame(r));
    await Promise.resolve();
  });
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe('AudioNoteModal — stored summary (GH-254)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConfirm.mockResolvedValue(true);
    mockRecording = null;
    document.body.innerHTML = '';
  });

  it('renders a stored summary immediately without calling the LLM', async () => {
    mockRecording = { ...BASE_RECORDING, summary: 'Stored summary text.', summary_model: 'qwen3' };

    render(React.createElement(AudioNoteModal, { isOpen: true, onClose: vi.fn(), note: NOTE }), {
      wrapper: createWrapper(),
    });
    await openModal();

    expect(document.body.textContent).toContain('Stored summary text.');
    expect(document.body.textContent).not.toContain('Generate AI Summary');
    expect(mockSummarizeStream).not.toHaveBeenCalled();
  });

  it('keeps the collapsed Generate button when nothing is stored', async () => {
    mockRecording = { ...BASE_RECORDING, summary: null };

    render(React.createElement(AudioNoteModal, { isOpen: true, onClose: vi.fn(), note: NOTE }), {
      wrapper: createWrapper(),
    });
    await openModal();

    expect(document.body.textContent).toContain('Generate AI Summary');
    expect(mockSummarizeStream).not.toHaveBeenCalled();
  });

  it('regenerate confirms and then streams a fresh summary', async () => {
    mockRecording = { ...BASE_RECORDING, summary: 'Old summary.' };
    mockSummarizeStream.mockImplementation(async function* () {
      yield 'New ';
      yield 'summary.';
    });

    render(React.createElement(AudioNoteModal, { isOpen: true, onClose: vi.fn(), note: NOTE }), {
      wrapper: createWrapper(),
    });
    await openModal();

    const button = document.body.querySelector(
      '[aria-label="Regenerate summary"]',
    ) as HTMLButtonElement;
    expect(button).toBeTruthy();

    await act(async () => {
      fireEvent.click(button);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockConfirm).toHaveBeenCalled();
    expect(mockSummarizeStream).toHaveBeenCalledWith(1);
    expect(document.body.textContent).toContain('New summary.');
  });

  it('a failed regeneration restores the previous summary', async () => {
    mockRecording = { ...BASE_RECORDING, summary: 'Old summary.' };
    mockSummarizeStream.mockImplementation(() => {
      throw new Error('provider offline');
    });

    render(React.createElement(AudioNoteModal, { isOpen: true, onClose: vi.fn(), note: NOTE }), {
      wrapper: createWrapper(),
    });
    await openModal();

    await act(async () => {
      fireEvent.click(
        document.body.querySelector('[aria-label="Regenerate summary"]') as HTMLButtonElement,
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(document.body.textContent).toContain('Old summary.');
    expect(document.body.textContent).toContain('Failed to generate summary');
  });

  it('declining the confirmation does not stream', async () => {
    mockRecording = { ...BASE_RECORDING, summary: 'Old summary.' };
    mockConfirm.mockResolvedValue(false);

    render(React.createElement(AudioNoteModal, { isOpen: true, onClose: vi.fn(), note: NOTE }), {
      wrapper: createWrapper(),
    });
    await openModal();

    await act(async () => {
      fireEvent.click(
        document.body.querySelector('[aria-label="Regenerate summary"]') as HTMLButtonElement,
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockSummarizeStream).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('Old summary.');
  });
});
