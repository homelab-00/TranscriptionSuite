/**
 * Maps server startup-events.jsonl lines into DownloadHub items (GH-318).
 *
 * Pure: takes the hub as an argument so both the Docker events watcher and
 * the bare-metal MLX one can share it, and vitest can cover it without IPC.
 *
 * An item is created only on evidence of an actual download - a `download`
 * phase, numeric byte counts, or a sub-100 percent - so loading a model that
 * is already in the cache never raises the download bar.
 *
 * Understands two event shapes:
 *  - current: `kind`, `name`, `phase` ('download' | 'load'), numeric
 *    `downloadedBytes` / `totalBytes`
 *  - legacy (older server images): `progress` 0-100 plus pre-formatted
 *    `downloadedSize` / `totalSize` strings
 */

import type { DownloadHub, DownloadKind, DownloadSource } from './downloadHub.js';
import type { StartupEvent } from './startupEventWatcher.js';

/** Emitted with category `download` by older servers, but it is a load failure. */
const NOT_A_DOWNLOAD_IDS = new Set(['model-preload-error']);

const KNOWN_KINDS: readonly DownloadKind[] = [
  'server-image',
  'sidecar-image',
  'server-deps',
  'feature-deps',
  'model',
  'live-model',
  'diarization-model',
  'alignment-model',
  'ggml-model',
  'whisper-server',
  'app-update',
  'export',
];

function resolveKind(event: StartupEvent): DownloadKind {
  if (event.kind && (KNOWN_KINDS as readonly string[]).includes(event.kind)) {
    return event.kind as DownloadKind;
  }
  if (event.id === 'bootstrap-deps') return 'server-deps';
  if (event.id.startsWith('bootstrap-')) return 'feature-deps';
  return 'model';
}

/** "Downloading parakeet..." -> "parakeet" (legacy events carry only a status line). */
function nameFromLabel(label: string): string {
  const stripped = label
    .replace(/^(Downloading|Loading|Installing)\s+/i, '')
    .replace(/\.{3}$/, '')
    .trim();
  return stripped || label;
}

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function applyServerDownloadEvent(
  hub: DownloadHub,
  event: StartupEvent,
  /** Which server the event came from: the container, or the bare-metal one. */
  source: DownloadSource = 'server',
): void {
  if (event.category !== 'download') return;
  if (NOT_A_DOWNLOAD_IDS.has(event.id)) return;

  const running = hub.active(event.id);

  if (event.status === 'complete') {
    running?.complete();
    return;
  }
  if (event.status === 'error') {
    running?.fail(event.error || event.label || 'Download failed');
    return;
  }

  const hasBytes = isNumber(event.downloadedBytes) || isNumber(event.totalBytes);
  const legacyPercent = isNumber(event.progress) ? event.progress : undefined;
  const isDownloading =
    event.phase === 'download' ||
    (event.phase !== 'load' && (hasBytes || (legacyPercent !== undefined && legacyPercent < 100)));

  if (!isDownloading) {
    // The bytes are in; the server is now loading the weights into memory.
    if (running && (event.phase === 'load' || (legacyPercent ?? 0) >= 100)) running.complete();
    return;
  }

  const handle = hub.begin({
    id: event.id,
    kind: resolveKind(event),
    label: event.name || nameFromLabel(event.label),
    source,
  });

  if (hasBytes) {
    handle.update({
      bytesDone: isNumber(event.downloadedBytes) ? event.downloadedBytes : undefined,
      bytesTotal: isNumber(event.totalBytes) ? event.totalBytes : undefined,
      ...(event.detail ? { detail: event.detail } : {}),
    });
    return;
  }

  const sizeText =
    event.downloadedSize && event.totalSize
      ? `${event.downloadedSize} / ${event.totalSize}`
      : undefined;
  const detail = event.detail || sizeText;
  if (legacyPercent !== undefined || detail) {
    handle.update({
      ...(legacyPercent !== undefined ? { percent: legacyPercent } : {}),
      ...(detail ? { detail } : {}),
    });
  }
}
