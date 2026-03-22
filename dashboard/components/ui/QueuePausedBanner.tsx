/**
 * QueuePausedBanner — persistent amber banner visible across all views when the
 * import queue is paused. Shows pending file count and a Resume button.
 */

import { useImportQueueStore, selectPendingCount } from '../../src/stores/importQueueStore';

export function QueuePausedBanner() {
  const isPaused = useImportQueueStore((s) => s.isPaused);
  const pendingCount = useImportQueueStore(selectPendingCount);
  const resumeQueue = useImportQueueStore((s) => s.resumeQueue);

  if (!isPaused) return null;

  return (
    <div className="flex items-center justify-between gap-3 border border-amber-400/30 bg-amber-400/10 px-4 py-2 text-sm text-amber-400">
      <span>
        Queue paused — {pendingCount} file{pendingCount !== 1 ? 's' : ''} waiting
      </span>
      <button
        type="button"
        onClick={resumeQueue}
        className="rounded bg-amber-400/20 px-3 py-1 text-xs font-medium text-amber-300 transition-colors hover:bg-amber-400/30"
      >
        Resume
      </button>
    </div>
  );
}
