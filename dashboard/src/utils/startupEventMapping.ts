/**
 * Pure mapping from startup-events.jsonl payloads (activity:event IPC) to
 * notifications-store inputs. Two outputs per event:
 *  - mapStartupEvent: an individual log entry (warnings, info) or null
 *  - serverStartPatch: a patch for the "Starting server" card (stage text only)
 * Kept side-effect-free so vitest covers the mapping without IPC mocks.
 */

import type { NotifyInput } from '../stores/notificationsStore';

/** Shape of activity:event payloads (see electron/startupEventWatcher.ts). */
export interface StartupActivityEventLike {
  id: string;
  category: string;
  label: string;
  status?: string;
  progress?: number;
  totalSize?: string;
  downloadedSize?: string;
  detail?: string;
  severity?: string;
  persistent?: boolean;
  phase?: string;
  durationMs?: number;
}

export const SERVER_START_ID = 'server-start';

export function mapStartupEvent(event: StartupActivityEventLike): NotifyInput | null {
  // category === 'download' is deliberately not mapped: the main process
  // routes those into the download bar (GH-318).
  if (event.category === 'warning' || event.category === 'info') {
    return {
      id: event.id,
      category: 'server',
      title: event.label,
      status: event.severity === 'error' ? 'error' : 'complete',
      ...(event.severity === 'warning' || event.severity === 'error'
        ? { severity: event.severity }
        : {}),
      ...(event.detail ? { detail: event.detail } : {}),
      ...(event.severity === 'error' ? { error: event.label } : {}),
    };
  }
  // category === 'server' stage events feed only the aggregate card;
  // downloads feed only the download bar.
  return null;
}

export function serverStartPatch(event: StartupActivityEventLike): NotifyInput | null {
  if (event.id === 'server-ready') {
    return {
      id: SERVER_START_ID,
      category: 'server',
      title: 'Server ready',
      // Clear the last stage label ('Loading model...' etc.) so it does not
      // linger under the terminal 'Server ready' title.
      detail: '',
      status: 'complete',
    };
  }
  // The card carries the current stage as its detail and no percent: server
  // stages are not measurable, and a download's real progress is shown by
  // the download bar.
  if (event.category === 'server') {
    return {
      id: SERVER_START_ID,
      category: 'server',
      title: 'Starting server...',
      status: 'active',
      detail: event.label,
    };
  }
  // Loading model weights into memory is a startup stage, not a download.
  if (
    event.id.startsWith('model-load-') &&
    event.status !== 'complete' &&
    event.status !== 'error' &&
    (event.phase === 'load' || event.progress === 100)
  ) {
    return {
      id: SERVER_START_ID,
      category: 'server',
      title: 'Starting server...',
      status: 'active',
      detail: event.label,
    };
  }
  return null;
}
