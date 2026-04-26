/**
 * useNotebookWatcher — manages the notebook folder-watch toggle.
 *
 * Mirror of useSessionWatcher but for notebook-auto jobs.
 * Auto-watch jobs include file creation timestamps so they land on the
 * correct calendar date in the notebook.
 * - Loads the persisted watch path AND active flag from config on mount (Issue #100).
 * - Re-arms the watcher on launch only when both the saved path and active flag are truthy.
 * - Polls folder accessibility every 10s when watch is active (4.1).
 *
 * The watcher:filesDetected IPC subscription lives in `useWatcherFilesBridge`
 * (mounted once at the app root). Subscribing here too caused duplicate
 * imports once both watcher hooks were mounted — see Issue #94.
 */

import { useState, useEffect, useCallback } from 'react';
import { useImportQueueStore } from '../stores/importQueueStore';
import { getConfig, setConfig } from '../config/store';

export function useNotebookWatcher() {
  const notebookWatchPath = useImportQueueStore((s) => s.notebookWatchPath);
  const notebookWatchActive = useImportQueueStore((s) => s.notebookWatchActive);
  const setNotebookWatchPath = useImportQueueStore((s) => s.setNotebookWatchPath);
  const setNotebookWatchActiveRaw = useImportQueueStore((s) => s.setNotebookWatchActive);
  const appendWatchLog = useImportQueueStore((s) => s.appendWatchLog);

  const [notebookWatchAccessible, setNotebookWatchAccessible] = useState(true);

  // Persist the active flag whenever it changes (UI toggle, auto-disable, path change).
  // Sync wrapper — fire-and-forget the disk write so onChange / .catch consumers
  // don't have to await; errors logged but do not propagate.
  const setNotebookWatchActive = useCallback(
    (active: boolean) => {
      setNotebookWatchActiveRaw(active);
      setConfig('folderWatch.notebookWatchActive', active).catch((err: unknown) => {
        const message = err instanceof Error ? err.message : 'Unknown error';
        console.error('[useNotebookWatcher] Failed to persist active flag:', message);
      });
    },
    [setNotebookWatchActiveRaw],
  );

  // Hydrate path AND active flag together on mount (Issue #100).
  // Re-arm only when both are truthy — never path-only or active-only.
  useEffect(() => {
    Promise.all([
      getConfig<string>('folderWatch.notebookPath'),
      getConfig<boolean>('folderWatch.notebookWatchActive'),
    ])
      .then(([savedPath, savedActive]) => {
        if (savedPath) setNotebookWatchPath(savedPath);
        if (savedPath && savedActive === true) setNotebookWatchActiveRaw(true);
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : 'Unknown error';
        console.error('[useNotebookWatcher] Failed to hydrate from config:', message);
      });
  }, [setNotebookWatchPath, setNotebookWatchActiveRaw]);

  // Start / stop watcher when active state or path changes
  useEffect(() => {
    const electronAPI = (window as any).electronAPI;
    if (!electronAPI?.watcher || !notebookWatchPath) return;

    if (notebookWatchActive) {
      electronAPI.watcher.startNotebook(notebookWatchPath).catch((err: Error) => {
        console.error('[useNotebookWatcher] Failed to start:', err);
        appendWatchLog({
          message: `Notebook watcher failed to start: ${err.message}`,
          level: 'warn',
        });
        setNotebookWatchActive(false);
      });
      appendWatchLog({ message: 'Notebook folder watch started', level: 'info' });
      return () => {
        electronAPI.watcher.stopNotebook().catch(() => {});
        appendWatchLog({ message: 'Notebook folder watch stopped', level: 'info' });
      };
    }
  }, [notebookWatchActive, notebookWatchPath, setNotebookWatchActive, appendWatchLog]);

  // Poll folder accessibility every 10s when watch is active (4.1)
  useEffect(() => {
    if (!notebookWatchActive || !notebookWatchPath) {
      setNotebookWatchAccessible(true);
      return;
    }
    const electronAPI = (window as any).electronAPI;
    if (!electronAPI?.watcher?.checkPath) return;

    let mounted = true;
    const check = () => {
      electronAPI.watcher
        .checkPath(notebookWatchPath)
        .then((ok: boolean) => {
          if (mounted) setNotebookWatchAccessible(ok);
        })
        .catch(() => {
          if (mounted) setNotebookWatchAccessible(false);
        });
    };

    check();
    const id = setInterval(check, 10_000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, [notebookWatchActive, notebookWatchPath]);

  /** Persist and apply a new watch path. Stops the watcher if it was active. */
  const setWatchPath = useCallback(
    async (newPath: string) => {
      const wasActive = notebookWatchActive;
      if (wasActive) {
        setNotebookWatchActiveRaw(false);
      }
      setNotebookWatchPath(newPath);
      // Persist active=false BEFORE the new path so quit-mid-flow leaves a
      // coherent disk state — never `{ active: true, path: <newPath> }`.
      if (wasActive) {
        await setConfig('folderWatch.notebookWatchActive', false);
      }
      await setConfig('folderWatch.notebookPath', newPath);
    },
    [notebookWatchActive, setNotebookWatchActiveRaw, setNotebookWatchPath],
  );

  return {
    notebookWatchPath,
    notebookWatchActive,
    setNotebookWatchActive,
    setWatchPath,
    notebookWatchAccessible,
  };
}
