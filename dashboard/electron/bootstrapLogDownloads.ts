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
import type { StartupEvent } from './startupEventWatcher.js';

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
  // ── VibeVoice-ASR quantization runtime ────────────────────────────────────
  // Listed before the plain VibeVoice-ASR patterns: first match wins per line.
  {
    match: '[bootstrap] VibeVoice-ASR core already installed; installing quantization runtime',
    action: 'start',
    id: 'bootstrap-vibevoice-quant',
    kind: 'feature-deps',
    label: 'VibeVoice-ASR quantization runtime',
  },
  {
    match: '[bootstrap] VibeVoice-ASR quantization runtime dependencies ready',
    action: 'complete',
    id: 'bootstrap-vibevoice-quant',
    kind: 'feature-deps',
    label: 'VibeVoice-ASR quantization runtime',
  },
  {
    match: '[bootstrap] VibeVoice-ASR quantization runtime dependency installation failed:',
    action: 'fail',
    id: 'bootstrap-vibevoice-quant',
    kind: 'feature-deps',
    label: 'VibeVoice-ASR quantization runtime',
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
  // ── FunASR (SenseVoice) ───────────────────────────────────────────────────
  {
    match: '[bootstrap] Installing FunASR for SenseVoice support',
    action: 'start',
    id: 'bootstrap-funasr',
    kind: 'feature-deps',
    label: 'FunASR',
  },
  {
    match: '[bootstrap] FunASR installed',
    action: 'complete',
    id: 'bootstrap-funasr',
    kind: 'feature-deps',
    label: 'FunASR',
  },
  {
    match: '[bootstrap] FunASR installation failed:',
    action: 'fail',
    id: 'bootstrap-funasr',
    kind: 'feature-deps',
    label: 'FunASR',
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

/** Server log line that reports a failed model preload. */
const MODEL_PRELOAD_FAILED_MARKER = 'Model preload failed';

/** How many acted-on lines are remembered for replay detection. */
const SEEN_LINES_MAX = 500;

/**
 * Stateful front of the parser: feeds the hub, and remembers the lines it
 * acted on.
 *
 * The container log stream is restarted with `--since <session start>` (for
 * example when the Logs view subscribes after the container exited), which
 * replays every line. Log lines carry timestamps, so a line seen before is a
 * replay and must not open a second download or raise a second warning.
 */
export class BootstrapLogTracker {
  private readonly seen = new Set<string>();

  constructor(
    private readonly hub: DownloadHub,
    /** Receives server events derived from the log (never download events). */
    private readonly onServerEvent?: (event: StartupEvent) => void,
  ) {}

  /** Feed one container log line. */
  apply(line: string): void {
    const isInstallMarker = BOOTSTRAP_PATTERNS.some((p) => line.includes(p.match));
    const isPreloadFailure = line.includes(MODEL_PRELOAD_FAILED_MARKER);
    if (!isInstallMarker && !isPreloadFailure) return;

    if (this.seen.has(line)) return;
    this.seen.add(line);
    if (this.seen.size > SEEN_LINES_MAX) {
      // Sets iterate in insertion order: drop the oldest remembered line.
      this.seen.delete(this.seen.values().next().value as string);
    }

    if (isInstallMarker) applyBootstrapLogLine(this.hub, line);
    if (isPreloadFailure) this.reportPreloadFailure();
  }

  /**
   * A failed preload is a load failure, not a download, so it goes out as a
   * server warning. On a server whose startup events do not reach the
   * dashboard this log line is the only signal there is; where they do, the
   * server's own event has the same id and simply updates the same record.
   */
  private reportPreloadFailure(): void {
    try {
      this.onServerEvent?.({
        id: 'model-preload-error',
        category: 'warning',
        label:
          'Model preload failed. The server started without a loaded model - check the Logs tab, fix the model selection and restart.',
        status: 'error',
        severity: 'error',
        persistent: true,
      });
    } catch {
      // A listener failure (window gone) must not break log handling.
    }
  }
}
