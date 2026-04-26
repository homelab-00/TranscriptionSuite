/**
 * useSessionWatcher — manages the session folder-watch toggle.
 *
 * - Loads the persisted watch path AND active flag from config on mount (Issue #100).
 * - Starts/stops the watcher via IPC when the active toggle changes.
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

export function useSessionWatcher() {
  const sessionWatchPath = useImportQueueStore((s) => s.sessionWatchPath);
  const sessionWatchActive = useImportQueueStore((s) => s.sessionWatchActive);
  const setSessionWatchPath = useImportQueueStore((s) => s.setSessionWatchPath);
  const setSessionWatchActiveRaw = useImportQueueStore((s) => s.setSessionWatchActive);
  const appendWatchLog = useImportQueueStore((s) => s.appendWatchLog);

  const [sessionWatchAccessible, setSessionWatchAccessible] = useState(true);

  // Persist the active flag whenever it changes (UI toggle, auto-disable, path change).
  // Sync wrapper — fire-and-forget the disk write so onChange / .catch consumers
  // don't have to await; errors logged but do not propagate.
  const setSessionWatchActive = useCallback(
    (active: boolean) => {
      setSessionWatchActiveRaw(active);
      setConfig('folderWatch.sessionWatchActive', active).catch((err: unknown) => {
        const message = err instanceof Error ? err.message : 'Unknown error';
        console.error('[useSessionWatcher] Failed to persist active flag:', message);
      });
    },
    [setSessionWatchActiveRaw],
  );

  // Hydrate path AND active flag together on mount (Issue #100).
  // Re-arm only when both are truthy — never path-only or active-only.
  useEffect(() => {
    Promise.all([
      getConfig<string>('folderWatch.sessionPath'),
      getConfig<boolean>('folderWatch.sessionWatchActive'),
    ])
      .then(([savedPath, savedActive]) => {
        if (savedPath) setSessionWatchPath(savedPath);
        if (savedPath && savedActive === true) setSessionWatchActiveRaw(true);
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : 'Unknown error';
        console.error('[useSessionWatcher] Failed to hydrate from config:', message);
      });
  }, [setSessionWatchPath, setSessionWatchActiveRaw]);

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
      const wasActive = sessionWatchActive;
      if (wasActive) {
        setSessionWatchActiveRaw(false);
      }
      setSessionWatchPath(newPath);
      // Persist active=false BEFORE the new path so quit-mid-flow leaves a
      // coherent disk state — never `{ active: true, path: <newPath> }`.
      if (wasActive) {
        await setConfig('folderWatch.sessionWatchActive', false);
      }
      await setConfig('folderWatch.sessionPath', newPath);
    },
    [sessionWatchActive, setSessionWatchActiveRaw, setSessionWatchPath],
  );

  return {
    sessionWatchPath,
    sessionWatchActive,
    setSessionWatchActive,
    setWatchPath,
    sessionWatchAccessible,
  };
}
