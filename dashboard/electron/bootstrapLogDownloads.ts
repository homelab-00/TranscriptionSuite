/**
 * Bootstrap log parser for the download bar (GH-318).
 *
 * Scans container log lines for the start / complete / fail markers of the
 * in-container dependency installs and reports them into the DownloadHub.
 * A log line carries no progress, so the items created here are
 * indeterminate. When the server also reports the same install through its
 * startup events (same id, with real progress) the hub merges both into one
 * item - this parser is then just the fallback signal.
 *
 * Model loading is deliberately not matched: loading weights that are
 * already in the cache is not a download, and real model downloads arrive
 * with byte progress through the startup events.
 */

import type { DownloadHub, DownloadKind } from './downloadHub.js';

interface BootstrapPattern {
  /** Substring to match inside the log line. */
  match: string;
  action: 'start' | 'complete' | 'fail';
  id: string;
  kind: DownloadKind;
  label: string;
}

const BOOTSTRAP_PATTERNS: BootstrapPattern[] = [
  // ── Runtime dependencies ──────────────────────────────────────────────────
  {
    match: '[bootstrap] Installing Python runtime dependencies',
    action: 'start',
    id: 'bootstrap-deps',
    kind: 'server-deps',
    label: 'Runtime dependencies',
  },
  {
    match: '[bootstrap] Runtime dependencies installed',
    action: 'complete',
    id: 'bootstrap-deps',
    kind: 'server-deps',
    label: 'Runtime dependencies',
  },
  // ── faster-whisper ────────────────────────────────────────────────────────
  {
    match: '[bootstrap] Installing faster-whisper family dependencies',
    action: 'start',
    id: 'bootstrap-faster-whisper',
    kind: 'feature-deps',
    label: 'faster-whisper',
  },
  {
    match: '[bootstrap] faster-whisper family dependencies installed',
    action: 'complete',
    id: 'bootstrap-faster-whisper',
    kind: 'feature-deps',
    label: 'faster-whisper',
  },
  {
    match: '[bootstrap] faster-whisper dependency installation failed:',
    action: 'fail',
    id: 'bootstrap-faster-whisper',
    kind: 'feature-deps',
    label: 'faster-whisper',
  },
  // ── NeMo toolkit ──────────────────────────────────────────────────────────
  {
    match: '[bootstrap] Installing NeMo toolkit',
    action: 'start',
    id: 'bootstrap-nemo',
    kind: 'feature-deps',
    label: 'NeMo toolkit',
  },
  {
    match: '[bootstrap] NeMo toolkit installed',
    action: 'complete',
    id: 'bootstrap-nemo',
    kind: 'feature-deps',
    label: 'NeMo toolkit',
  },
  {
    match: '[bootstrap] NeMo toolkit installation failed:',
    action: 'fail',
    id: 'bootstrap-nemo',
    kind: 'feature-deps',
    label: 'NeMo toolkit',
  },
  // ── VibeVoice-ASR ─────────────────────────────────────────────────────────
  {
    match: '[bootstrap] Installing VibeVoice-ASR',
    action: 'start',
    id: 'bootstrap-vibevoice',
    kind: 'feature-deps',
    label: 'VibeVoice-ASR',
  },
  {
    match: '[bootstrap] VibeVoice-ASR support installed',
    action: 'complete',
    id: 'bootstrap-vibevoice',
    kind: 'feature-deps',
    label: 'VibeVoice-ASR',
  },
  {
    match: '[bootstrap] VibeVoice-ASR installation failed:',
    action: 'fail',
    id: 'bootstrap-vibevoice',
    kind: 'feature-deps',
    label: 'VibeVoice-ASR',
  },
];

export function applyBootstrapLogLine(hub: DownloadHub, line: string): void {
  for (const pattern of BOOTSTRAP_PATTERNS) {
    const at = line.indexOf(pattern.match);
    if (at === -1) continue;

    if (pattern.action === 'start') {
      hub.begin({ id: pattern.id, kind: pattern.kind, label: pattern.label, source: 'server' });
    } else if (pattern.action === 'complete') {
      hub.active(pattern.id)?.complete();
    } else {
      const error = line.slice(at + pattern.match.length).trim() || 'Unknown error';
      hub.active(pattern.id)?.fail(error);
    }
    return; // First match wins per line
  }
}
