/**
 * Notification emitters for the unified import queue. Called from
 * importQueueStore.processQueue so ALL four job types (session-normal,
 * session-auto, notebook-normal, notebook-auto) are tracked uniformly -
 * session jobs have no callback mechanism, so this is the single hook point.
 *
 * A "note job" is an AddNoteModal submission: a notebook-typed job carrying
 * options.title (plain notebook imports never set a title).
 */

import { apiClient } from '../api/client';
import { useNotificationsStore } from '../stores/notificationsStore';
import type { UnifiedImportJob } from '../stores/importQueueStore';

export function jobDisplayName(job: UnifiedImportJob): string {
  return typeof job.file === 'string' ? (job.file.split(/[\\/]/).pop() ?? job.file) : job.file.name;
}

export function isNoteJob(job: UnifiedImportJob): boolean {
  // AddNoteModal jobs carry options.title and/or options.file_created_at
  // (calendar slot); NotebookView plain ImportTab passes neither. A note
  // with a cleared title AND no slot is indistinguishable at the queue level
  // and falls back to the import category - accepted cosmetic edge.
  return (
    job.type.startsWith('notebook') &&
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
    detail: isSession
      ? job.outputFilename
        ? `Saved ${job.outputFilename}`
        : 'Saved to the output folder'
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
