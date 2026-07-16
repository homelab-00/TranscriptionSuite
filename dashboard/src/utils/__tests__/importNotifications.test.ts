import { describe, it, expect, beforeEach } from 'vitest';
import { useNotificationsStore } from '../../stores/notificationsStore';
import {
  jobDisplayName,
  isNoteJob,
  notifyJobProcessing,
  notifyJobSuccess,
  notifyJobError,
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

beforeEach(() => {
  useNotificationsStore.setState({ notifications: [] });
});

describe('importNotifications helpers', () => {
  it('derives display names from File objects and native paths', () => {
    expect(jobDisplayName(job({}))).toBe('lecture.mp3');
    expect(jobDisplayName(job({ file: '/home/user/audio/talk.wav' }))).toBe('talk.wav');
  });

  it('detects note jobs by notebook type + title or calendar-slot marker', () => {
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
});
