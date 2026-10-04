/**
 * DownloadBar - the universal download bar (GH-318).
 *
 * One strip, visible on every view, for anything the app or the server is
 * downloading: container images, model weights, runtime dependencies, app
 * updates, exports. Hidden when idle. A single download renders as one row;
 * several collapse into an aggregate row with an expandable list.
 *
 * Reads the downloads store only - useDownloadsBridge keeps that store in
 * sync with the main-process DownloadHub.
 */

import React, { useId, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { AlertCircle, CheckCircle2, ChevronDown, Download, X } from 'lucide-react';
import { ProgressBar } from './ProgressBar';
import { useDownloadsStore } from '../../src/stores/downloadsStore';
import {
  aggregateDownloads,
  describeProgress,
  itemFraction,
} from '../../src/utils/downloadProgress';

const ACTIVE_TONE = 'border-cyan-400/30 bg-cyan-400/10 text-cyan-200';
const FAILED_TONE = 'border-red-400/30 bg-red-400/10 text-red-200';
const ACTION_BTN =
  'shrink-0 rounded bg-white/5 px-3 py-1 text-xs font-medium text-slate-300 transition-colors hover:bg-white/10';

function toPercent(fraction: number | null): number | null {
  return fraction === null ? null : fraction * 100;
}

function itemTitle(item: DownloadItem): string {
  if (item.status === 'error') return `${item.label} download failed`;
  if (item.status === 'complete') return `${item.label} downloaded`;
  return `Downloading ${item.label}`;
}

function itemMeta(item: DownloadItem): string {
  if (item.status !== 'active') return '';
  return describeProgress({
    fraction: itemFraction(item),
    bytesDone: item.bytesDone,
    bytesTotal: item.bytesTotal,
    bytesPerSecond: item.bytesPerSecond,
    etaSeconds: item.etaSeconds,
  });
}

function summaryTitle(activeCount: number, failedCount: number, total: number): string {
  if (activeCount === 0 && failedCount === total) return `${failedCount} downloads failed`;
  const running = `${activeCount} download${activeCount === 1 ? '' : 's'}`;
  return failedCount > 0 ? `${running}, ${failedCount} failed` : running;
}

function cancelDownload(id: string): void {
  void window.electronAPI?.downloads?.cancel(id).catch(() => {});
}

function ItemActions({ item }: { item: DownloadItem }) {
  const dismiss = useDownloadsStore((s) => s.dismiss);
  if (item.status === 'active' && item.cancellable) {
    return (
      <button type="button" onClick={() => cancelDownload(item.id)} className={ACTION_BTN}>
        Cancel
      </button>
    );
  }
  if (item.status === 'error') {
    return (
      <button
        type="button"
        onClick={() => dismiss(item.runId)}
        aria-label="Dismiss"
        title="Dismiss"
        className="shrink-0 rounded-md p-1 text-slate-400 transition-colors hover:bg-white/10 hover:text-slate-200"
      >
        <X size={14} />
      </button>
    );
  }
  return null;
}

function StatusGlyph({ status }: { status: DownloadStatus }) {
  if (status === 'error') return <AlertCircle size={16} className="shrink-0 text-red-400" />;
  if (status === 'complete') {
    return <CheckCircle2 size={16} className="shrink-0 text-emerald-400" />;
  }
  return <Download size={16} className="shrink-0" />;
}

/** One download: title, progress, the line under it. Used alone and inside the list. */
function ItemBody({ item, title }: { item: DownloadItem; title: string }) {
  const meta = itemMeta(item);
  const failed = item.status === 'error';
  const subline = failed ? item.error : item.status === 'active' ? item.detail : undefined;
  return (
    <div className="min-w-0 flex-1">
      <div className="flex items-baseline justify-between gap-3">
        <span className="truncate">{title}</span>
        {meta && <span className="shrink-0 font-mono text-xs opacity-80">{meta}</span>}
      </div>
      {item.status === 'active' && (
        <ProgressBar
          className="mt-1"
          value={toPercent(itemFraction(item))}
          label={item.label}
          valueText={meta || undefined}
        />
      )}
      {subline && (
        <p className={`mt-0.5 truncate text-xs ${failed ? 'text-red-300' : 'opacity-60'}`}>
          {subline}
        </p>
      )}
    </div>
  );
}

export const DownloadBar: React.FC = () => {
  const items = useDownloadsStore(useShallow((s) => s.items));
  const [expanded, setExpanded] = useState(false);
  const listId = useId();

  if (items.length === 0) return null;

  if (items.length === 1) {
    const item = items[0];
    return (
      <div
        role="region"
        aria-label="Downloads"
        className={`flex items-center gap-3 border px-4 py-2 text-sm ${item.status === 'error' ? FAILED_TONE : ACTIVE_TONE}`}
      >
        <StatusGlyph status={item.status} />
        <ItemBody item={item} title={itemTitle(item)} />
        <ItemActions item={item} />
      </div>
    );
  }

  const aggregate = aggregateDownloads(items);
  const failedCount = items.filter((i) => i.status === 'error').length;
  const meta = describeProgress(aggregate);
  const title = summaryTitle(aggregate.activeCount, failedCount, items.length);

  return (
    <div
      role="region"
      aria-label="Downloads"
      className={`border px-4 py-2 text-sm ${aggregate.activeCount === 0 ? FAILED_TONE : ACTIVE_TONE}`}
    >
      <div className="flex items-center gap-3">
        <Download size={16} className="shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <span className="truncate">{title}</span>
            {meta && <span className="shrink-0 font-mono text-xs opacity-80">{meta}</span>}
          </div>
          {aggregate.activeCount > 0 && (
            <ProgressBar
              className="mt-1"
              value={toPercent(aggregate.fraction)}
              label="All downloads"
              valueText={meta || undefined}
            />
          )}
        </div>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-controls={listId}
          aria-label={expanded ? 'Hide downloads' : 'Show all downloads'}
          title={expanded ? 'Hide downloads' : 'Show all downloads'}
          className="shrink-0 rounded-md p-1 text-slate-300 transition-colors hover:bg-white/10"
        >
          <ChevronDown
            size={16}
            className={`transition-transform ${expanded ? 'rotate-180' : ''}`}
          />
        </button>
      </div>

      {expanded && (
        <ul id={listId} className="mt-2 space-y-2 border-t border-white/10 pt-2">
          {items.map((item) => (
            <li
              key={item.runId}
              className={`flex items-center gap-3 ${item.status === 'error' ? 'text-red-200' : ''}`}
            >
              <StatusGlyph status={item.status} />
              <ItemBody item={item} title={item.label} />
              <ItemActions item={item} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
