/**
 * NotificationToasts - floating bottom-right toast stack over the
 * notifications store. Successor to ActivityNotifications: same placement
 * and card styling, but reads AppNotification records and dismissal only
 * hides the toast (the record stays in the Notifications view forever).
 */

import React, { useEffect } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { X } from 'lucide-react';
import {
  CATEGORY_COLOR,
  CATEGORY_ICON,
  NotificationStatusIcon,
  severityBorderClass,
} from './notificationVisuals';
import {
  useNotificationsStore,
  selectToastNotifications,
  type AppNotification,
} from '../../src/stores/notificationsStore';

const AUTO_DISMISS_MS = 5_000;

function ToastCard({ item }: { item: AppNotification }) {
  const dismissToast = useNotificationsStore((s) => s.dismissToast);
  const isActive = item.status === 'active';

  // Auto-dismiss the TOAST for terminal states; the log record is untouched.
  useEffect(() => {
    if (item.status !== 'complete' && item.status !== 'error') return;
    const timer = setTimeout(() => dismissToast(item.entryId), AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [item.status, item.entryId, dismissToast]);

  return (
    <div
      className={`animate-in slide-in-from-right-4 fade-in relative flex items-center gap-3 rounded-xl border border-white/10 bg-black/70 px-4 py-3 shadow-2xl backdrop-blur-xl duration-300 ${severityBorderClass(item)}`}
    >
      <span className={CATEGORY_COLOR[item.category]}>{CATEGORY_ICON[item.category]}</span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-xs font-medium text-slate-200">{item.title}</span>
          <NotificationStatusIcon status={item.status} />
        </div>

        {item.detail && isActive && (
          <p className="mt-0.5 truncate text-[10px] text-slate-500">{item.detail}</p>
        )}

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

        {isActive && item.downloadedSize && item.totalSize && (
          <p className="mt-0.5 text-[10px] text-slate-500">
            {item.downloadedSize} / {item.totalSize}
          </p>
        )}

        {item.status === 'error' && item.error && (
          <p className="mt-1 truncate text-[10px] text-red-400">{item.error}</p>
        )}
      </div>

      <button
        onClick={() => dismissToast(item.entryId)}
        className="shrink-0 rounded-md p-1 text-slate-500 transition-colors hover:bg-white/10 hover:text-slate-300"
        title="Dismiss"
      >
        <X size={12} />
      </button>
    </div>
  );
}

export const NotificationToasts: React.FC = () => {
  const items = useNotificationsStore(useShallow(selectToastNotifications));
  if (items.length === 0) return null;

  return (
    <div className="fixed right-4 bottom-4 z-50 flex w-72 flex-col gap-2">
      {items.map((item) => (
        <ToastCard key={item.entryId} item={item} />
      ))}
    </div>
  );
};
