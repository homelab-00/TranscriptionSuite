/**
 * DownloadButtons — explicit "Download transcript" / "Download summary"
 * affordances for completed recordings (Issue #104, Story 3.5).
 *
 * AC contract:
 *   - AC1: both buttons render; summary is disabled when no summary exists
 *     with an explanatory tooltip
 *   - AC2: clicking opens the native OS file-save dialog with a default
 *     filename rendered from the active profile's template
 *   - AC4: write success/failure surfaces inline (toast + ARIA announce)
 *   - AC5: descriptive aria-labels via Story 1.8 helpers; success
 *     announced via the ARIA live region.
 *
 * The component is purely presentational — callers pass a render function
 * for filenames (so the active-profile template can be plugged in) and
 * a fetch function that returns the body content. This keeps it unit-
 * testable without coupling to a specific data store.
 */

import { useCallback, useState } from 'react';

import { Button } from '../ui/Button';
import { useFileSaveDialog } from '../../src/hooks/useFileSaveDialog';
import { useAriaAnnouncer } from '../../src/hooks/useAriaAnnouncer';
import { downloadButtonLabel } from '../../src/utils/a11yLabels';

export interface DownloadButtonsProps {
  /**
   * Default filename suggestion (rendered against the active profile's
   * template). The user can override in the save-dialog.
   */
  transcriptFilename: string;
  summaryFilename: string;
  /** Fetcher for the transcript body. Called when the user confirms save. */
  fetchTranscript: () => Promise<string>;
  /** Fetcher for the summary body. Called when the user confirms save. */
  fetchSummary: () => Promise<string>;
  /** When false, the summary button is disabled with the FR6 tooltip. */
  hasSummary: boolean;
  /** Optional toast surface — receives `(message, kind)`. */
  onToast?: (message: string, kind: 'success' | 'error') => void;
}

export function DownloadButtons({
  transcriptFilename,
  summaryFilename,
  fetchTranscript,
  fetchSummary,
  hasSummary,
  onToast,
}: DownloadButtonsProps) {
  const saveFile = useFileSaveDialog();
  const announce = useAriaAnnouncer();
  const [busy, setBusy] = useState<'transcript' | 'summary' | null>(null);

  const handleDownload = useCallback(
    async (kind: 'transcript' | 'summary', defaultPath: string, fetcher: () => Promise<string>) => {
      setBusy(kind);
      try {
        const target = await saveFile({ defaultPath });
        if (!target) {
          // User cancelled — silent (no toast, no announce). Story 3.5
          // doesn't specify a cancel signal; the dialog's "X" is its own UX.
          return;
        }
        const content = await fetcher();
        const api = window.electronAPI?.fileIO;
        if (!api?.writeText) {
          throw new Error('File-save bridge unavailable — running in web preview?');
        }
        await api.writeText(target, content);
        const label = kind === 'summary' ? 'Summary' : 'Transcript';
        announce(`${label} saved to ${target}`);
        onToast?.(`${label} saved to ${target}`, 'success');
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Unknown error';
        onToast?.(`Could not save file: ${message}`, 'error');
      } finally {
        setBusy(null);
      }
    },
    [saveFile, announce, onToast],
  );

  return (
    <div className="flex items-center gap-3">
      <Button
        variant="secondary"
        aria-label={downloadButtonLabel('transcript')}
        disabled={busy !== null}
        onClick={() => handleDownload('transcript', transcriptFilename, fetchTranscript)}
      >
        {busy === 'transcript' ? 'Saving…' : 'Download transcript'}
      </Button>
      <Button
        variant="secondary"
        aria-label={downloadButtonLabel('summary')}
        disabled={busy !== null || !hasSummary}
        title={hasSummary ? undefined : 'No summary yet — generate from the AI panel'}
        onClick={() => handleDownload('summary', summaryFilename, fetchSummary)}
      >
        {busy === 'summary' ? 'Saving…' : 'Download summary'}
      </Button>
    </div>
  );
}
