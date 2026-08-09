import React from 'react';
import type { JobProgressDetails } from '../../src/services/jobProgress';

interface JobProgressBlockProps {
  /** Structured progress from summarizeJobProgress / useJobProgress. */
  details: JobProgressDetails;
  /** True when the job has reported no progress change for too long. */
  stalled?: boolean;
  /** Top-row content left of the percent readout (status icon, file name). */
  leading?: React.ReactNode;
}

/**
 * Expanded progress block for the one job being transcribed: progress bar
 * plus a big percent so progress is obvious at a glance. Originally the
 * active-row rendering of the Session import queue; now shared with the
 * Notebook import queue and the Main Transcription processing state.
 */
export const JobProgressBlock: React.FC<JobProgressBlockProps> = ({
  details,
  stalled = false,
  leading,
}) => (
  <div className="border-accent-cyan/20 bg-accent-cyan/5 rounded-lg border px-3 py-2.5">
    <div className="flex items-center gap-3">
      {leading}
      {details.percent !== null ? (
        <span className="text-accent-cyan text-lg leading-none font-semibold tabular-nums">
          {details.percent}%
        </span>
      ) : (
        <span className="text-accent-cyan text-sm font-medium">{details.phaseLabel}...</span>
      )}
    </div>
    <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
      {details.percent !== null ? (
        <div
          className="bg-accent-cyan h-full rounded-full transition-all duration-300"
          style={{ width: `${details.percent}%` }}
        />
      ) : (
        <div className="bg-accent-cyan h-full w-1/3 animate-pulse rounded-full" />
      )}
    </div>
    <div className="mt-1.5 flex items-center justify-between gap-3 text-xs text-slate-400">
      <span className="truncate">
        {details.percent !== null ? details.phaseLabel : details.phaseLabel + '...'}
        {details.positionText && <span className="text-slate-300"> {details.positionText}</span>}
      </span>
      <span className="whitespace-nowrap">
        {details.elapsedText && `elapsed ${details.elapsedText}`}
        {details.etaText && <span className="text-slate-300"> · ETA {details.etaText}</span>}
      </span>
    </div>
    {stalled && (
      <p className="mt-1.5 text-xs text-amber-400">No recent progress, the job may be stalled</p>
    )}
  </div>
);
