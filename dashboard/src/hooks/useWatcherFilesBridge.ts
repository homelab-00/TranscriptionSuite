/**
 * useWatcherFilesBridge — singleton bridge that subscribes to
 * `electronAPI.watcher.onFilesDetected` and forwards every payload to
 * `useImportQueueStore.handleFilesDetected`.
 *
 * Why this exists (Issue #94):
 *   The preload's `onFilesDetected` registers a fresh `ipcRenderer.on(
 *   'watcher:filesDetected', handler)` on every call. Because `SessionView`
 *   stays mounted for the app's lifetime to preserve WebSocket/audio state
 *   (App.tsx), `useSessionWatcher` (in `SessionImportTab`) and
 *   `useNotebookWatcher` (in `NotebookView`) could both have a live
 *   subscription on the same channel — one IPC dispatch then ran
 *   `handleFilesDetected` twice and each file was queued twice.
 *
 * Mount this hook exactly once at the app root. The per-tab watcher hooks
 * stay focused on path persistence, start/stop control, and accessibility
 * polling — they no longer subscribe to the IPC channel themselves.
 */

import { useEffect } from 'react';
import { useImportQueueStore } from '../stores/importQueueStore';

type FilesDetectedHandler = ReturnType<typeof useImportQueueStore.getState>['handleFilesDetected'];
type OnFilesDetected = ((cb: FilesDetectedHandler) => () => void) | undefined;

export function useWatcherFilesBridge(): void {
  const handleFilesDetected = useImportQueueStore((s) => s.handleFilesDetected);

  useEffect(() => {
    const electronAPI = (window as any).electronAPI;
    const onFilesDetected: OnFilesDetected = electronAPI?.watcher?.onFilesDetected;
    if (!onFilesDetected) return;
    return onFilesDetected(handleFilesDetected);
  }, [handleFilesDetected]);
}
