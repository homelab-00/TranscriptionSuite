/**
 * AddNoteModal — Canary language plumbing (gh-102 followup #2)
 *
 * Verifies the notebook-upload modal honors the persisted `session.mainLanguage`
 * (and translation-target keys when Canary bidi is active). Mirrors the
 * SessionImportTab pattern shipped in gh-102-followup-1:
 *
 *   1. Canary + Source Language = Spanish, submit → addFiles called with
 *      options.language="es".
 *   2. Canary + Auto Detect (or empty/unresolvable), submit → addFiles NOT
 *      called; toast.error shown with the same wording the live-recording /
 *      session-import guard uses ("Source language required").
 *   3. Canary + bidi translation active (English source, target = French),
 *      submit → addFiles called with language="en", translation_enabled=true,
 *      translation_target_language="fr".
 *   4. Whisper + Auto Detect → addFiles called with options.language=undefined
 *      (regression check on the auto-detect happy path).
 *   5. Languages still loading when user submits (Canary active) →
 *      refuse-with-toast using "loading languages — please try again in a
 *      moment." wording.
 */

import React from 'react';
import { render, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const CANARY_MODEL = 'nvidia/canary-1b-v2';
const WHISPER_MODEL = 'openai/whisper-large-v3-turbo';

// ── Hoisted mock state ────────────────────────────────────────────────────

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
const mockToastSuccess = vi.fn();
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
        diarization: { parallel: false },
      },
    },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock('../../src/stores/importQueueStore', () => {
  const fakeState = {
    addFiles: (...args: unknown[]) => mockAddFiles(...args),
  };
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
  getConfig: (...args: unknown[]) => mockGetConfig(...args),
  setConfig: vi.fn().mockResolvedValue(undefined),
}));

// Real modelCapabilities — we want the real `supportsAutoDetect`,
// `isCanaryModel`, and `supportsTranslation` so the picker→code resolution is
// end-to-end.
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

import { AddNoteModal } from '../views/AddNoteModal';

const NEMO_LANGUAGES_FOR_TEST: Array<{ code: string; name: string }> = [
  { code: 'auto', name: 'Auto Detect' },
  { code: 'en', name: 'English' },
  { code: 'es', name: 'Spanish' },
  { code: 'fr', name: 'French' },
  { code: 'de', name: 'German' },
];

const WHISPER_LANGUAGES_FOR_TEST: Array<{ code: string; name: string }> = [
  { code: 'auto', name: 'Auto Detect' },
  { code: 'en', name: 'English' },
  { code: 'es', name: 'Spanish' },
];

function buildFile(name = 'sample.mp3'): File {
  return new File([new Uint8Array([0])], name, { type: 'audio/mpeg' });
}

/** Populate the modal's selectedFiles by changing the hidden file input. */
async function attachFile(file: File): Promise<void> {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement | null;
  if (!input) throw new Error('file input not found in AddNoteModal');
  Object.defineProperty(input, 'files', {
    value: {
      0: file,
      length: 1,
      item: (i: number) => (i === 0 ? file : null),
      [Symbol.iterator]: function* () {
        yield file;
      },
    },
    configurable: true,
  });
  await act(async () => {
    fireEvent.change(input);
  });
}

/** Click the modal's Create Note submit button. */
async function clickCreateNote(): Promise<void> {
  const buttons = Array.from(document.querySelectorAll('button')) as HTMLButtonElement[];
  const createButton = buttons.find((b) => /create note|queueing/i.test(b.textContent ?? ''));
  if (!createButton) throw new Error('Create Note button not found in AddNoteModal');
  await act(async () => {
    fireEvent.click(createButton);
    await Promise.resolve();
  });
}

describe('AddNoteModal — Canary language plumbing (gh-102 followup #2)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockToastError.mockReset();
    mockToastSuccess.mockReset();
    mockAddFiles.mockReset();
    mockGetConfig.mockReset();
    mockGetConfig.mockResolvedValue(undefined);

    mockActiveModel = CANARY_MODEL;
    mockLanguageSet = {
      languages: NEMO_LANGUAGES_FOR_TEST,
      loading: false,
      backendType: 'canary',
    };

    // Modal renders into document.body via createPortal. Reset between tests
    // to avoid stale DOM bleeding across cases.
    document.body.innerHTML = '';
  });

  it('Canary + Spanish persisted: submit enqueues with options.language="es"', async () => {
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'Spanish';
      return undefined;
    });

    render(React.createElement(AddNoteModal, { isOpen: true, onClose: vi.fn() }));

    await act(async () => {
      // Allow hydrate useEffect's Promise.all to resolve
      await Promise.resolve();
      await Promise.resolve();
    });

    await attachFile(buildFile());
    await clickCreateNote();

    expect(mockToastError).not.toHaveBeenCalled();
    expect(mockAddFiles).toHaveBeenCalledTimes(1);
    const [, , options] = mockAddFiles.mock.calls[0] as [unknown, unknown, Record<string, unknown>];
    expect(options.language).toBe('es');
    expect(options.translation_enabled).toBeUndefined();
    expect(options.translation_target_language).toBeUndefined();
  });

  it('Canary + Auto Detect: submit refuses with toast.error and does not enqueue', async () => {
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'Auto Detect';
      return undefined;
    });

    render(React.createElement(AddNoteModal, { isOpen: true, onClose: vi.fn() }));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    await attachFile(buildFile());
    await clickCreateNote();

    expect(mockAddFiles).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledTimes(1);
    const [title, opts] = mockToastError.mock.calls[0] as [string, { description?: string }];
    // Strict equality enforces the spec's "wording-grep parity" Always:
    // invariant — any future copy drift between AddNoteModal,
    // NotebookView.ImportTab, and SessionImportTab.handleFiles will fail
    // tests instead of silently succeeding.
    expect(title).toBe('Source language required');
    expect(opts?.description).toBe(
      '"Auto Detect" is not a valid source language for the active model. Pick a language from the Source Language dropdown.',
    );
  });

  it('Canary + bidi (English source, French target): submit enqueues with translation fields', async () => {
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'English';
      if (key === 'session.mainBidiTarget') return 'French';
      return undefined;
    });

    render(React.createElement(AddNoteModal, { isOpen: true, onClose: vi.fn() }));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    await attachFile(buildFile());
    await clickCreateNote();

    expect(mockToastError).not.toHaveBeenCalled();
    expect(mockAddFiles).toHaveBeenCalledTimes(1);
    const [, , options] = mockAddFiles.mock.calls[0] as [unknown, unknown, Record<string, unknown>];
    expect(options.language).toBe('en');
    expect(options.translation_enabled).toBe(true);
    expect(options.translation_target_language).toBe('fr');
  });

  it('Whisper + Auto Detect: submit enqueues with options.language=undefined (regression check)', async () => {
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

    render(React.createElement(AddNoteModal, { isOpen: true, onClose: vi.fn() }));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    await attachFile(buildFile());
    await clickCreateNote();

    expect(mockToastError).not.toHaveBeenCalled();
    expect(mockAddFiles).toHaveBeenCalledTimes(1);
    const [, , options] = mockAddFiles.mock.calls[0] as [unknown, unknown, Record<string, unknown>];
    expect(options.language).toBeUndefined();
    expect(options.translation_enabled).toBeUndefined();
    expect(options.translation_target_language).toBeUndefined();
  });

  it('Canary + languages still loading: submit refuses with "loading languages" wording', async () => {
    mockLanguageSet = {
      languages: [{ code: 'auto', name: 'Auto Detect' }],
      loading: true,
      backendType: 'canary',
    };
    mockGetConfig.mockImplementation(async (key: string) => {
      if (key === 'session.mainLanguage') return 'Spanish';
      return undefined;
    });

    render(React.createElement(AddNoteModal, { isOpen: true, onClose: vi.fn() }));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    await attachFile(buildFile());
    await clickCreateNote();

    expect(mockAddFiles).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledTimes(1);
    const [title, opts] = mockToastError.mock.calls[0] as [string, { description?: string }];
    // Strict equality enforces wording-grep parity for the loading branch
    // tail ("please try again in a moment.") — see comment in the
    // Auto-Detect refuse case above.
    expect(title).toBe('Source language required');
    expect(opts?.description).toBe('Loading languages — please try again in a moment.');
  });
});
