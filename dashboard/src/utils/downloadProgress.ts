/**
 * Pure progress math and formatting for the universal download bar (GH-318).
 *
 * The one rule that matters: a percent is never invented. An item is
 * determinate only when it reports bytes or an honest coarse fraction, and an
 * aggregate over several items never mixes the two into a single number.
 */

export interface DownloadAggregate {
  /** Items still downloading (failed and finished ones are left out). */
  activeCount: number;
  /** Active items that report a measurable fraction. */
  determinateCount: number;
  /** 0-1, or null when the aggregate bar must be indeterminate. */
  fraction: number | null;
  bytesDone?: number;
  bytesTotal?: number;
  bytesPerSecond?: number;
  etaSeconds?: number;
}

/** Human-readable size, matching the server-side `_format_bytes`. */
export function formatBytes(bytes: number): string {
  let value = bytes;
  for (const unit of ['B', 'KB', 'MB', 'GB']) {
    if (value < 1024) {
      return unit === 'B' ? `${Math.trunc(value)} ${unit}` : `${value.toFixed(1)} ${unit}`;
    }
    value /= 1024;
  }
  return `${value.toFixed(1)} TB`;
}

/** Whole seconds rendered with the two most significant units. */
export function formatDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

/** 0-1 for a determinate item, null for an indeterminate one. */
export function itemFraction(item: DownloadItem): number | null {
  if (item.bytesTotal !== undefined && item.bytesTotal > 0 && item.bytesDone !== undefined) {
    return Math.min(1, Math.max(0, item.bytesDone / item.bytesTotal));
  }
  if (item.percent !== undefined) return Math.min(1, Math.max(0, item.percent / 100));
  return null;
}

function hasByteTotal(item: DownloadItem): boolean {
  return item.bytesTotal !== undefined && item.bytesTotal > 0 && item.bytesDone !== undefined;
}

export function aggregateDownloads(items: readonly DownloadItem[]): DownloadAggregate {
  const active = items.filter((i) => i.status === 'active');
  const fractions = active.map(itemFraction);
  const determinateCount = fractions.filter((f) => f !== null).length;
  const base = { activeCount: active.length, determinateCount };

  if (active.length === 0) return { ...base, fraction: null };

  if (active.every(hasByteTotal)) {
    const bytesDone = active.reduce((sum, i) => sum + (i.bytesDone ?? 0), 0);
    const bytesTotal = active.reduce((sum, i) => sum + (i.bytesTotal ?? 0), 0);
    const bytesPerSecond = active.reduce((sum, i) => sum + (i.bytesPerSecond ?? 0), 0);
    return {
      ...base,
      fraction: Math.min(1, bytesDone / bytesTotal),
      bytesDone,
      bytesTotal,
      ...(bytesPerSecond > 0
        ? {
            bytesPerSecond,
            etaSeconds: Math.round(Math.max(0, bytesTotal - bytesDone) / bytesPerSecond),
          }
        : {}),
    };
  }

  if (determinateCount === active.length) {
    const sum = fractions.reduce<number>((acc, f) => acc + (f ?? 0), 0);
    return { ...base, fraction: sum / active.length };
  }

  // At least one indeterminate item: no honest single number exists.
  const withBytes = active.filter((i) => i.bytesDone !== undefined);
  return {
    ...base,
    fraction: null,
    ...(withBytes.length > 0
      ? { bytesDone: withBytes.reduce((sum, i) => sum + (i.bytesDone ?? 0), 0) }
      : {}),
  };
}

/** "42% · 1.0 GB / 2.0 GB · 12.0 MB/s · 2m 10s left" - only the parts that are known. */
export function describeProgress(progress: {
  fraction: number | null;
  bytesDone?: number;
  bytesTotal?: number;
  bytesPerSecond?: number;
  etaSeconds?: number;
}): string {
  const parts: string[] = [];
  if (progress.fraction !== null) parts.push(`${Math.round(progress.fraction * 100)}%`);
  if (progress.bytesDone !== undefined && progress.bytesTotal !== undefined) {
    parts.push(`${formatBytes(progress.bytesDone)} / ${formatBytes(progress.bytesTotal)}`);
  } else if (progress.bytesDone !== undefined && progress.bytesDone > 0) {
    parts.push(formatBytes(progress.bytesDone));
  }
  if (progress.bytesPerSecond !== undefined && progress.bytesPerSecond > 0) {
    parts.push(`${formatBytes(progress.bytesPerSecond)}/s`);
  }
  if (progress.etaSeconds !== undefined) parts.push(`${formatDuration(progress.etaSeconds)} left`);
  return parts.join(' · ');
}
