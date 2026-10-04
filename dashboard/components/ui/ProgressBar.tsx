/**
 * ProgressBar - the shared progress track for the dashboard.
 *
 * Determinate when `value` is a finite number (clamped to 0-100);
 * indeterminate otherwise, so an unknown or NaN progress renders a sweeping
 * bar instead of a broken width. Exposes `role="progressbar"` with the ARIA
 * value attributes, omitting `aria-valuenow` when indeterminate.
 */

import React from 'react';

interface ProgressBarProps {
  /** 0-100. null / undefined / NaN renders an indeterminate bar. */
  value?: number | null;
  /** Accessible name: what is progressing. */
  label: string;
  /** Spoken value, e.g. "42%, 1.1 GB of 2.6 GB". */
  valueText?: string;
  size?: 'xs' | 'sm';
  tone?: 'cyan' | 'red';
  className?: string;
}

const TONE_FILL: Record<NonNullable<ProgressBarProps['tone']>, string> = {
  cyan: 'bg-accent-cyan',
  red: 'bg-red-400',
};

export const ProgressBar: React.FC<ProgressBarProps> = ({
  value,
  label,
  valueText,
  size = 'xs',
  tone = 'cyan',
  className = '',
}) => {
  const determinate = typeof value === 'number' && Number.isFinite(value);
  const clamped = determinate ? Math.round(Math.max(0, Math.min(100, value))) : undefined;
  const fill = TONE_FILL[tone];

  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clamped}
      aria-valuetext={valueText}
      className={`w-full overflow-hidden rounded-full bg-white/10 ${size === 'sm' ? 'h-1.5' : 'h-1'} ${className}`}
    >
      {clamped !== undefined ? (
        <div
          className={`${fill} h-full rounded-full transition-all duration-300`}
          style={{ width: `${clamped}%` }}
        />
      ) : (
        <div className={`${fill} progress-indeterminate h-full w-1/3 rounded-full`} />
      )}
    </div>
  );
};
