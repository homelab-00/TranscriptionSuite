/**
 * AudioNoteModal — auto-action badge integration (Issue #104, Sprint 4 deferred-work no. 3).
 *
 * The modal must read recording.auto_summary_status / auto_export_status from
 * the recording-detail response and render an AutoActionStatusBadge for each
 * non-null status. The badge component itself is tested in
 * AutoActionStatusBadge.test.tsx — what we verify here is the WIRING:
 *
 *   1. Both statuses non-null → two badges render with the right action types.
 *   2. Both statuses null → no badges render (toggle-off / not-yet-fired case).
 *   3. Clicking the export retry button invokes useAutoActionRetry.mutate('auto_export').
 */

import React from 'react';
import { render, act, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ── Hoisted controllable state ────────────────────────────────────────────

let mockRecording: Record<string, unknown> | null = null;
const mockMutate = vi.fn();

// ── Heavy mocks (mirror AudioNoteModal hook surface) ───────────────────────

vi.mock('../../../src/hooks/useRecording', () => ({
  useRecording: () => ({
    recording: mockRecording,
    transcription: { recording_id: 1, segments: [] },
    loading: false,
    error: null,
    refresh: vi.fn(),
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
  useConfirm: () => ({ confirm: vi.fn().mockResolvedValue(true), dialog: null }),
}));

vi.mock('../../../src/hooks/useAutoActionRetry', () => ({
  useAutoActionRetry: () => ({
    mutate: (...args: unknown[]) => mockMutate(...args),
    isPending: false,
    error: null,
  }),
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

// ── Tests ──────────────────────────────────────────────────────────────────

describe('AudioNoteModal — auto-action badge wiring (Sprint 4 deferred-work no. 3)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMutate.mockReset();
    mockRecording = null;
    // The modal portals into document.body; clear any stale subtree from prior runs.
    document.body.innerHTML = '';
  });

  it('renders both badges when summary and export statuses are non-null', async () => {
    mockRecording = {
      ...BASE_RECORDING,
      auto_summary_status: 'success',
      auto_summary_error: null,
      auto_export_status: 'failed',
      auto_export_error: 'Disk full',
      auto_export_path: '/mnt/exports',
    };

    render(React.createElement(AudioNoteModal, { isOpen: true, onClose: vi.fn(), note: NOTE }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      // The modal gates content render on portalContainer (set in a useEffect)
      // AND on a double-rAF for the open animation. Flush both microtasks
      // and animation frames before querying the DOM.
      await Promise.resolve();
      await Promise.resolve();
      await new Promise((r) => requestAnimationFrame(r));
      await new Promise((r) => requestAnimationFrame(r));
      await Promise.resolve();
    });

    // Modal renders into document.body via createPortal — query there, not the container.
    const summaryBadge = document.body.querySelector(
      '[data-action-type="auto_summary"][data-severity="ok"]',
    );
    const exportBadge = document.body.querySelector(
      '[data-action-type="auto_export"][data-severity="error"]',
    );
    expect(summaryBadge).toBeTruthy();
    expect(exportBadge).toBeTruthy();
    expect(exportBadge?.textContent).toContain('Disk full');
  });

  it('renders zero badges when both statuses are null', async () => {
    mockRecording = {
      ...BASE_RECORDING,
      auto_summary_status: null,
      auto_summary_error: null,
      auto_export_status: null,
      auto_export_error: null,
      auto_export_path: null,
    };

    render(React.createElement(AudioNoteModal, { isOpen: true, onClose: vi.fn(), note: NOTE }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      // The modal gates content render on portalContainer (set in a useEffect)
      // AND on a double-rAF for the open animation. Flush both microtasks
      // and animation frames before querying the DOM.
      await Promise.resolve();
      await Promise.resolve();
      await new Promise((r) => requestAnimationFrame(r));
      await new Promise((r) => requestAnimationFrame(r));
      await Promise.resolve();
    });

    expect(document.body.querySelector('[data-action-type="auto_summary"]')).toBeFalsy();
    expect(document.body.querySelector('[data-action-type="auto_export"]')).toBeFalsy();
  });

  it('export retry button invokes useAutoActionRetry.mutate("auto_export")', async () => {
    mockRecording = {
      ...BASE_RECORDING,
      auto_summary_status: null,
      auto_export_status: 'failed',
      auto_export_error: 'Disk full',
      auto_export_path: '/mnt/exports',
    };

    render(React.createElement(AudioNoteModal, { isOpen: true, onClose: vi.fn(), note: NOTE }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      // The modal gates content render on portalContainer (set in a useEffect)
      // AND on a double-rAF for the open animation. Flush both microtasks
      // and animation frames before querying the DOM.
      await Promise.resolve();
      await Promise.resolve();
      await new Promise((r) => requestAnimationFrame(r));
      await new Promise((r) => requestAnimationFrame(r));
      await Promise.resolve();
    });

    const exportBadge = document.body.querySelector(
      '[data-action-type="auto_export"][data-severity="error"]',
    );
    expect(exportBadge).toBeTruthy();
    const retryButton = exportBadge?.querySelector('button');
    expect(retryButton).toBeTruthy();

    await act(async () => {
      fireEvent.click(retryButton!);
    });

    expect(mockMutate).toHaveBeenCalledTimes(1);
    expect(mockMutate).toHaveBeenCalledWith('auto_export');
  });
});
