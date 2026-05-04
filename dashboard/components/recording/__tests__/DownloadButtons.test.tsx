/**
 * DownloadButtons tests (Issue #104, Story 3.5).
 *
 * Covers:
 *   - AC1: both buttons render; summary disabled when hasSummary=false
 *     and shows the FR6 tooltip
 *   - AC2: clicking opens save dialog with the default filename suggestion
 *   - AC4: write error surfaces a toast; success ARIA-announces
 *   - AC5: aria-labels match the Story 1.8 helpers
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DownloadButtons } from '../DownloadButtons';

const announceMock = vi.fn();

vi.mock('../../../src/hooks/useAriaAnnouncer', () => ({
  useAriaAnnouncer: () => announceMock,
}));

interface FileIOMock {
  saveFile: ReturnType<typeof vi.fn>;
  writeText: ReturnType<typeof vi.fn>;
  selectFolder?: ReturnType<typeof vi.fn>;
  getDownloadsPath?: ReturnType<typeof vi.fn>;
}

const originalElectronAPI = (window as unknown as { electronAPI?: unknown }).electronAPI;

function installFileIO(io: FileIOMock) {
  (window as unknown as { electronAPI: { fileIO: FileIOMock } }).electronAPI = {
    fileIO: io,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  announceMock.mockReset();
});

afterEach(() => {
  (window as unknown as { electronAPI?: unknown }).electronAPI = originalElectronAPI;
});

// ──────────────────────────────────────────────────────────────────────────
// AC3.5.AC1 — both buttons render
// ──────────────────────────────────────────────────────────────────────────

describe('DownloadButtons — AC3.5.AC1 + AC5 a11y labels', () => {
  it('renders both buttons with the Story 1.8 aria-labels', () => {
    render(
      <DownloadButtons
        transcriptFilename="x.txt"
        summaryFilename="x-summary.txt"
        fetchTranscript={vi.fn()}
        fetchSummary={vi.fn()}
        hasSummary
      />,
    );
    expect(
      screen.getByRole('button', {
        name: 'Download transcript as plain text',
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Download summary as plain text' }),
    ).toBeInTheDocument();
  });

  it('disables the summary button when hasSummary=false with FR6 tooltip', () => {
    render(
      <DownloadButtons
        transcriptFilename="x.txt"
        summaryFilename="x-summary.txt"
        fetchTranscript={vi.fn()}
        fetchSummary={vi.fn()}
        hasSummary={false}
      />,
    );
    const summary = screen.getByRole('button', {
      name: 'Download summary as plain text',
    });
    expect(summary).toBeDisabled();
    expect(summary).toHaveAttribute('title', 'No summary yet — generate from the AI panel');
  });
});

// ──────────────────────────────────────────────────────────────────────────
// AC3.5.AC2 — save dialog opens with default filename
// ──────────────────────────────────────────────────────────────────────────

describe('DownloadButtons — AC3.5.AC2 save dialog flow', () => {
  it('opens the save dialog with the default filename, then writes content', async () => {
    const saveFile = vi.fn().mockResolvedValue('/picked/transcript.txt');
    const writeText = vi.fn().mockResolvedValue(undefined);
    installFileIO({ saveFile, writeText });

    const fetchTranscript = vi.fn().mockResolvedValue('Hello world.');

    render(
      <DownloadButtons
        transcriptFilename="2026-05-08 - Sample.txt"
        summaryFilename="x-summary.txt"
        fetchTranscript={fetchTranscript}
        fetchSummary={vi.fn()}
        hasSummary
      />,
    );

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Download transcript as plain text',
      }),
    );

    await waitFor(() => expect(writeText).toHaveBeenCalled());
    expect(saveFile).toHaveBeenCalledWith({
      defaultPath: '2026-05-08 - Sample.txt',
    });
    expect(writeText).toHaveBeenCalledWith('/picked/transcript.txt', 'Hello world.');
  });

  it('does nothing when user cancels the save dialog', async () => {
    const saveFile = vi.fn().mockResolvedValue(null);
    const writeText = vi.fn();
    installFileIO({ saveFile, writeText });

    const fetchTranscript = vi.fn();

    render(
      <DownloadButtons
        transcriptFilename="x.txt"
        summaryFilename="x-summary.txt"
        fetchTranscript={fetchTranscript}
        fetchSummary={vi.fn()}
        hasSummary
      />,
    );

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Download transcript as plain text',
      }),
    );

    await waitFor(() => expect(saveFile).toHaveBeenCalled());
    expect(fetchTranscript).not.toHaveBeenCalled();
    expect(writeText).not.toHaveBeenCalled();
  });
});

// ──────────────────────────────────────────────────────────────────────────
// AC3.5.AC4 — error surfacing + AC5 ARIA announce on success
// ──────────────────────────────────────────────────────────────────────────

describe('DownloadButtons — AC3.5.AC4/AC5 success and error paths', () => {
  it('announces success via ARIA live region on save', async () => {
    installFileIO({
      saveFile: vi.fn().mockResolvedValue('/saved/here.txt'),
      writeText: vi.fn().mockResolvedValue(undefined),
    });

    render(
      <DownloadButtons
        transcriptFilename="x.txt"
        summaryFilename="x-summary.txt"
        fetchTranscript={vi.fn().mockResolvedValue('content')}
        fetchSummary={vi.fn()}
        hasSummary
      />,
    );

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Download transcript as plain text',
      }),
    );

    await waitFor(() => expect(announceMock).toHaveBeenCalled());
    expect(announceMock).toHaveBeenCalledWith('Transcript saved to /saved/here.txt');
  });

  it('emits an error toast when writeText fails', async () => {
    installFileIO({
      saveFile: vi.fn().mockResolvedValue('/some/path.txt'),
      writeText: vi.fn().mockRejectedValue(new Error('disk full')),
    });

    const onToast = vi.fn();
    render(
      <DownloadButtons
        transcriptFilename="x.txt"
        summaryFilename="x-summary.txt"
        fetchTranscript={vi.fn().mockResolvedValue('content')}
        fetchSummary={vi.fn()}
        hasSummary
        onToast={onToast}
      />,
    );

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Download transcript as plain text',
      }),
    );

    await waitFor(() =>
      expect(onToast).toHaveBeenCalledWith('Could not save file: disk full', 'error'),
    );
  });
});
