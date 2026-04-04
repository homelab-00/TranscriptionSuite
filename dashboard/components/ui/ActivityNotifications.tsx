/**
 * Floating activity notification widget — bottom-right overlay.
 *
 * Shows active and recent download activity as a vertical stack of small cards.
 * Each notification is individually dismissable.
 */

import React, { useEffect } from 'react';
import {
  X,
  Container,
  Cpu,
  BrainCircuit,
  Cog,
  Loader2,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react';
import {
  useActivityStore,
  selectVisibleNotifications,
  type ActivityItem,
  type LegacyDownloadType,
} from '../../src/stores/activityStore';

// ─── Icon mapping ────────────────────────────────────────────────────────────

const LEGACY_TYPE_ICON: Record<LegacyDownloadType, React.ReactNode> = {
  'docker-image': <Container size={16} />,
  'sidecar-image': <Cpu size={16} />,
  'ml-model': <BrainCircuit size={16} />,
  'runtime-dep': <Cog size={16} />,
  'model-preload': <BrainCircuit size={16} />,
};

const LEGACY_TYPE_COLOR: Record<LegacyDownloadType, string> = {
  'docker-image': 'text-accent-cyan',
  'sidecar-image': 'text-accent-magenta',
  'ml-model': 'text-accent-orange',
  'runtime-dep': 'text-slate-400',
  'model-preload': 'text-slate-400',
};

function getIcon(item: ActivityItem): React.ReactNode {
  if (item.legacyType && LEGACY_TYPE_ICON[item.legacyType]) {
    return LEGACY_TYPE_ICON[item.legacyType];
  }
  return <BrainCircuit size={16} />;
}

function getColor(item: ActivityItem): string {
  if (item.legacyType && LEGACY_TYPE_COLOR[item.legacyType]) {
    return LEGACY_TYPE_COLOR[item.legacyType];
  }
  return 'text-accent-cyan';
}

/** Border accent for error items. */
function getBorderClass(item: ActivityItem): string {
  if (item.severity === 'error') return 'border-l-2 border-l-red-500';
  return '';
}

// ─── Single notification card ────────────────────────────────────────────────

function StatusIcon({ item }: { item: ActivityItem }) {
  switch (item.status) {
    case 'active':
      return <Loader2 size={14} className="text-accent-cyan animate-spin" />;
    case 'complete':
      return <CheckCircle2 size={14} className="text-emerald-400" />;
    case 'error':
      return <AlertCircle size={14} className="text-red-400" />;
    default:
      return null;
  }
}

const AUTO_DISMISS_MS = 5_000;

function ActivityCard({ item }: { item: ActivityItem }) {
  const dismiss = useActivityStore((s) => s.dismissActivity);
  const isActive = item.status === 'active';
  const isDownload = item.category === 'download';
  const showProgress = isActive && isDownload && item.legacyType !== 'model-preload';

  // Auto-dismiss completed notifications. Persistent items are never auto-dismissed.
  useEffect(() => {
    if (item.persistent) return;
    if (item.status !== 'complete' && item.status !== 'error') return;
    const timer = setTimeout(() => dismiss(item.id), AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [item.status, item.id, item.persistent, dismiss]);

  return (
    <div
      className={`animate-in slide-in-from-right-4 fade-in relative flex items-center gap-3 rounded-xl border border-white/10 bg-black/70 px-4 py-3 shadow-2xl backdrop-blur-xl duration-300 ${getBorderClass(item)}`}
    >
      {/* Category icon */}
      <span className={getColor(item)}>{getIcon(item)}</span>

      {/* Content */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-xs font-medium text-slate-200">{item.label}</span>
          <StatusIcon item={item} />
        </div>

        {/* Progress bar */}
        {showProgress && (
          <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-white/10">
            {item.progress !== undefined ? (
              <div
                className="bg-accent-cyan h-full rounded-full transition-all duration-300"
                style={{ width: `${item.progress}%` }}
              />
            ) : (
              <div className="bg-accent-cyan h-full w-1/3 animate-pulse rounded-full" />
            )}
          </div>
        )}

        {/* Download size info */}
        {item.downloadedSize && item.totalSize && showProgress && (
          <p className="mt-0.5 text-[10px] text-slate-500">
            {item.downloadedSize} / {item.totalSize}
          </p>
        )}

        {/* Detail (e.g., package count) */}
        {item.detail && isActive && (
          <p className="mt-0.5 text-[10px] text-slate-500">{item.detail}</p>
        )}

        {/* Error message */}
        {item.status === 'error' && item.error && (
          <p className="mt-1 truncate text-[10px] text-red-400">{item.error}</p>
        )}
      </div>

      {/* Dismiss button */}
      <button
        onClick={() => dismiss(item.id)}
        className="shrink-0 rounded-md p-1 text-slate-500 transition-colors hover:bg-white/10 hover:text-slate-300"
        title="Dismiss"
      >
        <X size={12} />
      </button>
    </div>
  );
}

// ─── Main widget ─────────────────────────────────────────────────────────────

export const ActivityNotifications: React.FC = () => {
  const items = useActivityStore(selectVisibleNotifications);

  if (items.length === 0) return null;

  return (
    <div className="fixed right-4 bottom-4 z-50 flex w-72 flex-col gap-2">
      {items.map((item) => (
        <ActivityCard key={item.id} item={item} />
      ))}
    </div>
  );
};
