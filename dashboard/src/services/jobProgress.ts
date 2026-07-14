import type { JobTrackerProgress } from '../api/types';

/** Format seconds as mm:ss, or h:mm:ss over an hour. */
export function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
    : `${m}:${String(sec).padStart(2, '0')}`;
}

const PHASE_LABELS: Record<string, string> = {
  loading_model: 'Loading model...',
  transcribing: 'Transcribing',
  diarizing: 'Identifying speakers',
  transcribing_diarizing: 'Transcribing + identifying speakers',
};

/**
 * Human label for an in-flight transcription job (GH-211).
 * `startedAt` is epoch seconds from the server tracker; `nowSeconds` is
 * injected for testability. Duration-reporting phases render position,
 * percent, elapsed and a heuristic ETA; opaque phases (diarization) render
 * phase + elapsed only.
 */
export function describeJobProgress(
  progress: JobTrackerProgress | null | undefined,
  startedAt: number | null | undefined,
  nowSeconds: number,
): string {
  const elapsed = startedAt ? Math.max(0, nowSeconds - startedAt) : null;
  const elapsedPart = elapsed !== null ? ` (elapsed ${formatClock(elapsed)})` : '';
  const phase = progress?.phase ?? null;

  if (phase === 'loading_model') return 'Loading model...';

  if (
    (phase === 'transcribing' || phase === 'transcribing_diarizing') &&
    progress &&
    progress.total > 0
  ) {
    const pct = Math.min(100, Math.round((progress.current / progress.total) * 100));
    let eta = '';
    if (
      elapsed !== null &&
      elapsed > 5 &&
      progress.current > 0 &&
      progress.current < progress.total
    ) {
      const remaining = ((progress.total - progress.current) * elapsed) / progress.current;
      eta = `, ETA ${formatClock(remaining)}`;
    }
    const verb = PHASE_LABELS[phase];
    return `${verb} ${formatClock(progress.current)} / ${formatClock(progress.total)} (${pct}%${
      elapsed !== null ? `, elapsed ${formatClock(elapsed)}` : ''
    }${eta})`;
  }

  if (phase && PHASE_LABELS[phase]) return `${PHASE_LABELS[phase]}...${elapsedPart}`;

  if (progress && progress.total > 0) {
    return `Processing ${formatClock(progress.current)} / ${formatClock(progress.total)}${elapsedPart}`;
  }
  return `Processing...${elapsedPart}`;
}
