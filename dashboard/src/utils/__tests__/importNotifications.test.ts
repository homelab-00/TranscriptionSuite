import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useNotificationsStore } from '../../stores/notificationsStore';

// Hoisted so the vi.mock factory below can reference it (vitest lifts mocks
// above imports). attachNotebookTranscript resolves the transcript through
// apiClient.getRecordingTranscription; the mock lets us drive its result.
const { mockGetRecordingTranscription } = vi.hoisted(() => ({
  mockGetRecordingTranscription: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  apiClient: {
    getRecordingTranscription: (...args: unknown[]) => mockGetRecordingTranscription(...args),
  },
}));

import {
  jobDisplayName,
  isNoteJob,
  notifyJobProcessing,
  notifyJobSuccess,
  notifyJobError,
  attachSessionTranscript,
  attachNotebookTranscript,
} from '../importNotifications';
import type { UnifiedImportJob } from '../../stores/importQueueStore';

function job(overrides: Partial<UnifiedImportJob>): UnifiedImportJob {
  return {
    id: 'job-1',
    file: new File(['x'], 'lecture.mp3'),
    type: 'session-normal',
    status: 'pending',
    ...overrides,
  } as UnifiedImportJob;
}

/** Flush the microtask queue so a resolved/rejected promise chain settles. */
async function flushMicrotasks(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

beforeEach(() => {
  useNotificationsStore.setState({ notifications: [] });
  mockGetRecordingTranscription.mockReset();
});

describe('importNotifications helpers', () => {
  it('derives display names from File objects and native paths', () => {
    expect(jobDisplayName(job({}))).toBe('lecture.mp3');
    expect(jobDisplayName(job({ file: '/home/user/audio/talk.wav' }))).toBe('talk.wav');
  });

  it('detects note jobs by notebook-normal type + title or calendar-slot marker', () => {
    expect(isNoteJob(job({}))).toBe(false);
    expect(isNoteJob(job({ type: 'notebook-normal' }))).toBe(false);
    expect(isNoteJob(job({ type: 'notebook-normal', options: { title: 'My note' } }))).toBe(true);
    expect(
      isNoteJob(
        job({ type: 'notebook-normal', options: { file_created_at: '2026-07-16T10:00:00' } }),
      ),
    ).toBe(true);
    expect(isNoteJob(job({ type: 'session-normal', options: { title: 'Not a note' } }))).toBe(
      false,
    );
    // Folder-watch auto-imports are notebook-AUTO and always stamp
    // file_created_at, but they are ordinary imports, not notes.
    expect(
      isNoteJob(
        job({ type: 'notebook-auto', options: { file_created_at: '2026-07-16T10:00:00' } }),
      ),
    ).toBe(false);
  });

  it('tracks a session import through processing, success', () => {
    const j = job({});
    notifyJobProcessing(j);
    let n = useNotificationsStore.getState().notifications;
    expect(n).toHaveLength(1);
    expect(n[0].category).toBe('import');
    expect(n[0].status).toBe('active');
    notifyJobSuccess(job({ status: 'success', outputFilename: 'lecture.srt' }));
    n = useNotificationsStore.getState().notifications;
    expect(n).toHaveLength(1);
    expect(n[0].status).toBe('complete');
    expect(n[0].detail).toContain('lecture.srt');
  });

  it('tracks a note job with note category and title', () => {
    const j = job({ type: 'notebook-normal', options: { title: 'Meeting notes' } });
    notifyJobProcessing(j);
    const n = useNotificationsStore.getState().notifications[0];
    expect(n.category).toBe('note');
    expect(n.title).toContain('Meeting notes');
  });

  it('records job failures', () => {
    const j = job({});
    notifyJobProcessing(j);
    notifyJobError(j, 'server exploded');
    const n = useNotificationsStore.getState().notifications[0];
    expect(n.status).toBe('error');
    expect(n.error).toBe('server exploded');
  });

  it('attachSessionTranscript attaches trimmed text to the newest entry', () => {
    const j = job({});
    notifyJobProcessing(j);
    attachSessionTranscript(j, '  hello world  ');
    expect(useNotificationsStore.getState().notifications[0].transcript).toBe('hello world');
  });

  it('attachSessionTranscript is a no-op on whitespace-only text', () => {
    const j = job({});
    notifyJobProcessing(j);
    attachSessionTranscript(j, '   \n  ');
    expect(useNotificationsStore.getState().notifications[0].transcript).toBeUndefined();
  });

  it('attachNotebookTranscript fetches and joins segments onto the entry', async () => {
    mockGetRecordingTranscription.mockResolvedValue({
      recording_id: 7,
      segments: [{ text: 'a' }, { text: 'b' }],
    });
    const j = job({ type: 'notebook-normal' });
    notifyJobProcessing(j);
    attachNotebookTranscript(j, 7);
    await flushMicrotasks();
    expect(mockGetRecordingTranscription).toHaveBeenCalledWith(7);
    expect(useNotificationsStore.getState().notifications[0].transcript).toBe('a\nb');
  });

  it('attachNotebookTranscript swallows a rejection and leaves no transcript', async () => {
    mockGetRecordingTranscription.mockRejectedValue(new Error('fetch failed'));
    const j = job({ type: 'notebook-normal' });
    notifyJobProcessing(j);
    expect(() => attachNotebookTranscript(j, 7)).not.toThrow();
    await flushMicrotasks();
    expect(useNotificationsStore.getState().notifications[0].transcript).toBeUndefined();
  });
});
