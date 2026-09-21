import { useEffect, useRef, useState } from 'react';
import { useAdminStatus } from './useAdminStatus';
import { jobTrackerFromAdminStatus } from '../api/types';
import { describeJobProgress, summarizeJobProgress } from '../services/jobProgress';
import type { JobProgressDetails } from '../services/jobProgress';

const STALL_AFTER_SECONDS = 120;

/**
 * Live label + structured details + stall flag for the single active server
 * job (GH-211). Polls faster (3s) while a job is running; the stall flag
 * trips after 120s without any change in (current, total, phase).
 */
export function useJobProgress(active: boolean): {
  label: string;
  details: JobProgressDetails;
  stalled: boolean;
} {
  const admin = useAdminStatus(active ? 3_000 : 10_000);
  const tracker = jobTrackerFromAdminStatus(admin.status);
  const [, forceTick] = useState(0);
  const lastChangeRef = useRef<{ key: string; at: number }>({ key: '', at: Date.now() / 1000 });
  const wasActiveRef = useRef(false);

  // re-render every second while active so elapsed/ETA tick smoothly
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => forceTick((n) => n + 1), 1_000);
    return () => clearInterval(t);
  }, [active]);

  const now = Date.now() / 1000;
  const key = JSON.stringify([
    tracker?.progress?.current,
    tracker?.progress?.total,
    tracker?.progress?.phase,
  ]);
  // The host view never unmounts, so this hook outlives individual jobs. Start
  // the stall clock when a job becomes active; otherwise the idle key keeps a
  // timestamp from mount (or from the end of the previous job) and every job
  // started 2+ idle minutes later reads as stalled from its first frame.
  const becameActive = active && !wasActiveRef.current;
  wasActiveRef.current = active;
  if (becameActive || key !== lastChangeRef.current.key) {
    lastChangeRef.current = { key, at: now };
  }
  const stalled = active && now - lastChangeRef.current.at > STALL_AFTER_SECONDS;
  const label = describeJobProgress(tracker?.progress ?? null, tracker?.started_at ?? null, now);
  const details = summarizeJobProgress(tracker?.progress ?? null, tracker?.started_at ?? null, now);
  return { label, details, stalled: !!stalled };
}
