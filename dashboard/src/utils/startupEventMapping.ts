/**
 * Pure mapping from startup-events.jsonl payloads (activity:event IPC) to
 * notifications-store inputs. Two outputs per event:
 *  - mapStartupEvent: an individual log entry (downloads, warnings) or null
 *  - serverStartPatch: a patch for the aggregate "Starting server" card
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

/** Coarse stage weights for the aggregate progress bar (server stages emit no percent). */
const STAGE_PROGRESS: Record<string, number> = {
  'bootstrap-env': 5,
  'bootstrap-deps': 35,
  'lifespan-start': 55,
  'lifespan-gpu': 65,
  'server-ready': 100,
};

function terminalStatus(status?: string): 'active' | 'complete' | 'error' {
  return status === 'complete' || status === 'error' ? status : 'active';
}

export function mapStartupEvent(event: StartupActivityEventLike): NotifyInput | null {
  if (event.category === 'download') {
    const status = terminalStatus(event.status);
    return {
      id: event.id,
      category: 'download',
      title: event.label,
      status,
      ...(event.progress !== undefined ? { progress: event.progress } : {}),
      ...(event.totalSize ? { totalSize: event.totalSize } : {}),
      ...(event.downloadedSize ? { downloadedSize: event.downloadedSize } : {}),
      ...(event.detail ? { detail: event.detail } : {}),
      ...(status === 'error' ? { error: event.label } : {}),
    };
  }
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
  // category === 'server' stage events feed only the aggregate card.
  return null;
}

export function serverStartPatch(event: StartupActivityEventLike): NotifyInput | null {
  if (event.id === 'server-ready') {
    return {
      id: SERVER_START_ID,
      category: 'server',
      title: 'Server ready',
      status: 'complete',
      progress: 100,
    };
  }
  if (event.category === 'server') {
    const progress = STAGE_PROGRESS[event.id];
    return {
      id: SERVER_START_ID,
      category: 'server',
      title: 'Starting server...',
      status: 'active',
      detail: event.label,
      ...(progress !== undefined ? { progress } : {}),
    };
  }
  // Model downloads/loads advance the aggregate bar through the 65-95 band.
  if (event.id.startsWith('model-load-') && event.progress !== undefined) {
    return {
      id: SERVER_START_ID,
      category: 'server',
      title: 'Starting server...',
      status: 'active',
      detail: event.label,
      progress: 65 + Math.round((event.progress / 100) * 30),
    };
  }
  if (event.id === 'bootstrap-deps') {
    return {
      id: SERVER_START_ID,
      category: 'server',
      title: 'Starting server...',
      status: 'active',
      detail: event.label,
      progress: STAGE_PROGRESS['bootstrap-deps'],
    };
  }
  return null;
}
