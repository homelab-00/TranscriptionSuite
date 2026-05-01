/**
 * GH #92 — AddNoteModal initialFiles seeding
 *
 * Verifies that when the modal is opened via the per-hour drag-and-drop path
 * (Notebook → Calendar tab), the preloaded files appear in the selected files
 * list and the title defaults to the first file's stem name (matching the
 * in-modal handleFiles behavior).
 */

import React from 'react';
import { render, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const WHISPER_MODEL = 'openai/whisper-large-v3-turbo';

// ── Hoisted mocks (mirror AddNoteModal.canary-language.test.tsx) ─────────

vi.mock('../../src/hooks/useLanguages', () => ({
  useLanguages: () => ({
    languages: [{ code: 'auto', name: 'Auto Detect' }],
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
        diarization: { parallel: false },
      },
    },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock('../../src/stores/importQueueStore', () => {
  const fakeState = { addFiles: vi.fn() };
  return {
    useImportQueueStore: Object.assign(
      (selector?: (s: typeof fakeState) => unknown) =>
        typeof selector === 'function' ? selector(fakeState) : fakeState,
      { getState: () => fakeState },
    ),
  };
});

vi.mock('../../src/api/client', () => ({
  apiClient: {
    getAdminStatus: vi.fn().mockResolvedValue({ config: { diarization: { parallel: false } } }),
  },
}));

vi.mock('../../src/config/store', () => ({
  getConfig: vi.fn().mockResolvedValue(undefined),
  setConfig: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

import { AddNoteModal } from '../views/AddNoteModal';

function buildFile(name: string): File {
  return new File([new Uint8Array([0])], name, { type: 'audio/mpeg' });
}

describe('[GH #92] AddNoteModal initialFiles seeding', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
  });

  it('seeds selectedFiles from initialFiles and uses first file name as title', async () => {
    const file = buildFile('voice-memo.mp3');
    render(
      React.createElement(AddNoteModal, {
        isOpen: true,
        onClose: vi.fn(),
        initialTime: 14,
        initialDate: '2026-05-02',
        initialFiles: [file],
      }),
    );

    await act(async () => {
      // Allow open-effect to apply (it runs synchronously on isOpen=true)
      await Promise.resolve();
    });

    // The dropped file appears in the selected files list.
    const filenameNode = Array.from(document.querySelectorAll('span')).find(
      (s) => s.textContent === 'voice-memo.mp3',
    );
    expect(filenameNode).toBeDefined();

    // Title defaults to the file stem (not the time-based "14:00 Recording").
    const titleInput = document.querySelector(
      'input[placeholder="Enter title..."]',
    ) as HTMLInputElement | null;
    expect(titleInput).not.toBeNull();
    expect(titleInput?.value).toBe('voice-memo');
  });

  it('falls back to time-based title when no initialFiles are provided', async () => {
    render(
      React.createElement(AddNoteModal, {
        isOpen: true,
        onClose: vi.fn(),
        initialTime: 9,
        initialDate: '2026-05-02',
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });

    const titleInput = document.querySelector(
      'input[placeholder="Enter title..."]',
    ) as HTMLInputElement | null;
    expect(titleInput?.value).toBe('09:00 Recording');
  });
});
