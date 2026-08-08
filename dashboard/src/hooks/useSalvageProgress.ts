/**
 * useSalvageProgress - watches the server for an in-progress salvage of a
 * dropped recording (GH-239) and mirrors it into the notification center.
 *
 * Polls GET /api/status (public; carries job_tracker.salvage + progress):
 * every IDLE_POLL_MS normally, ACTIVE_POLL_MS while a salvage runs, with
 * immediate re-checks on window focus and salvageStore.requestCheck().
 * Mounted exactly once at the app root (App.tsx), like useNotificationBridge.
 *
 * Outcome resolution when a salvage ends, in order:
 *   1. Listed by GET /recent      -> "Recording recovered". This wins over
 *      everything else, including a stale drop marker: a completed salvage
 *      must never be reported as discarded (GH-239).
 *   2. dropRequestedJobId matches -> "Recovery stopped" (no further probes).
 *   3. GET /recent itself failed  -> generic finish. NEVER fall through to
 *      GET /result/{id} on a failed /recent probe: a 200 there marks the job
 *      delivered and would remove a recovered transcript from the recovery
 *      banner before anyone has seen it.
 *   4. GET /result/{id} 410       -> failed, with the server reason.
 *   5. Anything else (403/404: another client's job) -> generic finish.
 */

import { useEffect, useRef } from 'react';

import { apiClient } from '../api/client';
import { jobTrackerFromServerStatus, type SalvageInfo } from '../api/types';
import { useNotificationsStore } from '../stores/notificationsStore';
import { useSalvageStore } from '../stores/salvageStore';

export const IDLE_POLL_MS = 15_000;
export const ACTIVE_POLL_MS = 2_000;

const PHASE_LABELS: Record<string, string> = {
  loading_model: 'Loading model',
  transcribing: 'Transcribing',
  diarizing: 'Identifying speakers',
  transcribing_diarizing: 'Transcribing and identifying speakers',
};

const notifId = (jobId: string) => `salvage-${jobId}`;

/**
 * Poll /api/status until the single job slot frees up. Checks immediately
 * (so an already-free server resolves without sleeping), then every
 * intervalMs until timeoutMs. Missing tracker info counts as free - the UI
 * must not deadlock on an old server.
 */
export async function waitForJobSlotFree(
  timeoutMs = 120_000,
  intervalMs = 1_000,
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    try {
      const tracker = jobTrackerFromServerStatus(await apiClient.getStatus());
      if (!tracker || !tracker.is_busy) return true;
    } catch {
      // Transient fetch failure - keep waiting until the deadline.
    }
    if (Date.now() >= deadline) return false;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

export function useSalvageProgress(): void {
  const activeSalvageRef = useRef<SalvageInfo | null>(null);
  const checkNonce = useSalvageStore((s) => s.checkNonce);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let inFlight = false;

    const resolveOutcome = async (ended: SalvageInfo): Promise<void> => {
      const store = useNotificationsStore.getState();
      const salvageStore = useSalvageStore.getState();
      const id = notifId(ended.job_id);
      // Probe /recent first: it is a side-effect-free read, and a completed
      // salvage must win over a stale drop marker - the user must never be
      // told a recovered transcript was discarded (GH-239).
      let recentProbeOk = false;
      let recoveredInRecent = false;
      try {
        const recentResp = await apiClient.fetchRecentUndelivered();
        recentProbeOk = recentResp.ok;
        const recent: unknown = recentProbeOk ? await recentResp.json() : [];
        recoveredInRecent =
          Array.isArray(recent) &&
          recent.some((j) => (j as { job_id?: string })?.job_id === ended.job_id);
      } catch {
        recentProbeOk = false;
      }
      try {
        if (recoveredInRecent) {
          store.notify({
            id,
            category: 'transcription',
            title: 'Recording recovered',
            detail: 'Transcript available in Main Transcription',
            status: 'complete',
          });
          return;
        }
        if (salvageStore.dropRequestedJobId === ended.job_id) {
          store.notify({
            id,
            category: 'transcription',
            title: 'Recovery stopped',
            detail: 'Recording saved - retry available',
            status: 'complete',
          });
          return;
        }
        // Only probe /result when the /recent probe actually succeeded: a
        // 200 from /result marks the job delivered and would remove a
        // recovered transcript from the recovery banner.
        if (!recentProbeOk) {
          store.notify({
            id,
            category: 'transcription',
            title: 'Recovery finished',
            detail: '',
            status: 'complete',
          });
          return;
        }
        const resp = await apiClient.fetchTranscriptionResult(ended.job_id);
        if (resp.status === 410) {
          const body = (await resp.json().catch(() => null)) as { detail?: string } | null;
          store.notify({
            id,
            category: 'transcription',
            title: 'Recovery failed',
            detail: '',
            status: 'error',
            error: body?.detail ?? 'The salvage transcription failed',
          });
          return;
        }
        store.notify({
          id,
          category: 'transcription',
          title: 'Recovery finished',
          detail: '',
          status: 'complete',
        });
      } catch {
        store.notify({
          id,
          category: 'transcription',
          title: 'Recovery finished',
          detail: '',
          status: 'complete',
        });
      } finally {
        if (salvageStore.dropRequestedJobId === ended.job_id) {
          salvageStore.clearDropRequested();
        }
        salvageStore.markSalvageEnded();
      }
    };

    const tick = async (): Promise<void> => {
      if (inFlight) return;
      inFlight = true;
      let delay = activeSalvageRef.current ? ACTIVE_POLL_MS : IDLE_POLL_MS;
      try {
        const tracker = jobTrackerFromServerStatus(await apiClient.getStatus());
        if (disposed) return;
        const salvage = tracker?.salvage ?? null;
        if (salvage) {
          activeSalvageRef.current = salvage;
          const progress = tracker?.progress ?? null;
          const percent =
            progress && progress.total > 0
              ? Math.round((progress.current / progress.total) * 100)
              : undefined;
          const phase = progress?.phase ? (PHASE_LABELS[progress.phase] ?? progress.phase) : null;
          useNotificationsStore.getState().notify({
            id: notifId(salvage.job_id),
            category: 'transcription',
            title: 'Recovering interrupted recording',
            detail: [salvage.client_name, phase].filter(Boolean).join(' - '),
            status: 'active',
            ...(percent !== undefined ? { progress: percent } : {}),
          });
          delay = ACTIVE_POLL_MS;
        } else if (activeSalvageRef.current) {
          const ended = activeSalvageRef.current;
          activeSalvageRef.current = null;
          await resolveOutcome(ended);
          delay = IDLE_POLL_MS;
        }
      } catch {
        // Server unreachable - app-level indicators cover it; retry next tick.
      } finally {
        inFlight = false;
      }
      if (timer) clearTimeout(timer);
      if (!disposed) {
        timer = setTimeout(() => void tick(), delay);
      }
    };

    void tick();
    const onFocus = () => {
      if (timer) clearTimeout(timer);
      void tick();
    };
    window.addEventListener('focus', onFocus);
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      window.removeEventListener('focus', onFocus);
    };
  }, [checkNonce]);
}
