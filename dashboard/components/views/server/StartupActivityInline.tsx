import { Loader2 } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';
import { useActivityStore, type ActivityItem } from '../../../src/stores/activityStore';

const selectActiveVisibleItems = (state: { items: ActivityItem[] }): ActivityItem[] =>
  state.items.filter((item) => item.status === 'active' && !item.dismissed);

/**
 * Inline mirror of active download/startup activity for the Server tab
 * (GH-207): the floating widget is easy to miss or dismiss; while the
 * server is starting this shows the same items next to the status light.
 */
export function StartupActivityInline() {
  const items = useActivityStore(useShallow(selectActiveVisibleItems));
  if (items.length === 0) return null;
  return (
    <div className="mt-2 space-y-1.5">
      {items.map((item) => (
        <div key={item.id} className="flex items-center gap-2 text-xs text-slate-400">
          <Loader2 size={12} className="shrink-0 animate-spin" />
          <span className="min-w-0 truncate">{item.label}</span>
          {item.progress !== undefined && (
            <span className="shrink-0 font-mono text-slate-500">{item.progress}%</span>
          )}
          {item.downloadedSize && item.totalSize && (
            <span className="shrink-0 font-mono text-[10px] text-slate-600">
              {item.downloadedSize} / {item.totalSize}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
