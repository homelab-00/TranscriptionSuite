/**
 * useSessionWatcher — manages the session folder-watch toggle and IPC bridge.
 *
 * - Loads the persisted watch path from config on mount.
 * - Registers the watcher:filesDetected push listener and routes events to the store.
 * - Starts/stops the watcher via IPC when the active toggle changes.
 * - The active toggle is ALWAYS false on mount (ephemeral state).
 * - Polls folder accessibility every 10s when watch is active (4.1).
 */

import { useState, useEffect, useCallback } from 'react';
import { useImportQueueStore } from '../stores/importQueueStore';
import { getConfig, setConfig } from '../config/store';

export function useSessionWatcher() {
  const sessionWatchPath = useImportQueueStore((s) => s.sessionWatchPath);
  const sessionWatchActive = useImportQueueStore((s) => s.sessionWatchActive);
  const setSessionWatchPath = useImportQueueStore((s) => s.setSessionWatchPath);
  const setSessionWatchActive = useImportQueueStore((s) => s.setSessionWatchActive);
  const handleFilesDetected = useImportQueueStore((s) => s.handleFilesDetected);
  const appendWatchLog = useImportQueueStore((s) => s.appendWatchLog);

  const [sessionWatchAccessible, setSessionWatchAccessible] = useState(true);

  // Load persisted watch path on mount (toggle stays OFF — ephemeral)
  useEffect(() => {
    getConfig<string>('folderWatch.sessionPath').then((savedPath) => {
      if (savedPath) setSessionWatchPath(savedPath);
    });
  }, [setSessionWatchPath]);

  // Register the push listener from main process
  useEffect(() => {
    const electronAPI = (window as any).electronAPI;
    if (!electronAPI?.watcher?.onFilesDetected) return;
    const cleanup = electronAPI.watcher.onFilesDetected(handleFilesDetected);
    return cleanup;
  }, [handleFilesDetected]);

  // Start / stop watcher when active state or path changes
  useEffect(() => {
    const electronAPI = (window as any).electronAPI;
    if (!electronAPI?.watcher || !sessionWatchPath) return;

    if (sessionWatchActive) {
      electronAPI.watcher.startSession(sessionWatchPath).catch((err: Error) => {
        console.error('[useSessionWatcher] Failed to start:', err);
        appendWatchLog({
          message: `Session watcher failed to start: ${err.message}`,
          level: 'warn',
        });
        setSessionWatchActive(false);
      });
      appendWatchLog({ message: 'Session folder watch started', level: 'info' });
      return () => {
        electronAPI.watcher.stopSession().catch(() => {});
        appendWatchLog({ message: 'Session folder watch stopped', level: 'info' });
      };
    }
  }, [sessionWatchActive, sessionWatchPath, setSessionWatchActive, appendWatchLog]);

  // Poll folder accessibility every 10s when watch is active (4.1)
  useEffect(() => {
    if (!sessionWatchActive || !sessionWatchPath) {
      setSessionWatchAccessible(true);
      return;
    }
    const electronAPI = (window as any).electronAPI;
    if (!electronAPI?.watcher?.checkPath) return;

    let mounted = true;
    const check = () => {
      electronAPI.watcher
        .checkPath(sessionWatchPath)
        .then((ok: boolean) => {
          if (mounted) setSessionWatchAccessible(ok);
        })
        .catch(() => {
          if (mounted) setSessionWatchAccessible(false);
        });
    };

    check();
    const id = setInterval(check, 10_000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, [sessionWatchActive, sessionWatchPath]);

  /** Persist and apply a new watch path. Stops the watcher if it was active. */
  const setWatchPath = useCallback(
    async (newPath: string) => {
      if (sessionWatchActive) {
        setSessionWatchActive(false);
      }
      setSessionWatchPath(newPath);
      await setConfig('folderWatch.sessionPath', newPath);
    },
    [sessionWatchActive, setSessionWatchActive, setSessionWatchPath],
  );

  return {
    sessionWatchPath,
    sessionWatchActive,
    setSessionWatchActive,
    setWatchPath,
    sessionWatchAccessible,
  };
}
