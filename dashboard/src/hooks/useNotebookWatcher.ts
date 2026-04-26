/**
 * useNotebookWatcher — manages the notebook folder-watch toggle.
 *
 * Mirror of useSessionWatcher but for notebook-auto jobs.
 * Auto-watch jobs include file creation timestamps so they land on the
 * correct calendar date in the notebook.
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
  const setNotebookWatchActive = useImportQueueStore((s) => s.setNotebookWatchActive);
  const appendWatchLog = useImportQueueStore((s) => s.appendWatchLog);

  const [notebookWatchAccessible, setNotebookWatchAccessible] = useState(true);

  // Load persisted watch path on mount (toggle stays OFF — ephemeral)
  useEffect(() => {
    getConfig<string>('folderWatch.notebookPath').then((savedPath) => {
      if (savedPath) setNotebookWatchPath(savedPath);
    });
  }, [setNotebookWatchPath]);

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
      if (notebookWatchActive) {
        setNotebookWatchActive(false);
      }
      setNotebookWatchPath(newPath);
      await setConfig('folderWatch.notebookPath', newPath);
    },
    [notebookWatchActive, setNotebookWatchActive, setNotebookWatchPath],
  );

  return {
    notebookWatchPath,
    notebookWatchActive,
    setNotebookWatchActive,
    setWatchPath,
    notebookWatchAccessible,
  };
}
