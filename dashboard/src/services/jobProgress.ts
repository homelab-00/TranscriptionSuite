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
  loading_model: 'Loading model',
  transcribing: 'Transcribing',
  diarizing: 'Identifying speakers',
  transcribing_diarizing: 'Transcribing + identifying speakers',
};

/**
 * Job progress broken into renderable parts.
 * kind drives the layout: 'duration' has a real percent + position,
 * 'loading'/'phase' are indeterminate, 'position' has totals but no phase,
 * 'generic' has nothing but elapsed (at best).
 */
export interface JobProgressDetails {
  kind: 'loading' | 'duration' | 'phase' | 'position' | 'generic';
  phaseLabel: string;
  percent: number | null;
  positionText: string | null;
  elapsedText: string | null;
  etaText: string | null;
}

/**
 * Structured progress for an in-flight transcription job. Single source of
 * truth for both the compact label (describeJobProgress) and the expanded
 * active-row rendering in the Import Queue.
 */
export function summarizeJobProgress(
  progress: JobTrackerProgress | null | undefined,
  startedAt: number | null | undefined,
  nowSeconds: number,
): JobProgressDetails {
  const elapsed = startedAt ? Math.max(0, nowSeconds - startedAt) : null;
  const elapsedText = elapsed !== null ? formatClock(elapsed) : null;
  const phase = progress?.phase ?? null;

  if (phase === 'loading_model') {
    return {
      kind: 'loading',
      phaseLabel: PHASE_LABELS.loading_model,
      percent: null,
      positionText: null,
      elapsedText,
      etaText: null,
    };
  }

  if (
    (phase === 'transcribing' || phase === 'transcribing_diarizing') &&
    progress &&
    progress.total > 0
  ) {
    const pct = Math.min(100, Math.round((progress.current / progress.total) * 100));
    let etaText: string | null = null;
    if (
      elapsed !== null &&
      elapsed > 5 &&
      progress.current > 0 &&
      progress.current < progress.total
    ) {
      const remaining = ((progress.total - progress.current) * elapsed) / progress.current;
      etaText = formatClock(remaining);
    }
    return {
      kind: 'duration',
      phaseLabel: PHASE_LABELS[phase],
      percent: pct,
      positionText: `${formatClock(progress.current)} / ${formatClock(progress.total)}`,
      elapsedText,
      etaText,
    };
  }

  if (phase && PHASE_LABELS[phase]) {
    return {
      kind: 'phase',
      phaseLabel: PHASE_LABELS[phase],
      percent: null,
      positionText: null,
      elapsedText,
      etaText: null,
    };
  }

  if (progress && progress.total > 0) {
    return {
      kind: 'position',
      phaseLabel: 'Processing',
      percent: null,
      positionText: `${formatClock(progress.current)} / ${formatClock(progress.total)}`,
      elapsedText,
      etaText: null,
    };
  }

  return {
    kind: 'generic',
    phaseLabel: 'Processing',
    percent: null,
    positionText: null,
    elapsedText,
    etaText: null,
  };
}

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
  const d = summarizeJobProgress(progress, startedAt, nowSeconds);
  const elapsedPart = d.elapsedText !== null ? ` (elapsed ${d.elapsedText})` : '';

  switch (d.kind) {
    case 'loading':
      return 'Loading model...';
    case 'duration': {
      const elapsed = d.elapsedText !== null ? `, elapsed ${d.elapsedText}` : '';
      const eta = d.etaText !== null ? `, ETA ${d.etaText}` : '';
      return `${d.phaseLabel} ${d.positionText} (${d.percent}%${elapsed}${eta})`;
    }
    case 'phase':
      return `${d.phaseLabel}...${elapsedPart}`;
    case 'position':
      return `Processing ${d.positionText}${elapsedPart}`;
    case 'generic':
      return `Processing...${elapsedPart}`;
  }
}
