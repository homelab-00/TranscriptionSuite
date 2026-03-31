/**
 * Downloads panel — Steam-style detailed download manager.
 *
 * Shows full download history with progress bars, controls, speed,
 * size, and timestamps. Displayed as a top-level sidebar view.
 */

import React, { useCallback } from 'react';
import {
  Container,
  Cpu,
  BrainCircuit,
  Cog,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Ban,
  Trash2,
  Clock,
} from 'lucide-react';
import { Button } from '../ui/Button';
import {
  useDownloadStore,
  type DownloadItem,
  type DownloadType,
} from '../../src/stores/downloadStore';

// ─── Icon + color mapping ────────────────────────────────────────────────────

const TYPE_ICON: Record<DownloadType, React.ReactNode> = {
  'docker-image': <Container size={18} />,
  'sidecar-image': <Cpu size={18} />,
  'ml-model': <BrainCircuit size={18} />,
  'runtime-dep': <Cog size={18} />,
};

const TYPE_COLOR: Record<DownloadType, string> = {
  'docker-image': 'text-accent-cyan',
  'sidecar-image': 'text-accent-magenta',
  'ml-model': 'text-accent-orange',
  'runtime-dep': 'text-slate-400',
};

const TYPE_LABEL: Record<DownloadType, string> = {
  'docker-image': 'Docker Image',
  'sidecar-image': 'Sidecar Image',
  'ml-model': 'ML Model',
  'runtime-dep': 'Runtime',
};

const STATUS_BADGE: Record<DownloadItem['status'], { label: string; className: string }> = {
  queued: { label: 'Queued', className: 'bg-slate-700 text-slate-300' },
  downloading: { label: 'Downloading', className: 'bg-accent-cyan/20 text-accent-cyan' },
  complete: { label: 'Complete', className: 'bg-emerald-900/40 text-emerald-400' },
  error: { label: 'Failed', className: 'bg-red-900/40 text-red-400' },
  cancelled: { label: 'Cancelled', className: 'bg-slate-700 text-slate-500' },
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('en-US', { hour12: false });
}

function formatDuration(startMs: number, endMs?: number): string {
  const elapsed = Math.round(((endMs ?? Date.now()) - startMs) / 1000);
  if (elapsed < 60) return `${elapsed}s`;
  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  return `${mins}m ${secs}s`;
}

// ─── Row component ───────────────────────────────────────────────────────────

function DownloadRow({ item }: { item: DownloadItem }) {
  const isActive = item.status === 'queued' || item.status === 'downloading';
  const badge = STATUS_BADGE[item.status];

  return (
    <div className="border-glass-border flex items-center gap-4 border-b px-6 py-4 last:border-b-0">
      {/* Type icon */}
      <div className={`shrink-0 ${TYPE_COLOR[item.type]}`}>{TYPE_ICON[item.type]}</div>

      {/* Info column */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-3">
          <span className="truncate text-sm font-medium text-white">{item.label}</span>
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${badge.className}`}
          >
            {badge.label}
          </span>
        </div>

        <div className="mt-1 flex items-center gap-3 text-[11px] text-slate-500">
          <span>{TYPE_LABEL[item.type]}</span>
          {item.size && <span>{item.size}</span>}
          <span className="inline-flex items-center gap-1">
            <Clock size={10} />
            {formatTime(item.startedAt)}
          </span>
          {item.completedAt && <span>{formatDuration(item.startedAt, item.completedAt)}</span>}
        </div>

        {/* Progress bar for active items */}
        {isActive && (
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
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
          <p className="mt-1 text-xs text-red-400">{item.error}</p>
        )}
      </div>

      {/* Status icon */}
      <div className="shrink-0">
        {isActive && <Loader2 size={18} className="text-accent-cyan animate-spin" />}
        {item.status === 'complete' && <CheckCircle2 size={18} className="text-emerald-400" />}
        {item.status === 'error' && <AlertCircle size={18} className="text-red-400" />}
        {item.status === 'cancelled' && <Ban size={18} className="text-slate-500" />}
      </div>
    </div>
  );
}

// ─── Empty state ─────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 py-20 text-center">
      <Container size={40} className="text-slate-600" />
      <p className="text-sm text-slate-500">No downloads yet</p>
      <p className="max-w-xs text-xs text-slate-600">
        Downloads will appear here when you pull Docker images, download models, or install runtime
        dependencies.
      </p>
    </div>
  );
}

// ─── Main panel ──────────────────────────────────────────────────────────────

export const DownloadsPanel: React.FC = () => {
  const items = useDownloadStore((s) => s.items);
  const clearHistory = useDownloadStore((s) => s.clearHistory);

  const hasHistory = items.some(
    (i) => i.status === 'complete' || i.status === 'error' || i.status === 'cancelled',
  );

  const handleClearHistory = useCallback(() => {
    clearHistory();
  }, [clearHistory]);

  // Sort: active first, then by startedAt descending
  const sorted = [...items].sort((a, b) => {
    const aActive = a.status === 'queued' || a.status === 'downloading' ? 0 : 1;
    const bActive = b.status === 'queued' || b.status === 'downloading' ? 0 : 1;
    if (aActive !== bActive) return aActive - bActive;
    return b.startedAt - a.startedAt;
  });

  return (
    <div className="mx-auto flex h-full w-full max-w-7xl flex-col p-6">
      {/* Header */}
      <div className="mb-6 flex flex-none items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight text-white">Downloads</h1>
        {hasHistory && (
          <Button
            variant="glass"
            size="sm"
            className="h-8 text-xs"
            onClick={handleClearHistory}
            icon={<Trash2 size={14} />}
          >
            Clear History
          </Button>
        )}
      </div>

      {/* Download list */}
      <div className="border-glass-border flex min-h-0 flex-1 flex-col overflow-y-auto rounded-xl border bg-black/20">
        {sorted.length === 0 ? (
          <EmptyState />
        ) : (
          sorted.map((item) => <DownloadRow key={item.id} item={item} />)
        )}
      </div>
    </div>
  );
};
