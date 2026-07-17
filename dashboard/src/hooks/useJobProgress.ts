import { useEffect, useRef, useState } from 'react';
import { useAdminStatus } from './useAdminStatus';
import { jobTrackerFromAdminStatus } from '../api/types';
import { describeJobProgress } from '../services/jobProgress';

const STALL_AFTER_SECONDS = 120;

/**
 * Live label + stall flag for the single active server job (GH-211).
 * Polls faster (3s) while a job is running; the stall flag trips after 120s
 * without any change in (current, total, phase).
 */
export function useJobProgress(active: boolean): { label: string; stalled: boolean } {
  const admin = useAdminStatus(active ? 3_000 : 10_000);
  const tracker = jobTrackerFromAdminStatus(admin.status);
  const [, forceTick] = useState(0);
  const lastChangeRef = useRef<{ key: string; at: number }>({ key: '', at: Date.now() / 1000 });

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
  if (key !== lastChangeRef.current.key) {
    lastChangeRef.current = { key, at: now };
  }
  const stalled = active && now - lastChangeRef.current.at > STALL_AFTER_SECONDS;
  const label = describeJobProgress(tracker?.progress ?? null, tracker?.started_at ?? null, now);
  return { label, stalled: !!stalled };
}
