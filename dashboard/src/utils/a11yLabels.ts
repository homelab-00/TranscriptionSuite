/**
 * Descriptive accessibility-label utilities (Issue #104, Story 1.8 AC3).
 *
 * Centralises label strings so screen-reader text is consistent across
 * the dashboard. Bare `<button>Download</button>` should never ship —
 * use `downloadButtonLabel('transcript' | 'summary')` instead.
 *
 * If you need a label not covered here, ADD it here rather than inlining
 * — that way the FR53 vocabulary stays in one place.
 */

export type DownloadKind = 'transcript' | 'summary' | 'audio';

export function downloadButtonLabel(kind: DownloadKind): string {
  switch (kind) {
    case 'summary':
      return 'Download summary as plain text';
    case 'audio':
      return 'Download recording audio file';
    case 'transcript':
    default:
      return 'Download transcript as plain text';
  }
}

export type RetryKind = 'summary' | 'export' | 'webhook';

export function retryButtonLabel(kind: RetryKind): string {
  switch (kind) {
    case 'summary':
      return 'Retry AI summary';
    case 'export':
      return 'Retry transcript export';
    case 'webhook':
      return 'Retry webhook delivery';
  }
}

export function folderPickerButtonLabel(target: string): string {
  return `Choose ${target} folder`;
}
