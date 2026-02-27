import { useEffect, useState } from 'react';
import {
  type ClientDebugLogEntry,
  getCachedClientDebugLogPath,
  getClientDebugLogPath,
  getClientDebugLogs,
  ingestClientLogLine,
  subscribeClientDebugLogs,
} from '../services/clientDebugLog';

export interface UseClientDebugLogsState {
  logs: ClientDebugLogEntry[];
  logPath: string | null;
}

let clientLogBridgeRefCount = 0;
let clientLogBridgeCleanup: (() => void) | null = null;

export function useClientDebugLogs(): UseClientDebugLogsState {
  const [logs, setLogs] = useState<ClientDebugLogEntry[]>(() => getClientDebugLogs());
  const [logPath, setLogPath] = useState<string | null>(() => getCachedClientDebugLogPath());

  useEffect(() => {
    return subscribeClientDebugLogs(() => {
      setLogs(getClientDebugLogs());
    });
  }, []);

  useEffect(() => {
    const appBridge = typeof window === 'undefined' ? undefined : window.electronAPI?.app;
    if (!appBridge?.onClientLogLine) {
      return;
    }

    clientLogBridgeRefCount += 1;
    if (!clientLogBridgeCleanup) {
      clientLogBridgeCleanup = appBridge.onClientLogLine((entry) => {
        ingestClientLogLine(entry);
      });
    }

    return () => {
      clientLogBridgeRefCount = Math.max(0, clientLogBridgeRefCount - 1);
      if (clientLogBridgeRefCount === 0 && clientLogBridgeCleanup) {
        clientLogBridgeCleanup();
        clientLogBridgeCleanup = null;
      }
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    void getClientDebugLogPath().then((resolvedPath) => {
      if (mounted) {
        setLogPath(resolvedPath);
      }
    });
    return () => {
      mounted = false;
    };
  }, []);

  return { logs, logPath };
}
