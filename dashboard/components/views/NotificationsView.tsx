/**
 * NotificationsView - the session notification log (View.NOTIFICATIONS).
 *
 * Read-only by design: records cannot be dismissed or deleted here; the
 * whole log clears when the app quits. Transcription records embed the
 * transcript behind a collapsible block (transcripts can be megabytes).
 */

import { useMemo, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { Bell, ChevronDown } from 'lucide-react';
import { GlassCard } from '../ui/GlassCard';
import {
  CATEGORY_COLOR,
  CATEGORY_ICON,
  NotificationStatusIcon,
  severityBorderClass,
} from '../ui/notificationVisuals';
import {
  useNotificationsStore,
  selectAllNotifications,
  type AppNotification,
} from '../../src/stores/notificationsStore';

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function TranscriptBlock({ transcript }: { transcript: string }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex items-center gap-1 text-xs text-slate-500 transition-colors hover:text-slate-400"
      >
        <ChevronDown size={12} className={`transition-transform ${expanded ? 'rotate-180' : ''}`} />
        Transcript ({transcript.length.toLocaleString()} characters)
      </button>
      {expanded && (
        <div className="custom-scrollbar selectable-text mt-2 max-h-64 overflow-y-auto rounded-lg border border-white/10 bg-black/30 p-3 text-xs whitespace-pre-wrap text-slate-300">
          {transcript}
        </div>
      )}
    </div>
  );
}

function NotificationRow({ item }: { item: AppNotification }) {
  const isActive = item.status === 'active';
  return (
    <div
      className={`rounded-xl border border-white/10 bg-white/5 px-4 py-3 ${severityBorderClass(item)}`}
    >
      <div className="flex items-center gap-3">
        <span className={`shrink-0 ${CATEGORY_COLOR[item.category]}`}>
          {CATEGORY_ICON[item.category]}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-slate-200">{item.title}</span>
            <NotificationStatusIcon status={item.status} />
          </div>
          {item.detail && <p className="mt-0.5 text-xs text-slate-500">{item.detail}</p>}
        </div>
        <span className="shrink-0 font-mono text-[10px] text-slate-500">
          {formatTime(item.createdAt)}
        </span>
      </div>

      {isActive && (
        <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-white/10">
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
      {isActive && item.downloadedSize && item.totalSize && (
        <p className="mt-0.5 text-[10px] text-slate-500">
          {item.downloadedSize} / {item.totalSize}
        </p>
      )}
      {item.status === 'error' && item.error && (
        <p className="mt-1 text-xs text-red-400">{item.error}</p>
      )}
      {item.transcript && <TranscriptBlock transcript={item.transcript} />}
    </div>
  );
}

export function NotificationsView() {
  const notifications = useNotificationsStore(useShallow(selectAllNotifications));
  const sorted = useMemo(
    () => [...notifications].sort((a, b) => b.createdAt - a.createdAt),
    [notifications],
  );

  return (
    <div className="custom-scrollbar h-full overflow-y-auto p-6">
      <GlassCard title="Notifications">
        <p className="mb-4 text-xs text-slate-500">
          Session log - every tracked action since the dashboard started. Cleared when the app
          quits; entries cannot be removed here.
        </p>
        {sorted.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-16 text-slate-500">
            <Bell size={24} />
            <p className="text-sm">No notifications yet this session.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {sorted.map((item) => (
              <NotificationRow key={item.entryId} item={item} />
            ))}
          </div>
        )}
      </GlassCard>
    </div>
  );
}
