import { useEffect, useState } from 'react';
import {
  type ClientDebugLogEntry,
  getCachedClientDebugLogPath,
  getClientDebugLogPath,
  getClientDebugLogs,
  subscribeClientDebugLogs,
} from '../services/clientDebugLog';

export interface UseClientDebugLogsState {
  logs: ClientDebugLogEntry[];
  logPath: string | null;
}

export function useClientDebugLogs(): UseClientDebugLogsState {
  const [logs, setLogs] = useState<ClientDebugLogEntry[]>(() => getClientDebugLogs());
  const [logPath, setLogPath] = useState<string | null>(() => getCachedClientDebugLogPath());

  useEffect(() => {
    return subscribeClientDebugLogs(() => {
      setLogs(getClientDebugLogs());
    });
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
