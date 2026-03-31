/**
 * Floating download notification widget — bottom-right overlay.
 *
 * Shows active and recent downloads as a vertical stack of small cards.
 * Each notification is individually dismissable. Uses type-specific icons
 * to differentiate download categories.
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
  Ban,
} from 'lucide-react';
import {
  useDownloadStore,
  selectVisibleNotifications,
  type DownloadItem,
  type DownloadType,
} from '../../src/stores/downloadStore';

// ─── Icon mapping ────────────────────────────────────────────────────────────

const TYPE_ICON: Record<DownloadType, React.ReactNode> = {
  'docker-image': <Container size={16} />,
  'sidecar-image': <Cpu size={16} />,
  'ml-model': <BrainCircuit size={16} />,
  'runtime-dep': <Cog size={16} />,
};

const TYPE_COLOR: Record<DownloadType, string> = {
  'docker-image': 'text-accent-cyan',
  'sidecar-image': 'text-accent-magenta',
  'ml-model': 'text-accent-orange',
  'runtime-dep': 'text-slate-400',
};

// ─── Single notification card ────────────────────────────────────────────────

function StatusIcon({ item }: { item: DownloadItem }) {
  switch (item.status) {
    case 'queued':
    case 'downloading':
      return <Loader2 size={14} className="text-accent-cyan animate-spin" />;
    case 'complete':
      return <CheckCircle2 size={14} className="text-emerald-400" />;
    case 'error':
      return <AlertCircle size={14} className="text-red-400" />;
    case 'cancelled':
      return <Ban size={14} className="text-slate-500" />;
  }
}

const AUTO_DISMISS_MS = 5_000;

function DownloadCard({ item }: { item: DownloadItem }) {
  const dismiss = useDownloadStore((s) => s.dismissDownload);
  const isActive = item.status === 'queued' || item.status === 'downloading';

  // Auto-dismiss completed/cancelled notifications after 5 seconds
  useEffect(() => {
    if (item.status !== 'complete' && item.status !== 'cancelled') return;
    const timer = setTimeout(() => dismiss(item.id), AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [item.status, item.id, dismiss]);

  return (
    <div className="animate-in slide-in-from-right-4 fade-in relative flex items-center gap-3 rounded-xl border border-white/10 bg-black/70 px-4 py-3 shadow-2xl backdrop-blur-xl duration-300">
      {/* Type icon */}
      <span className={TYPE_COLOR[item.type]}>{TYPE_ICON[item.type]}</span>

      {/* Content */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-xs font-medium text-slate-200">{item.label}</span>
          <StatusIcon item={item} />
        </div>

        {/* Progress bar */}
        {isActive && (
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

        {/* Error message */}
        {item.status === 'error' && item.error && (
          <p className="mt-1 truncate text-[10px] text-red-400">{item.error}</p>
        )}

        {/* Size info */}
        {item.size && isActive && <p className="mt-0.5 text-[10px] text-slate-500">{item.size}</p>}
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

export const DownloadNotifications: React.FC = () => {
  const items = useDownloadStore(selectVisibleNotifications);

  if (items.length === 0) return null;

  return (
    <div className="fixed right-4 bottom-4 z-50 flex w-72 flex-col gap-2">
      {items.map((item) => (
        <DownloadCard key={item.id} item={item} />
      ))}
    </div>
  );
};
