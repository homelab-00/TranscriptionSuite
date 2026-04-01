/**
 * Activity panel — unified activity view replacing the former Downloads panel.
 *
 * Shows full activity history with progress bars, status badges, size info,
 * and timestamps. Displayed as a top-level sidebar view.
 *
 * Supports 4 categories: download, server, warning, info.
 */

import React, { useCallback, useState } from 'react';
import {
  Container,
  Cpu,
  BrainCircuit,
  Cog,
  Server,
  AlertTriangle,
  Info,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Ban,
  Trash2,
  Clock,
  ChevronRight,
  ChevronDown,
  Timer,
} from 'lucide-react';
import { Button } from '../ui/Button';
import {
  useActivityStore,
  type ActivityItem,
  type ActivityCategory,
  type LegacyDownloadType,
} from '../../src/stores/activityStore';

// ─── Icon + color mapping ────────────────────────────────────────────────────

/** Icons for legacy download types (preserves visual distinction). */
const LEGACY_TYPE_ICON: Record<LegacyDownloadType, React.ReactNode> = {
  'docker-image': <Container size={18} />,
  'sidecar-image': <Cpu size={18} />,
  'ml-model': <BrainCircuit size={18} />,
  'runtime-dep': <Cog size={18} />,
  'model-preload': <BrainCircuit size={18} />,
};

const LEGACY_TYPE_COLOR: Record<LegacyDownloadType, string> = {
  'docker-image': 'text-accent-cyan',
  'sidecar-image': 'text-accent-magenta',
  'ml-model': 'text-accent-orange',
  'runtime-dep': 'text-slate-400',
  'model-preload': 'text-slate-400',
};

const LEGACY_TYPE_LABEL: Record<LegacyDownloadType, string> = {
  'docker-image': 'Docker Image',
  'sidecar-image': 'Sidecar Image',
  'ml-model': 'ML Model',
  'runtime-dep': 'Runtime',
  'model-preload': 'Model Load',
};

/** Icons for activity categories (used when no legacy type is available). */
const CATEGORY_ICON: Record<ActivityCategory, React.ReactNode> = {
  download: <BrainCircuit size={18} />,
  server: <Server size={18} />,
  warning: <AlertTriangle size={18} />,
  info: <Info size={18} />,
};

const CATEGORY_COLOR: Record<ActivityCategory, string> = {
  download: 'text-accent-cyan',
  server: 'text-slate-400',
  warning: 'text-amber-400',
  info: 'text-emerald-400',
};

const CATEGORY_LABEL: Record<ActivityCategory, string> = {
  download: 'Download',
  server: 'Server',
  warning: 'Warning',
  info: 'Info',
};

function getIcon(item: ActivityItem): React.ReactNode {
  if (item.legacyType && LEGACY_TYPE_ICON[item.legacyType]) {
    return LEGACY_TYPE_ICON[item.legacyType];
  }
  return CATEGORY_ICON[item.category];
}

function getColor(item: ActivityItem): string {
  if (item.legacyType && LEGACY_TYPE_COLOR[item.legacyType]) {
    return LEGACY_TYPE_COLOR[item.legacyType];
  }
  return CATEGORY_COLOR[item.category];
}

function getTypeLabel(item: ActivityItem): string {
  if (item.legacyType && LEGACY_TYPE_LABEL[item.legacyType]) {
    return LEGACY_TYPE_LABEL[item.legacyType];
  }
  return CATEGORY_LABEL[item.category];
}

const STATUS_BADGE: Record<ActivityItem['status'], { label: string; className: string }> = {
  active: { label: 'Active', className: 'bg-accent-cyan/20 text-accent-cyan' },
  complete: { label: 'Complete', className: 'bg-emerald-900/40 text-emerald-400' },
  error: { label: 'Failed', className: 'bg-red-900/40 text-red-400' },
  dismissed: { label: 'Dismissed', className: 'bg-slate-700 text-slate-500' },
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

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}

// ─── Row component ───────────────────────────────────────────────────────────

function ActivityRow({
  item,
  expanded,
  onToggleExpand,
}: {
  item: ActivityItem;
  expanded: boolean;
  onToggleExpand: () => void;
}) {
  const isActive = item.status === 'active';
  const isDownload = item.category === 'download';
  const showProgress = isActive && isDownload && item.legacyType !== 'model-preload';
  const badge = STATUS_BADGE[item.status];
  const hasExpandable = !!item.expandableDetail;
  const isComplete = item.status === 'complete';

  return (
    <div
      className={`border-glass-border border-b last:border-b-0 ${
        item.category === 'warning' ? 'border-l-2 border-l-amber-500/50' : ''
      }`}
    >
      <div className="flex items-center gap-4 px-6 py-4">
        {/* Expand toggle or type icon */}
        {hasExpandable ? (
          <button
            onClick={onToggleExpand}
            className={`shrink-0 ${getColor(item)} transition-colors hover:text-white`}
            title={expanded ? 'Collapse details' : 'Expand details'}
          >
            {expanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
          </button>
        ) : (
          <div className={`shrink-0 ${getColor(item)}`}>{getIcon(item)}</div>
        )}

        {/* Info column */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3">
            <span className="truncate text-sm font-medium text-white">{item.label}</span>
            <span
              className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${badge.className}`}
            >
              {badge.label}
            </span>
            {/* Duration badge for completed items */}
            {isComplete && item.durationMs !== undefined && (
              <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-slate-700/60 px-2 py-0.5 text-[10px] text-slate-400">
                <Timer size={9} />
                {formatMs(item.durationMs)}
              </span>
            )}
          </div>

          <div className="mt-1 flex items-center gap-3 text-[11px] text-slate-500">
            <span>{getTypeLabel(item)}</span>
            {item.totalSize && (
              <span>
                {item.downloadedSize
                  ? `${item.downloadedSize} / ${item.totalSize}`
                  : item.totalSize}
              </span>
            )}
            {item.detail && <span>{item.detail}</span>}
            <span className="inline-flex items-center gap-1">
              <Clock size={10} />
              {formatTime(item.startedAt)}
            </span>
            {item.completedAt && <span>{formatDuration(item.startedAt, item.completedAt)}</span>}
          </div>

          {/* Progress bar for active download items */}
          {showProgress && (
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
          {isComplete && <CheckCircle2 size={18} className="text-emerald-400" />}
          {item.status === 'error' && <AlertCircle size={18} className="text-red-400" />}
          {item.status === 'dismissed' && <Ban size={18} className="text-slate-500" />}
        </div>
      </div>

      {/* Expandable detail */}
      {hasExpandable && expanded && (
        <div className="border-t border-white/5 bg-white/[0.02] px-6 py-3 pl-16">
          <pre className="text-xs leading-relaxed break-words whitespace-pre-wrap text-slate-400">
            {item.expandableDetail}
          </pre>
        </div>
      )}
    </div>
  );
}

// ─── Empty state ─────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 py-20 text-center">
      <Server size={40} className="text-slate-600" />
      <p className="text-sm text-slate-500">No activity yet</p>
      <p className="max-w-xs text-xs text-slate-600">
        Activity will appear here when the server starts, models download, or dependencies install.
      </p>
    </div>
  );
}

// ─── Main panel ──────────────────────────────────────────────────────────────

export const ActivityPanel: React.FC = () => {
  const items = useActivityStore((s) => s.items);
  const clearAll = useActivityStore((s) => s.clearAll);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const hasHistory = items.some(
    (i) => i.status === 'complete' || i.status === 'error' || i.status === 'dismissed',
  );

  const handleClearHistory = useCallback(() => {
    clearAll();
    setExpandedIds(new Set());
  }, [clearAll]);

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  // Sort: active first, then by startedAt descending
  const sorted = [...items].sort((a, b) => {
    const aActive = a.status === 'active' ? 0 : 1;
    const bActive = b.status === 'active' ? 0 : 1;
    if (aActive !== bActive) return aActive - bActive;
    return b.startedAt - a.startedAt;
  });

  return (
    <div className="mx-auto flex h-full w-full max-w-7xl flex-col p-6">
      {/* Header */}
      <div className="mb-6 flex flex-none items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight text-white">Activity</h1>
        {hasHistory && (
          <Button
            variant="glass"
            size="sm"
            className="h-8 text-xs"
            onClick={handleClearHistory}
            icon={<Trash2 size={14} />}
          >
            Clear All
          </Button>
        )}
      </div>

      {/* Activity list */}
      <div className="border-glass-border flex min-h-0 flex-1 flex-col overflow-y-auto rounded-xl border bg-black/20">
        {sorted.length === 0 ? (
          <EmptyState />
        ) : (
          sorted.map((item) => (
            <ActivityRow
              key={item.id}
              item={item}
              expanded={expandedIds.has(item.id)}
              onToggleExpand={() => toggleExpand(item.id)}
            />
          ))
        )}
      </div>
    </div>
  );
};
