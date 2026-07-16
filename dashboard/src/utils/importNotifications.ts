/**
 * Notification emitters for the unified import queue. Called from
 * importQueueStore.processQueue so ALL four job types (session-normal,
 * session-auto, notebook-normal, notebook-auto) are tracked uniformly -
 * session jobs have no callback mechanism, so this is the single hook point.
 *
 * A "note job" is an AddNoteModal submission: a notebook-NORMAL job carrying a
 * calendar-slot marker (options.title and/or options.file_created_at). Only
 * AddNoteModal enqueues notebook-normal with those fields; the plain
 * NotebookView import tab passes neither. Folder-watch auto-imports are
 * notebook-AUTO and always stamp options.file_created_at, so they are excluded
 * from the note class by the type check - they are ordinary imports, not notes.
 */

import { apiClient } from '../api/client';
import { useNotificationsStore } from '../stores/notificationsStore';
import type { UnifiedImportJob } from '../stores/importQueueStore';

export function jobDisplayName(job: UnifiedImportJob): string {
  return typeof job.file === 'string' ? (job.file.split(/[\\/]/).pop() ?? job.file) : job.file.name;
}

export function isNoteJob(job: UnifiedImportJob): boolean {
  // Restricted to notebook-NORMAL: AddNoteModal is the only site that enqueues
  // notebook-normal with a title or calendar slot; the plain NotebookView
  // ImportTab passes neither. Folder-watch is notebook-AUTO and always stamps
  // file_created_at, so it must be excluded here or every auto-import would be
  // mislabeled a note. A note with a cleared title AND no slot is
  // indistinguishable at the queue level and falls back to the import category
  // - accepted cosmetic edge.
  return (
    job.type === 'notebook-normal' &&
    ((typeof job.options?.title === 'string' && job.options.title.length > 0) ||
      job.options?.file_created_at !== undefined)
  );
}

function eventId(job: UnifiedImportJob): string {
  return `import-${job.id}`;
}

/** Note display label: the user-supplied title, or the filename for untitled notes. */
function noteLabel(job: UnifiedImportJob): string {
  const title = job.options?.title?.trim();
  return title && title.length > 0 ? title : jobDisplayName(job);
}

export function notifyJobProcessing(job: UnifiedImportJob): void {
  useNotificationsStore.getState().notify({
    id: eventId(job),
    category: isNoteJob(job) ? 'note' : 'import',
    title: isNoteJob(job)
      ? `Creating note "${noteLabel(job)}"...`
      : `Importing "${jobDisplayName(job)}"...`,
    detail: 'Transcribing audio',
    status: 'active',
  });
}

export function notifyJobSuccess(job: UnifiedImportJob): void {
  const isSession = job.type === 'session-normal' || job.type === 'session-auto';
  useNotificationsStore.getState().notify({
    id: eventId(job),
    category: isNoteJob(job) ? 'note' : 'import',
    title: isNoteJob(job)
      ? `Note created - ${noteLabel(job)}`
      : `Import complete - ${jobDisplayName(job)}`,
    // A session job with no outputFilename resolved via the duplicate-dialog
    // use_existing/cancel path - nothing was written, so an empty string is the
    // honest detail. The empty string is deliberate, not undefined: it merges
    // over (clears) the stale active-phase 'Transcribing audio' detail, since
    // the store's stripUndefined drops only undefined and both detail surfaces
    // hide an empty string.
    detail: isSession
      ? job.outputFilename
        ? `Saved ${job.outputFilename}`
        : ''
      : 'Saved to the Audio Notebook',
    status: 'complete',
  });
}

export function notifyJobError(job: UnifiedImportJob, error: string): void {
  useNotificationsStore.getState().notify({
    id: eventId(job),
    category: isNoteJob(job) ? 'note' : 'import',
    title: isNoteJob(job)
      ? `Note creation failed - ${noteLabel(job)}`
      : `Import failed - ${jobDisplayName(job)}`,
    status: 'error',
    error,
  });
}

/**
 * Session-import completions DO have the transcript text in scope (inside
 * processSessionJob) - attach it so every completed transcription carries a
 * collapsible record, mirroring the longform and notebook paths.
 */
export function attachSessionTranscript(job: UnifiedImportJob, text: string): void {
  const trimmed = text.trim();
  if (!trimmed) return;
  useNotificationsStore.getState().updateNotification(eventId(job), { transcript: trimmed });
}

/**
 * Notebook completions carry no transcript text (only recording_id) - fetch
 * it lazily and attach it to the record as a collapsible transcript. Uses
 * apiClient (absolute base URL): a relative fetch dies on file:// (GH-202).
 */
export function attachNotebookTranscript(job: UnifiedImportJob, recordingId: number): void {
  void apiClient
    .getRecordingTranscription(recordingId)
    .then((t) => {
      const text = t.segments
        .map((s) => s.text)
        .join('\n')
        .trim();
      if (text) {
        useNotificationsStore.getState().updateNotification(eventId(job), { transcript: text });
      }
    })
    .catch(() => {
      // Best-effort: the transcript stays viewable in the Notebook itself.
    });
}
