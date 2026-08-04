/**
 * Retroactive diarization job service (GH-279).
 *
 * Starts a diarize job on an already-transcribed notebook recording and
 * resolves when the server-side job finishes. Uses the same
 * poll-/api/admin/status pattern as the import queue (importQueueStore):
 * the server has no push channel for notebook jobs, and the job tracker
 * result slot is cleared when the NEXT job starts, so polling every few
 * seconds is both necessary and sufficient.
 */
import { apiClient } from '../api/client';
import { jobTrackerFromAdminStatus } from '../api/types';
import type { JobTrackerResult } from '../api/types';

const POLL_INTERVAL_MS = 5000;
const MAX_POLL_HOURS = 24;
const MAX_POLLS = Math.ceil((MAX_POLL_HOURS * 60 * 60 * 1000) / POLL_INTERVAL_MS);

/**
 * Start retroactive diarization for a recording and wait for completion.
 *
 * Resolves with the job tracker result (check `.error` for job-level
 * failure). Rejects when the job cannot be started (HTTP error from the
 * diarize endpoint), when the job is lost (server restart), or on timeout.
 */
export async function diarizeRecordingAndWait(recordingId: number): Promise<JobTrackerResult> {
  const { job_id: serverJobId } = await apiClient.diarizeRecording(recordingId);

  for (let i = 0; i < MAX_POLLS; i++) {
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));

    try {
      const status = await apiClient.getAdminStatus();
      const jobTracker = jobTrackerFromAdminStatus(status);

      if (jobTracker?.is_busy && jobTracker?.active_job_id === serverJobId) continue;

      const result = jobTracker?.result ?? undefined;
      if (result && result.job_id === serverJobId) return result;

      if (!jobTracker?.is_busy && (!result || result.job_id !== serverJobId)) {
        throw new Error('Diarization job lost — server may have restarted');
      }
    } catch (err) {
      if (err instanceof Error && err.message.includes('job lost')) throw err;
      console.warn('Diarize poll error (will retry):', err);
    }
  }
  throw new Error(`Diarization timed out after ${MAX_POLL_HOURS} hours`);
}
