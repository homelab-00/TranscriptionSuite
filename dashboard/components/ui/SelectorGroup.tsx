import React from 'react';

interface SelectorGroupProps {
  icon: React.ReactNode;
  title: string;
  /** Short helper sentence rendered under the title. */
  hint?: string;
  /** Optional right-aligned element (badge, status light, button). */
  action?: React.ReactNode;
  /** Tailwind grid-cols classes for the tile grid. */
  columnsClass?: string;
  children: React.ReactNode;
}

/**
 * Labelled section inside the Instance Settings card: a colored icon heading
 * followed by a responsive grid of SelectorTiles (plus any auxiliary rows).
 */
export const SelectorGroup: React.FC<SelectorGroupProps> = ({
  icon,
  title,
  hint,
  action,
  columnsClass = 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-5',
  children,
}) => {
  return (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          {icon}
          <div>
            <h4 className="text-sm font-semibold text-white/90">{title}</h4>
            {hint && <p className="text-xs text-slate-400">{hint}</p>}
          </div>
        </div>
        {action}
      </div>
      <div className={`grid gap-2 ${columnsClass}`}>{children}</div>
    </div>
  );
};
